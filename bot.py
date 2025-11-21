import logging
import math
import os
import textwrap
import tempfile
from typing import Tuple, List, Optional

from PIL import Image, ImageDraw, ImageFont, ImageOps
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, ConversationHandler, filters
)

# Логирование
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурации и пути
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGES_FOLDER = os.path.join(BASE_DIR, "images")
FONTS_FOLDER = os.path.join(BASE_DIR, "fonts")
DEFAULT_FONT_FILENAME = "FOT-YurukaStd-UB.ttf"
DEFAULT_FONT_PATH = os.path.join(FONTS_FOLDER, DEFAULT_FONT_FILENAME)

OUTLINE_WIDTH = 5  # обводка
MARGIN = 40
LINE_SPACING_MULTIPLIER = 0.4  # множитель для отступа между строк

# Цвета персонажей
CHARACTER_COLORS = {
    "Ichika": (51, 170, 238, 255), "Saki": (245, 179, 3, 255), "Honami": (248, 102, 102, 255),
    "Shiho": (160, 193, 11, 255), "Minori": (243, 158, 125, 255), "Haruka": (100, 149, 240, 255),
    "Airi": (251, 138, 172, 255), "Shizuku": (92, 208, 185, 255), "Kohane": (255, 102, 153, 255),
    "An": (0, 186, 220, 255), "Akito": (255, 119, 34, 255), "Toya": (0, 119, 221, 255),
    "Tsukasa": (240, 154, 4, 255), "Emu": (255, 102, 187, 255), "Nene": (25, 205, 148, 255),
    "Rui": (187, 136, 238, 255), "Kanade": (187, 102, 136, 255), "Mafuyu": (113, 113, 175, 255),
    "Mizuki": (202, 141, 182, 255), "Ena": (177, 143, 108, 255), "Miku": (51, 204, 187, 255),
    "Rin": (232, 165, 5, 255), "Len": (211, 189, 0, 255), "Luka": (248, 140, 167, 255),
    "Meiko": (228, 72, 95, 255), "Kaito": (51, 102, 204, 255)
}

GROUPS = {
    "Virtual Singer": ["Miku", "Rin", "Len", "Luka", "Meiko", "Kaito"],
    "Leo/need": ["Ichika", "Saki", "Honami", "Shiho"],
    "More More Jump!": ["Minori", "Haruka", "Airi", "Shizuku"],
    "Vivid Bad Squad": ["Kohane", "An", "Akito", "Toya"],
    "WxS": ["Tsukasa", "Emu", "Nene", "Rui"],
    "25-ji, Nightcord de.": ["Kanade", "Mafuyu", "Mizuki", "Ena"]
}

GROUP_EMOJIS = {
    "Virtual Singer": "🎤",
    "Leo/need": "💫",
    "More More Jump!": "🍀",
    "Vivid Bad Squad": "💿",
    "WxS": "👑",
    "25-ji, Nightcord de.": "💔"
}

(
    CHOOSE_GROUP, CHOOSE_CHARACTER, CHOOSE_IMAGE,
    CONFIRM_IMAGE, ENTER_TEXT, CHOOSE_FONT_SIZE,
    CHOOSE_ORIENTATION, CHOOSE_POSITION, EDIT_STICKER,
    EDIT_FONT_SIZE, EDIT_TEXT
) = range(11)


