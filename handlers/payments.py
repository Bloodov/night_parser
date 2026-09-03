
"""Оплата: Telegram Stars и CryptoBot.

Опрос статуса счёта CryptoBot хранится в БД (таблица payments, статус 'pending'),
а не только в памяти процесса — поэтому переживает перезапуск бота: см.
recover_pending_payments(), которая вызывается при старте (bot.py) и продолжает
опрос счетов, оставшихся неоплаченными с прошлого запуска."""
import asyncio
import logging
from datetime import datetime

from aiogram import Router, F, Bot
from aiogram.types import (CallbackQuery, Message, LabeledPrice, PreCheckoutQuery)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import database as db
from config import PACKAGES, PAYMENT_TIMEOUT_SEC, PAYMENT_POLL_INTERVAL_SEC
from services.payments_api import cryptobot_create_invoice, cryptobot_get_invoice, payment_is_paid
from services.i18n import t, resolve_lang

router = Router()
logger = logging.getLogger(__name__)


def buy_menu_kb(lang: str):
    kb = InlineKeyboardBuilder()
    for i, p in enumerate(PACKAGES):
        kb.button(text=t("package_button", lang, coins=p["coins"], stars=p["stars"], usdt=p["usdt"]),
                  callback_data=f"pack:{i}")
    kb.adjust(1)
    return kb.as_markup()


@router.callback_query(F.data == "buy")
async def buy_menu(call: CallbackQuery):
    user = await db.get_user(call.from_user.id)
    lang = resolve_lang(user)
    await call.message.answer(t("buy_menu_header", lang), reply_markup=buy_menu_kb(lang))
    await call.answer()


@router.callback_query(F.data.startswith("pack:"))
async def choose_package(call: CallbackQuery):
    user = await db.get_user(call.from_user.id)
    lang = resolve_lang(user)

    idx = int(call.data.split(":")[1])
    p = PACKAGES[idx]
    kb = InlineKeyboardBuilder()
    kb.button(text=t("btn_pay_stars", lang, stars=p["stars"]), callback_data=f"pay_stars:{idx}")
    kb.button(text=t("btn_pay_crypto", lang, usdt=p["usdt"]), callback_data=f"pay_crypto:{idx}")
    kb.adjust(1)
    await call.message.answer(
        t("package_chosen", lang, coins=p["coins"]), reply_markup=kb.as_markup())
    await call.answer()


# ═══════════ 1. TELEGRAM STARS ═══════════

@router.callback_query(F.data.startswith("pay_stars:"))
async def pay_stars(call: CallbackQuery, bot: Bot):
    user = await db.get_user(call.from_user.id)
    lang = resolve_lang(user)

    idx = int(call.data.split(":")[1])
    p = PACKAGES[idx]
    await bot.send_invoice(
        chat_id=call.from_user.id,
        title=t("stars_invoice_title", lang, coins=p["coins"]),
        description=t("stars_invoice_description", lang, coins=p["coins"]),
        payload=f"stars:{idx}",
        currency="XTR",
        prices=[LabeledPrice(label=t("stars_price_label", lang), amount=p["stars"])],
    )
    await call.answer()


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery, bot: Bot):
    await bot.answer_pre_checkout_query(query.id, ok=True)


@router.message(F.successful_payment)
async def stars_paid(message: Message):
    payload = message.successful_payment.invoice_payload
    if not payload.startswith("stars:"):
        return
    idx = int(payload.split(":")[1])
    p = PACKAGES[idx]
    user_id = message.from_user.id

    user = await db.get_user(user_id)
    lang = resolve_lang(user)

    payment_id = await db.create_payment(
        user_id, "stars", str(p["stars"]), p["coins"],
        invoice_id=str(message.successful_payment.telegram_payment_charge_id))
    await db.update_balance(user_id, p["coins"], reason=f"оплата Stars ({p['stars']}⭐)")
    await db.set_payment_status(payment_id, "paid")

    await message.answer(t("stars_paid", lang, coins=p["coins"]))


# ═══════════ 2. CRYPTOBOT ═══════════

@router.callback_query(F.data.startswith("pay_crypto:"))
async def pay_crypto(call: CallbackQuery):
    user = await db.get_user(call.from_user.id)
    lang = resolve_lang(user)

    idx = int(call.data.split(":")[1])
    p = PACKAGES[idx]
    user_id = call.from_user.id

    inv = await cryptobot_create_invoice(p["coins"], p["usdt"])
    if not inv:
        await call.answer(t("crypto_api_error", lang), show_alert=True)
        return

    payment_id = await db.create_payment(user_id, "cryptobot", str(p["usdt"]),
                                         p["coins"], invoice_id=str(inv["invoice_id"]))
    asyncio.create_task(poll_payment(payment_id, call.bot, PAYMENT_TIMEOUT_SEC))

    kb = InlineKeyboardBuilder()
    kb.button(text=t("btn_pay_now", lang), url=inv["pay_url"])
    kb.adjust(1)
    minutes = PAYMENT_TIMEOUT_SEC // 60
    await call.message.answer(
        t("invoice_created", lang, usdt=p["usdt"], coins=p["coins"], minutes=minutes),
        reply_markup=kb.as_markup())
    await call.answer()


async def poll_payment(payment_id: int, bot: Bot, remaining_sec: float):
    """Опрашивает статус счёта CryptoBot до оплаты или истечения времени.
    remaining_sec — сколько секунд ещё ждать; при восстановлении после
    перезапуска бота сюда передаётся ОСТАВШЕЕСЯ время, а не полный таймаут заново."""
    payment = await db.get_payment(payment_id)
    if payment is None or payment["status"] != "pending":
        return

    invoice_id = payment["invoice_id"]
    user_id = payment["user_id"]
    coins = payment["coins"]

    elapsed = 0.0
    while elapsed < remaining_sec:
        await asyncio.sleep(PAYMENT_POLL_INTERVAL_SEC)
        elapsed += PAYMENT_POLL_INTERVAL_SEC

        # Перечитываем — статус мог измениться (например, помечен вручную админом)
        payment = await db.get_payment(payment_id)
        if payment is None or payment["status"] != "pending":
            return

        try:
            inv = await cryptobot_get_invoice(invoice_id)
        except Exception:
            logger.exception(f"Ошибка опроса CryptoBot по счёту {payment_id}")
            continue

        if payment_is_paid(inv):
            await db.update_balance(user_id, coins, reason=f"оплата CryptoBot (счёт #{payment_id})")
            await db.set_payment_status(payment_id, "paid")
            try:
                user = await db.get_user(user_id)
                lang = resolve_lang(user)
                await bot.send_message(user_id, t("payment_received", lang, coins=coins))
            except Exception:
                pass
            return

    await db.set_payment_status(payment_id, "expired")


async def recover_pending_payments(bot: Bot):
    """Вызывается один раз при старте бота — продолжает опрос счетов CryptoBot,
    которые остались неоплаченными (status='pending') с прошлого запуска,
    вместо того чтобы просто забыть о них."""
    rows = await db.get_pending_payments()
    now = datetime.now()
    resumed = 0
    for row in rows:
        try:
            created_at = datetime.fromisoformat(row["created_at"])
        except (TypeError, ValueError):
            created_at = now
        elapsed = (now - created_at).total_seconds()
        remaining = PAYMENT_TIMEOUT_SEC - elapsed
        if remaining <= 0:
            await db.set_payment_status(row["id"], "expired")
            continue
        asyncio.create_task(poll_payment(row["id"], bot, remaining))
        resumed += 1
    if resumed:
        logger.info(f"Восстановлено {resumed} неоплаченных счетов CryptoBot после перезапуска")
