"""Models and queries: tariffs, users, subscriptions, payments."""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from sqlalchemy import (BigInteger, Boolean, DateTime, ForeignKey, Integer,
                        String, func, select)
from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker,
                                    create_async_engine)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import config

DAY = 24 * 60


class Base(DeclarativeBase):
    pass


class Tariff(Base):
    __tablename__ = "tariffs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(64))
    minutes: Mapped[int] = mapped_column(Integer)
    price: Mapped[int] = mapped_column(Integer)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(128), default="")
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Subscription(Base):
    __tablename__ = "subscriptions"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    tariff_id: Mapped[int] = mapped_column(ForeignKey("tariffs.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    remind_at: Mapped[datetime] = mapped_column(DateTime)
    reminded: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    invite_link: Mapped[str | None] = mapped_column(String(128), nullable=True)


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    tariff_id: Mapped[int] = mapped_column(ForeignKey("tariffs.id"))
    amount: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


if config.db_url.startswith("sqlite"):
    os.makedirs("data", exist_ok=True)
engine = create_async_engine(config.db_url)
Session = async_sessionmaker(engine, expire_on_commit=False)

DEFAULT_TARIFFS = [
    ("1 місяць", 30 * DAY, 299, 1),
    ("3 місяці", 90 * DAY, 799, 2),
    ("12 місяців", 365 * DAY, 2490, 3),
]
DEMO_TARIFF = ("Демо: 3 хвилини", 3, 0, 0)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with Session() as s:
        if await s.scalar(select(func.count(Tariff.id))):
            return
        rows = DEFAULT_TARIFFS + ([DEMO_TARIFF] if config.demo_mode else [])
        s.add_all(Tariff(title=t, minutes=m, price=p, sort=o) for t, m, p, o in rows)
        await s.commit()


def human_duration(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} хв"
    if minutes < DAY:
        return f"{minutes // 60} год"
    return f"{minutes // DAY} дн"


def remind_offset(minutes: int) -> timedelta:
    """3 days before the end for real tariffs, a third of the term for short demo ones."""
    if minutes >= 7 * DAY:
        return timedelta(days=3)
    return timedelta(minutes=max(1, minutes // 3))


# --- users -----------------------------------------------------------------

async def upsert_user(s: AsyncSession, uid: int, full_name: str, username: str | None) -> None:
    user = await s.get(User, uid)
    if user is None:
        s.add(User(id=uid, full_name=full_name, username=username))
    else:
        user.full_name, user.username = full_name, username
    await s.commit()


# --- tariffs ---------------------------------------------------------------

async def list_tariffs(s: AsyncSession, only_active: bool = True) -> list[Tariff]:
    q = select(Tariff).order_by(Tariff.sort, Tariff.id)
    if only_active:
        q = q.where(Tariff.is_active.is_(True))
    return list(await s.scalars(q))


# --- subscriptions ---------------------------------------------------------

async def get_subscription(s: AsyncSession, uid: int) -> Subscription | None:
    return await s.get(Subscription, uid)


async def activate(s: AsyncSession, uid: int, tariff: Tariff) -> tuple[Subscription, bool]:
    """Record a payment and extend (or start) the subscription.

    Returns the subscription and whether it was already active (an extension)."""
    now = datetime.utcnow()
    sub = await s.get(Subscription, uid)
    extended = bool(sub and sub.active and sub.expires_at > now)
    start = sub.expires_at if extended else now
    expires = start + timedelta(minutes=tariff.minutes)
    if sub is None:
        sub = Subscription(user_id=uid, tariff_id=tariff.id, expires_at=expires,
                           remind_at=expires - remind_offset(tariff.minutes))
        s.add(sub)
    else:
        sub.tariff_id, sub.expires_at = tariff.id, expires
        sub.remind_at = expires - remind_offset(tariff.minutes)
        sub.reminded, sub.active = False, True
    s.add(Payment(user_id=uid, tariff_id=tariff.id, amount=tariff.price))
    await s.commit()
    return sub, extended


async def due_reminders(s: AsyncSession) -> list[Subscription]:
    now = datetime.utcnow()
    q = select(Subscription).where(Subscription.active.is_(True), Subscription.reminded.is_(False),
                                   Subscription.remind_at <= now, Subscription.expires_at > now)
    return list(await s.scalars(q))


async def due_expirations(s: AsyncSession) -> list[Subscription]:
    q = select(Subscription).where(Subscription.active.is_(True),
                                   Subscription.expires_at <= datetime.utcnow())
    return list(await s.scalars(q))


# --- owner panel -----------------------------------------------------------

async def stats(s: AsyncSession) -> dict:
    now = datetime.utcnow()
    active = await s.scalar(select(func.count()).select_from(Subscription)
                            .where(Subscription.active.is_(True)))
    soon = await s.scalar(select(func.count()).select_from(Subscription).where(
        Subscription.active.is_(True), Subscription.expires_at <= now + timedelta(days=3)))
    expired = await s.scalar(select(func.count()).select_from(Subscription)
                             .where(Subscription.active.is_(False)))
    month_sum = await s.scalar(select(func.coalesce(func.sum(Payment.amount), 0))
                               .where(Payment.created_at >= now - timedelta(days=30)))
    month_cnt = await s.scalar(select(func.count(Payment.id))
                               .where(Payment.created_at >= now - timedelta(days=30)))
    users = await s.scalar(select(func.count(User.id)))
    return {"active": active, "soon": soon, "expired": expired, "month_sum": month_sum,
            "month_cnt": month_cnt, "users": users}


async def active_subscribers(s: AsyncSession, limit: int = 30) -> list[tuple[User, Subscription, Tariff]]:
    q = (select(User, Subscription, Tariff)
         .join(Subscription, Subscription.user_id == User.id)
         .join(Tariff, Tariff.id == Subscription.tariff_id)
         .where(Subscription.active.is_(True))
         .order_by(Subscription.expires_at).limit(limit))
    return [tuple(r) for r in (await s.execute(q)).all()]


async def audience_ids(s: AsyncSession, audience: str) -> list[int]:
    if audience == "active":
        q = select(Subscription.user_id).where(Subscription.active.is_(True))
    elif audience == "expired":
        q = select(Subscription.user_id).where(Subscription.active.is_(False))
    else:
        q = select(User.id)
    return list(await s.scalars(q))
