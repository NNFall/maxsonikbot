from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter, TelegramBadRequest

from config import load_config
from database import crud

logger = logging.getLogger(__name__)

SEND_RATE_PER_SEC = 25
PREVIEW_LEAD_SEC = 30 * 60
CYCLE_SLEEP_SEC = 12 * 60 * 60
PROGRESS_TICK_SEC = 60


def _promo_kb(effect_id: int, effect_type: str) -> InlineKeyboardMarkup:
    prefix = 'photo_effect' if effect_type == 'photo' else 'effect'
    text = '📸 Сделать фото' if effect_type == 'photo' else '🎬 Сделать видео'
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data=f'{prefix}:{effect_id}')]
        ]
    )


def _pick_next_effect(effects: list[dict], last_effect_id: int | None) -> dict | None:
    if not effects:
        return None
    if last_effect_id is None:
        return effects[0]
    for idx, effect in enumerate(effects):
        if int(effect['id']) == int(last_effect_id):
            return effects[(idx + 1) % len(effects)]
    return effects[0]


async def _send_promo(bot: Bot, user_id: int, effect: dict) -> str:
    effect_type = effect.get('type') or 'video'
    text = f'Попробуйте этот эффект! 👇\n<b>{effect["button_name"]}</b>'
    demo_file_id = effect.get('demo_file_id')
    demo_type = effect.get('demo_type')
    kb = _promo_kb(int(effect['id']), effect_type)

    try:
        if demo_file_id:
            if demo_type == 'photo':
                await bot.send_photo(user_id, demo_file_id, caption=text, reply_markup=kb)
            else:
                await bot.send_video(user_id, demo_file_id, caption=text, reply_markup=kb)
        else:
            await bot.send_message(user_id, text, reply_markup=kb)
        return 'sent'
    except TelegramForbiddenError:
        logger.info('Mailer: user blocked bot user_id=%s', user_id)
        return 'blocked'
    except TelegramRetryAfter as e:
        logger.warning('Mailer: rate limited, sleep=%s', e.retry_after)
        await asyncio.sleep(e.retry_after)
        return 'retry_after'
    except TelegramBadRequest as e:
        logger.warning('Mailer: bad request user_id=%s error=%s', user_id, e)
        return 'failed'
    except Exception as e:
        logger.error('Mailer: send failed user_id=%s error=%s', user_id, e)
        return 'failed'


def _admin_ids(cfg) -> list[int]:
    ids = cfg.admin_notify_ids or cfg.admin_ids
    return [int(x) for x in ids] if ids else []


async def _send_preview(bot: Bot, admin_ids: list[int], effect: dict) -> None:
    for admin_id in admin_ids:
        try:
            await bot.send_message(
                admin_id,
                '⚠️ <b>Внимание!</b> Через 30 минут начнется автоматическая рассылка.\n'
                f'Эффект: <b>{effect["button_name"]}</b>',
            )
            await _send_promo(bot, admin_id, effect)
        except Exception:
            continue


def _progress_text(sent: int, total: int, errors: int) -> str:
    percent = int((sent / total) * 100) if total else 0
    return (
        '⏳ <b>Идет рассылка...</b>\n'
        f'Отправлено: {sent} из {total} ({percent}%)\n'
        f'Ошибок/Блокировок: {errors}'
    )


