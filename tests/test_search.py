"""
Тесты поиска (database.py: _build_fts_query, search_chats).
Запуск: pytest tests/test_search.py -v

test_multiword_query_does_not_crash — регресс-тест на реальный баг: FTS5 не
поддерживает неявный AND (через пробел) между скобочными OR-группами, только
явный "AND" — из-за этого любой многословный запрос падал с OperationalError,
пока не был явно протестирован (однословные запросы этот баг не ловят).
"""
import sys
import os
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import database as db


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


async def _fresh_db(tmp_path):
    db.DB_PATH = str(tmp_path / "test_search.db")
    await db.init_db()
    return db.DB_PATH


def test_build_fts_query_single_word():
    q = db._build_fts_query("crypto")
    assert "AND" not in q  # один терм — AND не нужен
    assert '"crypto"*' in q


def test_build_fts_query_multiword_uses_explicit_and():
    q = db._build_fts_query("crypto trading")
    assert " AND " in q


def test_multiword_query_does_not_crash(tmp_path):
    """Регресс-тест: раньше многословный запрос с транслитерацией падал с
    'fts5: syntax error near "("' — implicit AND между скобочными OR-группами
    невалиден в FTS5."""
    async def run():
        await _fresh_db(tmp_path)
        await db.add_chat("testchat", "Crypto Trading Hub", "best signals", 100, 1)
        results = await db.search_chats("crypto trading", 10)
        assert len(results) == 1
        assert results[0]["username"] == "testchat"

    asyncio.run(run())


def test_search_finds_transliterated_cross_script(tmp_path):
    async def run():
        await _fresh_db(tmp_path)
        await db.add_chat("ruchat", "Крипто Трейдинг", "крипто сигналы", 500, 1)
        results = await db.search_chats("crypto", 10)
        usernames = [r["username"] for r in results]
        assert "ruchat" in usernames

    asyncio.run(run())


def test_search_orders_matching_script_first(tmp_path):
    async def run():
        await _fresh_db(tmp_path)
        await db.add_chat("latchat", "Crypto News", "crypto updates", 100, 1)
        await db.add_chat("cyrchat", "Крипто Новости", "крипто новости дня", 9999, 1)
        results = await db.search_chats("crypto", 10)
        # латинский запрос -> латинские чаты должны идти первыми, несмотря на
        # то, что у кириллического больше участников
        assert results[0]["username"] == "latchat"

    asyncio.run(run())


def test_search_orders_by_language_when_detectable(tmp_path):
    async def run():
        await _fresh_db(tmp_path)
        await db.add_chat("degroup", "Deutsche Krypto Gruppe",
                          "die besten krypto signale und marktanalyse", 100, 1)
        await db.add_chat("engroup", "Crypto Trading Hub",
                          "best crypto signals and market analysis", 9999, 1)
        # запрос достаточно длинный, чтобы язык определился надёжно
        results = await db.search_chats("best crypto trading signals", 10)
        assert results[0]["username"] == "engroup"

    asyncio.run(run())


def test_search_empty_query_returns_empty_list(tmp_path):
    async def run():
        await _fresh_db(tmp_path)
        results = await db.search_chats("!!!???", 10)
        assert results == []

    asyncio.run(run())


def test_search_nonexistent_does_not_crash(tmp_path):
    async def run():
        await _fresh_db(tmp_path)
        await db.add_chat("onlychat", "Some Chat", "description", 100, 1)
        results = await db.search_chats("совершенно другой запрос xyz", 10)
        assert results == []

    asyncio.run(run())
