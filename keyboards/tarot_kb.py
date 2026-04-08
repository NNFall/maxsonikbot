from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def tarot_open_full_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='✅ Открыть полный расклад', callback_data='tarot:open_full')],
        ]
    )


def tarot_after_reading_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='🔮 Задать еще вопрос', callback_data='menu:ask')],
            [InlineKeyboardButton(text='🏠 Главное меню', callback_data='menu:main')],
        ]
    )
