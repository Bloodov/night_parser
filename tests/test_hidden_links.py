"""
Тесты извлечения ссылок из скрытых гиперссылок Telegram (handlers/user.py:
parse_links_from_message). Запуск: pytest tests/test_hidden_links.py -v

Контекст: Telegram позволяет отправить сообщение, где видимый текст — одно
("ВПИШУСЬ", название чата и т.п.), а настоящая ссылка спрятана "под" этим
текстом как отдельная сущность форматирования (entity type='text_link') —
она НЕ присутствует в message.text как обычная строка. Такие сообщения часто
получаются при копировании списков чатов с сайтов-каталогов, где в исходном
HTML ссылки были <a href="...">, а видимый текст — просто название.

Раньше парсер смотрел только на message.text и такие ссылки полностью
пропускал, даже если по факту в сообщении была валидная ссылка.
"""
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aiogram.types import Message, MessageEntity, User, Chat

import handlers.user as u


def _make_message(text: str, entities: list[MessageEntity] = None,
                  caption_entities: list[MessageEntity] = None) -> Message:
    return Message(
        message_id=1, date=datetime.now(),
        chat=Chat(id=1, type="private"),
        from_user=User(id=1, is_bot=False, first_name="T"),
        text=text,
        entities=entities,
        caption_entities=caption_entities,
    )


def test_single_hidden_link():
    msg = _make_message(
        "ВПИШУСЬ",
        entities=[MessageEntity(type="text_link", offset=0, length=7,
                                url="https://t.me/vpishus_chat")])
    entries = u.parse_links_from_message(msg)
    assert entries == [{"type": "public", "username": "vpishus_chat"}]


def test_multiple_hidden_links_like_rating_list():
    """Реальный сценарий: список из нескольких строк, у каждой — своя скрытая
    ссылка (типичный вид списка, скопированного с сайта-каталога чатов)."""
    text = "55 | Chat One\n54 | Chat Two\n53 | Chat Three"
    entities = [
        MessageEntity(type="text_link", offset=5, length=8, url="https://t.me/chatone"),
        MessageEntity(type="text_link", offset=19, length=8, url="https://t.me/chattwo"),
        MessageEntity(type="text_link", offset=33, length=10, url="https://t.me/chatthree"),
    ]
    msg = _make_message(text, entities=entities)
    entries = u.parse_links_from_message(msg)
    usernames = {e["username"] for e in entries}
    assert usernames == {"chatone", "chattwo", "chatthree"}
    assert len(entries) == 3


def test_mixed_visible_and_hidden_links():
    msg = _make_message(
        "Обычная: t.me/plainchat\nСкрытая ссылка",
        entities=[MessageEntity(type="text_link", offset=24, length=15,
                                url="https://t.me/hiddenchat")])
    entries = u.parse_links_from_message(msg)
    usernames = {e["username"] for e in entries}
    assert usernames == {"plainchat", "hiddenchat"}


def test_same_link_visible_and_hidden_deduplicated():
    msg = _make_message(
        "t.me/samechat",
        entities=[MessageEntity(type="text_link", offset=0, length=13,
                                url="https://t.me/samechat")])
    entries = u.parse_links_from_message(msg)
    assert len(entries) == 1


def test_hidden_private_invite_link():
    msg = _make_message(
        "Приватный чат тут",
        entities=[MessageEntity(type="text_link", offset=0, length=17,
                                url="https://t.me/+AbCdEf1234567890")])
    entries = u.parse_links_from_message(msg)
    assert len(entries) == 1
    assert entries[0]["type"] == "private"


def test_no_entities_falls_back_to_plain_text_parsing():
    msg = _make_message("t.me/regularchat", entities=None)
    entries = u.parse_links_from_message(msg)
    assert entries == [{"type": "public", "username": "regularchat"}]


def test_non_link_entities_ignored():
    """Другие типы entity (bold, italic и т.д.) не должны влиять на разбор."""
    msg = _make_message(
        "жирный текст без ссылок",
        entities=[MessageEntity(type="bold", offset=0, length=6)])
    entries = u.parse_links_from_message(msg)
    assert entries == []


def test_caption_entities_also_checked():
    """На случай, если ссылка присылается в подписи к фото/документу, а не
    в обычном текстовом сообщении."""
    msg = _make_message(
        None,
        caption_entities=[MessageEntity(type="text_link", offset=0, length=5,
                                        url="https://t.me/fromcaption")])
    entries = u.parse_links_from_message(msg)
    assert entries == [{"type": "public", "username": "fromcaption"}]


def test_no_links_at_all_returns_empty():
    """Ровно тот случай, что был у пользователя изначально: если в сообщении
    физически нет ни одной ссылки (ни в тексте, ни в скрытых entity) —
    результат должен быть пустым списком, а не ошибкой."""
    msg = _make_message("55 | Просто название без ссылки\n54 | Ещё одно", entities=None)
    entries = u.parse_links_from_message(msg)
    assert entries == []
