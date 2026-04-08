from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from services.tarot_deck import DrawnCard

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CardSlot:
    x: int
    y: int
    width: int
    height: int
    angle: float = 0.0


@dataclass(frozen=True)
class TarotLayout:
    canvas_width: int
    canvas_height: int
    background: str | None
    slots: list[CardSlot]


DEFAULT_LAYOUT = TarotLayout(
    canvas_width=1280,
    canvas_height=720,
    background=None,
    slots=[
        CardSlot(x=230, y=140, width=260, height=440, angle=-4.0),
        CardSlot(x=510, y=120, width=260, height=440, angle=0.0),
        CardSlot(x=790, y=140, width=260, height=440, angle=4.0),
    ],
)


def _load_slot(raw: dict) -> CardSlot:
    return CardSlot(
        x=int(raw.get('x', 0)),
        y=int(raw.get('y', 0)),
        width=int(raw.get('width', 200)),
        height=int(raw.get('height', 340)),
        angle=float(raw.get('angle', 0.0)),
    )


def load_layout(layout_path: str) -> TarotLayout:
    path = Path(layout_path)
    if not path.exists():
        return DEFAULT_LAYOUT

    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return DEFAULT_LAYOUT

    raw_slots = payload.get('slots') if isinstance(payload, dict) else None
    if not isinstance(raw_slots, list) or len(raw_slots) < 3:
        return DEFAULT_LAYOUT

    slots = [_load_slot(slot) for slot in raw_slots[:3]]
    return TarotLayout(
        canvas_width=int(payload.get('canvas_width', DEFAULT_LAYOUT.canvas_width)),
        canvas_height=int(payload.get('canvas_height', DEFAULT_LAYOUT.canvas_height)),
        background=payload.get('background') or DEFAULT_LAYOUT.background,
        slots=slots,
    )


def _open_background(layout: TarotLayout, fallback_background_path: str) -> Image.Image:
    background_path = layout.background or fallback_background_path
    bg_file = Path(background_path)
    if bg_file.exists():
        try:
            bg = Image.open(bg_file).convert('RGBA')
            if bg.size != (layout.canvas_width, layout.canvas_height):
                bg = bg.resize((layout.canvas_width, layout.canvas_height), Image.Resampling.LANCZOS)
            return bg
        except Exception as e:
            logger.warning('Tarot background open failed path=%s error=%s', bg_file, e)

    return Image.new('RGBA', (layout.canvas_width, layout.canvas_height), (30, 123, 198, 255))


def compose_spread_image(
    drawn_cards: list[DrawnCard],
    output_path: str,
    layout_path: str,
    background_path: str,
) -> Path:
    if len(drawn_cards) < 3:
        raise ValueError('Three drawn cards required')

    layout = load_layout(layout_path)
    canvas = _open_background(layout, background_path)

    for idx, drawn in enumerate(drawn_cards[:3]):
        slot = layout.slots[idx]
        card_img = Image.open(drawn.card.image_path).convert('RGBA')
        card_img = card_img.resize((slot.width, slot.height), Image.Resampling.LANCZOS)
        if drawn.is_reversed:
            card_img = card_img.rotate(180, expand=True, resample=Image.Resampling.BICUBIC)
        if slot.angle:
            card_img = card_img.rotate(slot.angle, expand=True, resample=Image.Resampling.BICUBIC)

        x = slot.x + (slot.width - card_img.width) // 2
        y = slot.y + (slot.height - card_img.height) // 2
        canvas.alpha_composite(card_img, (x, y))

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert('RGB').save(out, format='JPEG', quality=95)
    return out
