from __future__ import annotations

import uuid
import logging
from pathlib import Path
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, FSInputFile
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.fsm.context import FSMContext

from config import load_config
from handlers.states import ConcatState, CutState
from services.ffmpeg_service import concat_videos, check_ffmpeg, remove_fragment
from services.notify import notify_admin
from keyboards.tools_kb import tools_kb

router = Router()
config = load_config()
logger = logging.getLogger(__name__)

DOWNLOAD_LIMIT_MB = 50
DOWNLOAD_LIMIT_BYTES = DOWNLOAD_LIMIT_MB * 1024 * 1024
SEND_VIDEO_TIMEOUT_SEC = 120
SEND_VIDEO_RETRY_TIMEOUT_SEC = 300


async def _download_video(message: Message, dest: Path) -> bool:
    if message.video and message.video.file_size and message.video.file_size > DOWNLOAD_LIMIT_BYTES:
        size_mb = message.video.file_size / 1024 / 1024
        logger.info(
            'Video too large user_id=%s username=@%s size_mb=%.2f limit_mb=%s',
            message.from_user.id,
            message.from_user.username,
            size_mb,
            DOWNLOAD_LIMIT_MB,
        )
        await message.answer(
            f'❌ Видео слишком большое для скачивания ботом.\n'
            f'Максимум: {DOWNLOAD_LIMIT_MB} МБ.'
        )
        try:
            dest.unlink(missing_ok=True)
        except Exception:
            pass
        return False
    if message.video and message.video.file_size:
        size_mb = message.video.file_size / 1024 / 1024
        logger.info(
            'Video download start user_id=%s username=@%s size_mb=%.2f',
            message.from_user.id,
            message.from_user.username,
            size_mb,
        )
    try:
        await message.bot.download(message.video.file_id, destination=dest)
        return True
    except TelegramBadRequest as e:
        if 'file is too big' in str(e).lower():
            await message.answer(
                f'❌ Видео слишком большое для скачивания ботом.\n'
                f'Максимум: {DOWNLOAD_LIMIT_MB} МБ.'
            )
            try:
                dest.unlink(missing_ok=True)
            except Exception:
                pass
            return False
        try:
            dest.unlink(missing_ok=True)
        except Exception:
            pass
        raise
    except Exception:
        try:
            dest.unlink(missing_ok=True)
        except Exception:
            pass
        raise


async def _send_video_with_retry(message: Message, file_path: Path) -> bool:
    try:
        await message.answer_video(FSInputFile(str(file_path)), request_timeout=SEND_VIDEO_TIMEOUT_SEC)
        return True
    except TelegramBadRequest as e:
        if 'file is too big' in str(e).lower():
            await message.answer('❌ Файл слишком большой для отправки через Telegram.')
            return False
        raise
    except TelegramNetworkError as e:
        logger.warning('Send video timeout, retrying: %s', e)
    except Exception as e:
        logger.warning('Send video error, retrying: %s', e)

    try:
        await message.answer_video(FSInputFile(str(file_path)), request_timeout=SEND_VIDEO_RETRY_TIMEOUT_SEC)
        return True
    except TelegramBadRequest as e:
        if 'file is too big' in str(e).lower():
            await message.answer('❌ Файл слишком большой для отправки через Telegram.')
            return False
        raise
    except Exception as e:
        logger.error('Send video failed after retry: %s', e)
        return False