# шрифт
def safe_font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def list_images_for_character(char: str) -> List[str]:
    path = os.path.join(IMAGES_FOLDER, char)
    if not os.path.isdir(path):
        return []
    files = [f for f in os.listdir(path) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
    files.sort()
    return files


# !!!сама структура создания стикеров
# загрузка изображения, область в которой можно рисовать, размеры и цвет текста для каждого персонажа
class StickerBuilder:
    def __init__(self, template_path: str, character: str, default_font: str = DEFAULT_FONT_PATH):
        self.template_path = template_path
        self.character = character
        self.default_font = default_font
        self.outline_color = (255, 255, 255, 255)
        self.outline_width = OUTLINE_WIDTH
        self.margin = MARGIN
        self.line_spacing_multiplier = LINE_SPACING_MULTIPLIER  # Новая переменная для отступа между строк
        self._img = Image.open(self.template_path).convert("RGBA")
        self._draw = ImageDraw.Draw(self._img)
        self.w, self.h = self._img.size
        self.fill_color = CHARACTER_COLORS.get(character, (255, 255, 255, 255))

    # размер шрифта и если текст слишком большой
    def _text_size(self, text: str, font: ImageFont.FreeTypeFont) -> Tuple[int, int]:
        bbox = self._draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    # рисуется контур для текста в пределах радиуса r(только точки внутри круга радиуса r), затем основной текст
    def _draw_outline_text(self, position, text, font, fill):
        x, y = position
        r = self.outline_width
        # создание контура
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                if dx * dx + dy * dy <= r * r:
                    self._draw.text((x + dx, y + dy), text, font=font, fill=self.outline_color)
        # сам текст
        self._draw.text((x, y), text, font=font, fill=fill)

 
    def _get_safe_area(self, use_margin: bool) -> Tuple[int, int, int, int]:
        """безопасная область с учётом области текста и контура"""
        base_margin = self.margin if use_margin else 0
        # сам контур в отступах
        safe_inset = max(base_margin, self.outline_width * 2)
        return safe_inset, safe_inset, self.w - safe_inset, self.h - safe_inset

    def prepare_font_to_fit(self, lines, initial_size, max_width, max_height):
        size = max(6, initial_size)
        while size > 6:
            font = safe_font(self.default_font, size)
            line_heights = [self._text_size(ln, font)[1] for ln in lines]
            line_spacing = max(2, int(size * self.line_spacing_multiplier))
            total_h = sum(line_heights) + line_spacing * max(0, len(lines) - 1)
            max_line_w = max((self._text_size(ln, font)[0] for ln in lines), default=0)

            if max_line_w <= max_width and total_h <= max_height:
                return font, line_spacing, line_heights
            size -= 2
        # если чота не влезло
        font = safe_font(self.default_font, 6)
        line_heights = [self._text_size(ln, font)[1] for ln in lines]
        line_spacing = max(2, int(6 * self.line_spacing_multiplier))
        return font, line_spacing, line_heights

    # разбивает текст на строки, чтобы каждая строка не превышала max_width
    def _wrap_text_for_width(self, text, font, max_width):
        words = text.split()
        if not words:
            return [""]
        lines = []
        cur = words[0]
        for w in words[1:]:
            trial = cur + " " + w
            if self._text_size(trial, font)[0] <= max_width:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
        return lines

    # горизонтальный текст
    def draw_horizontal(self, text: str, font_size: int, position: str = "top_center", use_margin: bool = True):
        # безопасная область с учетом контура
        left, top, right, bottom = self._get_safe_area(use_margin)
        max_w = right - left
        max_h = bottom - top

        if max_w <= 0 or max_h <= 0:
            return

        temp_font = safe_font(self.default_font, font_size)
        lines = self._wrap_text_for_width(text, temp_font, max_w)

        font, line_spacing, line_heights = self.prepare_font_to_fit(lines, font_size, max_w, max_h)
        lines = self._wrap_text_for_width(text, font, max_w)
        line_heights = [self._text_size(ln, font)[1] for ln in lines]
        total_h = sum(line_heights) + line_spacing * max(0, len(lines) - 1)

        available_height = max_h

        if position in ["top_center", "top_left"]:
            y_start = top
        elif position == "mid_center":
            y_start = top + max(0, (available_height - total_h) // 2)
        elif position == "bot_center":
            y_start = top + max(0, available_height - total_h)
        else:
            y_start = top

        if y_start + total_h > bottom:
            y_start = bottom - total_h

        y = y_start
        for i, ln in enumerate(lines):
            lw, lh = self._text_size(ln, font)

            if "left" in position:
                x = left
            elif "center" in position:
                x = left + (max_w - lw) // 2
            else:
                x = right - lw

            x = max(left, min(x, right - lw))

            self._draw_outline_text((x, y), ln, font, self.fill_color)
            if i < len(lines) - 1:
                y += lh + line_spacing
            else:
                y += lh

    def draw_vertical(self, text: str, font_size: int, position: str = "left", use_margin: bool = True):
        """Вертикальное расположение текста с автоматическим уменьшением шрифта для длинных слов"""
        left, top, right, bottom = self._get_safe_area(use_margin)
        max_h = bottom - top
        max_w = right - left

        if max_h <= 0 or max_w <= 0:
            return

        words = text.split()
        if not words:
            return

        initial_size = font_size
        font = None
        final_columns = []

        while initial_size > 6:
            font = safe_font(self.default_font, initial_size)
            line_spacing = int(initial_size * self.line_spacing_multiplier)

            word_fits = True
            for word in words:
                word_height = 0
                for char in word:
                    char_w, char_h = self._text_size(char, font)
                    word_height += char_h + line_spacing
                if word:
                    word_height -= line_spacing

                if word_height > max_h:
                    word_fits = False
                    break

            if not word_fits:
                initial_size -= 2
                continue

            columns = []
            current_column = []
            current_height = 0

            for word in words:

                word_height = 0
                for char in word:
                    char_w, char_h = self._text_size(char, font)
                    word_height += char_h + line_spacing
                if word:
                    word_height -= line_spacing

                if current_height + word_height > max_h:
                    if current_column:
                        columns.append(current_column)
                        current_column = [word]
                        current_height = word_height
                    else:

                        word_fits = False
                        break
                else:
                    current_column.append(word)
                    current_height += word_height + line_spacing

            if current_column:
                columns.append(current_column)

            if not word_fits:
                initial_size -= 2
                continue

            max_char_width = max(
                [self._text_size(char, font)[0] for column in columns for word in column for char in word],
                default=0
            )
            total_width_needed = len(columns) * max_char_width + (len(columns) - 1) * line_spacing

            if total_width_needed > max_w * 0.5:
                initial_size -= 2
                continue

            if total_width_needed <= max_w:
                final_columns = columns
                break
            else:
                initial_size -= 2
        else:

            font = safe_font(self.default_font, 6)
            initial_size = 6
            line_spacing = int(6 * self.line_spacing_multiplier)

            columns = []
            current_column = []
            current_height = 0

            for word in words:
                word_height = 0
                for char in word:
                    char_w, char_h = self._text_size(char, font)
                    word_height += char_h + line_spacing
                if word:
                    word_height -= line_spacing

                if current_height + word_height > max_h:
                    if current_column:
                        columns.append(current_column)
                        current_column = [word]
                        current_height = word_height
                    else:
                        current_column = [word]
                        columns.append(current_column)
                        current_column = []
                        current_height = 0
                else:
                    current_column.append(word)
                    current_height += word_height + line_spacing

            if current_column:
                columns.append(current_column)
            final_columns = columns


        max_char_width = max(
            [self._text_size(char, font)[0] for column in final_columns for word in column for char in word],
            default=0
        )
        column_width = max_char_width + line_spacing
        total_width = len(final_columns) * column_width

        if position == "right":
            x_start = right - total_width
        else:  # left
            x_start = left

        x_start = max(left, min(x_start, right - total_width))

        for col_index, column in enumerate(final_columns):
            x = x_start + col_index * column_width

            total_column_height = 0
            for word in column:
                word_height = 0
                for char in word:
                    char_w, char_h = self._text_size(char, font)
                    word_height += char_h + line_spacing
                if word:
                    word_height -= line_spacing
                total_column_height += word_height + line_spacing

            if column:
                total_column_height -= line_spacing

            if total_column_height < max_h:
                y_start = top + (max_h - total_column_height) // 2
            else:
                y_start = top


            y = y_start
            for word_index, word in enumerate(column):
                for char_index, char in enumerate(word):
                    char_w, char_h = self._text_size(char, font)


                    char_x = x + (max_char_width - char_w) // 2

                    if (char_x >= left and char_x + char_w <= right and
                            y >= top and y + char_h <= bottom):
                        self._draw_outline_text((char_x, y), char, font, self.fill_color)


                    y += char_h + line_spacing


                if word_index < len(column) - 1:
                    y += line_spacing

    def build(self):
        return self._img

    def save_temp(self, prefix="out_", ext="png"):
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}", prefix=prefix)
        path = tmp.name
        tmp.close()
        self._img.save(path, "PNG")
        return path


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton(f"{GROUP_EMOJIS[g]} {g}", callback_data=f"group_{g}")] for g in GROUPS]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:

        try:
            await update.callback_query.edit_message_text("Выбери группу:", reply_markup=reply_markup)
        except Exception:
            await update.callback_query.message.reply_text("Выбери группу:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("Выбери группу:", reply_markup=reply_markup)
    return CHOOSE_GROUP


async def back_to_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await start(update, context)


async def choose_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    group = query.data.split("_", 1)[1]
    context.user_data["group"] = group
    available = [c for c in GROUPS[group] if list_images_for_character(c)]
    keyboard = [[InlineKeyboardButton(char, callback_data=f"char_{char}")] for char in available]
    keyboard.append([InlineKeyboardButton("< Назад", callback_data="back_to_groups")])
    await query.edit_message_text(f"Группа: *{group}*\nВыбери персонажа:", reply_markup=InlineKeyboardMarkup(keyboard),
                                  parse_mode='Markdown')
    return CHOOSE_CHARACTER


async def choose_character(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    char = query.data.split("_", 1)[1]
    context.user_data["character"] = char
    images = list_images_for_character(char)

    keyboard = []
    for i in range(0, len(images), 2):
        row = []

        row.append(InlineKeyboardButton(images[i], callback_data=f"img_{images[i]}"))

        if i + 1 < len(images):
            row.append(InlineKeyboardButton(images[i + 1], callback_data=f"img_{images[i + 1]}"))
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("< Назад", callback_data=f"back_to_chars_{context.user_data['group']}")])

    await query.edit_message_text(f"Персонаж: *{char}*\nВыбери изображение:",
                                  reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return CHOOSE_IMAGE

async def back_to_characters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    group = query.data.split("_", 3)[3]
    context.user_data["group"] = group
    available = [c for c in GROUPS[group] if list_images_for_character(c)]
    keyboard = [[InlineKeyboardButton(char, callback_data=f"char_{char}")] for char in available]
    keyboard.append([InlineKeyboardButton("< Назад", callback_data="back_to_groups")])
    await query.edit_message_text(f"Группа: *{group}*\nВыбери персонажа:", reply_markup=InlineKeyboardMarkup(keyboard),
                                  parse_mode='Markdown')
    return CHOOSE_CHARACTER


async def choose_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        await query.message.delete()
    except Exception:
        pass
    img = query.data.split("_", 1)[1]
    context.user_data["image"] = img
    char = context.user_data["character"]
    img_path = os.path.join(IMAGES_FOLDER, char, img)
    with open(img_path, "rb") as f:
        preview = await query.message.reply_photo(
            photo=f,
            caption=f"Выбираем этот штамп?\n\n{img}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Да", callback_data="confirm_yes")],
                [InlineKeyboardButton("< Другой", callback_data="confirm_no")]
            ])
        )
    context.user_data["preview_message_id"] = preview.message_id
    return CONFIRM_IMAGE


