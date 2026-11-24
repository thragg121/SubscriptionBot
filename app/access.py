"""Channel access: personal invite links and removal after expiry."""
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from app.config import config

log = logging.getLogger(__name__)


async def new_invite_link(bot: Bot, uid: int, old_link: str | None = None) -> str:
    """One-person link valid for 24 hours; the previous personal link is revoked."""
    if old_link:
        await revoke(bot, old_link)
    link = await bot.create_chat_invite_link(
        chat_id=config.channel_id,
        name=f"sub {uid}",
        expire_date=datetime.now() + timedelta(hours=24),
        member_limit=1,
    )
    return link.invite_link


async def revoke(bot: Bot, link: str) -> None:
    try:
        await bot.revoke_chat_invite_link(config.channel_id, link)
    except TelegramAPIError as e:
        log.info("revoke link failed: %s", e)


async def remove_from_channel(bot: Bot, uid: int) -> bool:
    """Kick (ban + unban) so the person leaves but can come back after paying again."""
    try:
        member = await bot.get_chat_member(config.channel_id, uid)
        if member.status in {"left", "kicked"}:
            return True
        await bot.ban_chat_member(config.channel_id, uid)
        await bot.unban_chat_member(config.channel_id, uid, only_if_banned=True)
        return True
    except TelegramAPIError as e:
        log.warning("could not remove %s from channel: %s", uid, e)
        return False
