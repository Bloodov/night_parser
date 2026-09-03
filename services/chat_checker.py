
import re
import asyncio
from aiogram import Bot
from aiogram.exceptions import (TelegramBadRequest, TelegramForbiddenError,
                                TelegramAPIError, TelegramRetryAfter)
from config import MIN_MEMBERS

# t.me/+HASH или t.me/joinchat/HASH — приватные инвайт-ссылки на группы
PRIVATE_INVITE_RE = re.compile(
    r'(?<![A-Za-z0-9])(?:https?://)?(?:t(?:elegram)?\.(?:me|dog))/(?:joinchat/|\+)([A-Za-z0-9_-]{10,64})',
    re.IGNORECASE)

# t.me/username, https://t.me/username, t.me/s/username — публичные чаты/каналы.
# Ищем ПО ВСЕЙ строке (не только в начале), чтобы работать с нумерованными
# списками ("1. t.me/xxx"), маркерами ("- @xxx"), доп. текстом на той же строке
# и данными, скопированными из таблиц (ссылка + таб + описание в одной строке).
_USERNAME_BODY = r'[A-Za-z][A-Za-z0-9_]{3,63}'
PUBLIC_LINK_RE = re.compile(
    r'(?<![A-Za-z0-9])(?:https?://)?(?:www\.)?t(?:elegram)?\.(?:me|dog)/(?:s/)?'
    r'(' + _USERNAME_BODY + r')(?=[/?#\s]|$)',
    re.IGNORECASE)

# Голое упоминание "@username" без ссылки — но не email-адрес вроде user@site.com
BARE_MENTION_RE = re.compile(
    r'(?<![A-Za-z0-9_.])@(' + _USERNAME_BODY + r')(?!\.[A-Za-z]{2,})\b')

# Служебные пути Telegram, которые не являются юзернеймом чата
_EXCLUDED_USERNAMES = {
    "joinchat", "addstickers", "share", "proxy", "socks", "setlanguage",
    "confirmphone", "iv", "login", "bg", "addtheme", "addemoji", "boost",
    "premium", "settings", "privacy", "c", "s",
}


def extract_username(text: str):
    """Достаёт username публичного чата из строки: t.me/xxx, https://t.me/xxx,
    t.me/s/xxx или голое упоминание @xxx — ссылка может быть где угодно в строке,
    не обязательно в начале."""
    m = PUBLIC_LINK_RE.search(text) or BARE_MENTION_RE.search(text)
    if not m:
        return None
    username = m.group(1)
    if username.lower() in _EXCLUDED_USERNAMES:
        return None
    if not (4 <= len(username) <= 64):
        return None
    return username


def extract_private_invite(text: str):
    """Если строка содержит приватную инвайт-ссылку (t.me/+hash, t.me/joinchat/hash) —
    возвращает (hash, нормализованная_ссылка). Иначе — None.

    ВАЖНО: это только проверка ФОРМАТА строки. Bot API не позволяет ботам
    проверять, существует ли чат за произвольной инвайт-ссылкой, если бот
    не состоит в этом чате — соответствующий метод (checkChatInvite) есть
    только в клиентском Telegram API, но не в Bot API. Поэтому для приватных
    чатов мы не можем подтвердить ни их существование, ни число участников."""
    m = PRIVATE_INVITE_RE.search(text)
    if not m:
        return None
    invite_hash = m.group(1)
    return invite_hash, f"https://t.me/+{invite_hash}"


def parse_chat_link(line: str):
    """Разбирает одну строку и возвращает:
    {"type": "public", "username": ...} — публичный чат
    {"type": "private", "hash": ..., "link": ...} — приватный чат (только по формату)
    None — не похоже на ссылку/username
    """
    line = line.strip()
    if not line:
        return None
    private = extract_private_invite(line)
    if private:
        invite_hash, link = private
        return {"type": "private", "hash": invite_hash.lower(), "link": link}
    username = extract_username(line)
    if username:
        return {"type": "public", "username": username}
    return None


async def check_chat(bot: Bot, username: str):
    """Проверка публичного чата. Возвращает (ok, причина_отказа, данные_чата).
    При ограничении частоты запросов (flood control) один раз ждёт и повторяет попытку —
    это неизбежно при проверке тысяч ссылок подряд."""
    chat = None
    for attempt in range(2):
        try:
            chat = await bot.get_chat(f"@{username}")
            break
        except TelegramRetryAfter as e:
            if attempt == 0:
                await asyncio.sleep(e.retry_after + 0.5)
                continue
            return False, "❌ Telegram временно ограничил проверку, попробуйте позже.", {}
        except TelegramBadRequest as e:
            err = str(e).lower()
            if "not" in err:
                return False, "❌ Чат не найден. Проверьте ссылку.", {}
            if "private" in err:
                return False, "❌ Чат приватный — принимаем только публичные.", {}
            return False, f"❌ Не удалось проверить чат: {e}", {}
        except TelegramForbiddenError:
            return False, "❌ Бот не может получить доступ к чату (нет прав / бот заблокирован).", {}
        except TelegramAPIError as e:
            return False, f"❌ Не удалось проверить чат: {e}", {}

    if chat.type not in ("group", "supergroup"):
        names = {"channel": "канал", "private": "личный чат", "bot": "бот"}
        return False, f"❌ Это не групповой чат, а {names.get(chat.type, chat.type)}.", {}

    # bot.get_chat() (ChatFullInfo) не содержит member_count —
    # число участников нужно запрашивать отдельным методом
    member_count = 0
    for attempt in range(2):
        try:
            member_count = await bot.get_chat_member_count(chat.id)
            break
        except TelegramRetryAfter as e:
            if attempt == 0:
                await asyncio.sleep(e.retry_after + 0.5)
                continue
        except TelegramAPIError:
            break

    if member_count < MIN_MEMBERS:
        return False, f"❌ В чате {member_count} участников, минимум {MIN_MEMBERS}.", {}

    return True, None, {
        "username": username,
        "title": chat.title or "",
        "description": chat.description or "",
        "member_count": member_count,
    }
