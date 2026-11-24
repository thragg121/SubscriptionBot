"""Background loop: reminders before the end and removal after expiry."""
import asyncio
import logging

from aiogram import Bot

from app import db, ui
from app.access import remove_from_channel, revoke
from app.config import config

log = logging.getLogger(__name__)


async def tick(bot: Bot) -> None:
    async with db.Session() as s:
        for sub in await db.due_reminders(s):
            try:
                await bot.send_message(
                    sub.user_id,
                    f"Підписка закінчується <b>{ui.fmt_dt(sub.expires_at)}</b>. "
                    "Продовжте, щоб не втратити доступ до каналу.",
                    reply_markup=ui.renew_kb())
            except Exception as e:
                log.info("reminder to %s failed: %s", sub.user_id, e)
            sub.reminded = True
        await s.commit()

        for sub in await db.due_expirations(s):
            removed = await remove_from_channel(bot, sub.user_id)
            if sub.invite_link:
                await revoke(bot, sub.invite_link)
                sub.invite_link = None
            sub.active = False
            await s.commit()
            try:
                await bot.send_message(
                    sub.user_id,
                    "Підписка закінчилась, доступ до каналу закрито. "
                    "Продовжте — і бот одразу надішле нове посилання.",
                    reply_markup=ui.renew_kb())
            except Exception as e:
                log.info("expiry message to %s failed: %s", sub.user_id, e)
            for admin in config.admin_ids:
                try:
                    await bot.send_message(admin, f"Підписка закінчилась: id {sub.user_id}"
                                                  f"{'' if removed else ' (не вдалося видалити з каналу)'}")
                except Exception:
                    pass


async def run(bot: Bot) -> None:
    while True:
        try:
            await tick(bot)
        except Exception:
            log.exception("scheduler tick failed")
        await asyncio.sleep(config.check_interval)
