from __future__ import annotations

import asyncio
import json
import logging
import re
from contextlib import suppress

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from config import load_config
from database import crud
from handlers.states import TarotState
from keyboards.payment_kb import choose_subscription_prompt_kb
from keyboards.tarot_kb import tarot_after_reading_kb, tarot_open_full_kb
from prompts.tarot_prompts import paywall_text
from services.balance_card import build_inactive_balance_text
from services.notify import notify_admin
from services.tarot_ai import generate_tarot_followup_text
from services.tarot_context import get_context, set_context
from services.tarot_deck import draw_cards, load_deck, restore_drawn_cards
from services.tarot_reading import build_tarot_bundle, run_paid_tarot_reading

router = Router()
config = load_config()
logger = logging.getLogger(__name__)
TAG_RE = re.compile(r'<[^>]+>')
FOLLOWUP_SHORT = {
    'что',
    'что?',
    'почему',
    'почему?',
    'не понял',
    'непонятно',
    'поясни',
    'поясните',
    'объясни',
    'объясните',
    'что это значит',
    'что значит',
    'что дальше',
    'и что дальше',
    'подробнее',
}
FOLLOWUP_PHRASES = (
    'что это значит',
    'что значит',
    'не понял',
    'непонятно',
    'поясни',
    'поясните',
    'объясни',
    'объясните',
    'можно подробнее',
    'как понять',
    'почему так',
    'и что дальше',
    'что дальше',
    'уточни',
    'уточните',
)
PROGRESS_STEPS = (
    'Настраиваюсь на расклад',
    'Собираю фокус вопроса',
    'Сверяюсь с энергией запроса',
    'Вытягиваю карту',
    'Считываю символы',
    'Проверяю ключевые акценты',
    'Сопоставляю энергии',
    'Уточняю смысл позиции',
    'Собираю ответ',
    'Формулирую вывод',
)


def _normalize_question(text: str | None) -> str:
    if not text:
        return ''
    return ' '.join(text.strip().split())


def _serialize_cards(cards) -> list[dict]:
    return [{'slug': card.card.slug, 'rev': int(card.is_reversed)} for card in cards]


async def _send_markdown_safe(bot, chat_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id, text, parse_mode=ParseMode.MARKDOWN)
    except TelegramBadRequest:
        plain = TAG_RE.sub('', text or '').replace('*', '').replace('_', '').replace('`', '').strip()
        await bot.send_message(chat_id, plain)


def _is_followup_message(text: str | None) -> bool:
    if not text:
        return False
    normalized = _normalize_question(text).lower()
    if not normalized:
        return False
    if normalized in FOLLOWUP_SHORT:
        return True
    return any(phrase in normalized for phrase in FOLLOWUP_PHRASES)


async def _progress_loop(progress_msg: Message) -> None:
    step_idx = 0
    while True:
        text = f'{PROGRESS_STEPS[step_idx % len(PROGRESS_STEPS)]}...'
        try:
            await progress_msg.edit_text(text)
        except TelegramBadRequest:
            pass
        await asyncio.sleep(10)
        step_idx += 1


async def _run_with_progress(message: Message):
    sticker_msg: Message | None = None
    sticker_id = (config.tarot_progress_sticker_id or '').strip()
    if sticker_id:
        try:
            sticker_msg = await message.answer_sticker(sticker_id)
            logger.info(
                'Tarot progress sticker sent chat_id=%s message_id=%s',
                message.chat.id,
                sticker_msg.message_id,
            )
        except Exception as e:
            logger.warning('Tarot progress sticker send failed chat_id=%s error=%s', message.chat.id, e)
    progress_msg = await message.answer('Настраиваюсь на расклад...')
    task = asyncio.create_task(_progress_loop(progress_msg))
    return sticker_msg, progress_msg, task


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


async def _stop_progress(
    sticker_msg: Message | None,
    progress_msg: Message | None,
    task: asyncio.Task | None,
) -> None:
    if task:
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=1.5)
        except asyncio.CancelledError:
            logger.info('Tarot progress task cancelled')
        except asyncio.TimeoutError:
            logger.warning('Tarot progress task cancel timeout')
        except Exception as e:
            logger.warning('Tarot progress task cancel error: %s', e)
    if progress_msg:
        await _safe_delete_message(progress_msg, 'Tarot progress')
    if sticker_msg:
        await _safe_delete_message(sticker_msg, 'Tarot progress sticker')


