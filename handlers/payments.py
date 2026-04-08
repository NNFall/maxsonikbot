from __future__ import annotations

import asyncio
import json
import logging
import uuid
from urllib.parse import quote
from datetime import datetime, timezone
from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, LabeledPrice, PreCheckoutQuery
from aiogram.fsm.context import FSMContext

from config import load_config
from database import crud
from keyboards.payment_kb import (
    plans_kb,
    methods_kb,
    pay_url_kb,
    payment_success_kb,
    subscription_manage_kb,
    choose_subscription_kb,
    choose_subscription_prompt_kb,
)
from services import yookassa as yk
from services.notify import notify_admin
from services.subscriptions import get_plans, get_plan, calc_period
from services.generation import (
    run_effect_generation,
    run_custom_generation,
    run_photo_effect_generation,
    run_photo_custom_generation,
    run_text_image_generation,
)
from contextlib import suppress

from services.tarot_reading import run_paid_tarot_reading, run_tarot_continuation
from keyboards.tarot_kb import tarot_after_reading_kb

router = Router()
config = load_config()
logger = logging.getLogger(__name__)

POLL_INTERVAL = 5
POLL_TIMEOUT = 600

_pending_yoo_tasks: dict[int, asyncio.Task] = {}
_payment_locks: dict[int, asyncio.Lock] = {}
PAY_PROGRESS_STEPS = (
    'Оплата получена',
    'Настраиваюсь на полный расклад',
    'Собираю фокус вопроса',
    'Сверяюсь с энергией запроса',
    'Открываю 2-ю карту',
    'Считываю символы 2-й карты',
    'Открываю 3-ю карту',
    'Считываю символы 3-й карты',
    'Сопоставляю позиции',
    'Формулирую вывод',
)


async def _payment_progress_loop(progress_msg: Message) -> None:
    step_idx = 0
    while True:
        text = f'{PAY_PROGRESS_STEPS[step_idx % len(PAY_PROGRESS_STEPS)]}...'
        try:
            await progress_msg.edit_text(text)
        except TelegramBadRequest:
            pass
        await asyncio.sleep(10)
        step_idx += 1


async def _start_payment_progress(bot, chat_id: int):
    sticker_msg: Message | None = None
    sticker_id = (config.tarot_progress_sticker_id or '').strip()
    if sticker_id:
        try:
            sticker_msg = await bot.send_sticker(chat_id, sticker_id)
            logger.info(
                'Payment progress sticker sent chat_id=%s message_id=%s',
                chat_id,
                sticker_msg.message_id,
            )
        except Exception as e:
            logger.warning('Payment progress sticker send failed chat_id=%s error=%s', chat_id, e)
    msg = await bot.send_message(chat_id, 'Оплата получена. Готовлю полный расклад...')
    task = asyncio.create_task(_payment_progress_loop(msg))
    return sticker_msg, msg, task


async def _safe_delete_message(msg: Message, label: str) -> None:
    for attempt in range(1, 4):
        try:
            await msg.delete()
            logger.info('%s deleted chat_id=%s message_id=%s', label, msg.chat.id, msg.message_id)
            return
        except Exception as e:
            logger.warning(
                '%s delete failed attempt=%s chat_id=%s message_id=%s error=%s',
                label,
                attempt,
                msg.chat.id,
                msg.message_id,
                e,
            )
            await asyncio.sleep(0.35)
    with suppress(Exception):
        await msg.bot.delete_message(msg.chat.id, msg.message_id)


async def _stop_payment_progress(
    sticker_msg: Message | None,
    msg: Message | None,
    task: asyncio.Task | None,
) -> None:
    if task:
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=1.5)
        except asyncio.CancelledError:
            logger.info('Payment progress task cancelled')
        except asyncio.TimeoutError:
            logger.warning('Payment progress task cancel timeout')
        except Exception as e:
            logger.warning('Payment progress task cancel error: %s', e)
    if msg:
        await _safe_delete_message(msg, 'Payment progress')
    if sticker_msg:
        await _safe_delete_message(sticker_msg, 'Payment progress sticker')


def _get_pending_action(data: dict) -> dict | None:
    payload = data.get('pending_action')
    if not payload:
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