# Подтверждения изображения и обратно
async def confirm_image_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data.split("_")[1]
    try:
        await query.message.delete()
    except Exception:
        pass
    if choice == "yes":
        await query.message.reply_text("Введи текст:")
        return ENTER_TEXT
    else:
        char = context.user_data["character"]
        group = context.user_data["group"]
        images = list_images_for_character(char)

        keyboard = []
        for i in range(0, len(images), 2):
            row = []

            row.append(InlineKeyboardButton(images[i], callback_data=f"img_{images[i]}"))

            if i + 1 < len(images):
                row.append(InlineKeyboardButton(images[i + 1], callback_data=f"img_{images[i + 1]}"))
            keyboard.append(row)

        keyboard.append([InlineKeyboardButton("< Назад", callback_data=f"back_to_chars_{group}")])

        await query.message.reply_text(f"Персонаж: *{char}*\nВыбери изображение:",
                                       reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return CHOOSE_IMAGE


async def enter_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["text"] = update.message.text
    await update.message.reply_text("Введи размер шрифта (например, 25):")
    return CHOOSE_FONT_SIZE


async def choose_font_size(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    context.user_data["font_size"] = 40 if text == "default" else max(6, int(text))
    keyboard = [
        [InlineKeyboardButton("Горизонтально", callback_data="orient_horizontal")],
        [InlineKeyboardButton("Вертикально", callback_data="orient_vertical")],
    ]
    await update.message.reply_text("Выбери ориентацию текста:", reply_markup=InlineKeyboardMarkup(keyboard))
    return CHOOSE_ORIENTATION


async def handle_orientation_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    orient = query.data.split("_", 1)[1]
    context.user_data["orientation"] = orient

    if orient == "horizontal":
        keyboard = [
            [InlineKeyboardButton("Сверху", callback_data="pos_top_center")],
            [InlineKeyboardButton("Посередине", callback_data="pos_mid_center")],
            [InlineKeyboardButton("Снизу", callback_data="pos_bot_center")],
        ]
        await query.edit_message_text("Выбери положение текста:", reply_markup=InlineKeyboardMarkup(keyboard))
        return CHOOSE_POSITION
    elif orient == "vertical":
        keyboard = [
            [InlineKeyboardButton("Слева", callback_data="pos_left")],
            [InlineKeyboardButton("Справа", callback_data="pos_right")],
        ]
        await query.edit_message_text("Выбери положение текста:", reply_markup=InlineKeyboardMarkup(keyboard))
        return CHOOSE_POSITION


async def handle_position_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    pos = query.data.split("_", 1)[1]
    context.user_data["position"] = pos

    try:
        await query.message.delete()
    except Exception:
        pass

    return await generate_and_send(update, context)


async def generate_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        char = context.user_data["character"]
        img_name = context.user_data["image"]
        text = context.user_data["text"]
        size = context.user_data["font_size"]
        orient = context.user_data["orientation"]
        pos = context.user_data.get("position", "top_center")
        template_path = os.path.join(IMAGES_FOLDER, char, img_name)
        builder = StickerBuilder(template_path, char, DEFAULT_FONT_PATH)

        if orient == "horizontal":
            builder.draw_horizontal(text, size, position=pos, use_margin=False)
        elif orient == "vertical":

            builder.draw_vertical(text, size, position=pos, use_margin=False)

        out_path = builder.save_temp(prefix=f"{char}_sticker_")
        with open(out_path, "rb") as f:
            message = await query.message.reply_document(
                document=f,
                filename=f"{char}_{img_name.split('.')[0]}_{orient}.png",
                caption=f"У Саки-чан получилось!\n. . .✉ @pjskstickers_bot",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Изменить", callback_data="edit_sticker"),
                     InlineKeyboardButton("Создать новый", callback_data="create_new")]

                ])
            )

        context.user_data["sticker_message_id"] = message.message_id
        context.user_data["sticker_file_path"] = out_path
        context.user_data["last_sticker_message"] = message
    except Exception as e:
        logger.exception(e)
        await query.message.reply_text(f"Ошибка: {e}")

        if "sticker_file_path" in context.user_data:
            try:
                os.remove(context.user_data["sticker_file_path"])
            except:
                pass
    return EDIT_STICKER


