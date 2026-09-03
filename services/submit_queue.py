"""
Фоновая обработка сдачи чатов.

Зачем это нужно:
— Раньше проверка ссылок выполнялась прямо внутри хендлера, пока пользователь ждал
  ответа. При большом списке (тысячи ссылок) это надолго занимало диалог с этим
  пользователем и создавало риск словить flood control у Telegram, если несколько
  человек одновременно сдавали большие списки.
— Теперь заявка на проверку сразу пишется в БД и ставится в очередь, а пользователь
  свободен — может искать чаты, смотреть профиль и т.д., пока проверка идёт в фоне.
  Результат придёт отдельным сообщением, когда всё будет готово.
— Заявки хранятся в БД (не только в памяти), поэтому переживают перезапуск бота:
  при старте функция recover_pending_jobs() подбирает все незавершённые заявки.
— GLOBAL_CONCURRENCY — это ОДИН общий семафор на весь бот, а не свой у каждой заявки.
  Если 5 пользователей одновременно сдадут по 500 ссылок, суммарно к Telegram будет
  уходить не 5×8=40 параллельных запросов, а не больше GLOBAL_CONCURRENCY — это
  снижает число ошибок 429 (Too Many Requests) от Telegram.
"""

import asyncio
import json
import logging

from aiogram import Bot

import database as db
from services.chat_checker import check_chat
from services.i18n import t, resolve_lang
from config import REWARD_PER_CHAT, REWARD_PER_PRIVATE_CHAT

logger = logging.getLogger(__name__)

GLOBAL_CONCURRENCY = 8   # сколько чатов проверяется параллельно суммарно по всему боту
JOB_WORKERS = 3          # сколько заявок разных пользователей обрабатываются одновременно
TELEGRAM_MSG_LIMIT = 4096

_queue: "asyncio.Queue[int]" = asyncio.Queue()
_semaphore = asyncio.Semaphore(GLOBAL_CONCURRENCY)
_bot: Bot | None = None


def init(bot: Bot):
    """Вызывается один раз при старте бота — даёт очереди доступ к Bot для отправки
    результатов пользователям."""
    global _bot
    _bot = bot


async def enqueue_job(job_id: int):
    """Кладёт свежесозданную заявку в очередь на обработку."""
    await _queue.put(job_id)


async def recover_pending_jobs():
    """Восстанавливает необработанные заявки после перезапуска бота."""
    job_ids = await db.get_pending_job_ids()
    for job_id in job_ids:
        await _queue.put(job_id)
    if job_ids:
        logger.info(f"Восстановлено {len(job_ids)} заявок на проверку чатов после перезапуска")


def _short(value, limit: int = 150) -> str:
    """Обрезает длинные тексты ошибок, чтобы одна 'взбесившаяся' ошибка
    не раздула итоговый отчёт на десятки килобайт."""
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "…"


async def _send_long(user_id: int, text: str):
    """Отправляет результат пользователю личным сообщением, разбивая на части,
    если текст превышает лимит Telegram (4096 символов на сообщение)."""
    if len(text) <= TELEGRAM_MSG_LIMIT:
        try:
            await _bot.send_message(user_id, text)
        except Exception:
            logger.exception(f"Не удалось отправить результат проверки пользователю {user_id}")
        return

    safe_limit = TELEGRAM_MSG_LIMIT - 100
    lines = text.split("\n")
    chunks, chunk = [], ""
    for line in lines:
        while len(line) > safe_limit:
            if chunk:
                chunks.append(chunk)
                chunk = ""
            chunks.append(line[:safe_limit])
            line = line[safe_limit:]
        candidate = f"{chunk}\n{line}" if chunk else line
        if len(candidate) > safe_limit:
            if chunk:
                chunks.append(chunk)
            chunk = line
        else:
            chunk = candidate
    if chunk:
        chunks.append(chunk)

    for c in chunks:
        try:
            await _bot.send_message(user_id, c)
        except Exception:
            logger.exception(f"Не удалось отправить результат проверки пользователю {user_id}")


