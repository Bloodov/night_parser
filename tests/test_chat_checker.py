"""
Регресс-тесты на распознавание ссылок (services/chat_checker.py).

Запуск: pytest tests/test_chat_checker.py -v

За время разработки этого бота мы трижды находили и чинили баги именно в
логике распознавания ссылок (строгая привязка к началу строки не работала с
нумерованными списками; email-адреса ложно распознавались как @username;
т.me/c/... ссылки на сообщения ложно матчились и т.д.) — этот файл фиксирует
все найденные кейсы, чтобы будущие правки их не сломали обратно.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.chat_checker import extract_username, extract_private_invite, parse_chat_link


# ═══════════ extract_username: базовые форматы ═══════════

def test_plain_username_with_at():
    assert extract_username("@somechat") == "somechat"


def test_tme_without_protocol():
    assert extract_username("t.me/somechat") == "somechat"


def test_tme_with_https():
    assert extract_username("https://t.me/somechat") == "somechat"


def test_tme_with_http():
    assert extract_username("http://t.me/somechat") == "somechat"


def test_tme_preview_s_prefix():
    """t.me/s/username — публичное превью канала, юзернейм после /s/."""
    assert extract_username("https://t.me/s/somechat") == "somechat"


def test_username_too_short_rejected():
    assert extract_username("@abc") is None  # меньше 4 символов


def test_no_link_returns_none():
    assert extract_username("просто какой-то текст без ссылок") is None


# ═══════════ extract_username: "грязные" реальные форматы ═══════════

def test_numbered_list_dot():
    assert extract_username("1. https://t.me/somechat") == "somechat"


def test_numbered_list_paren():
    assert extract_username("2) t.me/anotherchat") == "anotherchat"


def test_bullet_dash():
    assert extract_username("- @thirdchat") == "thirdchat"


def test_trailing_text_after_link():
    assert extract_username("t.me/anotherchat — крутой чат, залетай") == "anotherchat"


def test_leading_text_before_link():
    assert extract_username("заходи в чат https://t.me/sixthchat прямо сейчас") == "sixthchat"


def test_tabular_data_with_description():
    """Ссылка, скопированная из таблицы вместе с описанием через таб — частый
    источник багов, если парсер жадно проглатывает весь остаток строки."""
    line = "https://t.me/fourthchat\tОписание чата\tКатегория\t1 738"
    assert extract_username(line) == "fourthchat"


def test_surrounding_whitespace():
    assert extract_username("   https://t.me/fifthchat   ") == "fifthchat"


# ═══════════ extract_username: должно НЕ распознаваться ═══════════

def test_email_not_treated_as_mention():
    assert extract_username("random@gmail.com") is None


def test_email_in_sentence_not_matched():
    assert extract_username("напишите на support@company.com за помощью") is None


def test_message_link_not_matched_as_username():
    """t.me/c/<chat_id>/<msg_id> — ссылка на конкретное сообщение, не на чат."""
    assert extract_username("https://t.me/c/1242414317/160612") is None


def test_service_paths_excluded():
    assert extract_username("https://t.me/addstickers/somepack") is None
    assert extract_username("https://t.me/proxy?server=1.2.3.4&port=443") is None


# ═══════════ приватные инвайт-ссылки ═══════════

def test_private_plus_format():
    """extract_private_invite сохраняет регистр как есть — Telegram-хеши
    case-sensitive; к нижнему регистру их приводит уже parse_chat_link() перед
    дедупликацией (см. test_parse_private и test_private_joinchat_normalizes_to_plus_link)."""
    result = extract_private_invite("https://t.me/+AbCdEf1234567890")
    assert result is not None
    invite_hash, link = result
    assert invite_hash == "AbCdEf1234567890"
    assert link == "https://t.me/+AbCdEf1234567890"


def test_private_joinchat_format():
    result = extract_private_invite("t.me/joinchat/AbCdEf1234567890")
    assert result is not None
    invite_hash, _link = result
    assert invite_hash == "AbCdEf1234567890"


def test_private_joinchat_normalizes_to_plus_link():
    """joinchat/xxx и +xxx — один и тот же формат, должны давать одинаковый hash
    (иначе одна и та же приватная ссылка, присланная в двух форматах, не
    задедуплицируется)."""
    r1 = extract_private_invite("t.me/joinchat/SameHash1234567890")
    r2 = extract_private_invite("t.me/+SameHash1234567890")
    assert r1[0] == r2[0]


def test_private_too_short_hash_rejected():
    assert extract_private_invite("https://t.me/+short") is None


def test_private_with_trailing_text():
    result = extract_private_invite("https://t.me/+AbCdEf1234567890 — приватная ссылка, не палить")
    assert result is not None


# ═══════════ parse_chat_link: сводный разбор ═══════════

def test_parse_public():
    r = parse_chat_link("t.me/somechat")
    assert r == {"type": "public", "username": "somechat"}


def test_parse_private():
    r = parse_chat_link("https://t.me/+AbCdEf1234567890")
    assert r["type"] == "private"
    assert r["hash"] == "abcdef1234567890"
    assert r["link"] == "https://t.me/+AbCdEf1234567890"


def test_parse_none_for_garbage():
    assert parse_chat_link("это не ссылка вообще") is None


def test_parse_empty_line():
    assert parse_chat_link("") is None
    assert parse_chat_link("   ") is None


def test_parse_private_wins_over_public_when_both_could_match():
    """Приватная ссылка должна распознаваться как приватная, а не как публичный
    username '+AbCdEf...' — проверяем порядок проверки внутри parse_chat_link."""
    r = parse_chat_link("https://t.me/+AbCdEf1234567890")
    assert r["type"] == "private"
