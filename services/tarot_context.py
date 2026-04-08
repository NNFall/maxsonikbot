from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class TarotContext:
    question: str
    cards_payload: list[dict]
    mode: str
    last_text: str
    ts: float


_CTX: dict[int, TarotContext] = {}
_TTL_SECONDS = 600


def set_context(user_id: int, question: str, cards_payload: list[dict], mode: str, last_text: str) -> None:
    _CTX[user_id] = TarotContext(
        question=question,
        cards_payload=cards_payload,
        mode=mode,
        last_text=last_text,
        ts=time.time(),
    )


def get_context(user_id: int) -> TarotContext | None:
    ctx = _CTX.get(user_id)
    if not ctx:
        return None
    if time.time() - ctx.ts > _TTL_SECONDS:
        _CTX.pop(user_id, None)
        return None
    return ctx


def clear_context(user_id: int) -> None:
    _CTX.pop(user_id, None)
