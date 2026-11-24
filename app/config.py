import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    bot_token: str
    channel_id: int
    admin_ids: frozenset[int]
    demo_mode: bool
    db_url: str
    check_interval: int
    club_name: str


def _ids(raw: str) -> frozenset[int]:
    return frozenset(int(x) for x in raw.replace(" ", "").split(",") if x)


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is not set")
    channel = os.getenv("CHANNEL_ID", "").strip()
    if not channel:
        raise RuntimeError("CHANNEL_ID is not set")
    demo = os.getenv("DEMO_MODE", "1").strip() in {"1", "true", "yes"}
    return Config(
        bot_token=token,
        channel_id=int(channel),
        admin_ids=_ids(os.getenv("ADMIN_IDS", "")),
        demo_mode=demo,
        db_url=os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data/subscription.db"),
        check_interval=int(os.getenv("CHECK_INTERVAL", "20" if demo else "60")),
        club_name=os.getenv("CLUB_NAME", "Закритий клуб"),
    )


config = load_config()
