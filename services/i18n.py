"""
Локализация пользовательского интерфейса бота (ru/en).

Админ-панель (handlers/admin.py) НЕ локализована — она предполагается для
владельца бота, а не для обычных пользователей, поэтому остаётся на русском.

Строки хранятся как словарь: ключ -> {"ru": "...", "en": "..."}. Поддерживают
плейсхолдеры для .format(): t("insufficient_balance", "ru", price=5, balance=2).
"""

DEFAULT_LANG = "ru"
SUPPORTED_LANGS = ("ru", "en")

LANGUAGE_NAMES = {"ru": "Русский", "en": "English"}

_STRINGS: dict[str, dict[str, str]] = {
    # ── онбординг / язык ──
    "choose_language": {
        "ru": "🌍 Выберите язык интерфейса / Choose your interface language:",
        "en": "🌍 Выберите язык интерфейса / Choose your interface language:",
    },
    "language_set": {
        "ru": "✅ Язык интерфейса: {name}",
        "en": "✅ Interface language: {name}",
    },
    "welcome": {
        "ru": ("🌙 <b>Night Parser | Chat Parsing</b>\n\n"
              "🔍 Ищу чаты по ключевым словам из нашей базы.\n"
              "🤝 Сдавайте новые чаты и получайте коины.\n\n"
              "🪙 Стартовый баланс: <b>{balance} коинов</b>\n\n"
              "Выберите действие:"),
        "en": ("🌙 <b>Night Parser | Chat Parsing</b>\n\n"
              "🔍 I search chats by keywords from our database.\n"
              "🤝 Submit new chats and earn coins.\n\n"
              "🪙 Starting balance: <b>{balance} coins</b>\n\n"
              "Choose an action:"),
    },
    "welcome_back": {
        "ru": "🌙 <b>Night Parser | Chat Parsing</b>\n\nВыберите действие:",
        "en": "🌙 <b>Night Parser | Chat Parsing</b>\n\nChoose an action:",
    },

    # ── меню ──
    "btn_search": {"ru": "🔍 Поиск", "en": "🔍 Search"},
    "btn_submit": {"ru": "🤝 Сдать чат", "en": "🤝 Submit chat"},
    "btn_profile": {"ru": "👤 Профиль", "en": "👤 Profile"},
    "btn_buy": {"ru": "💎 Купить коины", "en": "💎 Buy coins"},
    "menu_placeholder": {"ru": "Выберите действие…", "en": "Choose an action…"},

    # ── поиск ──
    "search_prompt": {
        "ru": "🔍 Введите ключевое слово или фразу для поиска:",
        "en": "🔍 Enter a keyword or phrase to search:",
    },
    "link_hint": {
        "ru": "🔗 Похоже, вы прислали ссылку на чат.\nЧтобы сдать её в базу, нажмите «{btn}» и пришлите ссылку ещё раз.",
        "en": "🔗 Looks like you sent a chat link.\nTo submit it, tap «{btn}» and send the link again.",
    },
    "banned": {"ru": "⛔ Вы заблокированы.", "en": "⛔ You are banned."},
    "query_too_short": {
        "ru": "❗ Запрос слишком короткий (минимум 2 символа).",
        "en": "❗ Query is too short (minimum 2 characters).",
    },
    "insufficient_balance": {
        "ru": "❌ Недостаточно коинов! Нужно {price} 🪙, у вас {balance} 🪙.",
        "en": "❌ Not enough coins! Need {price} 🪙, you have {balance} 🪙.",
    },
    "no_results": {
        "ru": "❌ Чаты по запросу «{query}» не найдены.\nСписание не произведено.",
        "en": "❌ No chats found for «{query}».\nNo coins were charged.",
    },
    "search_charged": {
        "ru": "✅ Списано {price} 🪙 (баланс: {balance} 🪙).\nНажмите на чат, чтобы открыть его 👇",
        "en": "✅ Charged {price} 🪙 (balance: {balance} 🪙).\nTap a chat to open it 👇",
    },
    "referral_first_search": {
        "ru": "🎉 Ваш реферал сделал первый поиск — начислено +{bonus} 🪙!",
        "en": "🎉 Your referral made their first search — +{bonus} 🪙 credited!",
    },
    "results_list_header": {"ru": "📑 Список чатов:", "en": "📑 Chat list:"},
    "btn_download_txt": {"ru": "📄 Скачать .txt", "en": "📄 Download .txt"},
    "btn_new_search": {"ru": "🔍 Новый поиск", "en": "🔍 New search"},
    "no_results_alert": {"ru": "Нет результатов", "en": "No results"},
    "txt_export_header": {
        "ru": "Night Parser | Chat Parsing — результаты поиска",
        "en": "Night Parser | Chat Parsing — search results",
    },
    "txt_export_caption": {"ru": "📄 Ваши результаты", "en": "📄 Your results"},

    # ── карточка чата ──
    "btn_open_chat": {"ru": "🔗 Открыть чат", "en": "🔗 Open chat"},
    "btn_report": {"ru": "⚠️ Жалоба", "en": "⚠️ Report"},
    "members_count": {"ru": "👥 {count} участников\n", "en": "👥 {count} members\n"},

    # ── сдача чата ──
    "submit_intro": {
        "ru": ("🤝 <b>Сдача чатов в базу</b>\n\n"
              "📎 Пришлите <b>ссылку</b> на чат — по одной или списком (по одной на строку)\n"
              "📄 Или загрузите <b>.txt файл</b> — по одной ссылке в строке\n\n"
              "Принимаются публичные (t.me/username) и приватные (t.me/+хеш) чаты.\n\n"
              "📋 Требования к публичным чатам: групповой чат, не канал, от {min_members} участников.\n"
              "🪙 Награда: +{reward} коин за публичный чат{private_reward}\n\n"
              "❌ Отмена: /cancel"),
        "en": ("🤝 <b>Submit chats to the database</b>\n\n"
              "📎 Send a <b>link</b> to a chat — one, or a list (one per line)\n"
              "📄 Or upload a <b>.txt file</b> — one link per line\n\n"
              "Both public (t.me/username) and private (t.me/+hash) chats are accepted.\n\n"
              "📋 Requirements for public chats: group chat, not a channel, {min_members}+ members.\n"
              "🪙 Reward: +{reward} coin per public chat{private_reward}\n\n"
              "❌ Cancel: /cancel"),
    },
    "submit_intro_private_reward": {
        "ru": ", +{amount} за приватный.",
        "en": ", +{amount} for a private one.",
    },
    "submit_intro_private_no_reward": {
        "ru": " (за приватные — без награды, они не проверяются).",
        "en": " (no reward for private ones — they aren't verified).",
    },
    "submit_cancelled": {
        "ru": "❌ Сдача чата отменена.",
        "en": "❌ Chat submission cancelled.",
    },
    "file_wrong_type": {
        "ru": "❌ Принимаются только .txt файлы. Либо пришлите ссылку текстом.",
        "en": "❌ Only .txt files are accepted. Or send the link as text.",
    },
    "file_too_large": {
        "ru": "❌ Файл слишком большой (максимум 2 МБ).",
        "en": "❌ File is too large (2 MB max).",
    },
    "file_read_error": {
        "ru": "❌ Не удалось прочитать файл. Попробуйте ещё раз.",
        "en": "❌ Couldn't read the file. Please try again.",
    },
    "no_links_in_file": {
        "ru": "❌ В файле не найдено ни одной корректной ссылки.",
        "en": "❌ No valid links found in the file.",
    },
    "invalid_link_format": {
        "ru": "❌ Неверный формат. Пришлите ссылку вида: t.me/username или t.me/+хеш (или список ссылок — по одной на строку).",
        "en": "❌ Invalid format. Send a link like t.me/username or t.me/+hash (or a list — one per line).",
    },
    "already_queued": {
        "ru": "⏳ У вас уже есть ссылки в очереди на проверку. Дождитесь результата — я пришлю сообщение, как только всё будет готово.",
        "en": "⏳ You already have links in the verification queue. Please wait — I'll message you once it's done.",
    },
    "queued_confirmation": {
        "ru": ("📦 Принято в очередь: <b>{count}</b> ссылок(и).\n"
              "Как только проверка завершится, я пришлю результат сюда — а пока можно свободно "
              "пользоваться ботом: искать чаты, смотреть профиль и т.д. 👍"),
        "en": ("📦 Queued: <b>{count}</b> link(s).\n"
              "I'll send the result here once the check is done — meanwhile feel free to use "
              "the bot: search chats, check your profile, etc. 👍"),
    },

    # ── жалобы ──
    "already_reported": {
        "ru": "Вы уже отправляли жалобу на этот чат.",
        "en": "You already reported this chat.",
    },
    "chat_removed_alert": {
        "ru": "⚠️ Чат удалён из базы ({count} жалоб).",
        "en": "⚠️ Chat removed from the database ({count} reports).",
    },
    "report_accepted_alert": {
        "ru": "⚠️ Жалоба принята ({count}/{max}).",
        "en": "⚠️ Report accepted ({count}/{max}).",
    },

    # ── профиль ──
    "profile_not_found": {"ru": "Пользователь не найден", "en": "User not found"},
    "profile_text": {
        "ru": ("👤 <b>Профиль</b>\n\n"
              "🆔 ID: <code>{id}</code>\n"
              "💰 Баланс: <b>{balance} 🪙</b>\n\n"
              "🌐 Язык интерфейса: {lang_name} (сменить: /language)\n\n"
              "🎁 Приглашайте друзей: +{bonus} 🪙 за каждого:\n{link}"),
        "en": ("👤 <b>Profile</b>\n\n"
              "🆔 ID: <code>{id}</code>\n"
              "💰 Balance: <b>{balance} 🪙</b>\n\n"
              "🌐 Interface language: {lang_name} (change: /language)\n\n"
              "🎁 Invite friends: +{bonus} 🪙 each:\n{link}"),
    },
    "btn_share_link": {"ru": "📨 Поделиться ссылкой", "en": "📨 Share link"},
    "share_text": {"ru": "Ищи чаты здесь!", "en": "Find chats here!"},

    # ── смена языка ──
    "language_prompt": {
        "ru": "🌍 Выберите язык интерфейса:",
        "en": "🌍 Choose your interface language:",
    },

    # ── оплата ──
    "buy_menu_header": {
        "ru": "💎 <b>Покупка коинов</b>\n\nВыберите пакет:",
        "en": "💎 <b>Buy coins</b>\n\nChoose a package:",
    },
    "package_button": {
        "ru": "🪙 {coins} коинов — {stars}⭐ / {usdt} USDT",
        "en": "🪙 {coins} coins — {stars}⭐ / {usdt} USDT",
    },
    "package_chosen": {
        "ru": "🪙 Пакет: <b>{coins} коинов</b>\nВыберите способ оплаты:",
        "en": "🪙 Package: <b>{coins} coins</b>\nChoose a payment method:",
    },
    "btn_pay_stars": {"ru": "⭐ Оплатить {stars} Stars", "en": "⭐ Pay {stars} Stars"},
    "btn_pay_crypto": {
        "ru": "💎 Оплатить {usdt} USDT — CryptoBot",
        "en": "💎 Pay {usdt} USDT — CryptoBot",
    },
    "stars_invoice_title": {"ru": "{coins} коинов", "en": "{coins} coins"},
    "stars_invoice_description": {
        "ru": "Пополнение баланса Night Parser на {coins} коинов",
        "en": "Top up your Night Parser balance by {coins} coins",
    },
    "stars_price_label": {"ru": "Коины", "en": "Coins"},
    "stars_paid": {
        "ru": "✅ Оплата Stars получена!\n🪙 +{coins} коинов зачислено!",
        "en": "✅ Stars payment received!\n🪙 +{coins} coins credited!",
    },
    "crypto_api_error": {
        "ru": "❌ Ошибка платёжной системы. Попробуйте позже.",
        "en": "❌ Payment system error. Please try again later.",
    },
    "btn_pay_now": {"ru": "💳 Перейти к оплате", "en": "💳 Proceed to payment"},
    "invoice_created": {
        "ru": ("🧾 Счёт создан на <b>{usdt} USDT</b> ({coins} коинов).\n"
              "После оплаты коины начислятся автоматически (счёт действует {minutes} мин)."),
        "en": ("🧾 Invoice created for <b>{usdt} USDT</b> ({coins} coins).\n"
              "Coins will be credited automatically after payment (invoice valid for {minutes} min)."),
    },
    "payment_received": {
        "ru": "✅ Оплата получена!\n🪙 +{coins} коинов зачислено!",
        "en": "✅ Payment received!\n🪙 +{coins} coins credited!",
    },

    # ── обязательная подписка ──
    "subscribe_prompt": {
        "ru": "🔒 Для использования бота нужно подписаться на канал(ы) ниже:\n\n{channels}\n\nПосле подписки нажмите «{btn}».",
        "en": "🔒 To use the bot, please subscribe to the channel(s) below:\n\n{channels}\n\nThen tap «{btn}».",
    },
    "btn_check_subscription": {"ru": "✅ Я подписался", "en": "✅ I subscribed"},
    "still_not_subscribed": {
        "ru": "❌ Вы ещё не подписаны на: {names}",
        "en": "❌ You're not yet subscribed to: {names}",
    },
    "subscription_confirmed": {
        "ru": "✅ Подписка подтверждена, добро пожаловать!",
        "en": "✅ Subscription confirmed, welcome!",
    },

    # ── итог проверки сданных ссылок (services/submit_queue.py) ──
    "submit_report_header": {
        "ru": ("📊 <b>Проверка ваших ссылок завершена</b>\n\n"
              "✅ Принято: <b>{added}</b>\n"
              "🔁 Уже в базе: <b>{dup}</b>\n"
              "❌ Отклонено: <b>{rejected}</b>\n\n"
              "💰 Баланс: <b>{balance} 🪙</b>"),
        "en": ("📊 <b>Your links have been checked</b>\n\n"
              "✅ Accepted: <b>{added}</b>\n"
              "🔁 Already in the database: <b>{dup}</b>\n"
              "❌ Rejected: <b>{rejected}</b>\n\n"
              "💰 Balance: <b>{balance} 🪙</b>"),
    },
    "submit_rejected_list_header": {
        "ru": "\n\n<b>Отклонённые (первые {shown}):</b>\n",
        "en": "\n\n<b>Rejected (first {shown}):</b>\n",
    },
    "submit_rejected_more": {
        "ru": "\n…и ещё {count}",
        "en": "\n…and {count} more",
    },
}


