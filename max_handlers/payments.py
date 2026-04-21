from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from maxapi import F, Router
from maxapi.context import BaseContext
from maxapi.types import Command, MessageCallback, MessageCreated

from config import load_config
from database import crud
from max_keyboards import (
    choose_subscription_attachments,
    choose_subscription_prompt_attachments,
    pay_url_attachments,
    payment_success_attachments,
    subscription_manage_attachments,
    tarot_after_reading_attachments,
)
from services import yookassa as yk
from services.notify import notify_admin
from services.subscriptions import calc_period, get_plan, get_plans
from services.tarot_reading_max import run_paid_tarot_reading, run_tarot_continuation

router = Router("payments")
config = load_config()
logger = logging.getLogger(__name__)

POLL_INTERVAL = 5
POLL_TIMEOUT = 600

_pending_yoo_tasks: dict[int, asyncio.Task] = {}
_payment_locks: dict[int, asyncio.Lock] = {}


def _user_id_from_event(event: MessageCreated | MessageCallback) -> int | None:
    if getattr(event, "from_user", None):
        return int(event.from_user.user_id)
    if isinstance(event, MessageCreated) and event.message.sender:
        return int(event.message.sender.user_id)
    if isinstance(event, MessageCallback):
        return int(event.callback.user.user_id)
    return None


def _chat_id_from_event(event: MessageCreated | MessageCallback) -> int | None:
    message = getattr(event, "message", None)
    if message and message.recipient:
        return message.recipient.chat_id
    return None


def _username_from_event(event: MessageCreated | MessageCallback) -> str | None:
    if getattr(event, "from_user", None):
        return event.from_user.username
    if isinstance(event, MessageCreated) and event.message.sender:
        return event.message.sender.username
    if isinstance(event, MessageCallback):
        return event.callback.user.username
    return None


def _format_date(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return value


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception:
        return None


def _get_pending_action(data: dict) -> dict | None:
    payload = data.get("pending_action")
    if not payload:
        return None
    if isinstance(payload, dict):
        return payload
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


async def _expire_if_needed(user_id: int) -> None:
    sub = await crud.get_subscription(config.database_path, user_id)
    if not sub or sub.get("status") not in ("active", "inactive"):
        return
    if int(sub.get("auto_renew", 0)) == 1:
        return
    try:
        end = datetime.fromisoformat(sub["current_period_end"])
    except Exception:
        return
    if datetime.utcnow() >= end:
        await crud.mark_subscription_status(config.database_path, user_id, "expired")
        await crud.set_balance(config.database_path, user_id, 0)


def _build_receipt(amount_rub: int) -> dict | None:
    email = config.yookassa_receipt_email.strip() if config.yookassa_receipt_email else ""
    phone = config.yookassa_receipt_phone.strip() if config.yookassa_receipt_phone else ""
    tax_system = (config.yookassa_tax_system_code or "").strip()
    vat_code = (config.yookassa_vat_code or "").strip()
    item_name = (config.yookassa_item_name or "Подписка на расклады").strip()
    if not tax_system:
        return None
    if not email and not phone:
        return None

    item: dict = {
        "description": item_name,
        "quantity": "1.00",
        "amount": {
            "value": f"{amount_rub:.2f}",
            "currency": "RUB",
        },
        "vat_code": int(vat_code) if vat_code.isdigit() else 1,
    }
    if config.yookassa_payment_subject:
        item["payment_subject"] = config.yookassa_payment_subject
    if config.yookassa_payment_mode:
        item["payment_mode"] = config.yookassa_payment_mode

    receipt: dict = {"tax_system_code": int(tax_system), "items": [item]}
    receipt["customer"] = {"email": email} if email else {"phone": phone}
    return receipt


async def _guard_pending_payment(user_id: int, provider: str, bot, chat_id: int) -> bool:
    tx = await crud.get_pending_transaction_by_user(config.database_path, user_id, provider)
    if not tx:
        return False
    created_at = _parse_datetime(tx.get("created_at"))
    if not created_at:
        await crud.update_transaction_status(config.database_path, int(tx["id"]), "expired")
        return False
    age_sec = (datetime.utcnow() - created_at).total_seconds()
    if age_sec > POLL_TIMEOUT:
        await crud.update_transaction_status(config.database_path, int(tx["id"]), "expired")
        return False
    await bot.send_message(chat_id=chat_id, text="⏳ Оплата уже создана. Завершите предыдущую или дождитесь результата.")
    return True


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
        status="active",
    )

    user = await crud.get_user(config.database_path, user_id)
    if user and int(user.get("has_purchased", 0)) == 0:
        await crud.set_has_purchased(config.database_path, user_id, 1)
        referrer_id = await crud.get_referrer(config.database_path, user_id)
        rewarded = await crud.get_referrer_rewarded(config.database_path, user_id)
        if referrer_id and not rewarded:
            await crud.update_balance(config.database_path, referrer_id, config.ref_bonus)
            await crud.set_referrer_rewarded(config.database_path, user_id, 1)


