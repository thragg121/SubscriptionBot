"""Subscriber side: tariffs, payment, access link, my subscription."""
import logging
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message

from app import db, ui
from app.access import new_invite_link
from app.config import config

router = Router()
log = logging.getLogger(__name__)


@router.message(CommandStart())
async def start(message: Message) -> None:
    u = message.from_user
    async with db.Session() as s:
        await db.upsert_user(s, u.id, u.full_name, u.username)
        tariffs = await db.list_tariffs(s)
    text = ui.WELCOME.format(club=config.club_name) + (ui.DEMO_NOTE if config.demo_mode else "")
    await message.answer(text, reply_markup=ui.main_menu(u.id))
    await message.answer("Оберіть тариф:", reply_markup=ui.tariffs_kb(tariffs))


@router.message(F.text == ui.BTN_ABOUT)
async def about(message: Message) -> None:
    await message.answer(ui.ABOUT)


@router.message(F.text == ui.BTN_TARIFFS)
async def tariffs_msg(message: Message) -> None:
    async with db.Session() as s:
        tariffs = await db.list_tariffs(s)
    await message.answer("Оберіть тариф:", reply_markup=ui.tariffs_kb(tariffs))


@router.callback_query(F.data == "tariffs")
async def tariffs_cb(call: CallbackQuery) -> None:
    async with db.Session() as s:
        tariffs = await db.list_tariffs(s)
    await call.message.answer("Оберіть тариф:", reply_markup=ui.tariffs_kb(tariffs))
    await call.answer()


@router.callback_query(F.data.startswith("tariff:"))
async def tariff_chosen(call: CallbackQuery) -> None:
    async with db.Session() as s:
        t = await s.get(db.Tariff, int(call.data.split(":")[1]))
        sub = await db.get_subscription(s, call.from_user.id)
    if t is None or not t.is_active:
        await call.answer("Тариф недоступний", show_alert=True)
        return
    lines = [f"<b>{t.title}</b>", f"Ціна: {'безкоштовно' if t.price == 0 else f'{t.price} грн'}",
             f"Доступ: {db.human_duration(t.minutes)}"]
    if sub and sub.active and sub.expires_at > datetime.utcnow():
        lines.append(f"\nУ вас уже є підписка до {ui.fmt_dt(sub.expires_at)} — термін додасться до неї.")
    if config.demo_mode and t.price:
        lines.append("\n<i>Демо: оплата тестова, гроші не списуються.</i>")
    await call.message.edit_text("\n".join(lines), reply_markup=ui.pay_kb(t))
    await call.answer()


@router.callback_query(F.data.startswith("pay:"))
async def pay(call: CallbackQuery, bot: Bot) -> None:
    uid = call.from_user.id
    async with db.Session() as s:
        t = await s.get(db.Tariff, int(call.data.split(":")[1]))
        if t is None or not t.is_active:
            await call.answer("Тариф недоступний", show_alert=True)
            return
        await db.upsert_user(s, uid, call.from_user.full_name, call.from_user.username)
        sub, extended = await db.activate(s, uid, t)
        link = None
        if not extended:
            try:
                link = await new_invite_link(bot, uid, sub.invite_link)
            except Exception:
                log.exception("invite link failed")
            sub.invite_link = link
            await s.commit()
    await call.message.edit_reply_markup(reply_markup=None)
    if extended:
        await call.message.answer(f"Оплату отримано. Підписку продовжено до <b>{ui.fmt_dt(sub.expires_at)}</b>.")
    elif link:
        await call.message.answer(
            f"Оплату отримано. Доступ до <b>{ui.fmt_dt(sub.expires_at)}</b>.\n\n"
            "Ваше особисте посилання в канал (діє 24 години, для одного входу):",
            reply_markup=ui.link_kb(link))
    else:
        await call.message.answer("Оплату отримано, але посилання створити не вдалося. "
                                  "Власник уже знає — напишіть йому, якщо посилання не прийде.")
    await call.answer()
    await notify_owner(bot, call, t, sub, extended)


async def notify_owner(bot: Bot, call: CallbackQuery, t: db.Tariff, sub: db.Subscription, extended: bool) -> None:
    u = call.from_user
    who = f"{u.full_name}" + (f" (@{u.username})" if u.username else "")
    text = (f"<b>{'Продовження' if extended else 'Нова оплата'}</b>\n{who}\nТариф: {t.title}\n"
            f"Сума: {t.price} грн\nДоступ до: {ui.fmt_dt(sub.expires_at)}")
    for admin in config.admin_ids:
        try:
            await bot.send_message(admin, text)
        except Exception:
            log.warning("owner notify failed for %s", admin)
    if config.demo_mode and u.id not in config.admin_ids:
        await call.message.answer("<i>Так власнику приходить сповіщення про оплату:</i>\n\n" + text)


@router.message(F.text == ui.BTN_MY)
async def my_subscription(message: Message) -> None:
    async with db.Session() as s:
        sub = await db.get_subscription(s, message.from_user.id)
        t = await s.get(db.Tariff, sub.tariff_id) if sub else None
    if sub is None:
        await message.answer("Підписки поки немає. Оберіть тариф у меню «Тарифи».")
        return
    if sub.active:
        text = f"Підписка активна: <b>{t.title if t else ''}</b>\nДо: <b>{ui.fmt_dt(sub.expires_at)}</b>"
    else:
        text = f"Підписка закінчилась {ui.fmt_dt(sub.expires_at)}. Продовжте, щоб повернутися в канал."
    await message.answer(text, reply_markup=ui.my_sub_kb(sub.active))


@router.callback_query(F.data == "relink")
async def relink(call: CallbackQuery, bot: Bot) -> None:
    async with db.Session() as s:
        sub = await db.get_subscription(s, call.from_user.id)
        if not sub or not sub.active:
            await call.answer("Підписка не активна", show_alert=True)
            return
        sub.invite_link = await new_invite_link(bot, call.from_user.id, sub.invite_link)
        await s.commit()
    await call.message.answer("Нове посилання (попереднє більше не діє):", reply_markup=ui.link_kb(sub.invite_link))
    await call.answer()
