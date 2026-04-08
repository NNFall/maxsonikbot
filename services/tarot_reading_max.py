from __future__ import annotations

import asyncio
import logging
import random
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from PIL import Image
from maxapi.enums.parse_mode import ParseMode
from maxapi.types import InputMedia

from config import load_config
from database import crud
from services.notify import notify_admin
from services.tarot_ai import generate_tarot_continuation_text, generate_tarot_reading_text
from services.tarot_context import set_context
from services.tarot_deck import DrawnCard, TarotCard, draw_cards, load_deck, restore_drawn_cards
from services.tarot_layout import compose_spread_image

logger = logging.getLogger(__name__)
TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class TarotReadingBundle:
    cards: list[DrawnCard]
    image_path: Path
    text: str


def _plain_text(text: str) -> str:
    cleaned = TAG_RE.sub("", text or "").strip()
    return cleaned.replace("*", "").replace("_", "").replace("`", "")


def _serialize_cards(cards: list[DrawnCard]) -> list[dict]:
    return [{"slug": card.card.slug, "rev": int(card.is_reversed)} for card in cards]


def _render_single_card_image(card: DrawnCard, output_path: str) -> Path:
    image = Image.open(card.card.image_path).convert("RGBA")
    if card.is_reversed:
        image = image.rotate(180, expand=True, resample=Image.Resampling.BICUBIC)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(out, format="JPEG", quality=95)
    return out


def _draw_additional_cards(deck: list[TarotCard], exclude_slug: str, count: int = 2) -> list[DrawnCard]:
    available = [card for card in deck if card.slug != exclude_slug]
    if len(available) < count:
        raise RuntimeError("Not enough cards to draw the continuation")
    selected = random.sample(available, count)
    return [DrawnCard(card=card, is_reversed=bool(random.getrandbits(1))) for card in selected]


async def _send_markdown_safe(bot, chat_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id=chat_id, text=text, format=ParseMode.MARKDOWN)
    except Exception:
        await bot.send_message(chat_id=chat_id, text=_plain_text(text))


async def _send_local_image(bot, chat_id: int, path: Path) -> None:
    upload = await bot.upload_media(InputMedia(str(path)))
    await bot.send_message(chat_id=chat_id, attachments=[upload])


