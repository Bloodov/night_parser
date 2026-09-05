
import os
import re
import json
import aiosqlite
from datetime import datetime
from services.translit import script_variants, detect_script
from services.language_detect import detect_language

# Путь к файлу БД настраивается через переменную окружения DB_PATH — это важно
# на хостингах вроде Railway, где файловая система эфемерна и без persistent
# volume + указания пути ВНУТРИ этого volume база будет обнуляться при каждом
# перезапуске/редеплое. По умолчанию — как раньше, файл рядом с кодом (для
# локального запуска этого достаточно).
DB_PATH = os.getenv("DB_PATH", "night_parser.db")
STARTING_BALANCE = 100


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # WAL позволяет читать базу, пока идёт запись (важно: несколько фоновых
        # воркеров очереди пишут в БД параллельно с обычными хендлерами) —
        # заметно снижает риск ошибки "database is locked".
        await db.execute("PRAGMA journal_mode=WAL")
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id        INTEGER PRIMARY KEY,
            username       TEXT,
            referrer_id    INTEGER,
            balance        INTEGER DEFAULT 100,
            is_banned      INTEGER DEFAULT 0,
            registered_at  TEXT,
            last_submit_at TEXT,
            submits_today  INTEGER DEFAULT 0,
            submit_date    TEXT
        );
        CREATE TABLE IF NOT EXISTS chats (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT UNIQUE,
            title         TEXT,
            description   TEXT,
            member_count  INTEGER,
            submitted_by  INTEGER,
            added_at      TEXT,
            reports_count INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS search_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            query       TEXT,
            results     INTEGER,
            searched_at TEXT
        );
        CREATE TABLE IF NOT EXISTS reports (
            user_id       INTEGER,
            chat_username TEXT,
            reported_at   TEXT,
            UNIQUE(user_id, chat_username)
        );
        CREATE TABLE IF NOT EXISTS payments (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            provider    TEXT,
            amount      TEXT,
            coins       INTEGER,
            status      TEXT DEFAULT 'pending',
            invoice_id  TEXT,
            created_at  TEXT
        );
        CREATE TABLE IF NOT EXISTS submit_jobs (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER,
            entries_json  TEXT,
            status        TEXT DEFAULT 'queued',
            created_at    TEXT,
            finished_at   TEXT,
            added         INTEGER DEFAULT 0,
            dup           INTEGER DEFAULT 0,
            rejected_json TEXT
        );
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS required_channels (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id     INTEGER,
            username    TEXT,
            title       TEXT,
            added_at    TEXT
        );
        CREATE TABLE IF NOT EXISTS balance_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER,
            delta      INTEGER,
            reason     TEXT,
            created_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_balance_log_user ON balance_log(user_id);
        """)
        await db.commit()

        # Миграция: добавляем поддержку приватных чатов в уже существующую БД
        cur = await db.execute("PRAGMA table_info(chats)")
        existing_cols = {row[1] for row in await cur.fetchall()}
        if "is_private" not in existing_cols:
            await db.execute("ALTER TABLE chats ADD COLUMN is_private INTEGER DEFAULT 0")
        if "invite_link" not in existing_cols:
            await db.execute("ALTER TABLE chats ADD COLUMN invite_link TEXT")
        if "language" not in existing_cols:
            # ISO 639-1 код языка (ru/en/de/uk/...) или NULL, если не определён —
            # см. services/language_detect.py. Существующие чаты получат язык
            # при следующей еженедельной проверке живости (services/health_check.py),
            # отдельный проход по всей базе прямо сейчас не гоняем, чтобы не
            # создавать резкий скачок нагрузки на CPU при миграции большой базы.
            await db.execute("ALTER TABLE chats ADD COLUMN language TEXT")
        await db.commit()

        # Миграция: реферальный бонус теперь платится за первый реальный поиск
        # приглашённого, а не за одну лишь регистрацию (/start ничего не
        # подтверждает — легко фармится пустыми аккаунтами).
        cur = await db.execute("PRAGMA table_info(users)")
        existing_user_cols = {row[1] for row in await cur.fetchall()}
        if "referral_paid" not in existing_user_cols:
            await db.execute("ALTER TABLE users ADD COLUMN referral_paid INTEGER DEFAULT 0")
            # Обратная совместимость: у уже существующих пользователей с рефералом
            # бонус УЖЕ выплачен по старой логике (сразу при регистрации) —
            # помечаем как выплаченный, иначе их следующий поиск заплатит бонус повторно.
            await db.execute(
                "UPDATE users SET referral_paid = 1 WHERE referrer_id IS NOT NULL")
        if "language" not in existing_user_cols:
            # Язык ИНТЕРФЕЙСА пользователя (ru/en) — выбирается при первом /start.
            # NULL означает "ещё не выбрал" (для уже существующих пользователей
            # при миграции — покажем выбор языка при следующем /start или, если
            # они просто продолжат писать боту, будем использовать язык по
            # умолчанию, пока явно не сменят через /language).
            await db.execute("ALTER TABLE users ADD COLUMN language TEXT")
        await db.commit()

        # Полнотекстовый поиск (FTS5) вместо LIKE '%...%' — быстрее и с ранжированием
        # по релевантности на больших объёмах (десятки тысяч чатов и больше).
        # username — отдельная колонка, чтобы можно было искать публичные чаты
        # ТОЛЬКО по title+username (без description — там часто встречаются
        # шумовые слова вроде "админ: @contact", не относящиеся к теме чата).
        await db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS chats_fts USING fts5(
                title, description, username, content='chats', content_rowid='id'
            )
        """)

        # Миграция: у более старой версии chats_fts не было колонки username —
        # FTS5 не поддерживает ALTER ADD COLUMN для virtual table, поэтому
        # пересоздаём таблицу и переиндексируем всё заново (безопасно и быстро,
        # см. 'rebuild' ниже).
        cur = await db.execute("PRAGMA table_info(chats_fts)")
        fts_cols = {row[1] for row in await cur.fetchall()}
        if "username" not in fts_cols:
            await db.executescript("""
                DROP TRIGGER IF EXISTS chats_ai;
                DROP TRIGGER IF EXISTS chats_ad;
                DROP TRIGGER IF EXISTS chats_au;
                DROP TABLE IF EXISTS chats_fts;
            """)
            await db.execute("""
                CREATE VIRTUAL TABLE chats_fts USING fts5(
                    title, description, username, content='chats', content_rowid='id'
                )
            """)
            await db.execute(
                "DELETE FROM _migrations WHERE name = 'chats_fts_rebuild'")
            await db.commit()

        await db.executescript("""
            CREATE TRIGGER IF NOT EXISTS chats_ai AFTER INSERT ON chats BEGIN
                INSERT INTO chats_fts(rowid, title, description, username)
                VALUES (new.id, new.title, new.description, new.username);
            END;
            CREATE TRIGGER IF NOT EXISTS chats_ad AFTER DELETE ON chats BEGIN
                INSERT INTO chats_fts(chats_fts, rowid, title, description, username)
                VALUES('delete', old.id, old.title, old.description, old.username);
            END;
            CREATE TRIGGER IF NOT EXISTS chats_au AFTER UPDATE ON chats BEGIN
                INSERT INTO chats_fts(chats_fts, rowid, title, description, username)
                VALUES('delete', old.id, old.title, old.description, old.username);
                INSERT INTO chats_fts(rowid, title, description, username)
                VALUES (new.id, new.title, new.description, new.username);
            END;
            CREATE TABLE IF NOT EXISTS _migrations (name TEXT PRIMARY KEY);
        """)
        await db.commit()

        # ВАЖНО: для FTS5-таблицы с content='...' (внешний контент) обычный
        # SELECT COUNT(*) FROM chats_fts отражает данные исходной таблицы chats,
        # а НЕ реальное состояние поискового индекса — индекс при этом может быть
        # полностью пуст, даже если COUNT(*) > 0. Поэтому нельзя определять
        # «нужен ли бэкфилл» по количеству строк — это давало бы вечно пустой
        # индекс на уже существующей базе. Вместо этого используем официальную
        # команду 'rebuild' и отдельную таблицу-маркер, чтобы выполнить её ровно
        # один раз (rebuild полностью пересобирает индекс из chats, безопасно
        # запускать один раз при миграции старой базы).
        cur = await db.execute(
            "SELECT 1 FROM _migrations WHERE name = 'chats_fts_rebuild'")
        already_built = await cur.fetchone() is not None
        if not already_built:
            await db.execute("INSERT INTO chats_fts(chats_fts) VALUES('rebuild')")
            await db.execute(
                "INSERT INTO _migrations (name) VALUES ('chats_fts_rebuild')")
            await db.commit()