def _parse_tx_plan_id(tx: dict) -> str | None:
    payload = tx.get("payload")
    if not payload:
        return None
    try:
        data = json.loads(payload)
        return data.get("plan_id")
    except Exception:
        return None


def _is_renew_tx(tx: dict) -> bool:
    payload = tx.get("payload")
    if not payload:
        return False
    try:
        data = json.loads(payload)
        return bool(data.get("renew_now"))
    except Exception:
        return False


async def _handle_pending_action(tx_id: int, user_id: int, chat_id: int, bot) -> str | None:
    pending = await crud.consume_pending_action(config.database_path, tx_id)
    if not pending:
        return None
    try:
        payload = json.loads(pending["action_payload"])
    except json.JSONDecodeError:
        return None

    action_type = payload.get("type")
    if action_type != "tarot_full":
        return action_type

    question = payload.get("question")
    username = payload.get("username")
    cards_payload = payload.get("cards")
    first_card = payload.get("first_card")
    first_text = payload.get("first_text") or ""
    if not question:
        return action_type

    await bot.send_message(
        chat_id=chat_id,
        text="✅ Оплата прошла успешно.\nПродолжаю расклад...",
    )

    ok = False
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
    if ok:
        await bot.send_message(
            chat_id=chat_id,
            text="✅ Расклад завершен.\nЕсли хотите, задайте новый вопрос или вернитесь в меню.",
            attachments=tarot_after_reading_attachments(),
        )
    return action_type


async def _poll_yookassa_payment(bot, tx_id: int, user_id: int, chat_id: int, username: str | None = None) -> None:
    try:
        loop = asyncio.get_running_loop()
        start = loop.time()
        while True:
            tx = await crud.get_transaction(config.database_path, tx_id)
            if not tx:
                return
            if tx["status"] == "paid":
                return
            try:
                payment = await asyncio.to_thread(yk.get_payment, tx["provider_payment_id"])
            except Exception as e:
                logger.error("YooKassa poll error tx_id=%s error=%s", tx_id, e)
                await asyncio.sleep(POLL_INTERVAL)
                continue

            status = getattr(payment, "status", "unknown")
            logger.info("YooKassa status tx_id=%s status=%s", tx_id, status)
            if status == "succeeded":
                await crud.update_transaction_status(config.database_path, tx_id, "paid")
                plan_id = _parse_tx_plan_id(tx)
                if plan_id:
                    payment_method_id = None
                    try:
                        if payment.payment_method and getattr(payment.payment_method, "id", None):
                            payment_method_id = payment.payment_method.id
                    except Exception:
                        payment_method_id = None
                    await _apply_subscription(
                        user_id,
                        plan_id,
                        provider="yookassa",
                        auto_renew=1 if payment_method_id else 0,
                        payment_method_id=payment_method_id,
                    )
                    pending_type = await _handle_pending_action(tx_id, user_id, chat_id, bot)
                    if pending_type != "tarot_full":
                        await bot.send_message(
                            chat_id=chat_id,
                            text="✅ Подписка активирована. Расклады начислены.",
                            attachments=payment_success_attachments(),
                        )
                    if _is_renew_tx(tx):
                        await notify_admin(
                            bot,
                            config.admin_notify_ids,
                            f"✅ Продлил подписку (ЮKassa). Пользователь {user_id} (@{username or '-'}) , план {plan_id}",
                        )
                    else:
                        await notify_admin(
                            bot,
                            config.admin_notify_ids,
                            f"💰 Успешная оплата (ЮKassa). Пользователь {user_id} (@{username or '-'}) , план {plan_id}",
                        )
                else:
                    await bot.send_message(
                        chat_id=chat_id,
                        text="✅ Оплата прошла успешно.",
                        attachments=payment_success_attachments(),
                    )
                    await _handle_pending_action(tx_id, user_id, chat_id, bot)
                return

            if loop.time() - start > POLL_TIMEOUT:
                return
            await asyncio.sleep(POLL_INTERVAL)
    finally:
        _pending_yoo_tasks.pop(tx_id, None)


