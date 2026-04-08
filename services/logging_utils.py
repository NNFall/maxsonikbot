from __future__ import annotations


def shorten(text: str, limit: int = 160) -> str:
    text = text.replace('\n', ' ').strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + '...'


def format_user(user_id: int, username: str | None) -> str:
    if username:
        return f'id={user_id} username=@{username}'
    return f'id={user_id} username=-'