# ── Пользователи ──

async def get_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return await cur.fetchone()


async def create_user(user_id: int, username: str, referrer_id=None) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, referrer_id, balance, registered_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, username, referrer_id, STARTING_BALANCE, datetime.now().isoformat()))
        await db.commit()
        return cur.rowcount > 0


async def update_balance(user_id: int, delta: int, reason: str = ""):
    """Меняет баланс И записывает изменение в журнал (balance_log) — без причины
    разобраться в жалобе "у меня пропали коины" невозможно."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?",
                         (delta, user_id))
        await db.execute(
            "INSERT INTO balance_log (user_id, delta, reason, created_at) VALUES (?, ?, ?, ?)",
            (user_id, delta, reason, datetime.now().isoformat()))
        await db.commit()


async def get_balance_log(user_id: int, limit: int = 30):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM balance_log WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit))
        return await cur.fetchall()


async def find_user_by_username(username: str):
    """Ищет пользователя по @username (регистронезависимо, без @) —
    для админского поиска логов "по юзеру или айди"."""
    username = username.lstrip("@")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,))
        return await cur.fetchone()


async def set_banned(user_id: int, banned: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_banned = ? WHERE user_id = ?",
                         (int(banned), user_id))
        await db.commit()


async def set_user_language(user_id: int, language: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET language = ? WHERE user_id = ?",
                         (language, user_id))
        await db.commit()


# ── Лимиты сдачи чатов ──

async def check_submit_cooldown(user_id: int, cooldown_sec: int):
    """Проверяет кулдаун, ничего не обновляет. Вызывается один раз перед стартом сдачи."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT last_submit_at FROM users WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()

    if row and row["last_submit_at"]:
        last = datetime.fromisoformat(row["last_submit_at"])
        passed = (datetime.now() - last).total_seconds()
        if passed < cooldown_sec:
            return False, f"⏳ Подождите {int(cooldown_sec - passed)} сек. перед следующей сдачей."
    return True, None


