from __future__ import annotations

import argparse
import asyncio
import os

from maxapi import Bot, Dispatcher
from maxapi.types.updates import MessageCreated


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simple MAX echo bot for connectivity testing.")
    parser.add_argument("--token", default=None, help="MAX bot token. If omitted, uses MAX_BOT_TOKEN env var.")
    parser.add_argument(
        "--run-seconds",
        type=int,
        default=0,
        help="Optional timeout for polling in seconds (0 = run forever).",
    )
    return parser.parse_args()


async def run_echo(token: str, run_seconds: int = 0) -> None:
    bot = Bot(token=token)
    dp = Dispatcher()

    me = await bot.get_me()
    print(f"Connected to MAX as @{me.username} (id={me.user_id})")

    @dp.message_created()
    async def on_message(event: MessageCreated) -> None:
        sender = event.message.sender
        chat_id = event.message.recipient.chat_id
        text = (event.message.body.text or "").strip()

        if sender is None or chat_id is None:
            return

        if not text:
            await bot.send_message(chat_id=chat_id, text="Получил сообщение без текста.")
            return

        if text.lower() == "/start":
            await bot.send_message(chat_id=chat_id, text="Привет! Это тестовый echo-бот MAX. Напиши любой текст.")
            return

        await bot.send_message(chat_id=chat_id, text=f"echo: {text}")

    try:
        if run_seconds > 0:
            await asyncio.wait_for(dp.start_polling(bot), timeout=run_seconds)
        else:
            await dp.start_polling(bot)
    except TimeoutError:
        print(f"Polling stopped after {run_seconds} seconds.")
    finally:
        await bot.close_session()


def main() -> None:
    args = parse_args()
    token = args.token or os.getenv("MAX_BOT_TOKEN")
    if not token:
        raise RuntimeError("MAX token is empty. Pass --token or set MAX_BOT_TOKEN.")
    asyncio.run(run_echo(token, args.run_seconds))


if __name__ == "__main__":
    main()