async def _process_entries(entries: list[dict], user_id: int):
    """Проверка/добавление списка чатов (публичных и приватных).
    Возвращает (added, dup, rejected).
    Публичные чаты проверяются параллельно, но через ОБЩИЙ на весь бот семафор
    (см. GLOBAL_CONCURRENCY выше) — запись в БД делается последовательно."""
    added, dup, rejected = 0, 0, []

    public_entries = [e for e in entries if e["type"] == "public"]
    private_entries = [e for e in entries if e["type"] == "private"]

    # ── Приватные — без сети, быстро. Награда за них отдельная (обычно 0, см. config) —
    # раз мы не можем проверить существование чата, полноценная награда была бы
    # уязвима к фарму: бот мог бы генерировать случайные инвайт-хеши бесконечно.
    for entry in private_entries:
        try:
            pseudo_username = f"inv_{entry['hash']}"
            if await db.chat_exists(pseudo_username):
                dup += 1
            else:
                await db.add_private_chat(entry["hash"], entry["link"], user_id)
                if REWARD_PER_PRIVATE_CHAT:
                    await db.update_balance(user_id, REWARD_PER_PRIVATE_CHAT,
                                            reason=f"сдача приватного чата ({entry['link']})")
                added += 1
        except Exception as e:
            rejected.append(f"{entry['link']} — непредвиденная ошибка ({_short(e)})")

    # ── Публичные: сначала быстро отсеиваем то, что уже есть в базе ──
    to_check = []
    for entry in public_entries:
        if await db.chat_exists(entry["username"]):
            dup += 1
        else:
            to_check.append(entry)

    async def _check(entry):
        async with _semaphore:
            ok, reason, chat_data = await check_chat(_bot, entry["username"])
            return entry, ok, reason, chat_data

    checked = await asyncio.gather(*(_check(e) for e in to_check), return_exceptions=True)

    for result in checked:
        if isinstance(result, Exception):
            rejected.append(f"непредвиденная ошибка ({_short(result)})")
            continue
        entry, ok, reason, chat_data = result
        username = entry["username"]
        if not ok:
            rejected.append(f"@{username} — {_short(reason)}")
            continue
        try:
            await db.add_chat(chat_data["username"], chat_data["title"],
                              chat_data["description"] or "",
                              chat_data["member_count"], user_id)
            await db.update_balance(user_id, REWARD_PER_CHAT,
                                    reason=f"сдача чата @{username}")
            added += 1
        except Exception as e:
            rejected.append(f"@{username} — непредвиденная ошибка ({_short(e)})")

    return added, dup, rejected


async def _run_job(job_id: int):
    row = await db.get_submit_job(job_id)
    if row is None or row["status"] != "queued":
        return  # уже обработана (например, повторно попала в очередь после рестарта)

    entries = json.loads(row["entries_json"])
    user_id = row["user_id"]

    added, dup, rejected = await _process_entries(entries, user_id)

    await db.finish_submit_job(job_id, added, dup, rejected)
    await db.touch_submit_cooldown(user_id)

    updated = await db.get_user(user_id)
    lang = resolve_lang(updated)
    report = t("submit_report_header", lang, added=added, dup=dup,
              rejected=len(rejected), balance=updated["balance"])
    if rejected:
        preview = rejected[:30]
        report += t("submit_rejected_list_header", lang, shown=len(preview)) + "\n".join(preview)
        if len(rejected) > len(preview):
            report += t("submit_rejected_more", lang, count=len(rejected) - len(preview))

    await _send_long(user_id, report)


async def worker_loop():
    """Фоновая корутина-воркер. Запускается несколько экземпляров (JOB_WORKERS),
    чтобы заявки разных пользователей обрабатывались параллельно, но все они делят
    один и тот же _semaphore, так что общая скорость запросов к Telegram остаётся
    под контролем независимо от числа одновременных заявок."""
    while True:
        job_id = await _queue.get()
        try:
            await _run_job(job_id)
        except Exception:
            logger.exception(f"Ошибка при обработке заявки на сдачу чатов #{job_id}")
        finally:
            _queue.task_done()
