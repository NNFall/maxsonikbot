from __future__ import annotations

import asyncio
import logging
import json
from datetime import datetime, timedelta

from aiogram import Bot

from config import load_config
from database import crud
from services import yookassa as yk
from services.notify import notify_admin
from services.subscriptions import get_plan, calc_period

logger = logging.getLogger(__name__)


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
    await crud.set_balance(load_config().database_path, user_id, plan.generations)
    await crud.upsert_subscription(
        load_config().database_path,
        user_id=user_id,
        plan_id=plan.id,
        provider=provider,
        auto_renew=auto_renew,
        payment_method_id=payment_method_id,
        current_period_start=start,
        current_period_end=end,
        status='active',
    )


def _is_missing_payment_method_error(error_text: str) -> bool:
    lowered = (error_text or '').lower()
    return "payment_method_id doesn't exist" in lowered or 'payment_method_id' in lowered and 'exist' in lowered


def _fmt_ts(value: datetime) -> str:
    return value.strftime('%Y-%m-%d %H:%M')


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


async def _resolve_username(bot: Bot, user_id: int) -> str:
    try:
        chat = await bot.get_chat(user_id)
        username = getattr(chat, 'username', None)
        return f'@{username}' if username else '-'
    except Exception:
        return '-'


def _build_autorenew_success_text(
    user_id: int,
    username: str,
    plan_id: str,
    plan_title: str,
    tokens: int,
    amount_rub: int,
    payment_id: str | None,
) -> str:
    return (
        '🔄 Автосписание - УСПЕХ\n'
        f'User ID: {user_id} ({username})\n'
        f'Тариф: {plan_id} ({plan_title} - {tokens} токенов)\n'
        f'Сумма: {amount_rub} RUB\n'
        'Status: succeeded\n'
        f'Payment ID: {payment_id or "-"}'
    )


def _build_autorenew_error_text(
    user_id: int,
    username: str,
    plan_id: str,
    plan_title: str,
    tokens: int,
    amount_rub: int,
    status_or_error: str,
    payment_id: str | None,
    reason: str,
    retry_at: datetime | None,
) -> str:
    lines = [
        '🔄 Автосписание - ОШИБКА',
        f'User ID: {user_id} ({username})',
        f'Тариф: {plan_id} ({plan_title} - {tokens} токенов)',
        f'Сумма: {amount_rub} RUB',
        f'Status: {status_or_error}',
        f'Payment ID: {payment_id or "-"}',
        f'Причина: {reason}',
    ]
    if retry_at:
        lines.append(f'Следующая попытка: {_fmt_ts(retry_at)}')
    return '\n'.join(lines)


async def _schedule_retry_next_day(config, sub: dict) -> datetime:
    now_dt = datetime.utcnow()
    current_end = _parse_iso(sub.get('current_period_end'))
    base = current_end if current_end and current_end > now_dt else now_dt
    retry_at = base + timedelta(days=1)
    await crud.set_subscription_period_end(
        config.database_path,
        int(sub['user_id']),
        retry_at.isoformat(timespec='seconds'),
    )
    logger.info(
        'Autorenew retry scheduled user_id=%s plan_id=%s next_retry=%s',
        sub['user_id'],
        sub.get('plan_id'),
        retry_at.isoformat(timespec='seconds'),
    )
    return retry_at