def _format_date(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime('%Y-%m-%d')
    except Exception:
        return value


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace('Z', '+00:00')
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception:
        return None


async def _guard_pending_payment(user_id: int, provider: str, message: Message) -> bool:
    tx = await crud.get_pending_transaction_by_user(config.database_path, user_id, provider)
    if not tx:
        return False
    created_at = _parse_datetime(tx.get('created_at'))
    if not created_at:
        await crud.update_transaction_status(config.database_path, int(tx['id']), 'expired')
        logger.warning(
            'Expired pending payment with invalid created_at tx_id=%s user_id=%s provider=%s',
            tx.get('id'),
            user_id,
            provider,
        )
        return False
    age_sec = (datetime.utcnow() - created_at).total_seconds()
    if age_sec > POLL_TIMEOUT:
        await crud.update_transaction_status(config.database_path, int(tx['id']), 'expired')
        logger.info(
            'Expired stale pending payment tx_id=%s user_id=%s provider=%s age_sec=%.1f',
            tx.get('id'),
            user_id,
            provider,
            age_sec,
        )
        return False
    await message.answer('⏳ Оплата уже создана. Завершите предыдущую или дождитесь результата.')
    return True


async def _balance_link(bot) -> str:
    try:
        me = await bot.get_me()
        if me.username:
            return f'tg://resolve?domain={me.username}&text={quote("/balance")}'
    except Exception:
        pass
    return '/balance'


async def _expire_if_needed(user_id: int) -> None:
    sub = await crud.get_subscription(config.database_path, user_id)
    if not sub or sub.get('status') not in ('active', 'inactive'):
        return
    if int(sub.get('auto_renew', 0)) == 1:
        return
    try:
        end = datetime.fromisoformat(sub['current_period_end'])
    except Exception:
        return
    if datetime.utcnow() >= end:
        await crud.mark_subscription_status(config.database_path, user_id, 'expired')
        await crud.set_balance(config.database_path, user_id, 0)


async def _apply_subscription(
    user_id: int,
    plan_id: str,
    provider: str,
    auto_renew: int,
    payment_method_id: str | None,
) -> None:
    plan = get_plan(plan_id)
    if not plan:
        return

    start, end = calc_period(plan.days)
    await crud.set_balance(config.database_path, user_id, plan.generations)
    await crud.upsert_subscription(
        config.database_path,
        user_id=user_id,
        plan_id=plan.id,
        provider=provider,
        auto_renew=auto_renew,
        payment_method_id=payment_method_id,
        current_period_start=start,
        current_period_end=end,
        status='active',
    )

    user = await crud.get_user(config.database_path, user_id)
    if user and int(user.get('has_purchased', 0)) == 0:
        await crud.set_has_purchased(config.database_path, user_id, 1)
        referrer_id = await crud.get_referrer(config.database_path, user_id)
        rewarded = await crud.get_referrer_rewarded(config.database_path, user_id)
        if referrer_id and not rewarded:
            await crud.update_balance(config.database_path, referrer_id, config.ref_bonus)
            await crud.set_referrer_rewarded(config.database_path, user_id, 1)


async def _handle_pending_action(tx_id: int, user_id: int, chat_id: int, bot) -> str | None:
    pending = await crud.consume_pending_action(config.database_path, tx_id)
    if not pending:
        return None

    try:
        payload = json.loads(pending['action_payload'])
    except json.JSONDecodeError:
        return

    action_type = payload.get('type')
    if action_type == 'effect':
        effect_id = int(payload.get('effect_id', 0))
        photo_file_id = payload.get('photo_file_id')
        username = payload.get('username')
        if effect_id and photo_file_id:
            await run_effect_generation(bot, user_id, chat_id, effect_id, photo_file_id, username=username)
    elif action_type == 'photo_effect':
        effect_id = int(payload.get('effect_id', 0))
        photo_file_id = payload.get('photo_file_id')
        username = payload.get('username')
        if effect_id and photo_file_id:
            await run_photo_effect_generation(bot, user_id, chat_id, effect_id, photo_file_id, username=username)
    elif action_type == 'custom':
        photo_file_id = payload.get('photo_file_id')
        prompt = payload.get('prompt')
        duration = int(payload.get('duration', 0))
        photo_width = payload.get('photo_width')
        photo_height = payload.get('photo_height')
        username = payload.get('username')
        if photo_file_id and prompt and duration:
            await run_custom_generation(
                bot,
                user_id,
                chat_id,
                photo_file_id,
                prompt,
                duration,
                photo_width=photo_width,
                photo_height=photo_height,
                username=username,
            )
    elif action_type == 'photo_custom':
        photo_file_id = payload.get('photo_file_id')
        prompt = payload.get('prompt')
        username = payload.get('username')
        if photo_file_id and prompt:
            await run_photo_custom_generation(
                bot,
                user_id,
                chat_id,
                photo_file_id,
                prompt,
                username=username,
            )
    elif action_type == 'photo_text':
        prompt = payload.get('prompt')
        username = payload.get('username')
        if prompt:
            await run_text_image_generation(
                bot,
                user_id,
                chat_id,
                prompt,
                username=username,
            )
    elif action_type == 'tarot_full':
        question = payload.get('question')
        username = payload.get('username')
        cards_payload = payload.get('cards')
        first_card = payload.get('first_card')
        first_text = payload.get('first_text') or ''
        if question:
            sticker_msg, progress_msg, progress_task = await _start_payment_progress(bot, chat_id)
            ok = False
            try:
                if isinstance(first_card, dict):
                    ok = await run_tarot_continuation(
                        bot,
                        user_id=user_id,
                        chat_id=chat_id,
                        question=question,
                        username=username,
                        first_card_payload=first_card,
                        first_text=first_text,
                    )
                else:
                    ok = await run_paid_tarot_reading(
                        bot,
                        user_id=user_id,
                        chat_id=chat_id,
                        question=question,
                        username=username,
                        cards_payload=cards_payload if isinstance(cards_payload, list) else None,
                    )
                logger.info(
                    'Tarot payment flow result user_id=%s chat_id=%s ok=%s',
                    user_id,
                    chat_id,
                    ok,
                )
            finally:
                await _stop_payment_progress(sticker_msg, progress_msg, progress_task)
            if ok:
                try:
                    await bot.send_message(
                        chat_id,
                        '✅ Расклад завершен.\n'
                        'Если хотите, задайте новый вопрос или вернитесь в меню.',
                        reply_markup=tarot_after_reading_kb(),
                    )
                    logger.info(
                        'Tarot payment finish message sent user_id=%s chat_id=%s',
                        user_id,
                        chat_id,
                    )
                except Exception:
                    logger.exception(
                        'Tarot payment finish message failed user_id=%s chat_id=%s',
                        user_id,
                        chat_id,
                    )
        return action_type
    return action_type


def _parse_tx_plan_id(tx: dict) -> str | None:
    payload = tx.get('payload')
    if not payload:
        return None
    try:
        data = json.loads(payload)
        return data.get('plan_id')
    except Exception:
        return None


def _is_renew_tx(tx: dict) -> bool:
    payload = tx.get('payload')
    if not payload:
        return False
    try:
        data = json.loads(payload)
    except Exception:
        return False
    return bool(data.get('renew_now'))


def _parse_plan_id_from_payload(payload: str) -> str | None:
    if not payload:
        return None
    if payload.startswith('stars_sub:'):
        parts = payload.split(':')
        if len(parts) >= 3:
            return parts[1]
    try:
        data = json.loads(payload)
        return data.get('plan_id')
    except Exception:
        return None


def _build_receipt(amount_rub: int) -> dict | None:
    email = config.yookassa_receipt_email.strip() if config.yookassa_receipt_email else ''
    phone = config.yookassa_receipt_phone.strip() if config.yookassa_receipt_phone else ''
    tax_system = (config.yookassa_tax_system_code or '').strip()
    vat_code = (config.yookassa_vat_code or '').strip()
    item_name = (config.yookassa_item_name or 'Подписка на расклады').strip()
    if not tax_system:
        return None
    if not email and not phone:
        return None

    item: dict = {
        'description': item_name,
        'quantity': '1.00',
        'amount': {
            'value': f"{amount_rub:.2f}",
            'currency': 'RUB',
        },
        'vat_code': int(vat_code) if vat_code.isdigit() else 1,
    }
    if config.yookassa_payment_subject:
        item['payment_subject'] = config.yookassa_payment_subject
    if config.yookassa_payment_mode:
        item['payment_mode'] = config.yookassa_payment_mode

    receipt: dict = {
        'tax_system_code': int(tax_system),
        'items': [item],
    }
    if email:
        receipt['customer'] = {'email': email}
    else:
        receipt['customer'] = {'phone': phone}
    return receipt


async def _poll_yookassa_payment(bot, tx_id: int, user_id: int, chat_id: int, username: str | None = None) -> None:
    try:
        loop = asyncio.get_running_loop()
        start = loop.time()
        while True:
            tx = await crud.get_transaction(config.database_path, tx_id)
            if not tx:
                return
            if tx['status'] == 'paid':
                return

            try:
                payment = await asyncio.to_thread(yk.get_payment, tx['provider_payment_id'])
            except Exception as e:
                logger.error('YooKassa poll error tx_id=%s error=%s', tx_id, e)
                await asyncio.sleep(POLL_INTERVAL)
                continue

            status = getattr(payment, 'status', 'unknown')
            logger.info('YooKassa status tx_id=%s status=%s', tx_id, status)

            if status == 'succeeded':
                await crud.update_transaction_status(config.database_path, tx_id, 'paid')

                plan_id = _parse_tx_plan_id(tx)
                if plan_id:
                    payment_method_id = None
                    try:
                        if payment.payment_method and getattr(payment.payment_method, 'id', None):
                            payment_method_id = payment.payment_method.id
                    except Exception:
                        payment_method_id = None

                    await _apply_subscription(
                        user_id,
                        plan_id,
                        provider='yookassa',
                        auto_renew=1 if payment_method_id else 0,
                        payment_method_id=payment_method_id,
                    )

                    pending_type = await _handle_pending_action(tx_id, user_id, chat_id, bot)

                    if pending_type != 'tarot_full':
                        await bot.send_message(
                            chat_id,
                            '✅ Подписка активирована. Расклады начислены.',
                            reply_markup=payment_success_kb(),
                        )
                    if _is_renew_tx(tx):
                        await notify_admin(
                            bot,
                            config.admin_notify_ids,
                            f'✅ Продлил подписку (ЮKassa). Пользователь {user_id} (@{username or "-"}) , план {plan_id}'
                        )
                    else:
                        await notify_admin(
                            bot,
                            config.admin_notify_ids,
                            f'💰 Успешная оплата (ЮKassa). Пользователь {user_id} (@{username or "-"}) , план {plan_id}'
                        )
                else:
                    await bot.send_message(chat_id, '✅ Оплата прошла успешно.', reply_markup=payment_success_kb())
                if not plan_id:
                    await _handle_pending_action(tx_id, user_id, chat_id, bot)
                return

            if loop.time() - start > POLL_TIMEOUT:
                return

            await asyncio.sleep(POLL_INTERVAL)
    finally:
        _pending_yoo_tasks.pop(tx_id, None)


async def _start_yoo_payment(callback: CallbackQuery, state: FSMContext, plan_id: str) -> None:
    lock = _payment_locks.setdefault(callback.from_user.id, asyncio.Lock())
    if lock.locked():
        await callback.message.answer('⏳ Оплата уже создается. Подождите пару секунд.')
        return
    async with lock:
        if await _guard_pending_payment(callback.from_user.id, 'yookassa', callback.message):
            return
        plan = get_plan(plan_id)
        if not plan:
            await callback.message.answer('Тариф не найден.')
            return

        try:
            yk.configure(config.yookassa_shop_id, config.yookassa_secret_key)
        except Exception as e:
            await callback.message.answer('ЮKassa не настроена. Проверьте ключи.')
            await notify_admin(callback.bot, config.admin_notify_ids, f'❌ YooKassa config error: {e}')
            return

        bot_info = await callback.bot.get_me()
        return_url = f"https://t.me/{bot_info.username}"

        receipt = _build_receipt(plan.price_rub)
        payment = yk.create_payment(
            amount_rub=plan.price_rub,
            description=f"Подписка {plan.title}",
            return_url=return_url,
            metadata={'user_id': callback.from_user.id, 'plan_id': plan.id},
            save_payment_method=True,
            receipt=receipt,
        )

        tx_id = await crud.create_transaction(
            config.database_path,
            user_id=callback.from_user.id,
            amount=plan.price_rub,
            currency='RUB',
            credits=plan.generations,
            provider='yookassa',
            status='pending',
            provider_payment_id=payment.id,
            payload=json.dumps({'plan_id': plan.id, 'days': plan.days}),
        )

        pending = _get_pending_action(await state.get_data())
        if pending:
            await crud.create_pending_action(
                config.database_path,
                tx_id=tx_id,
                user_id=callback.from_user.id,
                action_type=pending.get('type', 'unknown'),
                action_payload=json.dumps(pending),
            )
            await state.clear()

        await callback.message.answer(
            'Оплата через ЮKassa. Нажмите кнопку ниже и завершите оплату.',
            reply_markup=pay_url_kb(payment.confirmation.confirmation_url)
        )

        if tx_id not in _pending_yoo_tasks:
            _pending_yoo_tasks[tx_id] = asyncio.create_task(
                _poll_yookassa_payment(
                    callback.bot,
                    tx_id,
                    callback.from_user.id,
                    callback.message.chat.id,
                    callback.from_user.username,
                )
            )


async def _start_stars_payment(callback: CallbackQuery, state: FSMContext, plan_id: str) -> None:
    lock = _payment_locks.setdefault(callback.from_user.id, asyncio.Lock())
    if lock.locked():
        await callback.message.answer('⏳ Оплата уже создается. Подождите пару секунд.')
        return
    async with lock:
        if await _guard_pending_payment(callback.from_user.id, 'stars', callback.message):
            return
        plan = get_plan(plan_id)
        if not plan:
            await callback.message.answer('Тариф не найден.')
            return

        payload = f"stars_sub:{plan_id}:{callback.from_user.id}:{uuid.uuid4().hex}"

        tx_id = await crud.create_transaction(
            config.database_path,
            user_id=callback.from_user.id,
            amount=plan.price_stars,
            currency='XTR',
            credits=plan.generations,
            provider='stars',
            status='pending',
            provider_payment_id=None,
            payload=payload,
        )

        pending = _get_pending_action(await state.get_data())
        if pending:
            await crud.create_pending_action(
                config.database_path,
                tx_id=tx_id,
                user_id=callback.from_user.id,
                action_type=pending.get('type', 'unknown'),
                action_payload=json.dumps(pending),
            )
            await state.clear()

        prices = [LabeledPrice(label=f"Подписка {plan.title}", amount=plan.price_stars)]
        await callback.bot.send_invoice(
            chat_id=callback.from_user.id,
            title='Подписка',
            description=f"{plan.generations} раскладов на {plan.title}",
            payload=payload,
            provider_token=config.stars_provider_token,
            currency='XTR',
            prices=prices,
        )


@router.callback_query(F.data == 'menu:balance')
async def cb_balance(callback: CallbackQuery) -> None:
    await callback.answer()
    await _expire_if_needed(callback.from_user.id)
    balance = await crud.get_balance(config.database_path, callback.from_user.id)
    sub = await crud.get_subscription(config.database_path, callback.from_user.id)
    plans = get_plans()

    is_active = sub and sub.get('status') == 'active' and int(sub.get('auto_renew', 0)) == 1
    if is_active:
        plan = get_plan(sub['plan_id'])
        end_date = _format_date(sub['current_period_end'])
        if plan:
            plan_title = f'{plan.price_rub} ₽ / {plan.title} — {plan.generations} раскладов'
        else:
            plan_title = sub['plan_id']
        await callback.message.answer(
            f'✅ <b>Подписка активна</b>\n'
            f'Тариф: <b>{plan_title}</b>\n'
            f'Остаток раскладов: <b>{balance}</b>\n'
            f'Обновление раскладов: <b>{end_date}</b>\n',
            reply_markup=subscription_manage_kb(sub['plan_id'], int(sub['auto_renew']) == 1)
        )
    else:
        week = plans.get('week')
        month = plans.get('month')
        balance_link = await _balance_link(callback.bot)
        balance_hint = f'<a href="{balance_link}">/balance</a>' if balance_link != '/balance' else '<code>/balance</code>'
        week_period = week.title.lower() if week else 'неделя'
        month_period = month.title.lower() if month else 'месяц'
        text = (
            f'❌ <b>Подписка не активна</b>\n'
            f'🔮 <b>Расклады:</b> {balance}\n\n'
            '<b>Подписка с автосписанием</b>\n'
            f'🔥 {week.price_rub} ₽ / {week_period} — {week.generations} раскладов\n'
            f'⭐ {month.price_rub} ₽ / {month_period} — {month.generations} раскладов\n\n'
            f'⭐ {week.price_stars} ⭐ — {week.generations} раскладов (разово)\n'
            f'⭐ {month.price_stars} ⭐ — {month.generations} раскладов (разово)\n\n'
            f'Отключить можно в любой момент в {balance_hint}.\n\n'
            f'Переходя к оплате, вы соглашаетесь с <a href="{config.offer_url}">офертой</a>.'
        )
        await callback.message.answer(
            text,
            reply_markup=choose_subscription_prompt_kb(),
        )


@router.message(Command('balance'))
async def cmd_balance(message: Message) -> None:
    await _expire_if_needed(message.from_user.id)
    balance = await crud.get_balance(config.database_path, message.from_user.id)
    sub = await crud.get_subscription(config.database_path, message.from_user.id)
    plans = get_plans()

    is_active = sub and sub.get('status') == 'active' and int(sub.get('auto_renew', 0)) == 1
    if is_active:
        plan = get_plan(sub['plan_id'])
        end_date = _format_date(sub['current_period_end'])
        if plan:
            plan_title = f'{plan.price_rub} ₽ / {plan.title} — {plan.generations} раскладов'
        else:
            plan_title = sub['plan_id']
        await message.answer(
            f'✅ <b>Подписка активна</b>\n'
            f'Тариф: <b>{plan_title}</b>\n'
            f'Остаток раскладов: <b>{balance}</b>\n'
            f'Обновление раскладов: <b>{end_date}</b>\n',
            reply_markup=subscription_manage_kb(sub['plan_id'], int(sub['auto_renew']) == 1)
        )
    else:
        week = plans.get('week')
        month = plans.get('month')
        balance_link = await _balance_link(message.bot)
        balance_hint = f'<a href="{balance_link}">/balance</a>' if balance_link != '/balance' else '<code>/balance</code>'
        week_period = week.title.lower() if week else 'неделя'
        month_period = month.title.lower() if month else 'месяц'
        text = (
            f'❌ <b>Подписка не активна</b>\n'
            f'🔮 <b>Расклады:</b> {balance}\n\n'
            '<b>Подписка с автосписанием</b>\n'
            f'🔥 {week.price_rub} ₽ / {week_period} — {week.generations} раскладов\n'
            f'⭐ {month.price_rub} ₽ / {month_period} — {month.generations} раскладов\n\n'
            f'⭐ {week.price_stars} ⭐ — {week.generations} раскладов (разово)\n'
            f'⭐ {month.price_stars} ⭐ — {month.generations} раскладов (разово)\n\n'
            f'Отключить можно в любой момент в {balance_hint}.\n\n'
            f'Переходя к оплате, вы соглашаетесь с <a href="{config.offer_url}">офертой</a>.'
        )
        await message.answer(
            text,
            reply_markup=choose_subscription_prompt_kb(),
        )


@router.callback_query(F.data == 'sub:choose')
async def cb_choose_subscription(callback: CallbackQuery) -> None:
    await callback.answer()
    plans = get_plans()
    await callback.message.answer('Выбери подписку 👇', reply_markup=choose_subscription_kb(plans))


@router.callback_query(F.data.startswith('sub:choose:yoo:'))
async def cb_choose_yoo(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    plan_id = callback.data.split(':', 3)[3]
    await _start_yoo_payment(callback, state, plan_id)


@router.callback_query(F.data.startswith('sub:choose:stars:'))
async def cb_choose_stars(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    plan_id = callback.data.split(':', 3)[3]
    await _start_stars_payment(callback, state, plan_id)


@router.callback_query(F.data.startswith('sub:plan:'))
async def cb_plan(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    plan_id = callback.data.split(':', 2)[2]
    plan = get_plan(plan_id)
    if not plan:
        await callback.message.answer('Тариф не найден.')
        return
    await callback.message.answer(
        f'Тариф: <b>{plan.generations} раскладов</b>.\nВыберите способ оплаты:',
        reply_markup=methods_kb(plan_id)
    )


@router.callback_query(F.data.startswith('sub:method:yoo:'))
async def cb_sub_pay_yoo(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    plan_id = callback.data.split(':', 3)[3]
    await _start_yoo_payment(callback, state, plan_id)


@router.callback_query(F.data.startswith('sub:method:stars:'))
async def cb_sub_pay_stars(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    plan_id = callback.data.split(':', 3)[3]
    await _start_stars_payment(callback, state, plan_id)


@router.callback_query(F.data == 'sub:renew_choose')
async def cb_sub_renew_choose(callback: CallbackQuery) -> None:
    await callback.answer()
    plans = get_plans()
    await callback.message.answer(
        '🔄 <b>Обновить подписку</b>\nВыберите тариф для продления:',
        reply_markup=choose_subscription_kb(
            plans,
            cb_yoo_prefix='sub:renew:yoo',
            cb_stars_prefix='sub:renew:stars',
        )
    )


@router.callback_query(F.data.startswith('sub:renew:yoo:'))
async def cb_sub_renew_yoo(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    plan_id = callback.data.split(':', 3)[3]
    plan = get_plan(plan_id)
    if not plan:
        await callback.message.answer('Тариф не найден.')
        return

    sub = await crud.get_subscription(config.database_path, callback.from_user.id)
    if sub and int(sub.get('auto_renew', 0)) == 1 and sub.get('payment_method_id'):
        lock = _payment_locks.setdefault(callback.from_user.id, asyncio.Lock())
        if lock.locked():
            await callback.message.answer('⏳ Оплата уже создается. Подождите пару секунд.')
            return
        async with lock:
            if await _guard_pending_payment(callback.from_user.id, 'yookassa', callback.message):
                return
            try:
                yk.configure(config.yookassa_shop_id, config.yookassa_secret_key)
                receipt = _build_receipt(plan.price_rub)
                payment = yk.create_recurrent_payment(
                    amount_rub=plan.price_rub,
                    description=f"Подписка {plan.title} — продление",
                    payment_method_id=sub['payment_method_id'],
                    metadata={'user_id': callback.from_user.id, 'plan_id': plan.id},
                    receipt=receipt,
                )
            except Exception as e:
                await callback.message.answer('Не удалось выполнить списание. Попробуйте позже.')
                if "payment_method_id" in str(e):
                    await crud.cancel_subscription(config.database_path, callback.from_user.id)
                await notify_admin(callback.bot, config.admin_notify_ids, f'❌ Продление не удалось (ошибка списания): {e}')
                return

            tx_id = await crud.create_transaction(
                config.database_path,
                user_id=callback.from_user.id,
                amount=plan.price_rub,
                currency='RUB',
                credits=plan.generations,
                provider='yookassa',
                status='pending',
                provider_payment_id=payment.id,
                payload=json.dumps({'plan_id': plan.id, 'days': plan.days, 'renew_now': True}),
            )

            _pending_yoo_tasks[tx_id] = asyncio.create_task(
                _poll_yookassa_payment(
                    callback.bot,
                    tx_id,
                    callback.from_user.id,
                    callback.message.chat.id,
                    callback.from_user.username,
                )
            )
            await callback.message.answer('🔄 Запрос на продление отправлен. Ожидаем подтверждение оплаты.')
            return

    await _start_yoo_payment(callback, state, plan_id)


@router.callback_query(F.data.startswith('sub:renew:stars:'))
async def cb_sub_renew_stars(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    plan_id = callback.data.split(':', 3)[3]
    await _start_stars_payment(callback, state, plan_id)


@router.callback_query(F.data.startswith('sub:renew_plan:'))
async def cb_sub_renew_plan(callback: CallbackQuery) -> None:
    await callback.answer()
    plan_id = callback.data.split(':', 2)[2]
    plan = get_plan(plan_id)
    if not plan:
        await callback.message.answer('Тариф не найден.')
        return

    sub = await crud.get_subscription(config.database_path, callback.from_user.id)
    if not sub:
        await callback.message.answer('Подписка не найдена. Оформите тариф в разделе Баланс.')
        return

    if int(sub.get('auto_renew', 0)) == 1 and sub.get('payment_method_id'):
        lock = _payment_locks.setdefault(callback.from_user.id, asyncio.Lock())
        if lock.locked():
            await callback.message.answer('⏳ Оплата уже создается. Подождите пару секунд.')
            return
        async with lock:
            if await _guard_pending_payment(callback.from_user.id, 'yookassa', callback.message):
                return
            try:
                yk.configure(config.yookassa_shop_id, config.yookassa_secret_key)
                payment = yk.create_recurrent_payment(
                    amount_rub=plan.price_rub,
                    description=f"Подписка {plan.title} — продление",
                    payment_method_id=sub['payment_method_id'],
                    metadata={'user_id': callback.from_user.id, 'plan_id': plan.id},
                )
            except Exception as e:
                await callback.message.answer('Не удалось выполнить списание. Попробуйте позже.')
                await notify_admin(callback.bot, config.admin_notify_ids, f'❌ Продление не удалось (ошибка списания): {e}')
                return

            tx_id = await crud.create_transaction(
                config.database_path,
                user_id=callback.from_user.id,
                amount=plan.price_rub,
                currency='RUB',
                credits=plan.generations,
                provider='yookassa',
                status='pending',
                provider_payment_id=payment.id,
                payload=json.dumps({'plan_id': plan.id, 'days': plan.days, 'renew_now': True}),
            )

            _pending_yoo_tasks[tx_id] = asyncio.create_task(
                _poll_yookassa_payment(
                    callback.bot,
                    tx_id,
                    callback.from_user.id,
                    callback.message.chat.id,
                    callback.from_user.username,
                )
            )
            await callback.message.answer('🔄 Запрос на продление отправлен. Ожидаем подтверждение оплаты.')
    else:
        await callback.message.answer(
            'Выберите способ оплаты для продления:',
            reply_markup=methods_kb(plan_id)
        )


@router.callback_query(F.data == 'sub:cancel')
async def cb_sub_cancel(callback: CallbackQuery) -> None:
    await callback.answer()
    await crud.cancel_subscription(config.database_path, callback.from_user.id)
    sub = await crud.get_subscription(config.database_path, callback.from_user.id)
    end_date = _format_date(sub['current_period_end']) if sub else 'неизвестно'
    await callback.message.answer(
        f'Подписка выключена. Расклады доступны до <b>{end_date}</b>.'
    )
    await notify_admin(
        callback.bot,
        config.admin_notify_ids,
        f'❌ Отключил подписку. Пользователь {callback.from_user.id} (@{callback.from_user.username or "-"})'
    )




@router.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery) -> None:
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message) -> None:
    payload = message.successful_payment.invoice_payload
    tx = await crud.get_transaction_by_payload(config.database_path, payload, 'stars')

    if not tx:
        await message.answer('Транзакция не найдена.')
        return

    if tx['status'] != 'paid':
        await crud.update_transaction_status(
            config.database_path,
            int(tx['id']),
            'paid',
            provider_payment_id=message.successful_payment.telegram_payment_charge_id,
        )

        plan_id = _parse_tx_plan_id(tx) or _parse_plan_id_from_payload(payload)
        if plan_id:
            await _apply_subscription(
                message.from_user.id,
                plan_id,
                provider='stars',
                auto_renew=0,
                payment_method_id=None,
            )

    pending_type = await _handle_pending_action(int(tx['id']), message.from_user.id, message.chat.id, message.bot)
    if pending_type != 'tarot_full':
        await message.answer(
            '✅ Подписка активирована. Расклады начислены.',
            reply_markup=payment_success_kb(),
        )
    await notify_admin(
        message.bot,
        config.admin_notify_ids,
        f"💰 Успешная оплата (Stars). Пользователь {message.from_user.id} (@{message.from_user.username or '-'})"
    )

