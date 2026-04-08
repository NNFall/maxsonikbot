from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='🔮 Задать вопрос', callback_data='menu:ask')],
            [InlineKeyboardButton(text='💳 Баланс / Подписка', callback_data='menu:balance')],
            [InlineKeyboardButton(text='❓ Помощь', callback_data='menu:help')],
        ]
    )
