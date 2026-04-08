from __future__ import annotations

import json
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from config import load_config
from database import crud
from keyboards.effects_kb import effects_kb
from keyboards.payment_kb import choose_subscription_prompt_kb
from handlers.states import PhotoEffectState
from services.generation import run_photo_effect_generation
from services.balance_card import build_inactive_balance_text

router = Router()
config = load_config()

PHOTO_EFFECTS_TEXT = (
    '📸 <b>Идеи для фото</b>\n'
    'Выберите шаблон для обработки фото.'
)


@router.callback_query(F.data == 'menu:photo_ideas')
async def cb_photo_ideas(callback: CallbackQuery) -> None:
    await callback.answer()
    effects = await crud.list_effects(config.database_path, active_only=True, effect_type='photo')
    if not effects:
        await callback.message.answer('⚠️ Фото-эффекты еще не добавлены.')
        return
    kb = effects_kb(effects, page=1, effect_prefix='photo_effect', nav_prefix='photo_nav')
    await callback.message.answer(PHOTO_EFFECTS_TEXT, reply_markup=kb)


@router.message(Command('photo_ideas'))
async def cmd_photo_ideas(message: Message) -> None:
    effects = await crud.list_effects(config.database_path, active_only=True, effect_type='photo')
    if not effects:
        await message.answer('⚠️ Фото-эффекты еще не добавлены.')
        return
    kb = effects_kb(effects, page=1, effect_prefix='photo_effect', nav_prefix='photo_nav')
    await message.answer(PHOTO_EFFECTS_TEXT, reply_markup=kb)


@router.callback_query(F.data.startswith('photo_nav:'))
async def cb_photo_nav(callback: CallbackQuery) -> None:
    await callback.answer()
    parts = callback.data.split(':')
    if len(parts) != 3:
        return
    _, direction, page_str = parts
    if direction not in ('prev', 'next'):
        return
    if not page_str.isdigit():
        return
    page = int(page_str)
    effects = await crud.list_effects(config.database_path, active_only=True, effect_type='photo')
    if not effects:
        await callback.message.answer('⚠️ Фото-эффекты еще не добавлены.')
        return
    kb = effects_kb(effects, page=page, effect_prefix='photo_effect', nav_prefix='photo_nav')
    try:
        await callback.message.edit_text(PHOTO_EFFECTS_TEXT, reply_markup=kb)
    except Exception:
        await callback.message.answer(PHOTO_EFFECTS_TEXT, reply_markup=kb)


@router.callback_query(F.data.startswith('photo_effect:'))
async def cb_photo_effect_select(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    effect_id = callback.data.split(':', 1)[1]
    if not effect_id.isdigit():
        return
    effect = await crud.get_effect(config.database_path, int(effect_id))
    if not effect or not effect.get('is_active') or effect.get('type') != 'photo':
        await callback.message.answer('⚠️ Эффект недоступен.')
        return

    demo_file_id = effect.get('demo_file_id')
    demo_type = effect.get('demo_type')
    if demo_file_id:
        if demo_type == 'photo':
            await callback.message.answer_photo(demo_file_id)
        else:
            await callback.message.answer_video(demo_file_id)

    await callback.message.answer(
        '🖼 <b>Хочешь такое же фото?</b>\n'
        f'Стоимость: <b>{config.photo_effect_cost}</b> раскладов.\n'
        'Пришли мне фотографию, и я обработаю ее в этом стиле! 👇'
    )
    await state.set_state(PhotoEffectState.waiting_photo)
    await state.update_data(effect_id=int(effect_id))


@router.callback_query(F.data.startswith('again:photo_effect:'))
async def cb_again_photo_effect(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    effect_id = callback.data.split(':', 2)[2]
    if not effect_id.isdigit():
        return
    await state.set_state(PhotoEffectState.waiting_photo)
    await state.update_data(effect_id=int(effect_id))
    await callback.message.answer('🖼 Пришли новую фотографию для этого эффекта 👇')


@router.message(PhotoEffectState.waiting_photo)
async def photo_effect_photo(message: Message, state: FSMContext) -> None:
    if not message.photo:
        await message.answer('📸 Нужна фотография. Пришлите фото.')
        return

    data = await state.get_data()
    effect_id = data.get('effect_id')
    effect = await crud.get_effect(config.database_path, int(effect_id)) if effect_id else None
    if not effect or effect.get('type') != 'photo':
        await message.answer('⚠️ Эффект не найден. Попробуйте снова.')
        await state.clear()
        return

    photo = message.photo[-1]
    balance = await crud.get_balance(config.database_path, message.from_user.id)

    if balance < config.photo_effect_cost:
        await state.update_data(
            pending_action=json.dumps(
                {
                    'type': 'photo_effect',
                    'effect_id': int(effect_id),
                    'photo_file_id': photo.file_id,
                    'username': message.from_user.username,
                }
            )
        )
        balance_text = await build_inactive_balance_text(message.bot, balance, include_header=False)
        await message.answer(
            f'⚠️ <b>Недостаточно раскладов.</b>\n\n'
            f'{balance_text}',
            reply_markup=choose_subscription_prompt_kb(),
        )
        return

    await run_photo_effect_generation(
        message.bot,
        message.from_user.id,
        message.chat.id,
        int(effect_id),
        photo.file_id,
        username=message.from_user.username,
    )
    await state.clear()