async def process_due_subscriptions(bot: Bot) -> None:
    config = load_config()
    now_iso = datetime.utcnow().isoformat(timespec='seconds')

    # expire non-auto subscriptions
    expired = await crud.list_expired_subscriptions(config.database_path, now_iso)
    for sub in expired:
        await crud.mark_subscription_status(config.database_path, sub['user_id'], 'expired')
        await crud.set_balance(config.database_path, sub['user_id'], 0)
        try:
            await bot.send_message(sub['user_id'], 'Срок подписки истек. расклады обнулены.')
        except Exception:
            pass

    due = await crud.list_due_subscriptions(config.database_path, now_iso)
    if not due:
        return

    try:
        yk.configure(config.yookassa_shop_id, config.yookassa_secret_key)
    except Exception as e:
        await notify_admin(bot, config.admin_notify_ids, f'❌ YooKassa config error: {e}')
        return

    for sub in due:
        plan = get_plan(sub['plan_id'])
        if not plan:
            logger.warning('Autorenew skipped unknown plan user_id=%s plan_id=%s', sub['user_id'], sub.get('plan_id'))
            continue

        username = await _resolve_username(bot, int(sub['user_id']))

        if not sub.get('payment_method_id'):
            await crud.expire_subscription(config.database_path, int(sub['user_id']))
            await crud.set_balance(config.database_path, int(sub['user_id']), 0)
            logger.error(
                'Autorenew expired due to missing payment_method_id user_id=%s plan_id=%s',
                sub['user_id'],
                plan.id,
            )
            await notify_admin(
                bot,
                config.admin_notify_ids,
                _build_autorenew_error_text(
                    user_id=int(sub['user_id']),
                    username=username,
                    plan_id=plan.id,
                    plan_title=plan.title,
                    tokens=plan.generations,
                    amount_rub=plan.price_rub,
                    status_or_error='error',
                    payment_id=None,
                    reason="payment_method_id doesn't exist",
                    retry_at=None,
                ) + '\nПодписка переведена в expired, баланс обнулен.',
            )
            continue

        logger.info(
            'Autorenew attempt start user_id=%s plan_id=%s current_period_end=%s',
            sub['user_id'],
            plan.id,
            sub.get('current_period_end'),
        )

        try:
            receipt = None
            if config.yookassa_tax_system_code and (config.yookassa_receipt_email or config.yookassa_receipt_phone):
                item = {
                    'description': config.yookassa_item_name or 'Подписка на расклады',
                    'quantity': '1.00',
                    'amount': {
                        'value': f"{plan.price_rub:.2f}",
                        'currency': 'RUB',
                    },
                    'vat_code': int(config.yookassa_vat_code) if str(config.yookassa_vat_code).isdigit() else 1,
                }
                if config.yookassa_payment_subject:
                    item['payment_subject'] = config.yookassa_payment_subject
                if config.yookassa_payment_mode:
                    item['payment_mode'] = config.yookassa_payment_mode

                receipt = {
                    'tax_system_code': int(config.yookassa_tax_system_code),
                    'items': [item],
                    'customer': {
                        'email': config.yookassa_receipt_email
                    } if config.yookassa_receipt_email else {
                        'phone': config.yookassa_receipt_phone
                    },
                }
            payment = await asyncio.to_thread(
                yk.create_recurrent_payment,
                plan.price_rub,
                f'Подписка {plan.title} - продление (автосписание)',
                sub['payment_method_id'],
                {'user_id': sub['user_id'], 'plan_id': plan.id},
                receipt,
            )
        except Exception as e:
            error_text = str(e)
            logger.error('Autorenew charge failed user_id=%s plan_id=%s error=%s', sub['user_id'], plan.id, error_text)
            if _is_missing_payment_method_error(error_text):
                await crud.expire_subscription(config.database_path, int(sub['user_id']))
                await crud.set_balance(config.database_path, int(sub['user_id']), 0)
                logger.error('Autorenew marked expired user_id=%s plan_id=%s', sub['user_id'], plan.id)
                await notify_admin(
                    bot,
                    config.admin_notify_ids,
                    _build_autorenew_error_text(
                        user_id=int(sub['user_id']),
                        username=username,
                        plan_id=plan.id,
                        plan_title=plan.title,
                        tokens=plan.generations,
                        amount_rub=plan.price_rub,
                        status_or_error='error',
                        payment_id=None,
                        reason=error_text,
                        retry_at=None,
                    ) + '\nПодписка переведена в expired, баланс обнулен.',
                )
                continue

            retry_at = await _schedule_retry_next_day(config, sub)
            await notify_admin(
                bot,
                config.admin_notify_ids,
                _build_autorenew_error_text(
                    user_id=int(sub['user_id']),
                    username=username,
                    plan_id=plan.id,
                    plan_title=plan.title,
                    tokens=plan.generations,
                    amount_rub=plan.price_rub,
                    status_or_error='error',
                    payment_id=None,
                    reason=error_text,
                    retry_at=retry_at,
                ),
            )
            continue

        status = getattr(payment, 'status', 'unknown')
        payment_id = getattr(payment, 'id', None)
        logger.info(
            'Autorenew payment response user_id=%s plan_id=%s status=%s payment_id=%s',
            sub['user_id'],
            plan.id,
            status,
            payment_id or '-',
        )
        if status == 'succeeded':
            await crud.create_transaction(
                config.database_path,
                user_id=sub['user_id'],
                amount=plan.price_rub,
                currency='RUB',
                credits=plan.generations,
                provider='yookassa',
                status='paid',
                provider_payment_id=payment_id,
                payload=json.dumps({'plan_id': plan.id, 'auto_renew': True}),
            )
            await _apply_subscription(
                sub['user_id'],
                plan.id,
                provider='yookassa',
                auto_renew=1,
                payment_method_id=sub['payment_method_id'],
            )
            renewed = await crud.get_subscription(config.database_path, int(sub['user_id']))
            logger.info(
                'Autorenew period renewed user_id=%s plan_id=%s period_start=%s period_end=%s',
                sub['user_id'],
                plan.id,
                renewed.get('current_period_start') if renewed else '-',
                renewed.get('current_period_end') if renewed else '-',
            )
            await notify_admin(
                bot,
                config.admin_notify_ids,
                _build_autorenew_success_text(
                    user_id=int(sub['user_id']),
                    username=username,
                    plan_id=plan.id,
                    plan_title=plan.title,
                    tokens=plan.generations,
                    amount_rub=plan.price_rub,
                    payment_id=payment_id,
                ),
            )
        else:
            retry_at = await _schedule_retry_next_day(config, sub)
            logger.warning('Autorenew payment non-succeeded user_id=%s plan_id=%s status=%s', sub['user_id'], plan.id, status)
            await notify_admin(
                bot,
                config.admin_notify_ids,
                _build_autorenew_error_text(
                    user_id=int(sub['user_id']),
                    username=username,
                    plan_id=plan.id,
                    plan_title=plan.title,
                    tokens=plan.generations,
                    amount_rub=plan.price_rub,
                    status_or_error=status,
                    payment_id=payment_id,
                    reason=f'ЮKassa вернула статус {status}',
                    retry_at=retry_at,
                ),
            )


async def subscription_watcher(bot: Bot, interval_sec: int = 60) -> None:
    while True:
        try:
            await process_due_subscriptions(bot)
        except Exception as e:
            logger.error('Subscription watcher error: %s', e)
        await asyncio.sleep(interval_sec)