async def touch_submit_cooldown(user_id: int):
    """Запускает отсчёт кулдауна. Вызывается один раз после того, как все ссылки проверены."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET last_submit_at = ? WHERE user_id = ?",
            (datetime.now().isoformat(), user_id))
        await db.commit()


# ── Чаты ──

async def chat_exists(username: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM chats WHERE username = ?", (username.lower(),))
        return await cur.fetchone() is not None


async def add_chat(username, title, description, member_count, submitted_by):
    language = detect_language(title, description)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO chats (username, title, description, member_count, "
            "submitted_by, added_at, is_private, invite_link, language) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, NULL, ?)",
            (username.lower(), title, description, member_count, submitted_by,
             datetime.now().isoformat(), language))
        await db.commit()


async def add_private_chat(invite_hash: str, invite_link: str, submitted_by: int):
    """Добавляет приватный чат по инвайт-ссылке. Название/число участников
    неизвестны — Bot API не даёт их получить без входа бота в чат."""
    pseudo_username = f"inv_{invite_hash.lower()}"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO chats (username, title, description, member_count, "
            "submitted_by, added_at, is_private, invite_link) "
            "VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
            (pseudo_username, "🔒 Приватный чат", "", 0,
             submitted_by, datetime.now().isoformat(), invite_link))
        await db.commit()
    return pseudo_username


def _build_fts_query(query: str) -> str:
    """Строит безопасный MATCH-запрос для FTS5 из произвольного пользовательского
    ввода: каждое слово оборачивается в кавычки (чтобы спецсимволы FTS5 вроде
    "-", ":", "*" не ломали синтаксис запроса) и получает суффикс префиксного
    поиска. Слова соединяются через явный AND — FTS5 НЕ поддерживает неявный
    AND (через пробел) между скобочными OR-группами, только между простыми
    термами, поэтому явный "AND" нужен всегда, когда среди частей есть группы.

    Для каждого слова дополнительно подставляется его транслитерация в другой
    алфавит (crypto -> крипто и наоборот) через OR — чтобы поиск на латинице
    находил и кириллические названия чатов той же тематики, и наоборот."""
    tokens = re.findall(r"\w+", query, flags=re.UNICODE)
    if not tokens:
        return ""
    parts = []
    for t in tokens[:10]:  # ограничиваем 10 словами на всякий случай
        variants = script_variants(t)
        quoted = [f'"{v}"*' for v in variants]
        parts.append(quoted[0] if len(quoted) == 1 else "(" + " OR ".join(quoted) + ")")
    return " AND ".join(parts)


async def search_chats(query: str, limit: int = 50):
    fts_query = _build_fts_query(query)
    if not fts_query:
        return []
    query_script = detect_script(query)
    query_language = detect_language(query)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        try:
            # Публичные чаты — ищем по title+username, БЕЗ description: там
            # часто встречаются шумовые слова вроде "админ: @contact",
            # не относящиеся к теме самого чата.
            cur = await db.execute(
                "SELECT c.username, c.title, c.member_count, c.is_private, "
                "c.invite_link, c.language "
                "FROM chats_fts f JOIN chats c ON c.id = f.rowid "
                "WHERE chats_fts MATCH ? AND c.is_private = 0 "
                "ORDER BY bm25(chats_fts), c.member_count DESC LIMIT ?",
                (f"{{title username}}: {fts_query}", limit))
            public_rows = await cur.fetchall()

            # FTS5 матчит ПРЕФИКСЫ ТОКЕНОВ: username вроде "secretcryptoclub" —
            # это один токен без разделителей, и "crypto"* не найдёт совпадение
            # ПОСЕРЕДИНЕ слова (только "начинается с"). Юзернеймы часто клеят
            # слова слитно, поэтому дополнительно ищем подстроку через LIKE —
            # она не зависит от токенизации и найдёт "crypto" где угодно внутри.
            like = f"%{query.strip()}%"
            cur = await db.execute(
                "SELECT username, title, member_count, is_private, invite_link, language "
                "FROM chats WHERE is_private = 0 AND username LIKE ? "
                "ORDER BY member_count DESC LIMIT ?", (like, limit))
            like_rows = await cur.fetchall()
            seen_usernames = {r["username"] for r in public_rows}
            for r in like_rows:
                if r["username"] not in seen_usernames:
                    public_rows.append(r)
                    seen_usernames.add(r["username"])

            # Приватные чаты (мы не можем проверить их username/участников) —
            # ищем по title+description, как раньше.
            cur = await db.execute(
                "SELECT c.username, c.title, c.member_count, c.is_private, "
                "c.invite_link, c.language "
                "FROM chats_fts f JOIN chats c ON c.id = f.rowid "
                "WHERE chats_fts MATCH ? AND c.is_private = 1 "
                "ORDER BY bm25(chats_fts), c.member_count DESC LIMIT ?",
                (f"{{title description}}: {fts_query}", limit))
            private_rows = await cur.fetchall()

            rows = (public_rows + private_rows)[:limit]
        except aiosqlite.OperationalError:
            # Подстраховка на случай нестандартной сборки SQLite без FTS5 —
            # возвращаемся к прежнему поиску через LIKE (без транслитерации:
            # LIKE не умеет OR-группы по вариантам так же аккуратно).
            like = f"%{query}%"
            cur = await db.execute(
                "SELECT username, title, member_count, is_private, invite_link, language "
                "FROM chats WHERE title LIKE ? OR description LIKE ? OR username LIKE ? "
                "ORDER BY member_count DESC LIMIT ?", (like, like, like, limit))
            rows = await cur.fetchall()

    # Сортировка результатов — устойчивая (relevance-порядок внутри каждой
    # группы сохраняется), просто разбиваем уже отсортированный по релевантности
    # список на группы приоритета:
    #   1) тот же ЯЗЫК, что и в запросе (самый точный сигнал, но определяется
    #      не всегда — короткие запросы/названия часто не дают уверенного языка)
    #   2) тот же АЛФАВИТ, что и в запросе, но язык не совпал или не определён
    #      (откат — почти всегда доступен, алфавит определяется однозначно)
    #   3) всё остальное
    if query_language:
        same_lang = [r for r in rows if r["language"] == query_language]
        same_script_only = [r for r in rows if r["language"] != query_language
                            and detect_script(r["title"]) == query_script]
        other = [r for r in rows if r["language"] != query_language
                and detect_script(r["title"]) != query_script]
        rows = same_lang + same_script_only + other
    elif query_script in ("lat", "cyr"):
        matching = [r for r in rows if detect_script(r["title"]) == query_script]
        other = [r for r in rows if detect_script(r["title"]) != query_script]
        rows = matching + other

    return rows


async def get_chat_by_username(username: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM chats WHERE username = ?", (username.lower(),))
        return await cur.fetchone()


async def delete_chat_by_username(username: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM chats WHERE username = ?", (username.lower(),))
        await db.commit()


async def refresh_chat_data(username: str, title: str, description: str, member_count: int):
    """Обновляет название/описание/число участников/язык уже существующей записи —
    используется еженедельной проверкой живости (services/health_check.py),
    чтобы число участников (и определённый язык) не 'протухали' без
    дополнительных запросов к API сверх тех, что и так нужны для самой
    проверки живости."""
    language = detect_language(title, description)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE chats SET title = ?, description = ?, member_count = ?, language = ? "
            "WHERE username = ?",
            (title, description, member_count, language, username.lower()))
        await db.commit()


async def get_chats_missing_language():
    """Публичные чаты без определённого языка — для ручного бэкфилла в админке
    (чисто CPU-операция, без обращений к Telegram, в отличие от health_check)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT username, title, description FROM chats "
            "WHERE is_private = 0 AND (language IS NULL OR language = '')")
        return await cur.fetchall()