async def build_tarot_bundle(
    question: str,
    user_id: int,
    mode: str,
    cards_override: list[DrawnCard] | None = None,
) -> TarotReadingBundle:
    cfg = load_config()
    deck = load_deck(cfg.tarot_cards_dir)
    if len(deck) < 3:
        raise RuntimeError(f"Not enough cards in TAROT_CARDS_DIR: {cfg.tarot_cards_dir}")

    cards = cards_override or draw_cards(deck, count=3)
    text = await generate_tarot_reading_text(question, cards, mode=mode)

    temp_dir = Path(cfg.media_temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    image_path = temp_dir / f"tarot_{mode}_{user_id}_{uuid.uuid4().hex}.jpg"

    if mode == "teaser":
        await asyncio.to_thread(_render_single_card_image, cards[0], str(image_path))
    else:
        await asyncio.to_thread(
            compose_spread_image,
            cards,
            str(image_path),
            cfg.tarot_layout_path,
            cfg.tarot_background_path,
        )

    return TarotReadingBundle(cards=cards, image_path=image_path, text=text)


async def run_teaser_tarot_reading(
    bot,
    user_id: int,
    chat_id: int,
    question: str,
    cards_payload: list[dict] | None = None,
) -> tuple[bool, list[dict], str]:
    cfg = load_config()
    cards_override = restore_drawn_cards(cfg.tarot_cards_dir, cards_payload or [])
    if not cards_override:
        deck = load_deck(cfg.tarot_cards_dir)
        cards_override = draw_cards(deck, count=1)

    bundle: TarotReadingBundle | None = None
    try:
        bundle = await build_tarot_bundle(question, user_id, mode="teaser", cards_override=cards_override)
        await _send_local_image(bot, chat_id, bundle.image_path)
        await _send_markdown_safe(bot, chat_id, bundle.text)
        payload = _serialize_cards(bundle.cards)
        set_context(
            user_id=user_id,
            question=question,
            cards_payload=payload,
            mode="teaser",
            last_text=bundle.text,
        )
        return True, payload, bundle.text
    except Exception:
        logger.exception("Tarot teaser failed user_id=%s", user_id)
        return False, [], ""
    finally:
        if bundle:
            bundle.image_path.unlink(missing_ok=True)


async def run_paid_tarot_reading(
    bot,
    user_id: int,
    chat_id: int,
    question: str,
    username: str | None = None,
    cards_payload: list[dict] | None = None,
) -> bool:
    cfg = load_config()
    cost = cfg.tarot_spread_cost
    balance = await crud.get_balance(cfg.database_path, user_id)
    if balance < cost:
        return False

    cards_override = restore_drawn_cards(cfg.tarot_cards_dir, cards_payload or [])
    if not cards_override:
        cards_override = None

    await crud.update_balance(cfg.database_path, user_id, -cost)
    bundle: TarotReadingBundle | None = None
    try:
        bundle = await build_tarot_bundle(question, user_id, mode="full", cards_override=cards_override)
        await _send_local_image(bot, chat_id, bundle.image_path)
        await _send_markdown_safe(bot, chat_id, bundle.text)
        set_context(
            user_id=user_id,
            question=question,
            cards_payload=_serialize_cards(bundle.cards),
            mode="full",
            last_text=bundle.text,
        )
        await notify_admin(
            bot,
            cfg.admin_notify_ids,
            f"✅ Успешный расклад (3 карты). Пользователь {user_id} (@{username or '-'})",
        )
        return True
    except Exception as e:
        logger.exception("Tarot full reading failed user_id=%s", user_id)
        await crud.update_balance(cfg.database_path, user_id, cost)
        await bot.send_message(chat_id=chat_id, text="❌ Не удалось выполнить расклад. Лимит раскладов возвращен.")
        await notify_admin(
            bot,
            cfg.admin_notify_ids,
            f"❌ Ошибка расклада (3 карты): {e} (user {user_id} @{username or '-'})",
        )
        return False
    finally:
        if bundle:
            bundle.image_path.unlink(missing_ok=True)


async def run_tarot_continuation(
    bot,
    user_id: int,
    chat_id: int,
    question: str,
    username: str | None,
    first_card_payload: dict,
    first_text: str,
) -> bool:
    cfg = load_config()
    cost = cfg.tarot_spread_cost
    balance = await crud.get_balance(cfg.database_path, user_id)
    if balance < cost:
        return False

    cards = restore_drawn_cards(cfg.tarot_cards_dir, [first_card_payload])
    if not cards:
        await bot.send_message(chat_id=chat_id, text="Не удалось восстановить первую карту. Попробуйте позже.")
        return False

    first_card = cards[0]
    deck = load_deck(cfg.tarot_cards_dir)
    if len(deck) < 3:
        await bot.send_message(chat_id=chat_id, text="В колоде недостаточно карт для продолжения расклада.")
        return False

    await crud.update_balance(cfg.database_path, user_id, -cost)
    temp_dir = Path(cfg.media_temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    image_paths: list[Path] = []

    try:
        new_cards = _draw_additional_cards(deck, exclude_slug=first_card.card.slug, count=2)
        text = await generate_tarot_continuation_text(question, first_card, first_text, new_cards)

        for idx, card in enumerate(new_cards, start=1):
            image_path = temp_dir / f"tarot_cont_{user_id}_{idx}_{uuid.uuid4().hex}.jpg"
            await asyncio.to_thread(_render_single_card_image, card, str(image_path))
            image_paths.append(image_path)
            await _send_local_image(bot, chat_id, image_path)

        await _send_markdown_safe(bot, chat_id, text)

        full_cards = [first_card] + new_cards
        set_context(
            user_id=user_id,
            question=question,
            cards_payload=_serialize_cards(full_cards),
            mode="full",
            last_text=text,
        )
        await notify_admin(
            bot,
            cfg.admin_notify_ids,
            f"✅ Успешный расклад (продолжение). Пользователь {user_id} (@{username or '-'})",
        )
        return True
    except Exception as e:
        logger.exception("Tarot continuation failed user_id=%s", user_id)
        await crud.update_balance(cfg.database_path, user_id, cost)
        await bot.send_message(chat_id=chat_id, text="Не удалось продолжить расклад. Лимит раскладов возвращен.")
        await notify_admin(
            bot,
            cfg.admin_notify_ids,
            f"❌ Ошибка продолжения расклада: {e} (user {user_id} @{username or '-'})",
        )
        return False
    finally:
        for path in image_paths:
            path.unlink(missing_ok=True)
