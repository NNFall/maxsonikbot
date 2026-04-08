from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import load_config
from services.tarot_ai import generate_tarot_reading_text
from services.tarot_deck import draw_cards, load_deck


async def _run(question: str, mode: str) -> None:
    cfg = load_config()
    deck = load_deck(cfg.tarot_cards_dir)
    if len(deck) < 3:
        raise RuntimeError(f'Need at least 3 cards in {cfg.tarot_cards_dir}')

    cards = draw_cards(deck, count=3)
    print('Selected cards:')
    for idx, card in enumerate(cards, start=1):
        orientation = 'reversed' if card.is_reversed else 'upright'
        print(f'  {idx}. {card.card.title} ({orientation})')

    text = await generate_tarot_reading_text(question, cards, mode=mode)
    print('\n----- MODEL OUTPUT START -----\n')
    print(text)
    print('\n----- MODEL OUTPUT END -----')


def main() -> None:
    parser = argparse.ArgumentParser(description='Test text LLM chain for tarot')
    parser.add_argument('--question', default='Когда я куплю себе Porsche?')
    parser.add_argument('--mode', choices=['teaser', 'full'], default='teaser')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(name)s | %(message)s')
    asyncio.run(_run(args.question, args.mode))


if __name__ == '__main__':
    main()