async def set_chat_language(username: str, language: str | None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE chats SET language = ? WHERE username = ?", (language, username.lower()))
        await db.commit()


async def all_chats(limit: int = 20, offset: int = 0, private_only: bool = False):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        where = "WHERE is_private = 1" if private_only else ""
        cur = await db.execute(
            f"SELECT * FROM chats {where} "
            "ORDER BY reports_count DESC, added_at DESC LIMIT ? OFFSET ?",
            (limit, offset))
        return await cur.fetchall()


async def count_chats(private_only: bool = False) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        where = "WHERE is_private = 1" if private_only else ""
        cur = await db.execute(f"SELECT COUNT(*) FROM chats {where}")
        return (await cur.fetchone())[0]


async def get_all_chats_for_export():
    """Все чаты без пагинации — используется кнопкой экспорта в админке."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT username, title, is_private, invite_link FROM chats ORDER BY id")
        return await cur.fetchall()


async def get_all_public_usernames() -> list[str]:
    """Список username всех публичных чатов — используется фоновой проверкой
    живости базы (services/health_check.py)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT username FROM chats WHERE is_private = 0")
        return [row[0] for row in await cur.fetchall()]


# ── Жалобы ──

async def add_report(user_id: int, chat_username: str):
    """Возвращает новое число жалоб или None, если юзер уже жаловался."""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO reports (user_id, chat_username, reported_at) VALUES (?, ?, ?)",
                (user_id, chat_username.lower(), datetime.now().isoformat()))
        except Exception:
            return None
        await db.execute("UPDATE chats SET reports_count = reports_count + 1 "
                         "WHERE username = ?", (chat_username.lower(),))
        await db.commit()
        cur = await db.execute("SELECT reports_count FROM chats WHERE username = ?",
                               (chat_username.lower(),))
        row = await cur.fetchone()
        return row[0] if row else None