async def create_new_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для кнопки 'Создать новый' - работает как /start"""
    query = update.callback_query
    await query.answer()

    if "sticker_file_path" in context.user_data:
        try:
            os.remove(context.user_data["sticker_file_path"])
        except:
            pass

    context.user_data.clear()


    keyboard = [[InlineKeyboardButton(f"{GROUP_EMOJIS[g]} {g}", callback_data=f"group_{g}")] for g in GROUPS]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.reply_text("Выбери группу:", reply_markup=reply_markup)
    return CHOOSE_GROUP


async def edit_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    sticker_message = context.user_data.get("last_sticker_message")

    try:
        await query.message.delete()
    except Exception:
        pass

    keyboard = [
        [InlineKeyboardButton("Текст", callback_data="edit_text")],
        [InlineKeyboardButton("Размер шрифта", callback_data="edit_font_size")],
        [InlineKeyboardButton("Ориентацию текста", callback_data="edit_orientation")],
        [InlineKeyboardButton("< Назад", callback_data="back_to_sticker")]
    ]

    await query.message.reply_text(
        "Что именно изменить?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return EDIT_STICKER


async def edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        await query.message.delete()
    except Exception:
        pass

    await query.message.reply_text("Введи новый текст:")
    return EDIT_TEXT


async def handle_edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ввода нового текста при редактировании"""
    try:
        new_text = update.message.text
        context.user_data["text"] = new_text


        char = context.user_data["character"]
        img_name = context.user_data["image"]
        font_size = context.user_data["font_size"]
        orient = context.user_data["orientation"]
        pos = context.user_data.get("position", "top_center")
        template_path = os.path.join(IMAGES_FOLDER, char, img_name)

        builder = StickerBuilder(template_path, char, DEFAULT_FONT_PATH)

        if orient == "horizontal":
            builder.draw_horizontal(new_text, font_size, position=pos, use_margin=False)
        elif orient == "vertical":
            builder.draw_vertical(new_text, font_size, position=pos, use_margin=False)

        if "sticker_file_path" in context.user_data:
            try:
                os.remove(context.user_data["sticker_file_path"])
            except:
                pass

        out_path = builder.save_temp(prefix=f"{char}_sticker_")

        with open(out_path, "rb") as f:
            message = await update.message.reply_document(
                document=f,
                filename=f"{char}_{img_name.split('.')[0]}_{orient}.png",
                caption=f"У Саки-чан получилось!\n. . .✉ @pjskstickers_bot",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Изменить", callback_data="edit_sticker"),
                     InlineKeyboardButton("Создать новый", callback_data="create_new")]
                ])
            )

        context.user_data["sticker_message_id"] = message.message_id
        context.user_data["sticker_file_path"] = out_path
        context.user_data["last_sticker_message"] = message

        return EDIT_STICKER

    except Exception as e:
        logger.exception(e)
        await update.message.reply_text(f"Ошибка при обновлении текста: {e}")
        return EDIT_STICKER


