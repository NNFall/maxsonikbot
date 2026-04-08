from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def menu_only_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='🏠 Главное меню', callback_data='menu:main')]
        ]
    )