async def _handle_followup(message: Message, ctx) -> None:
    cards = restore_drawn_cards(config.tarot_cards_dir, ctx.cards_payload)
    if ctx.mode == 'teaser' and cards:
        cards = [cards[0]]
    try:
        text = await generate_tarot_followup_text(
            ctx.question,
            _normalize_question(message.text),
            cards,
            ctx.last_text,
            ctx.mode,
        )
        await _send_markdown_safe(message.bot, message.chat.id, text)
        set_context(
            user_id=message.from_user.id,
            question=ctx.question,
            cards_payload=ctx.cards_payload,
            mode=ctx.mode,
            last_text=text,
        )
    except Exception as e:
        logger.exception('Tarot followup failed user_id=%s', message.from_user.id)
        await message.answer('Не удалось уточнить расклад. Попробуйте позже.')
        await notify_admin(
            message.bot,
            config.admin_notify_ids,
            f'Ошибка уточнения расклада: {e} (user {message.from_user.id} @{message.from_user.username or "-"})',
        )


async def _process_question(message: Message, state: FSMContext) -> None:
    question = _normalize_question(message.text)
    if len(question) < 4:
        await message.answer('Сформулируйте вопрос чуть подробнее.')
        return
    if len(question) > 350:
        await message.answer('Слишком длинный вопрос. Сократите его до 350 символов.')
        return

    user = await crud.get_user(config.database_path, message.from_user.id)
    if not user:
        await message.answer('Пользователь не найден. Нажмите /start')
        await state.clear()
        return

    deck = load_deck(config.tarot_cards_dir)
    if len(deck) < 3:
        await message.answer('В колоде недостаточно карт. Добавьте минимум 3 файла в папку карт.')
        return

    await state.clear()
    await state.update_data(tarot_question=question)
    balance = await crud.get_balance(config.database_path, message.from_user.id)

    asyncio.create_task(
        notify_admin(
            message.bot,
            config.admin_notify_ids,
            f'🔮 Пользователь задал вопрос: {message.from_user.id} (@{message.from_user.username or "-"})\n'
            f'Вопрос: {question}',
        )
    )

    # Paywall only for first-time users (one teaser in lifetime)
    if (
        int(user.get('free_trial_used', 0)) == 0
        and int(user.get('has_purchased', 0)) == 0
        and balance < config.tarot_spread_cost
    ):
        cards = draw_cards(deck, count=1)
        cards_payload = _serialize_cards(cards)
        await state.update_data(tarot_cards=cards_payload)
        sticker_msg, progress_msg, progress_task = await _run_with_progress(message)
        bundle = None
        try:
            bundle = await build_tarot_bundle(question, message.from_user.id, mode='teaser', cards_override=cards)
            await message.answer_photo(
                photo=FSInputFile(str(bundle.image_path)),
            )
            await _send_markdown_safe(message.bot, message.chat.id, bundle.text)
            set_context(
                user_id=message.from_user.id,
                question=question,
                cards_payload=cards_payload,
                mode='teaser',
                last_text=bundle.text,
            )
        except Exception as e:
            logger.exception('Tarot teaser failed user_id=%s', message.from_user.id)
            await message.answer('Не удалось открыть первую карту. Попробуйте позже.')
            await notify_admin(
                message.bot,
                config.admin_notify_ids,
                f'Ошибка первой карты: {e} (user {message.from_user.id} @{message.from_user.username or "-"})',
            )
            return
        finally:
            await _stop_progress(sticker_msg, progress_msg, progress_task)
            if bundle:
                with suppress(Exception):
                    bundle.image_path.unlink(missing_ok=True)

        await crud.set_free_trial_used(config.database_path, message.from_user.id, 1)
        await state.update_data(
            pending_action=json.dumps(
                {
                    'type': 'tarot_full',
                    'question': question,
                    'username': message.from_user.username,
                    'first_card': cards_payload[0] if cards_payload else None,
                    'first_text': bundle.text if bundle else '',
                }
            )
        )
        await message.answer(
            'Продолжение расклада в двух оставшихся картах дает главный ответ.\n'
            'Нажмите кнопку ниже, чтобы открыть полный расклад.',
            reply_markup=tarot_open_full_kb(),
        )
        return

    # Full reading for returning users (requires token balance)
    if balance < config.tarot_spread_cost:
        await state.update_data(
            pending_action=json.dumps(
                {
                    'type': 'tarot_full',
                    'question': question,
                    'username': message.from_user.username,
                }
            )
        )
        balance_text = await build_inactive_balance_text(message.bot, balance, include_header=False)
        await message.answer(
            f'Недостаточно раскладов для полного расклада.\n\n{balance_text}',
            reply_markup=choose_subscription_prompt_kb(),
        )
        return

    cards = draw_cards(deck, count=3)
    cards_payload = _serialize_cards(cards)
    await state.update_data(tarot_cards=cards_payload)
    sticker_msg, progress_msg, progress_task = await _run_with_progress(message)
    ok = False
    try:
        ok = await run_paid_tarot_reading(
            message.bot,
            user_id=message.from_user.id,
            chat_id=message.chat.id,
            question=question,
            username=message.from_user.username,
            cards_payload=cards_payload,
        )
        logger.info(
            'Tarot full reading result user_id=%s chat_id=%s ok=%s',
            message.from_user.id,
            message.chat.id,
            ok,
        )
    finally:
        await _stop_progress(sticker_msg, progress_msg, progress_task)
    if ok:
        try:
            await message.answer(
                '✅ Расклад завершен.\n'
                'Если хотите, задайте новый вопрос или вернитесь в меню.',
                reply_markup=tarot_after_reading_kb(),
            )
            logger.info(
                'Tarot finish message sent user_id=%s chat_id=%s',
                message.from_user.id,
                message.chat.id,
            )
        except Exception:
            logger.exception(
                'Tarot finish message failed user_id=%s chat_id=%s',
                message.from_user.id,
                message.chat.id,
            )


