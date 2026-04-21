from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from config import load_config
from database import crud
from max_keyboards import mailer_attachments
from prompts.mailer_push_templates import next_variant

logger = logging.getLogger(__name__)

SEND_RATE_PER_SEC = 25
PREVIEW_LEAD_SEC = 30 * 60
CYCLE_SLEEP_SEC = 12 * 60 * 60
PROGRESS_TICK_SEC = 60


def _pick_next_effect(effects: list[dict], last_effect_id: int | None) -> dict | None:
    if not effects:
        return None
    if last_effect_id is None:
        return effects[0]
    for idx, effect in enumerate(effects):
        if int(effect["id"]) == int(last_effect_id):
            return effects[(idx + 1) % len(effects)]
    return effects[0]


def _admin_ids(cfg) -> list[int]:
    ids = cfg.admin_notify_ids or cfg.admin_ids
    return [int(x) for x in ids] if ids else []


def _extract_mid(response: Any) -> str | None:
    try:
        return str(response.message.body.mid)
    except Exception:
        return None


def _progress_text(sent: int, total: int, errors: int) -> str:
    percent = int((sent / total) * 100) if total else 0
    return (
        "⏳ <b>Идет рассылка...</b>\n"
        f"Отправлено: {sent} из {total} ({percent}%)\n"
        f"Ошибок/блокировок: {errors}"
    )


def _promo_text(body: str, effect_name: str) -> str:
    return f"{body}\n\n🔮 Расклад: <b>{effect_name}</b>"


async def _send_message(bot, recipient_id: int, text: str, attachments=None):
    try:
        return await bot.send_message(chat_id=recipient_id, text=text, attachments=attachments)
    except Exception as chat_error:
        try:
            return await bot.send_message(user_id=recipient_id, text=text, attachments=attachments)
        except Exception as user_error:
            raise user_error from chat_error


async def _send_promo(bot, user_id: int, text: str) -> str:
    try:
        await _send_message(
            bot,
            user_id,
            text=text,
            attachments=mailer_attachments(),
        )
        return "sent"
    except Exception as e:
        lowered = str(e).lower()
        if any(word in lowered for word in ("forbidden", "denied", "block", "not found", "cannot")):
            logger.info("Mailer: user blocked bot user_id=%s", user_id)
            return "blocked"
        if any(word in lowered for word in ("429", "too many", "rate", "flood")):
            logger.warning("Mailer: rate limited user_id=%s", user_id)
            await asyncio.sleep(1.0)
            return "retry_after"
        logger.error("Mailer: send failed user_id=%s error=%s", user_id, e)
        return "failed"


async def _build_promo_text(state: dict, effect_name: str) -> tuple[int, str, str]:
    template_idx, template_body = next_variant(state.get("last_push_variant_idx"))
    return template_idx, template_body, _promo_text(template_body, effect_name)


async def _send_preview(bot, admin_ids: list[int], promo_body: str) -> None:
    preview_text = (
        "⚠️ <b>Внимание! Через 30 минут начнется автоматическая рассылка.</b>\n"
        f"Текст: {promo_body}"
    )
    for admin_id in admin_ids:
        try:
            await _send_message(bot, admin_id, preview_text)
        except Exception:
            continue


async def _choose_next_effect(config, state: dict) -> tuple[dict | None, str | None]:
    video_effects = await crud.list_effects(config.database_path, active_only=True, effect_type="video")
    photo_effects = await crud.list_effects(config.database_path, active_only=True, effect_type="photo")

    if not video_effects and not photo_effects:
        return None, None

    last_type = state.get("last_type") or "photo"
    next_type = "photo" if last_type == "video" else "video"

    if next_type == "photo" and photo_effects:
        return _pick_next_effect(photo_effects, state.get("last_photo_id")), "photo"
    if next_type == "video" and video_effects:
        return _pick_next_effect(video_effects, state.get("last_video_id")), "video"

    if video_effects:
        return _pick_next_effect(video_effects, state.get("last_video_id")), "video"
    return _pick_next_effect(photo_effects, state.get("last_photo_id")), "photo"


