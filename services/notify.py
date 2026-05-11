from __future__ import annotations

import logging
from typing import Iterable

from config import load_config
from database import crud

logger = logging.getLogger(__name__)


async def _resolve_notify_ids(explicit_ids: Iterable[int] | None) -> list[int]:
    cfg = load_config()
    ids = list(explicit_ids or [])
    ids.extend(cfg.admin_notify_ids or [])
    ids.extend(cfg.admin_ids or [])
    try:
        ids.extend(await crud.list_admins(cfg.database_path))
    except Exception as e:
        logger.warning("notify_admin: failed to read db admins: %s", e)
    # Keep order, remove duplicates and broken values.
    resolved: list[int] = []
    for item in ids:
        try:
            value = int(item)
        except Exception:
            continue
        if value not in resolved:
            resolved.append(value)
    return resolved


async def notify_admin(bot, admin_ids: list[int] | None, text: str) -> dict:
    resolved_ids = await _resolve_notify_ids(admin_ids)
    delivered: list[int] = []
    failed: list[dict] = []

    for admin_id in resolved_ids:
        try:
            await bot.send_message(chat_id=admin_id, text=text)
            delivered.append(admin_id)
            continue
        except Exception as e_chat:
            try:
                await bot.send_message(user_id=admin_id, text=text)
                delivered.append(admin_id)
                continue
            except Exception as e_user:
                failed.append(
                    {
                        "admin_id": admin_id,
                        "chat_error": f"{type(e_chat).__name__}: {e_chat}",
                        "user_error": f"{type(e_user).__name__}: {e_user}",
                    }
                )

    if failed:
        logger.warning("notify_admin: delivered=%s failed=%s", len(delivered), len(failed))
        for item in failed:
            logger.warning(
                "notify_admin failed admin_id=%s chat_error=%s user_error=%s",
                item["admin_id"],
                item["chat_error"],
                item["user_error"],
            )

    return {
        "resolved_ids": resolved_ids,
        "delivered": delivered,
        "failed": failed,
    }
