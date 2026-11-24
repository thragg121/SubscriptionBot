import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from app import db, scheduler
from app.config import config
from app.handlers_owner import router as owner_router
from app.handlers_user import router as user_router


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    await db.init_db()
    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_routers(owner_router, user_router)
    me = await bot.get_me()
    logging.info("Connected to Telegram as @%s (demo=%s)", me.username, config.demo_mode)
    await bot.set_my_commands([BotCommand(command="start", description="Тарифи й доступ")])
    task = asyncio.create_task(scheduler.run(bot))
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        task.cancel()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