def t(key: str, lang: str | None, **kwargs) -> str:
    """Возвращает переведённую строку. Неизвестный ключ возвращает сам ключ
    (виднее в чате, что не так, чем падать с ошибкой)."""
    lang = lang if lang in SUPPORTED_LANGS else DEFAULT_LANG
    entry = _STRINGS.get(key)
    if not entry:
        return key
    template = entry.get(lang) or entry.get(DEFAULT_LANG, key)
    return template.format(**kwargs) if kwargs else template


def resolve_lang(user) -> str:
    """user — Row/dict из db.get_user() (может быть None). Возвращает язык
    интерфейса пользователя с откатом на DEFAULT_LANG, если ещё не выбран."""
    if user is None:
        return DEFAULT_LANG
    lang = user["language"] if "language" in user.keys() else None
    return lang if lang in SUPPORTED_LANGS else DEFAULT_LANG


# ── меню: сопоставление текста кнопки <-> семантического действия ──
# Reply-клавиатуры Telegram не поддерживают callback_data, поэтому распознавание
# нажатия идёт по точному тексту кнопки — а он теперь зависит от языка
# пользователя. Поэтому хендлер должен реагировать на кнопку НЕЗАВИСИМО от
# того, на каком из поддерживаемых языков она была показана.
_MENU_KEYS = ("btn_search", "btn_submit", "btn_profile", "btn_buy")


def all_menu_button_texts() -> set[str]:
    """Все варианты текста кнопок меню на всех поддерживаемых языках — для
    фильтра F.text.in_(...) хендлера нижнего меню."""
    return {t(key, lang) for key in _MENU_KEYS for lang in SUPPORTED_LANGS}


def menu_key_from_text(text: str) -> str | None:
    """Обратный поиск: по тексту нажатой кнопки (на любом поддерживаемом языке)
    определяет семантический ключ действия, например 'btn_search'."""
    for key in _MENU_KEYS:
        for lang in SUPPORTED_LANGS:
            if t(key, lang) == text:
                return key
    return None
