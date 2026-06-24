import asyncio
import logging
from urllib.parse import urlparse, urlunparse

from maxapi import Bot, Dispatcher
from maxapi.enums.parse_mode import ParseMode
from maxapi.types import BotCommand

from config import load_config
from database.db import setup as setup_db
from max_handlers import all_routers
from services.smart_mailer_max import smart_mailing_loop
from services.subscription_tasks_max import subscription_watcher


def _normalize_webhook_path(path: str) -> str:
    clean = (path or "/").strip()
    if not clean.startswith("/"):
        clean = f"/{clean}"
    return clean


def _normalize_webhook_url(url: str, path: str) -> str:
    parsed = urlparse((url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("MAX_WEBHOOK_URL must be absolute URL (https://domain/path)")
    parsed_path = parsed.path or "/"
    if parsed_path in {"/", ""}:
        parsed_path = path
    return urlunparse((parsed.scheme, parsed.netloc, parsed_path, "", "", ""))


async def main() -> None:
    config = load_config()
    token = config.max_bot_token or config.bot_token
    if not token:
        raise RuntimeError("MAX_BOT_TOKEN (or BOT_TOKEN) is empty. Fill .env")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    logger = logging.getLogger(__name__)

    await setup_db(config.database_path)

    bot = Bot(token=token, format=ParseMode.HTML)
    bot.set_api_url(config.max_api_url)
    logger.info("MAX API URL: %s", config.max_api_url)
    dp = Dispatcher()
    dp.include_routers(*all_routers)

    commands = [
        BotCommand(name="start", description="Запуск бота"),
        BotCommand(name="menu", description="Главное меню"),
        BotCommand(name="ask", description="Разобрать сон"),
        BotCommand(name="balance", description="Баланс и подписка"),
        BotCommand(name="invite", description="Пригласить друга"),
        BotCommand(name="help", description="Помощь"),
    ]
    try:
        await bot.set_my_commands(*commands)
    except Exception as e:
        logger.warning("Could not set commands: %s", e)

    asyncio.create_task(subscription_watcher(bot))
    asyncio.create_task(smart_mailing_loop(bot))

    try:
        if config.max_use_webhook:
            webhook_path = _normalize_webhook_path(config.max_webhook_path)
            webhook_url = _normalize_webhook_url(config.max_webhook_url, webhook_path)
            webhook_secret = (config.max_webhook_secret or "").strip() or None
            if webhook_secret and not (5 <= len(webhook_secret) <= 256):
                raise ValueError("MAX_WEBHOOK_SECRET length must be 5..256")

            await bot.delete_webhook()
            await bot.subscribe_webhook(
                url=webhook_url,
                secret=webhook_secret,
            )
            logger.info(
                "Webhook mode enabled: url=%s host=%s port=%s path=%s",
                webhook_url,
                config.max_webhook_host,
                config.max_webhook_port,
                webhook_path,
            )
            await dp.handle_webhook(
                bot,
                host=config.max_webhook_host,
                port=config.max_webhook_port,
                path=webhook_path,
                secret=webhook_secret,
            )
        else:
            try:
                await bot.delete_webhook()
            except Exception as e:
                logger.warning("Could not clear webhooks: %s", e)

            # Keep polling compliant with MAX long-polling limits.
            bot.params["timeout"] = 30
            bot.params["limit"] = 100
            logger.warning(
                "Webhook disabled, using long polling with timeout=30 and limit=100. "
                "MAX recommends switching to webhook."
            )
            await dp.start_polling(bot, skip_updates=True)
    finally:
        await bot.close_session()


if __name__ == "__main__":
    asyncio.run(main())
