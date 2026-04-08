from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp'}


@dataclass(frozen=True)
class TarotCard:
    slug: str
    title: str
    image_path: Path


@dataclass(frozen=True)
class DrawnCard:
    card: TarotCard
    is_reversed: bool


def humanize_card_name(slug: str) -> str:
    name = slug.replace('_', ' ').replace('-', ' ').strip()
    if not name:
        return slug
    return ' '.join(part.capitalize() for part in name.split())


def load_deck(cards_dir: str) -> list[TarotCard]:
    root = Path(cards_dir)
    if not root.exists():
        return []

    cards: list[TarotCard] = []
    for file in sorted(root.rglob('*')):
        if not file.is_file():
            continue
        if file.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        slug = file.stem
        cards.append(TarotCard(slug=slug, title=humanize_card_name(slug), image_path=file))
    return cards


def _deck_index(cards_dir: str) -> dict[str, TarotCard]:
    return {card.slug: card for card in load_deck(cards_dir)}


def get_card_by_slug(cards_dir: str, slug: str) -> TarotCard | None:
    return _deck_index(cards_dir).get(slug)


def restore_drawn_cards(cards_dir: str, items: list[dict]) -> list[DrawnCard]:
    index = _deck_index(cards_dir)
    cards: list[DrawnCard] = []
    for item in items:
        slug = str(item.get('slug', '')).strip()
        if not slug:
            continue
        card = index.get(slug)
        if not card:
            continue
        is_reversed = bool(item.get('rev') or item.get('is_reversed'))
        cards.append(DrawnCard(card=card, is_reversed=is_reversed))
    return cards


def draw_cards(deck: list[TarotCard], count: int = 3) -> list[DrawnCard]:
    if len(deck) < count:
        raise ValueError(f'Not enough tarot cards in deck: required={count}, available={len(deck)}')

    selected = random.sample(deck, count)
    return [DrawnCard(card=card, is_reversed=bool(random.getrandbits(1))) for card in selected]
