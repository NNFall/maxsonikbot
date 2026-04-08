from math import ceil
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def effects_kb(
    effects: list[dict],
    page: int,
    per_page: int = 8,
    effect_prefix: str = 'effect',
    nav_prefix: str = 'nav',
) -> InlineKeyboardMarkup:
    total = len(effects)
    total_pages = max(1, ceil(total / per_page))
    page = max(1, min(page, total_pages))

    start = (page - 1) * per_page
    end = start + per_page
    current = effects[start:end]

    rows: list[list[InlineKeyboardButton]] = []
    for effect in current:
        rows.append([InlineKeyboardButton(text=effect['button_name'], callback_data=f"{effect_prefix}:{effect['id']}")])

    if total_pages > 1:
        nav_buttons: list[InlineKeyboardButton] = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton(text='⬅️', callback_data=f"{nav_prefix}:prev:{page - 1}"))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton(text='➡️', callback_data=f"{nav_prefix}:next:{page + 1}"))
        if nav_buttons:
            rows.append(nav_buttons)

    rows.append([InlineKeyboardButton(text='🏠 Меню', callback_data='menu:main')])
    return InlineKeyboardMarkup(inline_keyboard=rows)
