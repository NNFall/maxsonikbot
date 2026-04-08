from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def tools_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='📼 Склеить видео', callback_data='menu:concat')],
            [InlineKeyboardButton(text='✂️ Вырезать фрагмент', callback_data='menu:cut')],
            [InlineKeyboardButton(text='🏠 Меню', callback_data='menu:main')],
        ]
    )
