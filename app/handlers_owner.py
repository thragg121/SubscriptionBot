"""Owner panel: stats, subscribers, prices, broadcast.

In demo mode every visitor can open the panel; changing prices stays owner-only
and a visitor's broadcast goes only to the visitor."""
import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app import db, ui
from app.config import config

router = Router()
log = logging.getLogger(__name__)

AUDIENCE_LABELS = {"active": "активним підписникам", "expired": "тим, у кого підписка закінчилась",
                   "all": "усім, хто запускав бота"}


class Broadcast(StatesGroup):
    text = State()
    confirm = State()


class PriceEdit(StatesGroup):
    price = State()


async def panel_text() -> str:
    return "<b>Панель власника</b>\nОберіть розділ:" + (
        "\n\n<i>Демо: ви бачите дані всіх відвідувачів демо-бота.</i>" if config.demo_mode else "")


@router.message(Command("admin"))
@router.message(F.text == ui.BTN_OWNER)
async def panel(message: Message, state: FSMContext) -> None:
    if not ui.can_open_panel(message.from_user.id):
        return
    await state.clear()
    await message.answer(await panel_text(), reply_markup=ui.owner_kb())


@router.callback_query(F.data == "own:menu")
async def panel_cb(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text(await panel_text(), reply_markup=ui.owner_kb())
    await call.answer()


@router.callback_query(F.data == "own:stats")
async def show_stats(call: CallbackQuery) -> None:
    if not ui.can_open_panel(call.from_user.id):
        return await call.answer()
    async with db.Session() as s:
        st = await db.stats(s)
    text = ("<b>Статистика</b>\n"
            f"Активних підписок: <b>{st['active']}</b>\n"
            f"Закінчуються за 3 дні: {st['soon']}\n"
            f"Закінчились: {st['expired']}\n"
            f"Дохід за 30 днів: <b>{st['month_sum']} грн</b>, оплат: {st['month_cnt']}\n"
            f"Усього запускали бота: {st['users']}")
    await call.message.edit_text(text, reply_markup=ui.ikb([[("Назад", "own:menu")]]))
    await call.answer()


@router.callback_query(F.data == "own:subs")
async def show_subs(call: CallbackQuery) -> None:
    if not ui.can_open_panel(call.from_user.id):
        return await call.answer()
    async with db.Session() as s:
        rows = await db.active_subscribers(s)
    if not rows:
        text = "Активних підписників поки немає."
    else:
        lines = [f"{i}. {u.full_name}{' @' + u.username if u.username and not config.demo_mode else ''} — "
                 f"{t.title}, до {ui.fmt_dt(sub.expires_at)}" for i, (u, sub, t) in enumerate(rows, 1)]
        text = "<b>Активні підписники</b> (першими — у кого скоро закінчується)\n\n" + "\n".join(lines)
    await call.message.edit_text(text, reply_markup=ui.ikb([[("Назад", "own:menu")]]))
    await call.answer()


# --- tariffs & prices ------------------------------------------------------

@router.callback_query(F.data == "own:tariffs")
async def show_tariffs(call: CallbackQuery) -> None:
    if not ui.can_open_panel(call.from_user.id):
        return await call.answer()
    async with db.Session() as s:
        tariffs = await db.list_tariffs(s)
    await call.message.edit_text("<b>Тарифи й ціни</b>\nНатисніть тариф, щоб змінити ціну.",
                                 reply_markup=ui.owner_tariffs_kb(tariffs))
    await call.answer()


@router.callback_query(F.data.startswith("own:tedit:"))
async def edit_price_start(call: CallbackQuery, state: FSMContext) -> None:
    if not ui.is_owner(call.from_user.id):
        await call.answer("У демо ціни змінює тільки власник. У вашому боті: натискаєте тариф і вводите нову ціну "
                          "— клієнти одразу бачать оновлену.", show_alert=True)
        return
    await state.set_state(PriceEdit.price)
    await state.update_data(tariff_id=int(call.data.split(":")[2]))
    await call.message.answer("Введіть нову ціну в гривнях (тільки число):")
    await call.answer()


@router.message(PriceEdit.price)
async def edit_price_save(message: Message, state: FSMContext) -> None:
    if not (message.text or "").strip().isdigit():
        await message.answer("Потрібне число, наприклад 349.")
        return
    data = await state.get_data()
    async with db.Session() as s:
        t = await s.get(db.Tariff, data["tariff_id"])
        t.price = int(message.text.strip())
        await s.commit()
    await state.clear()
    await message.answer(f"Готово: {ui.tariff_label(t)}", reply_markup=ui.owner_kb())


# --- broadcast -------------------------------------------------------------

@router.callback_query(F.data == "own:bc")
async def bc_start(call: CallbackQuery) -> None:
    if not ui.can_open_panel(call.from_user.id):
        return await call.answer()
    async with db.Session() as s:
        counts = {a: len(await db.audience_ids(s, a)) for a in ("active", "expired", "all")}
    await call.message.edit_text("<b>Розсилка</b>\nКому надіслати?", reply_markup=ui.bc_audience_kb(counts))
    await call.answer()


@router.callback_query(F.data.in_({"bc:active", "bc:expired", "bc:all"}))
async def bc_audience(call: CallbackQuery, state: FSMContext) -> None:
    if not ui.can_open_panel(call.from_user.id):
        return await call.answer()
    await state.set_state(Broadcast.text)
    await state.update_data(audience=call.data.split(":")[1])
    await call.message.edit_text(f"Надішліть текст розсилки ({AUDIENCE_LABELS[call.data.split(':')[1]]}).")
    await call.answer()


@router.message(Broadcast.text)
async def bc_text(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.answer("Потрібен текст.")
        return
    data = await state.get_data()
    async with db.Session() as s:
        n = len(await db.audience_ids(s, data["audience"]))
    await state.update_data(text=message.html_text)
    await state.set_state(Broadcast.confirm)
    note = ("\n\n<i>Демо: розсилка прийде тільки вам.</i>"
            if config.demo_mode and not ui.is_owner(message.from_user.id) else "")
    await message.answer(f"<b>Перевірте</b> — отримувачів: {n} ({AUDIENCE_LABELS[data['audience']]})\n\n"
                         f"{message.html_text}{note}", reply_markup=ui.bc_confirm_kb())


@router.callback_query(Broadcast.confirm, F.data == "bc:send")
async def bc_send(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    await state.clear()
    await call.message.edit_reply_markup(reply_markup=None)
    text = f"<b>{config.club_name}:</b>\n{data['text']}"
    if config.demo_mode and not ui.is_owner(call.from_user.id):
        await bot.send_message(call.from_user.id, text)
        await call.message.answer("Надіслано (у демо — тільки вам).", reply_markup=ui.owner_kb())
        return await call.answer()
    async with db.Session() as s:
        ids = await db.audience_ids(s, data["audience"])
    ok = 0
    for uid in ids:
        try:
            await bot.send_message(uid, text)
            ok += 1
        except Exception:
            pass
        await asyncio.sleep(0.05)
    await call.message.answer(f"Розсилку надіслано: {ok} з {len(ids)}.", reply_markup=ui.owner_kb())
    await call.answer()


@router.callback_query(F.data == "bc:cancel")
async def bc_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text(await panel_text(), reply_markup=ui.owner_kb())
    await call.answer("Скасовано")