@router.callback_query(F.data == 'tarot:open_full')
async def cb_tarot_open_full(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    pending_payload = data.get('pending_action')
    pending_action: dict | None = None
    if pending_payload:
        try:
            pending_action = json.loads(pending_payload)
        except json.JSONDecodeError:
            pending_action = None

    if not pending_action or pending_action.get('type') != 'tarot_full':
        ctx = get_context(callback.from_user.id)
        if ctx and ctx.mode == 'teaser' and ctx.cards_payload:
            pending_action = {
                'type': 'tarot_full',
                'question': ctx.question,
                'username': callback.from_user.username,
                'first_card': ctx.cards_payload[0],
                'first_text': ctx.last_text,
            }
            await state.update_data(pending_action=json.dumps(pending_action))

    if not pending_action or pending_action.get('type') != 'tarot_full':
        await callback.message.answer('Не найден активный расклад. Задайте вопрос заново.')
        return

    balance = await crud.get_balance(config.database_path, callback.from_user.id)
    balance_text = await build_inactive_balance_text(callback.bot, balance, include_header=False)
    await callback.message.answer(
        f'{paywall_text()}\n\n{balance_text}',
        reply_markup=choose_subscription_prompt_kb(),
    )


@router.callback_query(F.data == 'menu:ask')
async def cb_menu_ask(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await callback.message.answer(
        '<b>Задайте вопрос таро</b>\n'
        'Примеры:\n'
        '• <i>Когда в моей жизни появятся серьезные отношения?</i>\n'
        '• <i>Что поможет мне увеличить доход?</i>\n\n'
        'Я сделаю расклад и дам подробный разбор.',
    )
    await state.set_state(TarotState.waiting_question)


@router.message(Command('ask'))
async def cmd_ask(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        '<b>Задайте вопрос таро</b>\n'
        'Примеры:\n'
        '• <i>Когда в моей жизни появятся серьезные отношения?</i>\n'
        '• <i>Что поможет мне увеличить доход?</i>\n\n'
        'Я сделаю расклад и дам подробный разбор.',
    )
    await state.set_state(TarotState.waiting_question)


@router.message(TarotState.waiting_question)
async def tarot_question_received(message: Message, state: FSMContext) -> None:
    await _process_question(message, state)


@router.message(StateFilter(None), F.text, ~F.text.startswith('/'))
async def tarot_fallback_question(message: Message, state: FSMContext) -> None:
    ctx = get_context(message.from_user.id)
    if ctx and _is_followup_message(message.text):
        await _handle_followup(message, ctx)
        return
    await _process_question(message, state)