# ── История поиска ──

async def log_search(user_id: int, query: str, results: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO search_history (user_id, query, results, searched_at) "
            "VALUES (?, ?, ?, ?)",
            (user_id, query, results, datetime.now().isoformat()))
        await db.commit()


# ── Платежи ──

async def create_payment(user_id: int, provider: str, amount: str, coins: int, invoice_id=""):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO payments (user_id, provider, amount, coins, invoice_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, provider, amount, coins, str(invoice_id), datetime.now().isoformat()))
        await db.commit()
        return cur.lastrowid


async def set_payment_status(payment_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE payments SET status = ? WHERE id = ?", (status, payment_id))
        await db.commit()


async def get_payment(payment_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM payments WHERE id = ?", (payment_id,))
        return await cur.fetchone()


async def get_pending_payments():
    """Незавершённые счета CryptoBot (Stars никогда не остаются 'pending' —
    их статус выставляется сразу синхронно). Используется при старте бота,
    чтобы продолжить опрос счетов, оставшихся неоплаченными с прошлого запуска."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM payments WHERE status = 'pending' AND provider != 'stars'")
        return await cur.fetchall()


# ── Очередь заявок на сдачу чатов ──
# Заявка хранится в БД (а не только в памяти), поэтому переживает перезапуск бота:
# при старте бот подбирает все заявки со статусом 'queued' и продолжает их обработку.

async def create_submit_job(user_id: int, entries: list[dict]) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO submit_jobs (user_id, entries_json, status, created_at) "
            "VALUES (?, ?, 'queued', ?)",
            (user_id, json.dumps(entries), datetime.now().isoformat()))
        await db.commit()
        return cur.lastrowid


async def has_active_submit_job(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT 1 FROM submit_jobs WHERE user_id = ? AND status = 'queued' LIMIT 1",
            (user_id,))
        return await cur.fetchone() is not None


async def get_pending_job_ids() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id FROM submit_jobs WHERE status = 'queued' ORDER BY id")
        return [row[0] for row in await cur.fetchall()]


async def get_submit_job(job_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM submit_jobs WHERE id = ?", (job_id,))
        return await cur.fetchone()


async def finish_submit_job(job_id: int, added: int, dup: int, rejected: list[str]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE submit_jobs SET status = 'done', finished_at = ?, "
            "added = ?, dup = ?, rejected_json = ? WHERE id = ?",
            (datetime.now().isoformat(), added, dup, json.dumps(rejected), job_id))
        await db.commit()


async def get_stats():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM users")
        total_users = (await cur.fetchone())[0]
        cur = await db.execute("SELECT COUNT(*) FROM chats")
        total_chats = (await cur.fetchone())[0]
        cur = await db.execute("SELECT COUNT(*) FROM search_history")
        total_searches = (await cur.fetchone())[0]
        cur = await db.execute("SELECT COALESCE(SUM(balance),0) FROM users")
        total_balance = (await cur.fetchone())[0]
        cur = await db.execute("SELECT COUNT(*) FROM payments WHERE status = 'paid'")
        total_purchases = (await cur.fetchone())[0]
    return total_users, total_chats, total_searches, total_balance, total_purchases


async def get_all_user_ids() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users WHERE is_banned = 0")
        return [row[0] for row in await cur.fetchall()]


async def pay_referral_bonus_if_due(user_id: int, bonus: int) -> int | None:
    """Если у пользователя есть реферер и бонус ещё не выплачен — платит
    рефереру и помечает выплаченным. Возвращает id реферера, если бонус
    только что выплачен (чтобы можно было его уведомить), иначе None.
    Вызывается при первом реальном действии приглашённого (первый поиск),
    а не при простой регистрации — иначе бонус легко фармится пустыми
    аккаунтами без единого реального действия."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT referrer_id, referral_paid FROM users WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        if not row or not row["referrer_id"] or row["referral_paid"]:
            return None
        referrer_id = row["referrer_id"]
        await db.execute(
            "UPDATE users SET referral_paid = 1 WHERE user_id = ?", (user_id,))
        await db.commit()

    await update_balance(referrer_id, bonus, reason=f"реферальный бонус за юзера {user_id}")
    return referrer_id


# ── Настройки (key-value) ──

async def get_setting(key: str, default=None):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cur.fetchone()
        return row[0] if row else default


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value))
        await db.commit()


async def is_force_subscribe_enabled() -> bool:
    return await get_setting("force_subscribe", "0") == "1"


async def set_force_subscribe(enabled: bool):
    await set_setting("force_subscribe", "1" if enabled else "0")


# ── Обязательные каналы для подписки ──

async def add_required_channel(chat_id: int, username: str, title: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO required_channels (chat_id, username, title, added_at) "
            "VALUES (?, ?, ?, ?)",
            (chat_id, username, title, datetime.now().isoformat()))
        await db.commit()
        return cur.lastrowid


async def remove_required_channel(channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM required_channels WHERE id = ?", (channel_id,))
        await db.commit()


async def list_required_channels():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM required_channels ORDER BY id")
        return await cur.fetchall()


async def get_required_channel(channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM required_channels WHERE id = ?", (channel_id,))
        return await cur.fetchone()
