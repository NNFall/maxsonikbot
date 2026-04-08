from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path
from aiogram import Bot
from aiogram.types import InputMediaPhoto

from config import load_config
from database import crud
from services.kie_api import (
    upload_file,
    create_task,
    poll_task,
    extract_result_url,
    create_image_task,
    extract_result_urls,
)
from services.replicate_api import (
    create_prediction,
    poll_prediction,
    extract_output_url,
    encode_image,
    closest_aspect_ratio,
)
from services.logging_utils import shorten, format_user
from services.notify import notify_admin
from keyboards.generation_kb import (
    effect_done_kb,
    custom_done_kb,
    photo_effect_done_kb,
    photo_custom_done_kb,
    photo_text_done_kb,
)

logger = logging.getLogger(__name__)
REPLICATE_MAX_ATTEMPTS = 2
REPLICATE_ATTEMPT_TIMEOUT_SEC = 90
REPLICATE_POLL_INTERVAL_SEC = 10
KIE_FALLBACK_DURATION_SEC = 6


async def run_effect_generation(
    bot: Bot,
    user_id: int,
    chat_id: int,
    effect_id: int,
    photo_file_id: str,
    username: str | None = None,
) -> bool:
    config = load_config()
    await _expire_subscription_if_needed(user_id)
    effect = await crud.get_effect(config.database_path, effect_id)
    if not effect:
        await bot.send_message(chat_id, 'Эффект не найден. Попробуйте снова.')
        return False

    balance = await crud.get_balance(config.database_path, user_id)
    if balance < config.effect_cost:
        await bot.send_message(chat_id, f'Недостаточно раскладов. Нужно {config.effect_cost} раскладов.')
        return False

    await crud.update_balance(config.database_path, user_id, -config.effect_cost)
    charged = True

    temp_dir = Path(config.media_temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"effect_{user_id}_{uuid.uuid4().hex}.jpg"
    final_prompt = f"{config.system_prompt} {effect['prompt']}".strip()

    try:
        await bot.download(photo_file_id, destination=temp_path)
        await bot.send_message(
            chat_id,
            f'💳 Списано <b>{config.effect_cost}</b> раскладов.\n'
            f'⏱ Длительность: <b>6</b> сек.\n'
            '✨ Генерирую видео, подождите...'
        )
        logger.info('Kie request %s prompt="%s"', format_user(user_id, username), shorten(final_prompt))
        image_url = await asyncio.to_thread(upload_file, str(temp_path), config.kie_api_key)
        task_id = await asyncio.to_thread(
            create_task,
            image_url,
            final_prompt,
            6,
            config.kie_api_key,
            config.kie_api_url,
        )
        logger.info('Kie task created task_id=%s %s', task_id, format_user(user_id, username))

        record = await poll_task(task_id, config.kie_api_key, timeout_sec=420)
        url = extract_result_url(record)
        if not url:
            raise RuntimeError('Kie result url not found')

        await bot.send_video(chat_id, url)
        await bot.send_message(
            chat_id,
            f'✅ Видео создано\nЭффект: <b>{effect["button_name"]}</b>',
            reply_markup=effect_done_kb(effect_id),
        )
        await notify_admin(
            bot,
            config.admin_notify_ids,
            f'✅ Успешная генерация (Эффект). Пользователь {user_id} (@{username or "-"}) , эффект {effect_id}'
        )
        return True
    except Exception as e:
        logger.exception('Kie generation failed %s effect_id=%s', format_user(user_id, username), effect_id)
        if charged:
            await crud.update_balance(config.database_path, user_id, config.effect_cost)
        await bot.send_message(chat_id, '❌ Ошибка генерации. Попробуйте позже. расклады возвращены.')
        await notify_admin(
            bot,
            config.admin_notify_ids,
            f'❌ Ошибка Kie.ai: {e} (user {user_id} @{username or "-"})'
        )
        return False
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass


async def _send_image_group(bot: Bot, chat_id: int, urls: list[str]) -> None:
    items: list[InputMediaPhoto] = []
    for idx, url in enumerate(urls):
        items.append(InputMediaPhoto(media=url))
    await bot.send_media_group(chat_id, items)


async def run_photo_effect_generation(
    bot: Bot,
    user_id: int,
    chat_id: int,
    effect_id: int,
    photo_file_id: str,
    username: str | None = None,
) -> bool:
    config = load_config()
    await _expire_subscription_if_needed(user_id)
    effect = await crud.get_effect(config.database_path, effect_id)
    if not effect:
        await bot.send_message(chat_id, 'Эффект не найден. Попробуйте снова.')
        return False

    balance = await crud.get_balance(config.database_path, user_id)
    if balance < config.photo_effect_cost:
        await bot.send_message(chat_id, f'Недостаточно раскладов. Нужно {config.photo_effect_cost} раскладов.')
        return False

    await crud.update_balance(config.database_path, user_id, -config.photo_effect_cost)
    charged = True

    temp_dir = Path(config.media_temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"photo_effect_{user_id}_{uuid.uuid4().hex}.jpg"
    final_prompt = f"{effect['prompt']}".strip()

    try:
        await bot.download(photo_file_id, destination=temp_path)
        await bot.send_message(
            chat_id,
            f'💳 Списано <b>{config.photo_effect_cost}</b> раскладов.\n'
            '✨ Генерирую фото, подождите...'
        )
        logger.info('Kie image request %s prompt="%s"', format_user(user_id, username), shorten(final_prompt))
        image_url = await asyncio.to_thread(upload_file, str(temp_path), config.kie_api_key)
        task_id = await asyncio.to_thread(
            create_image_task,
            final_prompt,
            config.kie_image_model,
            config.kie_api_key,
            config.kie_api_url,
            image_url,
        )
        logger.info('Kie image task created task_id=%s %s', task_id, format_user(user_id, username))

        record = await poll_task(task_id, config.kie_api_key)
        urls = extract_result_urls(record)
        if not urls:
            raise RuntimeError('Kie image result urls not found')

        await _send_image_group(bot, chat_id, urls)
        await bot.send_message(
            chat_id,
            f'✅ Фото создано\nЭффект: <b>{effect["button_name"]}</b>',
            reply_markup=photo_effect_done_kb(effect_id),
        )
        await notify_admin(
            bot,
            config.admin_notify_ids,
            f'✅ Успешная генерация (Фото-эффект). Пользователь {user_id} (@{username or "-"}) , эффект {effect_id}'
        )
        return True
    except Exception as e:
        logger.exception('Kie image generation failed %s effect_id=%s', format_user(user_id, username), effect_id)
        if charged:
            await crud.update_balance(config.database_path, user_id, config.photo_effect_cost)
        await bot.send_message(chat_id, '❌ Ошибка генерации. Попробуйте позже. расклады возвращены.')
        await notify_admin(
            bot,
            config.admin_notify_ids,
            f'❌ Ошибка Kie.ai (image): {e} (user {user_id} @{username or "-"})'
        )
        return False
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass


async def run_custom_generation(
    bot: Bot,
    user_id: int,
    chat_id: int,
    photo_file_id: str,
    prompt: str,
    duration: int,
    photo_width: int | None = None,
    photo_height: int | None = None,
    username: str | None = None,
) -> bool:
    config = load_config()
    await _expire_subscription_if_needed(user_id)
    cost = duration * config.custom_cost_per_sec

    balance = await crud.get_balance(config.database_path, user_id)
    if balance < cost:
        await bot.send_message(chat_id, f'Недостаточно раскладов. Нужно {cost} раскладов.')
        return False

    await crud.update_balance(config.database_path, user_id, -cost)
    charged = True

    temp_dir = Path(config.media_temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"custom_{user_id}_{uuid.uuid4().hex}.jpg"
    final_prompt = f"{config.system_prompt} {prompt}".strip()

    error_source = 'Replicate'
    try:
        await bot.download(photo_file_id, destination=temp_path)
        await bot.send_message(
            chat_id,
            f'💳 Списано <b>{cost}</b> раскладов.\n'
            f'⏱ Длительность: <b>{duration}</b> сек.\n'
            f'Цена: <b>{config.custom_cost_per_sec}</b> раскладов/сек.\n'
            '✨ Генерирую видео, подождите...'
        )
        logger.info('Replicate request %s prompt="%s"', format_user(user_id, username), shorten(final_prompt))

        file_size = temp_path.stat().st_size
        if file_size <= 256 * 1024:
            image_input = encode_image(str(temp_path))
        else:
            file_info = await bot.get_file(photo_file_id)
            image_input = f"https://api.telegram.org/file/bot{config.bot_token}/{file_info.file_path}"

        aspect_ratio = None
        if config.replicate_aspect_ratio_mode == 'match' and photo_width and photo_height:
            aspect_ratio = closest_aspect_ratio(photo_width, photo_height)

        replicate_error: Exception | None = None
        url: str | None = None
        for attempt in range(1, REPLICATE_MAX_ATTEMPTS + 1):
            try:
                try:
                    prediction = await asyncio.to_thread(
                        create_prediction,
                        image_input,
                        final_prompt,
                        duration,
                        config.replicate_api_token,
                        config.replicate_api_url,
                        config.replicate_model_version,
                        config.replicate_image_field,
                        aspect_ratio,
                    )
                except Exception:
                    if aspect_ratio:
                        logger.warning('Replicate aspect_ratio rejected, retry without. ratio=%s', aspect_ratio)
                        prediction = await asyncio.to_thread(
                            create_prediction,
                            image_input,
                            final_prompt,
                            duration,
                            config.replicate_api_token,
                            config.replicate_api_url,
                            config.replicate_model_version,
                            config.replicate_image_field,
                            None,
                        )
                    else:
                        raise

                prediction_id = prediction.get('id')
                if not prediction_id:
                    raise RuntimeError('Replicate missing prediction id')
                logger.info(
                    'Replicate task created prediction_id=%s %s attempt=%s/%s',
                    prediction_id,
                    format_user(user_id, username),
                    attempt,
                    REPLICATE_MAX_ATTEMPTS,
                )

                prediction = await poll_prediction(
                    prediction_id,
                    config.replicate_api_token,
                    config.replicate_api_url,
                    interval_sec=REPLICATE_POLL_INTERVAL_SEC,
                    timeout_sec=REPLICATE_ATTEMPT_TIMEOUT_SEC,
                )
                url = extract_output_url(prediction)
                if not url:
                    raise RuntimeError('Replicate output url not found')
                break
            except Exception as e:
                replicate_error = e
                logger.warning(
                    'Replicate attempt failed %s attempt=%s/%s error=%s',
                    format_user(user_id, username),
                    attempt,
                    REPLICATE_MAX_ATTEMPTS,
                    e,
                )
                if attempt < REPLICATE_MAX_ATTEMPTS:
                    await asyncio.sleep(2)

        if not url:
            logger.warning(
                'Replicate failed after retries, fallback to Kie %s error=%s',
                format_user(user_id, username),
                replicate_error,
            )
            error_source = 'Kie (fallback)'
            image_url = await asyncio.to_thread(upload_file, str(temp_path), config.kie_api_key)
            task_id = await asyncio.to_thread(
                create_task,
                image_url,
                final_prompt,
                KIE_FALLBACK_DURATION_SEC,
                config.kie_api_key,
                config.kie_api_url,
            )
            logger.info('Kie fallback task created task_id=%s %s', task_id, format_user(user_id, username))
            record = await poll_task(task_id, config.kie_api_key, timeout_sec=420)
            url = extract_result_url(record)
            if not url:
                raise RuntimeError('Kie fallback result url not found')

        await bot.send_video(chat_id, url)
        await bot.send_message(
            chat_id,
            f'✅ Видео создано\nЗапрос: <i>{shorten(prompt, 200)}</i>',
            reply_markup=custom_done_kb(),
        )
        await notify_admin(
            bot,
            config.admin_notify_ids,
            f'✅ Успешная генерация (Свой промпт). Пользователь {user_id} (@{username or "-"})'
        )
        return True
    except Exception as e:
        logger.exception('Replicate generation failed %s', format_user(user_id, username))
        if charged:
            await crud.update_balance(config.database_path, user_id, cost)
        await bot.send_message(chat_id, '❌ Ошибка генерации. Попробуйте позже. расклады возвращены.')
        await notify_admin(
            bot,
            config.admin_notify_ids,
            f'❌ Ошибка {error_source}: {e} (user {user_id} @{username or "-"})'
        )
        return False
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass


async def run_photo_custom_generation(
    bot: Bot,
    user_id: int,
    chat_id: int,
    photo_file_id: str,
    prompt: str,
    username: str | None = None,
) -> bool:
    config = load_config()
    await _expire_subscription_if_needed(user_id)
    balance = await crud.get_balance(config.database_path, user_id)
    if balance < config.photo_custom_cost:
        await bot.send_message(chat_id, f'Недостаточно раскладов. Нужно {config.photo_custom_cost} раскладов.')
        return False

    await crud.update_balance(config.database_path, user_id, -config.photo_custom_cost)
    charged = True

    temp_dir = Path(config.media_temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"photo_custom_{user_id}_{uuid.uuid4().hex}.jpg"
    final_prompt = f"{prompt}".strip()

    try:
        await bot.download(photo_file_id, destination=temp_path)
        await bot.send_message(
            chat_id,
            f'💳 Списано <b>{config.photo_custom_cost}</b> раскладов.\n'
            '✨ Генерирую фото, подождите...'
        )
        logger.info('Kie image request %s prompt="%s"', format_user(user_id, username), shorten(final_prompt))
        image_url = await asyncio.to_thread(upload_file, str(temp_path), config.kie_api_key)
        task_id = await asyncio.to_thread(
            create_image_task,
            final_prompt,
            config.kie_image_model,
            config.kie_api_key,
            config.kie_api_url,
            image_url,
        )
        logger.info('Kie image task created task_id=%s %s', task_id, format_user(user_id, username))

        record = await poll_task(task_id, config.kie_api_key)
        urls = extract_result_urls(record)
        if not urls:
            raise RuntimeError('Kie image result urls not found')

        await _send_image_group(bot, chat_id, urls)
        await bot.send_message(
            chat_id,
            f'✅ Фото создано\nЗапрос: <i>{shorten(prompt, 200)}</i>',
            reply_markup=photo_custom_done_kb(),
        )
        await notify_admin(
            bot,
            config.admin_notify_ids,
            f'✅ Успешная генерация (ИИ-Фотошоп). Пользователь {user_id} (@{username or "-"})'
        )
        return True
    except Exception as e:
        logger.exception('Kie image generation failed %s', format_user(user_id, username))
        if charged:
            await crud.update_balance(config.database_path, user_id, config.photo_custom_cost)
        await bot.send_message(chat_id, '❌ Ошибка генерации. Попробуйте позже. расклады возвращены.')
        await notify_admin(
            bot,
            config.admin_notify_ids,
            f'❌ Ошибка Kie.ai (image): {e} (user {user_id} @{username or "-"})'
        )
        return False
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass


async def run_text_image_generation(
    bot: Bot,
    user_id: int,
    chat_id: int,
    prompt: str,
    username: str | None = None,
) -> bool:
    config = load_config()
    await _expire_subscription_if_needed(user_id)
    balance = await crud.get_balance(config.database_path, user_id)
    if balance < config.photo_custom_cost:
        await bot.send_message(chat_id, f'Недостаточно раскладов. Нужно {config.photo_custom_cost} раскладов.')
        return False

    await crud.update_balance(config.database_path, user_id, -config.photo_custom_cost)
    charged = True
    final_prompt = prompt.strip()

    try:
        await bot.send_message(
            chat_id,
            f'💳 Списано <b>{config.photo_custom_cost}</b> раскладов.\n'
            '✨ Генерирую изображение, подождите...'
        )
        logger.info('Kie image request %s prompt="%s"', format_user(user_id, username), shorten(final_prompt))
        task_id = await asyncio.to_thread(
            create_image_task,
            final_prompt,
            config.kie_text_image_model,
            config.kie_api_key,
            config.kie_api_url,
            None,
        )
        logger.info('Kie image task created task_id=%s %s', task_id, format_user(user_id, username))

        record = await poll_task(task_id, config.kie_api_key)
        urls = extract_result_urls(record)
        if not urls:
            raise RuntimeError('Kie image result urls not found')

        await _send_image_group(bot, chat_id, urls)
        await bot.send_message(
            chat_id,
            f'✅ Изображение создано\nЗапрос: <i>{shorten(prompt, 200)}</i>',
            reply_markup=photo_text_done_kb(),
        )
        await notify_admin(
            bot,
            config.admin_notify_ids,
            f'✅ Успешная генерация (Текст→Фото). Пользователь {user_id} (@{username or "-"})'
        )
        return True
    except Exception as e:
        logger.exception('Kie text image generation failed %s', format_user(user_id, username))
        if charged:
            await crud.update_balance(config.database_path, user_id, config.photo_custom_cost)
        await bot.send_message(chat_id, '❌ Ошибка генерации. Попробуйте позже. расклады возвращены.')
        await notify_admin(
            bot,
            config.admin_notify_ids,
            f'❌ Ошибка Kie.ai (text image): {e} (user {user_id} @{username or "-"})'
        )
        return False


async def _expire_subscription_if_needed(user_id: int) -> None:
    sub = await crud.get_subscription(load_config().database_path, user_id)
    if not sub:
        return
    if sub.get('status') not in ('active', 'inactive'):
        return
    if int(sub.get('auto_renew', 0)) == 1:
        return
    try:
        end = datetime.fromisoformat(sub['current_period_end'])
    except Exception:
        return
    if datetime.utcnow() >= end:
        await crud.mark_subscription_status(load_config().database_path, user_id, 'expired')
        await crud.set_balance(load_config().database_path, user_id, 0)

