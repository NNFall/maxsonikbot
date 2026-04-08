from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def effect_done_kb(effect_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='🔁 Сгенерировать еще', callback_data=f'again:effect:{effect_id}')],
            [InlineKeyboardButton(text='🏠 Главное меню', callback_data='menu:main')],
        ]
    )


def custom_done_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='🔁 Сгенерировать еще', callback_data='again:custom')],
            [InlineKeyboardButton(text='🏠 Главное меню', callback_data='menu:main')],
        ]
    )


def photo_effect_done_kb(effect_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='🔁 Сгенерировать еще', callback_data=f'again:photo_effect:{effect_id}')],
            [InlineKeyboardButton(text='🏠 Главное меню', callback_data='menu:main')],
        ]
    )


def photo_custom_done_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='🔁 Сгенерировать еще', callback_data='again:photo_custom')],
            [InlineKeyboardButton(text='🏠 Главное меню', callback_data='menu:main')],
        ]
    )


def photo_text_done_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='🔁 Сгенерировать еще', callback_data='again:photo_text')],
            [InlineKeyboardButton(text='🏠 Главное меню', callback_data='menu:main')],
        ]
    )