async def smart_mailing_loop(bot) -> None:
    config = load_config()
    delay = 1 / SEND_RATE_PER_SEC
    admin_ids = _admin_ids(config)

    while True:
        try:
            state = await crud.get_mailer_state(config.database_path) or {}
            updated_at = state.get("updated_at")
            next_run_at = None
            if updated_at:
                try:
                    next_run_at = datetime.fromisoformat(updated_at) + timedelta(seconds=CYCLE_SLEEP_SEC)
                except Exception:
                    next_run_at = None

            effect = None
            next_type = None

            if next_run_at:
                now = datetime.utcnow()
                preview_at = next_run_at - timedelta(seconds=PREVIEW_LEAD_SEC)
                if now < preview_at:
                    await asyncio.sleep((preview_at - now).total_seconds())

                if datetime.utcnow() < next_run_at:
                    effect, next_type = await _choose_next_effect(config, state)
                    if not effect:
                        await asyncio.sleep(60 * 60)
                        continue

                    template_idx, promo_body, promo_text = await _build_promo_text(state, effect["button_name"])
                    if admin_ids:
                        await _send_preview(bot, admin_ids, promo_body)

                    wait_sec = (next_run_at - datetime.utcnow()).total_seconds()
                    if wait_sec > 0:
                        await asyncio.sleep(wait_sec)
                else:
                    template_idx, promo_body, promo_text = -1, "", ""
            else:
                template_idx, promo_body, promo_text = -1, "", ""

            if effect is None:
                effect, next_type = await _choose_next_effect(config, state)
                if not effect:
                    await asyncio.sleep(60 * 60)
                    continue

            if not promo_text:
                template_idx, promo_body, promo_text = await _build_promo_text(state, effect["button_name"])

            now_iso = datetime.utcnow().isoformat(timespec="seconds")
            active_ids = await crud.list_active_subscription_user_ids(config.database_path, now_iso)
            active_set = set(active_ids)
            user_ids = await crud.list_user_ids(config.database_path)
            target_ids = [uid for uid in user_ids if uid not in active_set]
            total = len(target_ids)

            progress_msgs: dict[int, str] = {}
            if admin_ids:
                start_text = (
                    "🚀 <b>Рассылка началась!</b>\n"
                    f"Расклад: <b>{effect['button_name']}</b>\n"
                    f"Целевая аудитория: <b>{total}</b> чел."
                )
                for admin_id in admin_ids:
                    try:
                        response = await _send_message(bot, admin_id, start_text)
                        mid = _extract_mid(response)
                        if mid:
                            progress_msgs[admin_id] = mid
                    except Exception:
                        continue

            sent = 0
            blocked = 0
            failed = 0
            last_tick = datetime.utcnow()

            for user_id in target_ids:
                now_iso = datetime.utcnow().isoformat(timespec="seconds")
                if await crud.is_subscription_active(config.database_path, user_id, now_iso):
                    continue

                status = await _send_promo(bot, user_id, promo_text)
                if status == "sent":
                    sent += 1
                elif status == "blocked":
                    blocked += 1
                elif status == "failed":
                    failed += 1
                await asyncio.sleep(delay)

                if progress_msgs and (datetime.utcnow() - last_tick).total_seconds() >= PROGRESS_TICK_SEC:
                    last_tick = datetime.utcnow()
                    progress_text = _progress_text(sent, total, blocked + failed)
                    for admin_id, message_id in list(progress_msgs.items()):
                        try:
                            await bot.edit_message(message_id=message_id, text=progress_text)
                        except Exception:
                            try:
                                response = await _send_message(bot, admin_id, progress_text)
                                mid = _extract_mid(response)
                                if mid:
                                    progress_msgs[admin_id] = mid
                            except Exception:
                                continue

            finish_text = (
                "✅ <b>Рассылка завершена.</b>\n"
                f"Успешно доставлено: <b>{sent}</b>\n"
                f"Не доставлено (бот заблокирован): <b>{blocked}</b>\n"
                "Следующая рассылка через 12 часов."
            )

            for admin_id, message_id in list(progress_msgs.items()):
                try:
                    await bot.edit_message(message_id=message_id, text=finish_text)
                except Exception:
                    try:
                        await _send_message(bot, admin_id, finish_text)
                    except Exception:
                        continue

            if next_type == "photo":
                await crud.set_mailer_state(
                    config.database_path,
                    int(effect["id"]),
                    last_type="photo",
                    last_photo_id=int(effect["id"]),
                    last_push_variant_idx=template_idx,
                )
            else:
                await crud.set_mailer_state(
                    config.database_path,
                    int(effect["id"]),
                    last_type="video",
                    last_video_id=int(effect["id"]),
                    last_push_variant_idx=template_idx,
                )

            logger.info(
                "Mailer: done effect_id=%s type=%s sent=%s blocked=%s failed=%s template_idx=%s",
                effect["id"],
                next_type,
                sent,
                blocked,
                failed,
                template_idx,
            )
        except Exception as e:
            logger.exception("Mailer: loop error: %s", e)
            await asyncio.sleep(30)
