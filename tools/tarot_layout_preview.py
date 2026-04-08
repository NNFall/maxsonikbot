from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import load_config
from services.tarot_deck import draw_cards, load_deck
from services.tarot_layout import compose_spread_image, load_layout


def _parse_slot(value: str) -> dict:
    parts = [item.strip() for item in value.split(',')]
    if len(parts) != 5:
        raise ValueError('Slot must be x,y,width,height,angle')
    x, y, width, height = (int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))
    angle = float(parts[4])
    return {'x': x, 'y': y, 'width': width, 'height': height, 'angle': angle}


def main() -> None:
    cfg = load_config()
    parser = argparse.ArgumentParser(description='Tarot spread layout preview')
    parser.add_argument('--cards-dir', default=cfg.tarot_cards_dir)
    parser.add_argument('--layout', default=cfg.tarot_layout_path)
    parser.add_argument('--background', default=cfg.tarot_background_path)
    parser.add_argument('--out', default='media/temp/tarot_layout_preview.jpg')
    parser.add_argument('--seed', type=int, default=None)
    parser.add_argument('--slot1', type=str, default=None, help='x,y,width,height,angle')
    parser.add_argument('--slot2', type=str, default=None, help='x,y,width,height,angle')
    parser.add_argument('--slot3', type=str, default=None, help='x,y,width,height,angle')
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    deck = load_deck(args.cards_dir)
    if len(deck) < 3:
        print(f'Not enough cards in {args.cards_dir}. Need at least 3 files.')
        return

    layout = load_layout(args.layout)
    payload = {
        'canvas_width': layout.canvas_width,
        'canvas_height': layout.canvas_height,
        'background': args.background,
        'slots': [
            {
                'x': layout.slots[0].x,
                'y': layout.slots[0].y,
                'width': layout.slots[0].width,
                'height': layout.slots[0].height,
                'angle': layout.slots[0].angle,
            },
            {
                'x': layout.slots[1].x,
                'y': layout.slots[1].y,
                'width': layout.slots[1].width,
                'height': layout.slots[1].height,
                'angle': layout.slots[1].angle,
            },
            {
                'x': layout.slots[2].x,
                'y': layout.slots[2].y,
                'width': layout.slots[2].width,
                'height': layout.slots[2].height,
                'angle': layout.slots[2].angle,
            },
        ],
    }

    for idx, raw in enumerate([args.slot1, args.slot2, args.slot3]):
        if raw:
            payload['slots'][idx] = _parse_slot(raw)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_layout_path = out_path.with_suffix('.layout.tmp.json')
    tmp_layout_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    try:
        cards = draw_cards(deck, count=3)
        compose_spread_image(cards, str(out_path), str(tmp_layout_path), args.background)
        print(f'Preview saved: {out_path}')
        for idx, card in enumerate(cards, start=1):
            orientation = 'reversed' if card.is_reversed else 'upright'
            print(f'{idx}. {card.card.title} ({orientation})')
    finally:
        tmp_layout_path.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
