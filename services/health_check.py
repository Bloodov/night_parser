"""
Периодическая проверка живости публичных чатов + обновление их данных.

База пополняется постоянно, но ничто не мешает уже добавленным чатам со временем
стать недоступными: чат мог быть удалён, бота могли кикнуть/забанить, чат мог
уйти в приватный режим или опуститься ниже порога MIN_MEMBERS. Без переpроверки
такие "мёртвые" записи копятся в базе и портят качество поиска. Заодно, раз уж
мы всё равно запрашиваем чат при проверке живости, — бесплатно обновляем и его
число участников/название/описание, которые иначе годами оставались бы такими,
какими были в момент сдачи чата.

Раз в HEALTH_CHECK_INTERVAL_HOURS часов эта задача проходит по всем публичным
чатам ОДНИМ проходом: если чат жив — обновляет его данные, если недоступен —
удаляет. Использует тот же общий семафор из submit_queue, чтобы не создавать
лишнюю нагрузку на Telegram API поверх обычной проверки сдаваемых ссылок —
общий лимит запросов на весь бот один.
"""

import asyncio
import logging

import database as db
from services.chat_checker import check_chat
from services import submit_queue

logger = logging.getLogger(__name__)

HEALTH_CHECK_INTERVAL_HOURS = 24 * 7  # раз в неделю
HEALTH_CHECK_BATCH_DELAY_SEC = 0.05   # небольшая пауза между чатами — щадим Telegram API

_bot = None


def init(bot):
    global _bot
    _bot = bot


async def _check_one(username: str):
    """Возвращает (ok, chat_data). chat_data заполнен только если ok=True —
    те же данные, что получает обычная сдача чата, просто мы их тут же
    используем для обновления записи, а не только для решения жив/не жив."""
    async with submit_queue._semaphore:
        ok, _reason, data = await check_chat(_bot, username)
        return ok, data


async def run_health_check():
    """Один проход по всей базе публичных чатов: обновляет данные живых, удаляет
    недоступные. Можно звать и вручную (например, из админ-команды), не только
    по расписанию. Возвращает (checked, removed, updated)."""
    usernames = await db.get_all_public_usernames()
    if not usernames:
        logger.info("Проверка живости базы: публичных чатов нет, нечего проверять")
        return 0, 0, 0

    logger.info(f"Проверка живости базы: начинаю проверку {len(usernames)} публичных чатов")
    removed = 0
    updated = 0
    checked = 0

    for username in usernames:
        try:
            alive, data = await _check_one(username)
        except Exception:
            logger.exception(f"Ошибка при проверке живости чата @{username}")
            alive, data = True, None  # при сбое проверки не удаляем чат — лучше ложно оставить, чем ложно стереть
        checked += 1

        if not alive:
            await db.delete_chat_by_username(username)
            removed += 1
        elif data:
            await db.refresh_chat_data(username, data["title"],
                                       data["description"] or "", data["member_count"])
            updated += 1

        await asyncio.sleep(HEALTH_CHECK_BATCH_DELAY_SEC)

    logger.info(
        f"Проверка живости базы завершена: проверено {checked}, "
        f"обновлено {updated}, удалено {removed}")
    return checked, removed, updated


async def health_check_loop():
    """Бесконечный цикл: ждём интервал, затем прогоняем проверку. Первый прогон
    происходит не сразу при старте бота, а через полный интервал — чтобы не
    нагружать бот дополнительной работой сразу после (пере)запуска."""
    while True:
        await asyncio.sleep(HEALTH_CHECK_INTERVAL_HOURS * 3600)
        try:
            await run_health_check()
        except Exception:
            logger.exception("Ошибка в фоновой проверке живости базы чатов")
