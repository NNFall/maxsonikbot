from __future__ import annotations


async def notify_admin(bot, admin_ids: list[int], text: str) -> None:
    for admin_id in admin_ids:
        try:
            await bot.send_message(chat_id=admin_id, text=text)
            continue
        except TypeError:
            pass
        except Exception:
            continue

        try:
            await bot.send_message(user_id=admin_id, text=text)
        except Exception:
            continue
