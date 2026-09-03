
import asyncio
import logging
import traceback

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import ErrorEvent

from config import BOT_TOKEN, ADMIN_IDS
import database as db
from handlers import user, payments, admin
from services import submit_queue, health_check
from middlewares.subscription import SubscriptionMiddleware

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)


async def main():
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    dp.include_routers(user.router, payments.router, admin.router)

    # Обязательная подписка (если включена в админке) — перехватывает сообщения
    # и нажатия кнопок раньше обычных хендлеров. Регистрируется как ВНЕШНЯЯ
    # мидлварь, чтобы срабатывать до FSM-мидлвари и любых фильтров хендлеров.
    subscription_middleware = SubscriptionMiddleware()
    dp.message.outer_middleware(subscription_middleware)
    dp.callback_query.outer_middleware(subscription_middleware)

    @dp.errors()
    async def on_error(event: ErrorEvent):
        """Глобальный обработчик: необработанные исключения раньше были видны
        только в логе на сервере — теперь ещё и уходят админу в личку, чтобы
        о проблеме узнавали сразу, а не когда пользователь напишет в поддержку."""
        logger.exception("Необработанная ошибка при обработке апдейта", exc_info=event.exception)
        if not ADMIN_IDS:
            return
        tb = "".join(traceback.format_exception(
            type(event.exception), event.exception, event.exception.__traceback__))
        text = f"⚠️ <b>Ошибка в боте</b>\n\n<code>{tb[-3500:]}</code>"
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, text)
            except Exception:
                pass

    await db.init_db()

    # Очередь фоновой проверки сдаваемых чатов: даём ей доступ к Bot для отправки
    # результатов, восстанавливаем заявки, оставшиеся с прошлого запуска, и
    # запускаем несколько воркеров, которые делят один общий лимит скорости
    # запросов к Telegram (см. services/submit_queue.py).
    submit_queue.init(bot)
    await submit_queue.recover_pending_jobs()
    for _ in range(submit_queue.JOB_WORKERS):
        asyncio.create_task(submit_queue.worker_loop())

    # Периодическая переpроверка живости уже добавленных публичных чатов.
    health_check.init(bot)
    asyncio.create_task(health_check.health_check_loop())

    # Незавершённые счета CryptoBot с прошлого запуска — продолжаем их опрос,
    # а не просто забываем о них.
    await payments.recover_pending_payments(bot)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