async def _start_yoo_payment(event: MessageCallback, context: BaseContext, plan_id: str, renew_now: bool = False) -> None:
    user_id = _user_id_from_event(event)
    chat_id = _chat_id_from_event(event)
    username = _username_from_event(event)
    if user_id is None or chat_id is None:
        await event.answer()
        return

    lock = _payment_locks.setdefault(user_id, asyncio.Lock())
    if lock.locked():
        await event.answer()
        await event.bot.send_message(chat_id=chat_id, text="⏳ Оплата уже создается. Подождите пару секунд.")
        return

    async with lock:
        if await _guard_pending_payment(user_id, "yookassa", event.bot, chat_id):
            return
        plan = get_plan(plan_id)
        if not plan:
            await event.bot.send_message(chat_id=chat_id, text="Тариф не найден.")
            return

        sub = await crud.get_subscription(config.database_path, user_id)
        has_recurrent = bool(sub and int(sub.get("auto_renew", 0)) == 1 and sub.get("payment_method_id"))
        if renew_now and has_recurrent:
            try:
                yk.configure(config.yookassa_shop_id, config.yookassa_secret_key)
                receipt = _build_receipt(plan.price_rub)
                payment = yk.create_recurrent_payment(
                    amount_rub=plan.price_rub,
                    description=f"Подписка {plan.title} — продление",
                    payment_method_id=sub["payment_method_id"],
                    metadata={"user_id": user_id, "plan_id": plan.id},
                    receipt=receipt,
                )
            except Exception as e:
                await event.bot.send_message(chat_id=chat_id, text="Не удалось выполнить списание. Попробуйте позже.")
                await notify_admin(
                    event.bot,
                    config.admin_notify_ids,
                    f"❌ Продление не удалось (ошибка списания): {e}",
                )
                return
            tx_payload = {"plan_id": plan.id, "days": plan.days, "renew_now": True}
            tx_id = await crud.create_transaction(
                config.database_path,
                user_id=user_id,
                amount=plan.price_rub,
                currency="RUB",
                credits=plan.generations,
                provider="yookassa",
                status="pending",
                provider_payment_id=payment.id,
                payload=json.dumps(tx_payload),
            )
            _pending_yoo_tasks[tx_id] = asyncio.create_task(
                _poll_yookassa_payment(event.bot, tx_id, user_id, chat_id, username)
            )
            await event.bot.send_message(chat_id=chat_id, text="🔄 Запрос на продление отправлен. Ожидаем подтверждение оплаты.")
            return

        try:
            yk.configure(config.yookassa_shop_id, config.yookassa_secret_key)
        except Exception as e:
            await event.bot.send_message(chat_id=chat_id, text="ЮKassa не настроена. Проверьте ключи.")
            await notify_admin(event.bot, config.admin_notify_ids, f"❌ YooKassa config error: {e}")
            return

        bot_info = await event.bot.get_me()
        return_url = f"https://max.ru/{bot_info.username}"
        receipt = _build_receipt(plan.price_rub)
        payment = yk.create_payment(
            amount_rub=plan.price_rub,
            description=f"Подписка {plan.title}",
            return_url=return_url,
            metadata={"user_id": user_id, "plan_id": plan.id},
            save_payment_method=True,
            receipt=receipt,
        )
        tx_payload = {"plan_id": plan.id, "days": plan.days}
        if renew_now:
            tx_payload["renew_now"] = True
        tx_id = await crud.create_transaction(
            config.database_path,
            user_id=user_id,
            amount=plan.price_rub,
            currency="RUB",
            credits=plan.generations,
            provider="yookassa",
            status="pending",
            provider_payment_id=payment.id,
            payload=json.dumps(tx_payload),
        )

        pending = _get_pending_action(await context.get_data())
        if pending:
            await crud.create_pending_action(
                config.database_path,
                tx_id=tx_id,
                user_id=user_id,
                action_type=pending.get("type", "unknown"),
                action_payload=json.dumps(pending),
            )
            await context.update_data(pending_action="")

        await event.bot.send_message(
            chat_id=chat_id,
            text="Оплата через ЮKassa. Нажмите кнопку ниже и завершите оплату.",
            attachments=pay_url_attachments(payment.confirmation.confirmation_url),
        )
        if tx_id not in _pending_yoo_tasks:
            _pending_yoo_tasks[tx_id] = asyncio.create_task(
                _poll_yookassa_payment(event.bot, tx_id, user_id, chat_id, username)
            )


