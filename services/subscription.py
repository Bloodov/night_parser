"""
Обязательная подписка на каналы перед использованием бота.

Если функция выключена в админке (или не задано ни одного канала) — проверка
подписки полностью пропускается, бот работает как раньше. Список требуемых
каналов и переключатель хранятся в БД (таблицы settings/required_channels),
поэтому настройка не теряется при перезапуске бота.

ВАЖНО: чтобы бот мог проверять членство произвольного пользователя в канале
через get_chat_member, он должен быть администратором этого канала — обычное
требование Telegram Bot API для таких проверок, не специфика этого кода.
"""

import asyncio
import logging
import time

from aiogram import Bot
from aiogram.utils.keyboard import InlineKeyboardBuilder

import database as db
from services.i18n import t

logger = logging.getLogger(__name__)

CHECK_CONCURRENCY = 8   # для массовой проверки всей базы пользователей (см. scan_user_base)
CACHE_TTL_SEC = 300     # 5 минут — не дёргаем Telegram на каждое сообщение уже подтверждённого юзера

# Кэшируем только ПОЛОЖИТЕЛЬНЫЕ вердикты (юзер подписан на всё) — если человек
# ещё не подписан, каждое его сообщение будет перепроверяться заново, чтобы он
# не оставался заблокированным дольше, чем реально нужно, после того как
# подписался. user_id -> время последней успешной проверки (monotonic).
_verified_cache: dict[int, float] = {}


def _is_cached_ok(user_id: int) -> bool:
    ts = _verified_cache.get(user_id)
    return ts is not None and (time.monotonic() - ts) < CACHE_TTL_SEC


def _mark_cached_ok(user_id: int):
    _verified_cache[user_id] = time.monotonic()


def clear_cache():
    """Вызывается при изменении списка каналов или переключателя в админке —
    старые положительные вердикты могли не учитывать новые требования."""
    _verified_cache.clear()


async def get_missing_channels(bot: Bot, user_id: int) -> list:
    """Возвращает список каналов (записи required_channels), на которые
    пользователь ЕЩЁ НЕ подписан. Пустой список означает: подписка либо
    выключена в админке, либо каналов не задано, либо пользователь подписан
    на все требуемые каналы (в т.ч. по недавно закэшированному результату —
    см. CACHE_TTL_SEC, это защищает от лишней нагрузки на Telegram API при
    активной аудитории)."""
    if not await db.is_force_subscribe_enabled():
        return []
    channels = await db.list_required_channels()
    if not channels:
        return []

    if _is_cached_ok(user_id):
        return []

    missing = []
    for ch in channels:
        try:
            member = await bot.get_chat_member(ch["chat_id"], user_id)
            if member.status in ("left", "kicked"):
                missing.append(ch)
        except Exception:
            # Бот не смог проверить (не админ канала, канал удалён и т.п.) —
            # не блокируем пользователя из-за проблемы на нашей стороне.
            logger.warning(
                f"Не удалось проверить подписку пользователя {user_id} "
                f"на канал '{ch['title']}' (id={ch['chat_id']})")
            continue

    if not missing:
        _mark_cached_ok(user_id)
    return missing


def build_prompt_text(missing_channels, lang: str = "ru") -> str:
    lines = "\n".join(f"📢 {c['title']}" for c in missing_channels)
    return t("subscribe_prompt", lang, channels=lines, btn=t("btn_check_subscription", lang))


def build_prompt_keyboard(missing_channels, lang: str = "ru"):
    kb = InlineKeyboardBuilder()
    for ch in missing_channels:
        if ch["username"]:
            kb.button(text=f"📢 {ch['title']}", url=f"https://t.me/{ch['username']}")
    kb.button(text=t("btn_check_subscription", lang), callback_data="check_subscription")
    kb.adjust(1)
    return kb.as_markup()


async def scan_user_base(bot: Bot, concurrency: int = CHECK_CONCURRENCY):
    """Проверяет ВСЕХ активных (не забаненных) пользователей бота на подписку —
    используется для статистики в админке. Возвращает (subscribed, not_subscribed, total).
    На больших базах пользователей может занять заметное время — каждая проверка
    делает по одному запросу к Telegram на каждый требуемый канал."""
    if not await db.is_force_subscribe_enabled():
        return 0, 0, 0
    channels = await db.list_required_channels()
    if not channels:
        return 0, 0, 0

    user_ids = await db.get_all_user_ids()
    if not user_ids:
        return 0, 0, 0

    sem = asyncio.Semaphore(concurrency)

    async def _check(user_id):
        async with sem:
            missing = await get_missing_channels(bot, user_id)
            return len(missing) == 0

    results = await asyncio.gather(*(_check(uid) for uid in user_ids), return_exceptions=True)
    subscribed = sum(1 for r in results if r is True)
    not_subscribed = sum(1 for r in results if r is False)
    return subscribed, not_subscribed, len(user_ids)
