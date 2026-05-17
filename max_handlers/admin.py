from __future__ import annotations

import html
import secrets
from datetime import datetime

from maxapi import Router
from maxapi.types import Command, MessageCreated

from config import load_config
from database import crud
from max_keyboards import admin_help_attachments
from services.notify import notify_admin
from services.subscriptions import get_plans

router = Router("admin")
config = load_config()

ADMIN_HELP_TEXT = (
    "<b>Админ-команды</b>\n\n"
    "<code>/admin_help</code> — список админ-команд\n"
    "<code>/botstats</code> — общая статистика бота\n"
    "<code>/adstats &lt;метка&gt;</code> — статистика по одной UTM-метке\n"
    "<code>/adstats_all</code> — статистика по всем UTM-меткам\n"
    "<code>/adtag &lt;метка&gt;</code> — ссылка с UTM-меткой\n"
    "<code>/genpromo &lt;толкования&gt;</code> — создать промокод\n\n"
    "<code>/sub_check &lt;ID&gt;</code> — проверить баланс пользователя\n"
    "<code>/sub_on &lt;ID&gt; &lt;amount&gt;</code> — начислить толкования\n"
    "<code>/sub_off &lt;ID&gt;</code> — обнулить баланс\n"
    "<code>/sub_cancel &lt;ID&gt;</code> — отключить автопродление\n\n"
    "<code>/admin_add &lt;ID&gt;</code> — добавить админа (только owner)\n"
    "<code>/admin_del &lt;ID&gt;</code> — удалить админа (только owner)\n"
    "<code>/admin_list</code> — список админов (только owner)\n"
    "<code>/notify_test</code> — тест доставки админ-уведомлений"
)


def _event_user_id(event: MessageCreated) -> int | None:
    if event.from_user:
        return int(event.from_user.user_id)
    if event.message.sender:
        return int(event.message.sender.user_id)
    return None


def _event_chat_id(event: MessageCreated) -> int | None:
    recipient = event.message.recipient
    return recipient.chat_id if recipient else None


async def _is_admin(user_id: int) -> bool:
    if user_id in config.admin_ids:
        return True
    return await crud.is_admin(config.database_path, user_id)


def _is_owner(user_id: int) -> bool:
    return user_id in config.admin_ids


async def _answer(event: MessageCreated, text: str) -> None:
    chat_id = _event_chat_id(event)
    if chat_id is None:
        return
    await event.bot.send_message(chat_id=chat_id, text=text)


async def _ensure_admin(event: MessageCreated) -> tuple[bool, int | None]:
    user_id = _event_user_id(event)
    if user_id is None:
        return False, None
    if await _is_admin(user_id):
        return True, user_id
    await _answer(
        event,
        f"⛔ Нет доступа.\nВаш ID: <code>{user_id}</code>\nПередайте этот ID владельцу для выдачи админки.",
    )
    return False, user_id


@router.message_created(Command("admin_help"))
async def cmd_admin_help(event: MessageCreated) -> None:
    user_id = _event_user_id(event)
    if user_id is None or not await _is_admin(user_id):
        return
    chat_id = _event_chat_id(event)
    if chat_id is None:
        return
    await event.bot.send_message(
        chat_id=chat_id,
        text=ADMIN_HELP_TEXT,
        attachments=admin_help_attachments(),
    )


@router.message_created(Command("notify_test"))
async def cmd_notify_test(event: MessageCreated) -> None:
    user_id = _event_user_id(event)
    if user_id is None or not await _is_admin(user_id):
        return
    chat_id = _event_chat_id(event)
    if chat_id is None:
        return

    report = await notify_admin(
        event.bot,
        config.admin_notify_ids,
        "🧪 Тест админ-уведомлений: если видите это сообщение, доставка работает.",
    )
    resolved = report.get("resolved_ids", [])
    delivered = report.get("delivered", [])
    failed = report.get("failed", [])
    failed_ids = ", ".join(str(item.get("admin_id")) for item in failed) if failed else "-"

    await event.bot.send_message(
        chat_id=chat_id,
        text=(
            "✅ Тест уведомлений выполнен.\n"
            f"Всего админов в выборке: {len(resolved)}\n"
            f"Доставлено: {len(delivered)}\n"
            f"Не доставлено: {len(failed)}\n"
            f"Проблемные ID: {failed_ids}"
        ),
    )


@router.message_created(Command("myid"))
async def cmd_myid(event: MessageCreated) -> None:
    user_id = _event_user_id(event)
    chat_id = _event_chat_id(event)
    if user_id is None or chat_id is None:
        return
    is_admin = await _is_admin(user_id)
    is_owner = _is_owner(user_id)
    await event.bot.send_message(
        chat_id=chat_id,
        text=(
            "<b>Ваши данные</b>\n"
            f"ID: <code>{user_id}</code>\n"
            f"Админ: {'да' if is_admin else 'нет'}\n"
            f"Owner: {'да' if is_owner else 'нет'}"
        ),
    )


