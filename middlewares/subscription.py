"""
Перехватывает все сообщения и нажатия кнопок: если у пользователя есть
непройденная обязательная подписка (см. services/subscription.py), показывает
приглашение подписаться вместо того, чтобы пропустить событие к обычному
хендлеру. Администраторы (config.ADMIN_IDS) и сама кнопка проверки подписки
всегда проходят без блокировки.
"""

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

import database as db
from config import ADMIN_IDS
from services import subscription
from services.i18n import resolve_lang


class SubscriptionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        user = getattr(event, "from_user", None)
        if user is None or user.id in ADMIN_IDS:
            return await handler(event, data)

        # Кнопка "Я подписался" обязана проходить всегда — иначе пользователь
        # не сможет ей воспользоваться, чтобы снять с себя блокировку.
        if isinstance(event, CallbackQuery) and event.data == "check_subscription":
            return await handler(event, data)

        # Служебное сообщение об успешной оплате (Stars) должно доходить до
        # хендлера в любом случае — иначе при потере подписки ровно в момент
        # оплаты пользователь заплатит реальные деньги и не получит коины.
        if isinstance(event, Message) and event.successful_payment is not None:
            return await handler(event, data)

        bot = data["bot"]
        missing = await subscription.get_missing_channels(bot, user.id)
        if not missing:
            return await handler(event, data)

        db_user = await db.get_user(user.id)
        lang = resolve_lang(db_user)
        text = subscription.build_prompt_text(missing, lang)
        kb = subscription.build_prompt_keyboard(missing, lang)

        target = event.message if isinstance(event, CallbackQuery) else event
        if target is not None:
            try:
                await target.answer(text, reply_markup=kb)
            except Exception:
                pass
        if isinstance(event, CallbackQuery):
            try:
                await event.answer()
            except Exception:
                pass
        return  # событие НЕ передаётся дальше — обычный хендлер не вызывается