async def smart_mailing_loop(bot: Bot) -> None:
    config = load_config()
    delay = 1 / SEND_RATE_PER_SEC
    admin_ids = _admin_ids(config)

    while True:
        try:
            state = await crud.get_mailer_state(config.database_path) or {}
            updated_at = state.get('updated_at')
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
                    video_effects = await crud.list_effects(config.database_path, active_only=True, effect_type='video')
                    photo_effects = await crud.list_effects(config.database_path, active_only=True, effect_type='photo')
                    if not video_effects and not photo_effects:
                        await asyncio.sleep(60 * 60)
                        continue

                    last_type = state.get('last_type') or 'photo'
                    next_type = 'photo' if last_type == 'video' else 'video'

                    if next_type == 'photo' and photo_effects:
                        last_id = state.get('last_photo_id')
                        effect = _pick_next_effect(photo_effects, last_id)
                    elif next_type == 'video' and video_effects:
                        last_id = state.get('last_video_id')
                        effect = _pick_next_effect(video_effects, last_id)
                    else:
                        if video_effects:
                            next_type = 'video'
                            last_id = state.get('last_video_id')
                            effect = _pick_next_effect(video_effects, last_id)
                        else:
                            next_type = 'photo'
                            last_id = state.get('last_photo_id')
                            effect = _pick_next_effect(photo_effects, last_id)

                    if not effect:
                        await asyncio.sleep(60 * 60)
                        continue

                    if admin_ids:
                        await _send_preview(bot, admin_ids, effect)
                    await asyncio.sleep((next_run_at - datetime.utcnow()).total_seconds())

            if effect is None:
                video_effects = await crud.list_effects(config.database_path, active_only=True, effect_type='video')
                photo_effects = await crud.list_effects(config.database_path, active_only=True, effect_type='photo')
                if not video_effects and not photo_effects:
                    await asyncio.sleep(60 * 60)
                    continue

                last_type = state.get('last_type') or 'photo'
                next_type = 'photo' if last_type == 'video' else 'video'

                if next_type == 'photo' and photo_effects:
                    last_id = state.get('last_photo_id')
                    effect = _pick_next_effect(photo_effects, last_id)
                elif next_type == 'video' and video_effects:
                    last_id = state.get('last_video_id')
                    effect = _pick_next_effect(video_effects, last_id)
                else:
                    if video_effects:
                        next_type = 'video'
                        last_id = state.get('last_video_id')
                        effect = _pick_next_effect(video_effects, last_id)
                    else:
                        next_type = 'photo'
                        last_id = state.get('last_photo_id')
                        effect = _pick_next_effect(photo_effects, last_id)

                if not effect:
                    await asyncio.sleep(60 * 60)
                    continue

            now_iso = datetime.utcnow().isoformat(timespec='seconds')
            active_ids = await crud.list_active_subscription_user_ids(config.database_path, now_iso)
            active_set = set(active_ids)
            user_ids = await crud.list_user_ids(config.database_path)
            target_ids = [uid for uid in user_ids if uid not in active_set]
            total = len(target_ids)

            progress_msgs: dict[int, int] = {}
            if admin_ids:
                for admin_id in admin_ids:
                    try:
                        msg = await bot.send_message(
                            admin_id,
                            '🚀 <b>Рассылка началась!</b>\n'
                            f'Эффект: <b>{effect["button_name"]}</b>\n'
                            f'Целевая аудитория: <b>{total}</b> чел.',
                        )
                        progress_msgs[admin_id] = msg.message_id
                    except Exception:
                        continue

            sent = 0
            blocked = 0
            failed = 0
            last_tick = datetime.utcnow()

            for user_id in target_ids:
                now_iso = datetime.utcnow().isoformat(timespec='seconds')
                if await crud.is_subscription_active(config.database_path, user_id, now_iso):
                    continue
                status = await _send_promo(bot, user_id, effect)
                if status == 'sent':
                    sent += 1
                elif status == 'blocked':
                    blocked += 1
                elif status == 'failed':
                    failed += 1
                await asyncio.sleep(delay)

                if admin_ids and progress_msgs:
                    if (datetime.utcnow() - last_tick).total_seconds() >= PROGRESS_TICK_SEC:
                        last_tick = datetime.utcnow()
                        for admin_id, msg_id in list(progress_msgs.items()):
                            try:
                                await bot.edit_message_text(
                                    _progress_text(sent, total, blocked + failed),
                                    chat_id=admin_id,
                                    message_id=msg_id,
                                )
                            except Exception:
                                continue

            if admin_ids and progress_msgs:
                finish_text = (
                    '✅ <b>Рассылка завершена.</b>\n'
                    f'Успешно доставлено: <b>{sent}</b>\n'
                    f'Не доставлено (бот заблокирован): <b>{blocked}</b>\n'
                    f'Следующая рассылка через 12 часов.'
                )
                if failed:
                    finish_text += f'\nОшибок: <b>{failed}</b>'
                for admin_id, msg_id in list(progress_msgs.items()):
                    try:
                        await bot.edit_message_text(
                            finish_text,
                            chat_id=admin_id,
                            message_id=msg_id,
                        )
                    except Exception:
                        try:
                            await bot.send_message(admin_id, finish_text)
                        except Exception:
                            continue

            if next_type == 'photo':
                await crud.set_mailer_state(
                    config.database_path,
                    int(effect['id']),
                    last_type='photo',
                    last_photo_id=int(effect['id']),
                )
            else:
                await crud.set_mailer_state(
                    config.database_path,
                    int(effect['id']),
                    last_type='video',
                    last_video_id=int(effect['id']),
                )
            logger.info(
                'Mailer: done effect_id=%s type=%s sent=%s blocked=%s failed=%s',
                effect['id'],
                next_type,
                sent,
                blocked,
                failed,
            )
        except Exception as e:
            logger.exception('Mailer: loop error: %s', e)
        # next cycle timing is based on mailer_state.updated_at