@router.message_created(Command("sub_on"))
async def cmd_sub_on(event: MessageCreated, args: list[str]) -> None:
    user_id = _event_user_id(event)
    if user_id is None or not await _is_admin(user_id):
        return
    if len(args) < 2 or not args[0].isdigit() or not args[1].isdigit():
        await _answer(event, "Использование: /sub_on <code>ID</code> <code>amount</code>")
        return
    target_user_id = int(args[0])
    amount = int(args[1])
    await crud.update_balance(config.database_path, target_user_id, amount)
    await _answer(event, f"Начислено {amount} толкований пользователю {target_user_id}.")


@router.message_created(Command("sub_off"))
async def cmd_sub_off(event: MessageCreated, args: list[str]) -> None:
    user_id = _event_user_id(event)
    if user_id is None or not await _is_admin(user_id):
        return
    if len(args) < 1 or not args[0].isdigit():
        await _answer(event, "Использование: /sub_off <code>ID</code>")
        return
    target_user_id = int(args[0])
    await crud.set_balance(config.database_path, target_user_id, 0)
    await _answer(event, f"Баланс пользователя {target_user_id} обнулен.")


@router.message_created(Command("sub_cancel"))
async def cmd_sub_cancel(event: MessageCreated, args: list[str]) -> None:
    user_id = _event_user_id(event)
    if user_id is None or not await _is_admin(user_id):
        return
    if len(args) < 1 or not args[0].isdigit():
        await _answer(event, "Использование: /sub_cancel <code>ID</code>")
        return
    target_user_id = int(args[0])
    await crud.cancel_subscription(config.database_path, target_user_id)
    await _answer(event, f"Подписка пользователя {target_user_id} отключена.")


@router.message_created(Command("sub_check"))
async def cmd_sub_check(event: MessageCreated, args: list[str]) -> None:
    user_id = _event_user_id(event)
    if user_id is None or not await _is_admin(user_id):
        return
    if len(args) < 1 or not args[0].isdigit():
        await _answer(event, "Использование: /sub_check <code>ID</code>")
        return
    target_user_id = int(args[0])
    balance = await crud.get_balance(config.database_path, target_user_id)
    await _answer(event, f"Баланс пользователя {target_user_id}: {balance} толкований")


@router.message_created(Command("adstats"))
async def cmd_adstats(event: MessageCreated, args: list[str]) -> None:
    user_id = _event_user_id(event)
    if user_id is None or not await _is_admin(user_id):
        return
    if len(args) < 1:
        await _answer(event, "Использование: /adstats <code>метка</code>")
        return

    tag = args[0].strip()
    users = await crud.count_users_by_utm(config.database_path, tag)
    buyers = await crud.count_buyers_by_utm(config.database_path, tag)
    conversion = (buyers / users * 100) if users else 0
    totals = await crud.sum_payments_by_utm(config.database_path, tag)

    total_rub = 0.0
    for currency, amount in totals:
        if currency == "RUB":
            total_rub += amount
        elif currency == "XTR":
            total_rub += amount * config.stars_rub_rate
    ltv = (total_rub / users) if users else 0

    await _answer(
        event,
        "📊 Статистика по метке\n"
        f"Метка: <code>{html.escape(tag)}</code>\n"
        f"Пользователей: {users}\n"
        f"Покупателей: {buyers}\n"
        f"Конверсия: {conversion:.2f}%\n"
        f"Сумма оплат (RUB экв): {total_rub:.2f}\n"
        f"LTV: {ltv:.2f}",
    )


@router.message_created(Command("adstats_all"))
async def cmd_adstats_all(event: MessageCreated) -> None:
    user_id = _event_user_id(event)
    if user_id is None or not await _is_admin(user_id):
        return

    stats = await crud.list_utm_stats(config.database_path)
    payments = await crud.list_utm_payments(config.database_path)
    totals_map: dict[str | None, dict[str, int]] = {}
    for utm_source, currency, amount in payments:
        totals_map.setdefault(utm_source, {})[currency] = amount

    lines = ["📊 <b>Статистика по всем меткам</b>"]
    for row in stats:
        tag = row["utm_source"] if row["utm_source"] else "без метки"
        users = int(row["users"])
        buyers = int(row["buyers"] or 0)
        conversion = (buyers / users * 100) if users else 0
        totals = totals_map.get(row["utm_source"], {})
        total_rub = 0.0
        for currency, amount in totals.items():
            if currency == "RUB":
                total_rub += amount
            elif currency == "XTR":
                total_rub += amount * config.stars_rub_rate
        ltv = (total_rub / users) if users else 0
        lines.append(
            f"• <code>{html.escape(str(tag))}</code> | users {users} | buyers {buyers} | "
            f"conv {conversion:.1f}% | sum {total_rub:.0f} | LTV {ltv:.1f}"
        )
    await _answer(event, "\n".join(lines))