async def _start_concat(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not check_ffmpeg(config.ffmpeg_path):
        await message.answer(
            '⚠️ <b>FFmpeg не найден.</b>\n'
            'Установите ffmpeg и укажите путь в <code>FFMPEG_PATH</code>.'
        )
        logger.error('FFmpeg not found: path=%s user_id=%s username=@%s', config.ffmpeg_path, message.from_user.id, message.from_user.username)
        return
    await message.answer('📼 <b>Склейка видео</b>\nПришлите первое видео.')
    await state.set_state(ConcatState.waiting_video1)


async def _start_cut(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not check_ffmpeg(config.ffmpeg_path):
        await message.answer(
            '⚠️ <b>FFmpeg не найден.</b>\n'
            'Установите ffmpeg и укажите путь в <code>FFMPEG_PATH</code>.'
        )
        logger.error('FFmpeg not found: path=%s user_id=%s username=@%s', config.ffmpeg_path, message.from_user.id, message.from_user.username)
        return
    await message.answer('✂️ <b>Вырезать фрагмент</b>\nПришлите видео, из которого нужно убрать часть.')
    await state.set_state(CutState.waiting_video)


@router.callback_query(F.data == 'menu:concat')
async def cb_concat(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await _start_concat(callback.message, state)


@router.callback_query(F.data == 'menu:tools')
async def cb_tools(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await callback.message.answer(
        '📼 <b>Инструменты</b>\nВыберите действие:',
        reply_markup=tools_kb(),
    )


@router.message(Command('concat'))
async def cmd_concat(message: Message, state: FSMContext) -> None:
    await _start_concat(message, state)


@router.message(ConcatState.waiting_video1)
async def concat_video1(message: Message, state: FSMContext) -> None:
    if not message.video:
        await message.answer('📼 Нужен видеофайл. Пришлите первое видео.')
        return

    temp_dir = Path(config.media_temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    path1 = temp_dir / f"concat_{message.from_user.id}_{uuid.uuid4().hex}_1.mp4"
    try:
        ok = await _download_video(message, path1)
        if not ok:
            return
    except Exception as e:
        logger.error('Concat download1 error user_id=%s username=@%s error=%s', message.from_user.id, message.from_user.username, e)
        await message.answer('❌ Не удалось скачать видео. Попробуйте позже.')
        return

    await state.update_data(video1=str(path1))
    await message.answer('📼 Теперь пришлите второе видео.')
    await state.set_state(ConcatState.waiting_video2)


@router.message(ConcatState.waiting_video2)
async def concat_video2(message: Message, state: FSMContext) -> None:
    if not message.video:
        await message.answer('📼 Нужен видеофайл. Пришлите второе видео.')
        return

    data = await state.get_data()
    path1 = data.get('video1')
    if not path1:
        await message.answer('Данные потеряны. Начните заново.')
        await state.clear()
        return

    temp_dir = Path(config.media_temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    path2 = temp_dir / f"concat_{message.from_user.id}_{uuid.uuid4().hex}_2.mp4"
    try:
        ok = await _download_video(message, path2)
        if not ok:
            return
    except Exception as e:
        logger.error('Concat download2 error user_id=%s username=@%s error=%s', message.from_user.id, message.from_user.username, e)
        await message.answer('❌ Не удалось скачать видео. Попробуйте позже.')
        return

    output = temp_dir / f"concat_{message.from_user.id}_{uuid.uuid4().hex}_out.mp4"

    try:
        logger.info('Concat start user_id=%s username=@%s', message.from_user.id, message.from_user.username)
        concat_videos([path1, str(path2)], str(output), config.ffmpeg_path)
        ok = await _send_video_with_retry(message, output)
        if not ok:
            return
        logger.info('Concat success user_id=%s username=@%s', message.from_user.id, message.from_user.username)
        await notify_admin(
            message.bot,
            config.admin_notify_ids,
            f'✅ Склейка видео выполнена. Пользователь {message.from_user.id} (@{message.from_user.username or "-"})'
        )
    except Exception as e:
        logger.error('Concat error user_id=%s username=@%s error=%s', message.from_user.id, message.from_user.username, e)
        await message.answer('Ошибка склейки видео. Проверьте, что ffmpeg установлен.')
        await notify_admin(
            message.bot,
            config.admin_notify_ids,
            f'❌ Ошибка FFmpeg: {e} (user {message.from_user.id} @{message.from_user.username or "-"})'
        )
    finally:
        for p in [path1, str(path2), str(output)]:
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass
        await state.clear()


@router.callback_query(F.data == 'menu:cut')
async def cb_cut(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await _start_cut(callback.message, state)


@router.message(Command('cut'))
async def cmd_cut(message: Message, state: FSMContext) -> None:
    await _start_cut(message, state)


@router.message(CutState.waiting_video)
async def cut_video_receive(message: Message, state: FSMContext) -> None:
    if not message.video:
        await message.answer('✂️ Нужен видеофайл. Пришлите видео.')
        return

    temp_dir = Path(config.media_temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    input_path = temp_dir / f"cut_{message.from_user.id}_{uuid.uuid4().hex}.mp4"
    try:
        ok = await _download_video(message, input_path)
        if not ok:
            return
    except Exception as e:
        logger.error('Cut download error user_id=%s username=@%s error=%s', message.from_user.id, message.from_user.username, e)
        await message.answer('❌ Не удалось скачать видео. Попробуйте позже.')
        return

    await state.update_data(input_path=str(input_path))
    await message.answer(
        '⏱ <b>Таймкоды удаления</b>\n'
        'Введите интервал, который нужно вырезать, в формате <code>мм:сс-мм:сс</code>\n'
        'Например: <code>00:05-00:09</code>.'
    )
    await state.set_state(CutState.waiting_timecodes)


def _parse_timecodes(text: str) -> tuple[int, int] | None:
    text = text.strip()
    if '-' not in text:
        return None
    left, right = text.split('-', 1)

    def to_seconds(value: str) -> int | None:
        value = value.strip()
        parts = value.split(':')
        if len(parts) != 2:
            return None
        if not parts[0].isdigit() or not parts[1].isdigit():
            return None
        mm = int(parts[0])
        ss = int(parts[1])
        if ss < 0 or ss > 59 or mm < 0:
            return None
        return mm * 60 + ss

    start = to_seconds(left)
    end = to_seconds(right)
    if start is None or end is None or end <= start:
        return None
    return start, end


@router.message(CutState.waiting_timecodes)
async def cut_video_timecodes(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer('Нужен текст с таймкодами, например: <code>00:05-00:09</code>.')
        return

    parsed = _parse_timecodes(message.text)
    if not parsed:
        await message.answer('Неверный формат. Пример: <code>00:05-00:09</code>.')
        return

    start_sec, end_sec = parsed
    data = await state.get_data()
    input_path = data.get('input_path')
    if not input_path:
        await message.answer('Данные потеряны. Начните заново.')
        await state.clear()
        return

    temp_dir = Path(config.media_temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    output = temp_dir / f"cut_{message.from_user.id}_{uuid.uuid4().hex}_out.mp4"

    try:
        logger.info(
            'Cut start user_id=%s username=@%s range=%s-%s',
            message.from_user.id,
            message.from_user.username,
            start_sec,
            end_sec,
        )
        remove_fragment(str(input_path), start_sec, end_sec, str(output), config.ffmpeg_path)
        ok = await _send_video_with_retry(message, output)
        if not ok:
            return
        logger.info('Cut success user_id=%s username=@%s', message.from_user.id, message.from_user.username)
        await notify_admin(
            message.bot,
            config.admin_notify_ids,
            f'✅ Вырезан фрагмент. Пользователь {message.from_user.id} (@{message.from_user.username or "-"})'
        )
    except Exception as e:
        logger.error('Cut error user_id=%s username=@%s error=%s', message.from_user.id, message.from_user.username, e)
        await message.answer('❌ Ошибка обработки видео. Проверьте формат и попробуйте снова.')
        await notify_admin(
            message.bot,
            config.admin_notify_ids,
            f'❌ Ошибка FFmpeg (cut): {e} (user {message.from_user.id} @{message.from_user.username or "-"})'
        )
    finally:
        for p in [input_path, str(output)]:
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass
        await state.clear()
