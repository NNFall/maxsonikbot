from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class DreamContext:
    dream_text: str
    mode: str
    last_text: str
    ts: float


_CTX: dict[int, DreamContext] = {}
_TTL_SECONDS = 600


def set_context(user_id: int, dream_text: str, mode: str, last_text: str) -> None:
    _CTX[user_id] = DreamContext(
        dream_text=dream_text,
        mode=mode,
        last_text=last_text,
        ts=time.time(),
    )


def get_context(user_id: int) -> DreamContext | None:
    ctx = _CTX.get(user_id)
    if not ctx:
        return None
    if time.time() - ctx.ts > _TTL_SECONDS:
        _CTX.pop(user_id, None)
        return None
    return ctx


def clear_context(user_id: int) -> None:
    _CTX.pop(user_id, None)