@router.message_created(Command("botstats"))
async def cmd_botstats(event: MessageCreated) -> None:
    user_id = _event_user_id(event)
    if user_id is None or not await _is_admin(user_id):
        return

    now_iso = datetime.utcnow().isoformat(timespec="seconds")
    plans = get_plans()
    week = plans.get("week")
    month = plans.get("month")

    total_users = await crud.count_users(config.database_path)
    free_users = await crud.count_promo_used_users(config.database_path)
    paid_users = await crud.count_paid_users(config.database_path)
    active_subs = await crud.count_active_subscriptions(config.database_path, now_iso)
    subs_by_plan = await crud.count_active_subscriptions_by_plan(config.database_path, now_iso)

    stars_payments = await crud.count_paid_transactions_by_currency(config.database_path, "XTR")
    stars_buyers = await crud.count_paid_users_by_currency(config.database_path, "XTR")
    totals = await crud.sum_paid_by_currency(config.database_path)

    total_rub = 0
    total_xtr = 0
    for currency, amount in totals:
        if currency == "RUB":
            total_rub += amount
        elif currency == "XTR":
            total_xtr += amount

    conversion = (paid_users / total_users * 100) if total_users else 0
    arpu = (total_rub / total_users) if total_users else 0
    arppu = (total_rub / paid_users) if paid_users else 0

    week_label = week.title.lower() if week else "неделя"
    month_label = month.title.lower() if month else "месяц"
    week_price = week.price_rub if week else 0
    month_price = month.price_rub if month else 0

    await _answer(
        event,
        "📊 <b>Общая статистика бота</b>\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"🎁 Использовали пробное толкование: {free_users}\n"
        f"💳 Оплативших: {paid_users}\n"
        f"🔥 Активных подписок: {active_subs}\n"
        f"🟢 Подписка {week_price}₽ ({week_label}): {subs_by_plan.get('week', 0)}\n"
        f"🔵 Подписка {month_price}₽ ({month_label}): {subs_by_plan.get('month', 0)}\n"
        f"⭐ Оплаты Stars (XTR): {stars_payments}\n"
        f"⭐ Покупателей Stars: {stars_buyers}\n"
        f"⭐ Сумма Stars: {total_xtr} XTR\n"
        f"💰 Выручка: {total_rub} ₽\n\n"
        f"📈 Конверсия в оплату: {conversion:.2f}%\n"
        f"💵 ARPU: {arpu:.2f} ₽\n"
        f"💎 ARPPU: {arppu:.2f} ₽",
    )


@router.message_created(Command("adtag"))
async def cmd_adtag(event: MessageCreated, args: list[str]) -> None:
    user_id = _event_user_id(event)
    if user_id is None or not await _is_admin(user_id):
        return
    if len(args) < 1:
        await _answer(event, "Использование: /adtag <code>метка</code>")
        return
    tag = args[0].strip()
    bot_info = await event.bot.get_me()
    link = f"https://max.ru/{bot_info.username}?start={tag}"
    await _answer(
        event,
        f"Метка: <code>{html.escape(tag)}</code>\n"
        f"Ссылка: <code>{link}</code>",
    )


@router.message_created(Command("genpromo"))
async def cmd_genpromo(event: MessageCreated, args: list[str]) -> None:
    ok, user_id = await _ensure_admin(event)
    if not ok or user_id is None:
        return
    if len(args) < 1 or not args[0].isdigit():
        await _answer(event, "Использование: /genpromo <code>кол-во</code>")
        return
    credits = int(args[0])
    code = secrets.token_urlsafe(6)
    await crud.create_promocode(config.database_path, code, credits)

    bot_info = await event.bot.get_me()
    link = f"https://max.ru/{bot_info.username}?start=promo_{code}"
    await _answer(event, f"Промокод создан: {link}")
    await notify_admin(
        event.bot,
        config.admin_notify_ids,
        f"🎁 Создан промокод на {credits} толкований: {code}",
    )


@router.message_created(Command("admin_add"))
async def cmd_admin_add(event: MessageCreated, args: list[str]) -> None:
    user_id = _event_user_id(event)
    if user_id is None or not _is_owner(user_id):
        return
    if len(args) < 1 or not args[0].isdigit():
        await _answer(event, "Использование: /admin_add <code>ID</code>")
        return
    target_user_id = int(args[0])
    await crud.add_admin(config.database_path, target_user_id, user_id)
    await _answer(event, f"Админ добавлен: {target_user_id}")


@router.message_created(Command("admin_del"))
async def cmd_admin_del(event: MessageCreated, args: list[str]) -> None:
    user_id = _event_user_id(event)
    if user_id is None or not _is_owner(user_id):
        return
    if len(args) < 1 or not args[0].isdigit():
        await _answer(event, "Использование: /admin_del <code>ID</code>")
        return
    target_user_id = int(args[0])
    await crud.remove_admin(config.database_path, target_user_id)
    await _answer(event, f"Админ удален: {target_user_id}")


@router.message_created(Command("admin_list"))
async def cmd_admin_list(event: MessageCreated) -> None:
    user_id = _event_user_id(event)
    if user_id is None or not _is_owner(user_id):
        return
    admins = await crud.list_admins(config.database_path)
    all_admins = list(dict.fromkeys(config.admin_ids + admins))
    if not all_admins:
        await _answer(event, "Админов нет.")
        return
    await _answer(event, "Админы:\n" + "\n".join(f"- {a}" for a in all_admins))
