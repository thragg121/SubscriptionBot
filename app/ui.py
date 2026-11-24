"""Texts and keyboards."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram.types import (InlineKeyboardButton, InlineKeyboardMarkup,
                           KeyboardButton, ReplyKeyboardMarkup)

from app.config import config
from app.db import Tariff, human_duration

KYIV = ZoneInfo("Europe/Kyiv")

BTN_TARIFFS = "Тарифи"
BTN_MY = "Моя підписка"
BTN_ABOUT = "Про клуб"
BTN_OWNER = "Панель власника"


def fmt_dt(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).astimezone(KYIV).strftime("%d.%m.%Y %H:%M")


def is_owner(uid: int) -> bool:
    return uid in config.admin_ids


def can_open_panel(uid: int) -> bool:
    return config.demo_mode or is_owner(uid)


def main_menu(uid: int) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=BTN_TARIFFS), KeyboardButton(text=BTN_MY)],
            [KeyboardButton(text=BTN_ABOUT)]]
    if can_open_panel(uid):
        rows[1].append(KeyboardButton(text=BTN_OWNER))
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def ikb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, url=d) if d.startswith("https://")
         else InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows])


def tariff_label(t: Tariff) -> str:
    price = "безкоштовно" if t.price == 0 else f"{t.price} грн"
    return f"{t.title} — {price}"


def tariffs_kb(tariffs: list[Tariff]) -> InlineKeyboardMarkup:
    return ikb([[(tariff_label(t), f"tariff:{t.id}")] for t in tariffs])


def pay_kb(t: Tariff) -> InlineKeyboardMarkup:
    label = "Отримати доступ" if t.price == 0 else f"Оплатити {t.price} грн"
    if config.demo_mode and t.price:
        label += " (демо)"
    return ikb([[(label, f"pay:{t.id}")], [("Назад до тарифів", "tariffs")]])


def link_kb(url: str) -> InlineKeyboardMarkup:
    return ikb([[("Увійти в канал", url)]])


def renew_kb() -> InlineKeyboardMarkup:
    return ikb([[("Продовжити підписку", "tariffs")]])


def my_sub_kb(active: bool) -> InlineKeyboardMarkup:
    rows = [[("Продовжити", "tariffs")]]
    if active:
        rows.append([("Нове посилання в канал", "relink")])
    return ikb(rows)


def owner_kb() -> InlineKeyboardMarkup:
    return ikb([[("Статистика", "own:stats"), ("Підписники", "own:subs")],
                [("Тарифи й ціни", "own:tariffs"), ("Розсилка", "own:bc")]])


def bc_audience_kb(counts: dict[str, int]) -> InlineKeyboardMarkup:
    return ikb([[(f"Активним ({counts['active']})", "bc:active")],
                [(f"Тим, у кого закінчилась ({counts['expired']})", "bc:expired")],
                [(f"Усім, хто запускав бота ({counts['all']})", "bc:all")],
                [("Скасувати", "bc:cancel")]])


def bc_confirm_kb() -> InlineKeyboardMarkup:
    return ikb([[("Надіслати", "bc:send"), ("Скасувати", "bc:cancel")]])


def owner_tariffs_kb(tariffs: list[Tariff]) -> InlineKeyboardMarkup:
    rows = [[(f"{tariff_label(t)} · {human_duration(t.minutes)}", f"own:tedit:{t.id}")] for t in tariffs]
    rows.append([("Назад", "own:menu")])
    return ikb(rows)


WELCOME = (
    "<b>{club}</b>\n\n"
    "Закритий канал з тренуваннями, планом харчування й відповідями на запитання.\n\n"
    "Як це працює:\n"
    "1. Обираєте тариф і оплачуєте.\n"
    "2. Бот одразу надсилає особисте посилання в канал.\n"
    "3. За кілька днів до кінця підписки бот нагадає продовжити.\n"
)

DEMO_NOTE = (
    "\n<i>Це демо. Оплата тут тестова, гроші не списуються. Спробуйте тариф «Демо: 3 хвилини» — "
    "побачите весь цикл: доступ, нагадування і автоматичне закінчення підписки. "
    "Кнопка «Панель власника» показує, що бачить власник каналу.</i>"
)

ABOUT = (
    "<b>Що всередині</b>\n"
    "- нові тренування щотижня;\n"
    "- план харчування на місяць;\n"
    "- відповіді на запитання учасників.\n\n"
    "Оплата: карта, Apple Pay, Google Pay (WayForPay / LiqPay / monobank — підключається під ваш бізнес).\n"
    "Доступ відкривається одразу після оплати, без ручної перевірки."
)
