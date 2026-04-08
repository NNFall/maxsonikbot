from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def duration_kb(min_sec: int = 1, max_sec: int = 6) -> InlineKeyboardMarkup:
    rows = []
    for sec in range(min_sec, max_sec + 1):
        rows.append([InlineKeyboardButton(text=f"{sec} сек", callback_data=f"dur:{sec}")])
    rows.append([InlineKeyboardButton(text='🏠 Меню', callback_data='menu:main')])
    return InlineKeyboardMarkup(inline_keyboard=rows)