async def _send_balance(bot, chat_id: int, user_id: int) -> None:
    await _expire_if_needed(user_id)
    balance = await crud.get_balance(config.database_path, user_id)
    sub = await crud.get_subscription(config.database_path, user_id)
    plans = get_plans()

    is_active = bool(sub and sub.get("status") == "active" and int(sub.get("auto_renew", 0)) == 1)
    if is_active:
        plan = get_plan(sub["plan_id"])
        end_date = _format_date(sub["current_period_end"])
        if plan:
            plan_title = f"{plan.price_rub} ₽ / {plan.title} — {plan.generations} раскладов"
        else:
            plan_title = sub["plan_id"]
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "✅ <b>Подписка активна</b>\n"
                f"Тариф: <b>{plan_title}</b>\n"
                f"Остаток раскладов: <b>{balance}</b>\n"
                f"Обновление раскладов: <b>{end_date}</b>"
            ),
            attachments=subscription_manage_attachments(int(sub.get("auto_renew", 0)) == 1),
        )
        return

    week = plans.get("week")
    month = plans.get("month")
    week_period = week.title.lower() if week else "неделя"
    month_period = month.title.lower() if month else "месяц"
    await bot.send_message(
        chat_id=chat_id,
        text=(
            "❌ <b>Подписка не активна</b>\n"
            f"🔮 <b>Расклады:</b> {balance}\n\n"
            "<b>Подписка с автосписанием</b>\n"
            f"🔥 {week.price_rub} ₽ / {week_period} — {week.generations} раскладов\n"
            f"⭐ {month.price_rub} ₽ / {month_period} — {month.generations} раскладов\n\n"
            f"Переходя к оплате, вы соглашаетесь с <a href=\"{config.offer_url}\">офертой</a>."
        ),
        attachments=choose_subscription_prompt_attachments(),
    )


@router.message_created(Command("balance"))
async def cmd_balance(event: MessageCreated) -> None:
    user_id = _user_id_from_event(event)
    chat_id = _chat_id_from_event(event)
    if user_id is None or chat_id is None:
        return
    await _send_balance(event.bot, chat_id, user_id)


@router.message_callback(F.callback.payload == "menu:balance")
async def cb_balance(event: MessageCallback) -> None:
    user_id = _user_id_from_event(event)
    chat_id = _chat_id_from_event(event)
    if user_id is None or chat_id is None:
        await event.answer()
        return
    await event.answer()
    await _send_balance(event.bot, chat_id, user_id)


@router.message_callback(F.callback.payload == "sub:choose")
async def cb_choose_subscription(event: MessageCallback) -> None:
    chat_id = _chat_id_from_event(event)
    if chat_id is None:
        await event.answer()
        return
    await event.answer()
    await event.bot.send_message(
        chat_id=chat_id,
        text="Выберите подписку 👇",
        attachments=choose_subscription_attachments(get_plans()),
    )


@router.message_callback(F.callback.payload.startswith("sub:choose:yoo:"))
async def cb_choose_yoo(event: MessageCallback, context: BaseContext) -> None:
    payload = event.callback.payload or ""
    plan_id = payload.split(":")[-1]
    await event.answer()
    await _start_yoo_payment(event, context, plan_id)


@router.message_callback(F.callback.payload == "sub:renew_choose")
async def cb_sub_renew_choose(event: MessageCallback) -> None:
    chat_id = _chat_id_from_event(event)
    if chat_id is None:
        await event.answer()
        return
    await event.answer()
    await event.bot.send_message(
        chat_id=chat_id,
        text="🔄 <b>Обновить подписку</b>\nВыберите тариф для продления:",
        attachments=choose_subscription_attachments(get_plans(), cb_yoo_prefix="sub:renew:yoo"),
    )


@router.message_callback(F.callback.payload.startswith("sub:renew:yoo:"))
async def cb_sub_renew_yoo(event: MessageCallback, context: BaseContext) -> None:
    payload = event.callback.payload or ""
    plan_id = payload.split(":")[-1]
    await event.answer()
    await _start_yoo_payment(event, context, plan_id, renew_now=True)


@router.message_callback(F.callback.payload == "sub:cancel")
async def cb_sub_cancel(event: MessageCallback) -> None:
    user_id = _user_id_from_event(event)
    chat_id = _chat_id_from_event(event)
    username = _username_from_event(event)
    if user_id is None or chat_id is None:
        await event.answer()
        return
    await event.answer()
    await crud.cancel_subscription(config.database_path, user_id)
    sub = await crud.get_subscription(config.database_path, user_id)
    end_date = _format_date(sub["current_period_end"]) if sub else "неизвестно"
    await event.bot.send_message(
        chat_id=chat_id,
        text=f"Подписка выключена. Расклады доступны до <b>{end_date}</b>.",
    )
    await notify_admin(
        event.bot,
        config.admin_notify_ids,
        f"❌ Отключил подписку. Пользователь {user_id} (@{username or '-'})",
    )
