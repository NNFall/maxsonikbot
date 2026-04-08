from __future__ import annotations

import secrets
import html
from datetime import datetime
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import load_config
from database import crud
from handlers.states import AdminAddEffectState
from services.notify import notify_admin
from services.subscriptions import get_plans

router = Router()
config = load_config()


async def _is_admin(user_id: int) -> bool:
    if user_id in config.admin_ids:
        return True
    return await crud.is_admin(config.database_path, user_id)


def _is_owner(user_id: int) -> bool:
    return user_id in config.admin_ids


@router.message(Command('add_session'))
async def cmd_add_session(message: Message, state: FSMContext) -> None:
    if not await _is_admin(message.from_user.id):
        return
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.button(text='📸 Фото', callback_data='admin_add_type:photo')
    builder.button(text='🎬 Видео', callback_data='admin_add_type:video')
    builder.adjust(2)
    await message.answer('Это эффект для ФОТО или для ВИДЕО?', reply_markup=builder.as_markup())
    await state.set_state(AdminAddEffectState.waiting_type)


@router.callback_query(AdminAddEffectState.waiting_type, F.data.startswith('admin_add_type:'))
async def add_effect_type(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _is_admin(callback.from_user.id):
        return
    await callback.answer()
    effect_type = callback.data.split(':', 1)[1]
    if effect_type not in ('photo', 'video'):
        await callback.message.answer('Неверный тип. Выберите фото или видео.')
        return
    await state.update_data(effect_type=effect_type)
    await callback.message.answer('Введите название кнопки (например: Поцелуй в камеру 😘).')
    await state.set_state(AdminAddEffectState.waiting_name)


@router.message(AdminAddEffectState.waiting_name)
async def add_effect_name(message: Message, state: FSMContext) -> None:
    if not await _is_admin(message.from_user.id):
        return
    name = (message.text or '').strip()
    if not name:
        await message.answer('Название не может быть пустым. Попробуйте снова.')
        return
    await state.update_data(button_name=name)
    await message.answer('Теперь отправьте промпт (на английском).')
    await state.set_state(AdminAddEffectState.waiting_prompt)


@router.message(AdminAddEffectState.waiting_prompt)
async def add_effect_prompt(message: Message, state: FSMContext) -> None:
    if not await _is_admin(message.from_user.id):
        return
    prompt = (message.text or '').strip()
    if not prompt:
        await message.answer('Промпт не может быть пустым. Попробуйте снова.')
        return
    await state.update_data(prompt=prompt)
    await message.answer('Пришлите демо-видео или фото. Если примера нет — напишите "нет".')
    await state.set_state(AdminAddEffectState.waiting_demo)


@router.message(AdminAddEffectState.waiting_demo)
async def add_effect_demo(message: Message, state: FSMContext) -> None:
    if not await _is_admin(message.from_user.id):
        return
    demo_file_id = None
    demo_type = None
    if message.text and message.text.strip().lower() == 'нет':
        demo_file_id = None
        demo_type = None
    elif message.video:
        demo_file_id = message.video.file_id
        demo_type = 'video'
    elif message.photo:
        demo_file_id = message.photo[-1].file_id
        demo_type = 'photo'
    else:
        await message.answer('Нужно видео или фото, либо напишите "нет".')
        return

    data = await state.get_data()
    button_name = data.get('button_name')
    prompt = data.get('prompt')
    if not button_name or not prompt:
        await message.answer('Данные потеряны. Начните заново.')
        await state.clear()
        return

    effect_type = data.get('effect_type') or 'video'
    effect_id = await crud.add_effect(
        config.database_path,
        button_name=button_name,
        prompt=prompt,
        demo_file_id=demo_file_id,
        demo_type=demo_type,
        effect_type=effect_type,
    )
    await message.answer(f'Эффект добавлен (ID: {effect_id}).')
    await state.clear()


@router.message(Command('session_del'))
async def cmd_session_del(message: Message) -> None:
    if not await _is_admin(message.from_user.id):
        return
    parts = (message.text or '').split(maxsplit=1)
    if len(parts) > 1:
        value = parts[1].strip()
        effect = None
        if value.isdigit():
            effect = await crud.get_effect(config.database_path, int(value))
        if not effect:
            effect = await crud.get_effect_by_name(config.database_path, value)
        if effect:
            await crud.deactivate_effect(config.database_path, int(effect['id']))
            await message.answer('Эффект удален (деактивирован).')
            return
        await message.answer('Эффект не найден.')
        return
    effects = await crud.list_effects(config.database_path, active_only=True)
    if not effects:
        await message.answer('Эффектов нет.')
        return
    builder = InlineKeyboardBuilder()
    for effect in effects:
        prefix = '📸' if effect.get('type') == 'photo' else '🎬'
        builder.button(text=f'{prefix} {effect["button_name"]}', callback_data=f"admin_del:{effect['id']}")
    builder.adjust(1)
    await message.answer('Выберите эффект для удаления:', reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith('admin_del:'))
async def admin_effect_delete(callback: CallbackQuery) -> None:
    if not await _is_admin(callback.from_user.id):
        return
    effect_id = callback.data.split(':', 1)[1]
    if not effect_id.isdigit():
        return
    await crud.deactivate_effect(config.database_path, int(effect_id))
    await callback.answer()
    await callback.message.answer('Эффект удален (деактивирован).')


@router.message(Command('sub_on'))
async def cmd_sub_on(message: Message) -> None:
    if not await _is_admin(message.from_user.id):
        return
    parts = (message.text or '').split()
    if len(parts) < 3:
        await message.answer(
            'Использование: /sub_on <code>ID</code> <code>amount</code>'
        )
        return
    if not parts[1].isdigit() or not parts[2].isdigit():
        await message.answer('ID и amount должны быть числами.')
        return
    user_id = int(parts[1])
    amount = int(parts[2])
    await crud.update_balance(config.database_path, user_id, amount)
    await message.answer(f'Начислено {amount} раскладов пользователю {user_id}.')


@router.message(Command('sub_off'))
async def cmd_sub_off(message: Message) -> None:
    if not await _is_admin(message.from_user.id):
        return
    parts = (message.text or '').split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer('Использование: /sub_off <code>ID</code>')
        return
    user_id = int(parts[1])
    await crud.set_balance(config.database_path, user_id, 0)
    await message.answer(f'Баланс пользователя {user_id} обнулен.')


@router.message(Command('sub_cancel'))
async def cmd_sub_cancel(message: Message) -> None:
    if not await _is_admin(message.from_user.id):
        return
    parts = (message.text or '').split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer('Использование: /sub_cancel <code>ID</code>')
        return
    user_id = int(parts[1])
    await crud.cancel_subscription(config.database_path, user_id)
    await message.answer(f'Подписка пользователя {user_id} отключена.')


@router.message(Command('sub_check'))
async def cmd_sub_check(message: Message) -> None:
    if not await _is_admin(message.from_user.id):
        return
    parts = (message.text or '').split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer('Использование: /sub_check <code>ID</code>')
        return
    user_id = int(parts[1])
    balance = await crud.get_balance(config.database_path, user_id)
    await message.answer(f'Баланс пользователя {user_id}: {balance} раскладов')


@router.message(Command('adstats'))
async def cmd_adstats(message: Message) -> None:
    if not await _is_admin(message.from_user.id):
        return
    parts = (message.text or '').split(maxsplit=1)
    if len(parts) < 2:
        await message.answer('Использование: /adstats <code>метка</code>')
        return
    tag = parts[1].strip()
    users = await crud.count_users_by_utm(config.database_path, tag)
    buyers = await crud.count_buyers_by_utm(config.database_path, tag)
    conversion = (buyers / users * 100) if users else 0
    totals = await crud.sum_payments_by_utm(config.database_path, tag)

    total_rub = 0.0
    for currency, amount in totals:
        if currency == 'RUB':
            total_rub += amount
        elif currency == 'XTR':
            total_rub += amount * config.stars_rub_rate

    ltv = (total_rub / users) if users else 0

    await message.answer(
        '📊 Статистика по метке\n'
        f'Метка: <code>{html.escape(tag)}</code>\n'
        f'Пользователей: {users}\n'
        f'Покупателей: {buyers}\n'
        f'Конверсия: {conversion:.2f}%\n'
        f'Сумма оплат (RUB экв): {total_rub:.2f}\n'
        f'LTV: {ltv:.2f}'
    )


@router.message(Command('adstats_all'))
async def cmd_adstats_all(message: Message) -> None:
    if not await _is_admin(message.from_user.id):
        return

    stats = await crud.list_utm_stats(config.database_path)
    payments = await crud.list_utm_payments(config.database_path)

    totals_map: dict[str | None, dict[str, int]] = {}
    for utm_source, currency, amount in payments:
        if utm_source not in totals_map:
            totals_map[utm_source] = {}
        totals_map[utm_source][currency] = amount

    lines = ['📊 <b>Статистика по всем меткам</b>']
    for row in stats:
        tag = row['utm_source'] if row['utm_source'] else 'без метки'
        users = int(row['users'])
        buyers = int(row['buyers'] or 0)
        conversion = (buyers / users * 100) if users else 0

        totals = totals_map.get(row['utm_source'], {})
        total_rub = 0.0
        for currency, amount in totals.items():
            if currency == 'RUB':
                total_rub += amount
            elif currency == 'XTR':
                total_rub += amount * config.stars_rub_rate

        ltv = (total_rub / users) if users else 0
        lines.append(
            f'• <code>{html.escape(str(tag))}</code> | users {users} | buyers {buyers} | '
            f'conv {conversion:.1f}% | sum {total_rub:.0f} | LTV {ltv:.1f}'
        )

    await message.answer('\n'.join(lines))


@router.message(Command('botstats'))
async def cmd_botstats(message: Message) -> None:
    if not await _is_admin(message.from_user.id):
        return

    now_iso = datetime.utcnow().isoformat(timespec='seconds')
    plans = get_plans()
    week = plans.get('week')
    month = plans.get('month')

    total_users = await crud.count_users(config.database_path)
    free_users = await crud.count_promo_used_users(config.database_path)
    paid_users = await crud.count_paid_users(config.database_path)
    active_subs = await crud.count_active_subscriptions(config.database_path, now_iso)
    subs_by_plan = await crud.count_active_subscriptions_by_plan(config.database_path, now_iso)

    stars_payments = await crud.count_paid_transactions_by_currency(config.database_path, 'XTR')
    stars_buyers = await crud.count_paid_users_by_currency(config.database_path, 'XTR')

    totals = await crud.sum_paid_by_currency(config.database_path)
    total_rub = 0
    total_xtr = 0
    for currency, amount in totals:
        if currency == 'RUB':
            total_rub += amount
        elif currency == 'XTR':
            total_xtr += amount

    conversion = (paid_users / total_users * 100) if total_users else 0
    arpu = (total_rub / total_users) if total_users else 0
    arppu = (total_rub / paid_users) if paid_users else 0

    week_label = week.title.lower() if week else 'неделя'
    month_label = month.title.lower() if month else 'месяц'
    week_price = week.price_rub if week else 0
    month_price = month.price_rub if month else 0

    await message.answer(
        '📊 <b>Общая статистика бота</b>\n\n'
        f'👥 Всего пользователей: {total_users}\n'
        f'🎁 Использовали бесплатную генерацию: {free_users}\n'
        f'💳 Оплативших: {paid_users}\n'
        f'🔥 Активных подписок: {active_subs}\n'
        f'🟢 Подписка {week_price}₽ ({week_label}): {subs_by_plan.get("week", 0)}\n'
        f'🔵 Подписка {month_price}₽ ({month_label}): {subs_by_plan.get("month", 0)}\n'
        f'⭐ Оплаты Stars (XTR): {stars_payments}\n'
        f'⭐ Покупателей Stars: {stars_buyers}\n'
        f'⭐ Сумма Stars: {total_xtr} XTR\n'
        f'💰 Выручка: {total_rub} ₽\n\n'
        f'📈 Конверсия в оплату: {conversion:.2f}%\n'
        f'💵 ARPU: {arpu:.2f} ₽\n'
        f'💎 ARPPU: {arppu:.2f} ₽'
    )


@router.message(Command('adtag'))
async def cmd_adtag(message: Message) -> None:
    if not await _is_admin(message.from_user.id):
        return
    parts = (message.text or '').split(maxsplit=1)
    if len(parts) < 2:
        await message.answer('Использование: /adtag <code>метка</code>')
        return
    tag = parts[1].strip()
    bot_info = await message.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={tag}"
    await message.answer(
        f'Метка: <code>{html.escape(tag)}</code>\n'
        f'Ссылка: <code>{link}</code>'
    )


@router.message(Command('genpromo'))
async def cmd_genpromo(message: Message) -> None:
    if not await _is_admin(message.from_user.id):
        return
    parts = (message.text or '').split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer('Использование: /genpromo <code>кол-во</code>')
        return
    credits = int(parts[1])
    code = secrets.token_urlsafe(6)
    await crud.create_promocode(config.database_path, code, credits)

    bot_info = await message.bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=promo_{code}"
    await message.answer(f'Промокод создан: {link}')
    await notify_admin(
        message.bot,
        config.admin_notify_ids,
        f'🎁 Создан промокод на {credits} раскладов: {code}'
    )


@router.message(Command('set_top'))
async def cmd_set_top(message: Message) -> None:
    if not await _is_admin(message.from_user.id):
        return
    parts = (message.text or '').split(maxsplit=1)
    if len(parts) > 1:
        value = parts[1].strip()
        effect = None
        if value.isdigit():
            effect = await crud.get_effect(config.database_path, int(value))
        if not effect:
            effect = await crud.get_effect_by_name(config.database_path, value)
        if effect:
            await crud.set_effect_top(config.database_path, int(effect['id']))
            await message.answer(f'Эффект "{effect["button_name"]}" поднят в ТОП.')
            return

    effects = await crud.list_effects(config.database_path, active_only=True)
    if not effects:
        await message.answer('Эффектов нет.')
        return
    builder = InlineKeyboardBuilder()
    for effect in effects:
        prefix = '📸' if effect.get('type') == 'photo' else '🎬'
        builder.button(text=f'{prefix} {effect["button_name"]}', callback_data=f"admin_top:{effect['id']}")
    builder.adjust(1)
    await message.answer('Выберите эффект для поднятия в ТОП:', reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith('admin_top:'))
async def cb_set_top(callback: CallbackQuery) -> None:
    if not await _is_admin(callback.from_user.id):
        return
    effect_id = callback.data.split(':', 1)[1]
    if not effect_id.isdigit():
        return
    await crud.set_effect_top(config.database_path, int(effect_id))
    await callback.answer()
    await callback.message.answer('Эффект поднят в ТОП.')


@router.message(Command('get_prompt'))
async def cmd_get_prompt(message: Message) -> None:
    if not await _is_admin(message.from_user.id):
        return
    parts = (message.text or '').split(maxsplit=1)
    if len(parts) > 1:
        value = parts[1].strip()
        effect = None
        if value.isdigit():
            effect = await crud.get_effect(config.database_path, int(value))
        if not effect:
            effect = await crud.get_effect_by_name(config.database_path, value)
        if effect:
            prompt_text = html.escape(effect.get('prompt') or '')
            await message.answer(
                f'Эффект: <b>{html.escape(effect["button_name"])}</b>\n'
                f'Тип: <b>{"Фото" if effect.get("type") == "photo" else "Видео"}</b>\n'
                f'Промпт:\n<pre>{prompt_text}</pre>'
            )
            return
        await message.answer('Эффект не найден.')
        return

    effects = await crud.list_effects(config.database_path, active_only=False)
    if not effects:
        await message.answer('Эффектов нет.')
        return
    builder = InlineKeyboardBuilder()
    for effect in effects:
        prefix = '📸' if effect.get('type') == 'photo' else '🎬'
        builder.button(text=f'{prefix} {effect["button_name"]}', callback_data=f"admin_prompt:{effect['id']}")
    builder.adjust(1)
    await message.answer('Выберите эффект, чтобы посмотреть промпт:', reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith('admin_prompt:'))
async def cb_get_prompt(callback: CallbackQuery) -> None:
    if not await _is_admin(callback.from_user.id):
        return
    effect_id = callback.data.split(':', 1)[1]
    if not effect_id.isdigit():
        return
    effect = await crud.get_effect(config.database_path, int(effect_id))
    if not effect:
        await callback.message.answer('Эффект не найден.')
        return
    prompt_text = html.escape(effect.get('prompt') or '')
    await callback.answer()
    await callback.message.answer(
        f'Эффект: <b>{html.escape(effect["button_name"])}</b>\n'
        f'Тип: <b>{"Фото" if effect.get("type") == "photo" else "Видео"}</b>\n'
        f'Промпт:\n<pre>{prompt_text}</pre>'
    )


@router.message(Command('admin_add'))
async def cmd_admin_add(message: Message) -> None:
    if not _is_owner(message.from_user.id):
        return
    parts = (message.text or '').split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer('Использование: /admin_add <code>ID</code>')
        return
    user_id = int(parts[1])
    await crud.add_admin(config.database_path, user_id, message.from_user.id)
    await message.answer(f'Админ добавлен: {user_id}')


@router.message(Command('admin_del'))
async def cmd_admin_del(message: Message) -> None:
    if not _is_owner(message.from_user.id):
        return
    parts = (message.text or '').split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer('Использование: /admin_del <code>ID</code>')
        return
    user_id = int(parts[1])
    await crud.remove_admin(config.database_path, user_id)
    await message.answer(f'Админ удален: {user_id}')


@router.message(Command('admin_list'))
async def cmd_admin_list(message: Message) -> None:
    if not _is_owner(message.from_user.id):
        return
    admins = await crud.list_admins(config.database_path)
    all_admins = list(dict.fromkeys(config.admin_ids + admins))
    if not all_admins:
        await message.answer('Админов нет.')
        return
    await message.answer('Админы:\n' + '\n'.join(f'- {a}' for a in all_admins))

