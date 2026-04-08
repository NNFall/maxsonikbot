import asyncio
import logging

from maxapi import Bot, Dispatcher
from maxapi.enums.parse_mode import ParseMode
from maxapi.types import BotCommand

from config import load_config
from database.db import setup as setup_db
from max_handlers import all_routers
from services.smart_mailer_max import smart_mailing_loop
from services.subscription_tasks_max import subscription_watcher


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
    dp = Dispatcher()
    dp.include_routers(*all_routers)

    commands = [
        BotCommand(name="start", description="Запуск бота"),
        BotCommand(name="menu", description="Главное меню"),
        BotCommand(name="ask", description="Задать вопрос Таро"),
        BotCommand(name="balance", description="Баланс и подписка"),
        BotCommand(name="invite", description="Пригласить друга"),
        BotCommand(name="help", description="Помощь"),
    ]
    try:
        await bot.set_my_commands(*commands)
    except Exception as e:
        logger.warning("Could not set commands: %s", e)

    try:
        await bot.delete_webhook()
    except Exception as e:
        logger.warning("Could not clear webhooks: %s", e)

    asyncio.create_task(subscription_watcher(bot))
    asyncio.create_task(smart_mailing_loop(bot))

    try:
        await dp.start_polling(bot, skip_updates=True)
    finally:
        await bot.close_session()


if __name__ == "__main__":
    asyncio.run(main())