async def edit_font_size(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        await query.message.delete()
    except Exception:
        pass

    await query.message.reply_text("Введи новый размер шрифта (например, 20):")
    return EDIT_FONT_SIZE


async def handle_edit_font_size(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ввода нового размера шрифта при редактировании"""
    try:
        text = update.message.text.strip().lower()
        new_font_size = 40 if text == "default" else max(6, int(text))
        context.user_data["font_size"] = new_font_size


        char = context.user_data["character"]
        img_name = context.user_data["image"]
        text = context.user_data["text"]
        orient = context.user_data["orientation"]
        pos = context.user_data.get("position", "top_center")
        template_path = os.path.join(IMAGES_FOLDER, char, img_name)

        builder = StickerBuilder(template_path, char, DEFAULT_FONT_PATH)

        if orient == "horizontal":
            builder.draw_horizontal(text, new_font_size, position=pos, use_margin=False)
        elif orient == "vertical":
            builder.draw_vertical(text, new_font_size, position=pos, use_margin=False)

        if "sticker_file_path" in context.user_data:
            try:
                os.remove(context.user_data["sticker_file_path"])
            except:
                pass

        out_path = builder.save_temp(prefix=f"{char}_sticker_")

        with open(out_path, "rb") as f:
            message = await update.message.reply_document(
                document=f,
                filename=f"{char}_{img_name.split('.')[0]}_{orient}.png",
                caption=f"У Саки-чан получилось!\n. . .✉ @pjskstickers_bot",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Изменить", callback_data="edit_sticker"),
                     InlineKeyboardButton("Создать новый", callback_data="create_new")]
                ])
            )

        context.user_data["sticker_message_id"] = message.message_id
        context.user_data["sticker_file_path"] = out_path
        context.user_data["last_sticker_message"] = message

        return EDIT_STICKER

    except ValueError:
        await update.message.reply_text("Пожалуйста, введите корректное число для размера шрифта:")
        return EDIT_FONT_SIZE
    except Exception as e:
        logger.exception(e)
        await update.message.reply_text(f"Ошибка при обновлении размера шрифта: {e}")
        return EDIT_STICKER


async def edit_orientation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        await query.message.delete()
    except Exception:
        pass

    keyboard = [
        [InlineKeyboardButton("Горизонтально", callback_data="orient_horizontal")],
        [InlineKeyboardButton("Вертикально", callback_data="orient_vertical")],
    ]
    await query.message.reply_text("Выбери ориентацию текста:", reply_markup=InlineKeyboardMarkup(keyboard))
    return CHOOSE_ORIENTATION


async def back_to_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        await query.message.delete()
    except Exception:
        pass

    sticker_file_path = context.user_data.get("sticker_file_path")
    if sticker_file_path and os.path.exists(sticker_file_path):
        char = context.user_data["character"]
        orient = context.user_data["orientation"]
        img_name = context.user_data["image"]

        with open(sticker_file_path, "rb") as f:
            message = await query.message.reply_document(
                document=f,
                filename=f"{char}_{img_name.split('.')[0]}_{orient}.png",
                caption=f"У Саки-чан получилось!\n. . .✉ @pjskstickers_bot",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Изменить", callback_data="edit_sticker"),
                     InlineKeyboardButton("Создать новый", callback_data="create_new")]
                ])
            )

        context.user_data["last_sticker_message"] = message
        context.user_data["sticker_message_id"] = message.message_id
    else:

        await query.message.reply_text("Восстанавливаю стикер...")
        return await generate_and_send(update, context)

    return EDIT_STICKER


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if "sticker_file_path" in context.user_data:
        try:
            os.remove(context.user_data["sticker_file_path"])
        except:
            pass

    if update.message:
        await update.message.reply_text("Отменено.")
    else:
        await update.callback_query.edit_message_text("Отменено.")
    return ConversationHandler.END


def main():
    TOKEN = "7952012867:AAFyxAgQFDxhyfWbNWt9eluq-_-RYROVgPU"
    app = Application.builder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSE_GROUP: [
                CallbackQueryHandler(choose_group, pattern="^group_"),
                CallbackQueryHandler(back_to_groups, pattern="^back_to_groups$")
            ],
            CHOOSE_CHARACTER: [
                CallbackQueryHandler(choose_character, pattern="^char_"),
                CallbackQueryHandler(back_to_groups, pattern="^back_to_groups$")
            ],
            CHOOSE_IMAGE: [
                CallbackQueryHandler(choose_image, pattern="^img_"),
    
                CallbackQueryHandler(back_to_characters, pattern="^back_to_chars_")
            ],
            CONFIRM_IMAGE: [
                CallbackQueryHandler(confirm_image_choice, pattern="^confirm_")
            ],
            ENTER_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_text)],
            CHOOSE_FONT_SIZE: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_font_size)],
            CHOOSE_ORIENTATION: [CallbackQueryHandler(handle_orientation_choice, pattern="^orient_")],
            CHOOSE_POSITION: [CallbackQueryHandler(handle_position_choice, pattern="^pos_")],
            EDIT_STICKER: [
                CallbackQueryHandler(edit_text, pattern="^edit_text$"),
                CallbackQueryHandler(edit_font_size, pattern="^edit_font_size$"),
                CallbackQueryHandler(edit_orientation, pattern="^edit_orientation$"),
                CallbackQueryHandler(back_to_sticker, pattern="^back_to_sticker$"),
                CallbackQueryHandler(edit_sticker, pattern="^edit_sticker$"),
                CallbackQueryHandler(create_new_sticker, pattern="^create_new$")

            ],
            EDIT_FONT_SIZE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_font_size)
            ],
            EDIT_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_text)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    app.add_handler(conv)
    app.run_polling()


if __name__ == "__main__":

    main()
