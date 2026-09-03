import os
from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, CommandObject, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (Message, CallbackQuery, FSInputFile,
                           InlineKeyboardButton, ReplyKeyboardMarkup,
                           KeyboardButton)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import database as db
from config import (BOT_USERNAME, SEARCH_PRICE, MAX_RESULTS,
                    REFERRAL_BONUS, REWARD_PER_CHAT, REWARD_PER_PRIVATE_CHAT,
                    SUBMIT_COOLDOWN_SEC, REPORT_PENALTY, REPORTS_TO_REMOVE, MIN_MEMBERS)
from services.chat_checker import parse_chat_link
from services import submit_queue, subscription
from services.i18n import t, resolve_lang, SUPPORTED_LANGS, LANGUAGE_NAMES, all_menu_button_texts, menu_key_from_text

router = Router()

search_cache: dict[int, list] = {}
page_state: dict[int, int] = {}


class SubmitStates(StatesGroup):
    waiting_link = State()


# ═══════════ КЛАВИАТУРЫ ═══════════

def main_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🔍 Поиск чатов", callback_data="search")
    kb.button(text="🤝 Сдать чат", callback_data="submit")
    kb.button(text="👤 Профиль", callback_data="profile")
    kb.button(text="💎 Купить коины", callback_data="buy")
    kb.adjust(2, 2)
    return kb.as_markup()


def reply_menu_kb(lang: str):
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t("btn_search", lang)), KeyboardButton(text=t("btn_submit", lang))],
            [KeyboardButton(text=t("btn_profile", lang)), KeyboardButton(text=t("btn_buy", lang))],
        ],
        resize_keyboard=True,
        input_field_placeholder=t("menu_placeholder", lang))
    return kb


def language_picker_kb():
    kb = InlineKeyboardBuilder()
    for code in SUPPORTED_LANGS:
        kb.button(text=LANGUAGE_NAMES[code], callback_data=f"setlang:{code}")
    kb.adjust(1)
    return kb.as_markup()


async def get_balance(user_id: int) -> int:
    user = await db.get_user(user_id)
    return user["balance"] if user else 0


# ═══════════ СТАРТ / ЯЗЫК ═══════════

@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject = None):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name

    referrer_id = None
    if command and command.args and command.args.startswith("ref_"):
        try:
            parsed_ref = int(command.args.split("_")[1])
            if parsed_ref != user_id:  # защита от самореферала
                referrer_id = parsed_ref
        except ValueError:
            pass

    is_new = await db.create_user(user_id, username, referrer_id)
    # Реферальный бонус рефереру теперь платится не здесь, а при первом реальном
    # поиске приглашённого (см. process_query) — простая регистрация ничего не
    # подтверждает и легко фармится пустыми аккаунтами.

    if is_new:
        # Новый пользователь — сначала выбор языка интерфейса, приветствие
        # покажем уже на выбранном языке (см. set_language_cb).
        await message.answer(t("choose_language", "ru"), reply_markup=language_picker_kb())
        return

    user = await db.get_user(user_id)
    lang = resolve_lang(user)
    await message.answer(
        t("welcome", lang, balance=user["balance"]),
        reply_markup=reply_menu_kb(lang))


@router.callback_query(F.data.startswith("setlang:"))
async def set_language_cb(call: CallbackQuery):
    lang = call.data.split(":", 1)[1]
    if lang not in SUPPORTED_LANGS:
        lang = "ru"
    await db.set_user_language(call.from_user.id, lang)

    try:
        await call.message.delete()
    except Exception:
        pass

    balance = await get_balance(call.from_user.id)
    await call.message.answer(
        t("welcome", lang, balance=balance),
        reply_markup=reply_menu_kb(lang))
    await call.answer(t("language_set", lang, name=LANGUAGE_NAMES[lang]))


@router.message(Command("language"))
async def language_cmd(message: Message):
    user = await db.get_user(message.from_user.id)
    lang = resolve_lang(user)
    await message.answer(t("language_prompt", lang), reply_markup=language_picker_kb())


@router.callback_query(F.data == "check_subscription")
async def check_subscription_cb(call: CallbackQuery, bot: Bot):
    user = await db.get_user(call.from_user.id)
    lang = resolve_lang(user)

    missing = await subscription.get_missing_channels(bot, call.from_user.id)
    if missing:
        names = ", ".join(c["title"] for c in missing)
        await call.answer(t("still_not_subscribed", lang, names=names), show_alert=True)
        return

    await call.answer(t("subscription_confirmed", lang), show_alert=True)
    try:
        await call.message.delete()
    except Exception:
        pass

    user_id = call.from_user.id
    username = call.from_user.username or call.from_user.first_name
    is_new = await db.create_user(user_id, username)
    if is_new:
        await call.message.answer(t("choose_language", "ru"), reply_markup=language_picker_kb())
        return

    await call.message.answer(t("welcome_back", lang), reply_markup=reply_menu_kb(lang))


@router.message(F.text.func(lambda text: text in all_menu_button_texts()))
async def reply_menu_handler(message: Message, state: FSMContext):
    await state.clear()
    user = await db.get_user(message.from_user.id)
    lang = resolve_lang(user)
    key = menu_key_from_text(message.text)

    if key == "btn_search":
        await message.answer(t("search_prompt", lang))

    elif key == "btn_submit":
        private_reward = (t("submit_intro_private_reward", lang, amount=REWARD_PER_PRIVATE_CHAT)
                          if REWARD_PER_PRIVATE_CHAT else t("submit_intro_private_no_reward", lang))
        await message.answer(
            t("submit_intro", lang, min_members=MIN_MEMBERS, reward=REWARD_PER_CHAT,
              private_reward=private_reward))
        await state.set_state(SubmitStates.waiting_link)

    elif key == "btn_profile":
        if not user:
            await message.answer(t("profile_not_found", lang))
            return
        ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{message.from_user.id}"
        kb = InlineKeyboardBuilder()
        kb.button(text=t("btn_share_link", lang),
                  url=f"https://t.me/share/url?url={ref_link}&text={t('share_text', lang)}")
        kb.adjust(1)
        await message.answer(
            t("profile_text", lang, id=message.from_user.id, balance=user["balance"],
              lang_name=LANGUAGE_NAMES[lang], bonus=REFERRAL_BONUS, link=ref_link),
            reply_markup=kb.as_markup())

    elif key == "btn_buy":
        from handlers.payments import buy_menu_kb
        await message.answer(t("buy_menu_header", lang), reply_markup=buy_menu_kb(lang))


# ═══════════ ПОИСК ═══════════

@router.callback_query(F.data == "search")
async def start_search(call: CallbackQuery):
    user = await db.get_user(call.from_user.id)
    lang = resolve_lang(user)
    await call.message.answer(t("search_prompt", lang))
    await call.answer()


@router.message(StateFilter(None), F.text, ~F.text.startswith("/"))
async def process_query(message: Message):
    user_id = message.from_user.id
    text = message.text.strip()

    # Нижнее меню обрабатывается выше, сюда не доходит
    if text in all_menu_button_texts():
        return

    user = await db.get_user(user_id)
    if user is None:
        await db.create_user(user_id, message.from_user.username or "user")
        user = await db.get_user(user_id)
    lang = resolve_lang(user)

    # Похоже на ссылку, но мы не в режиме сдачи — подсказываем, а не ищем "t.me/..."
    if parse_chat_link(text.splitlines()[0]):
        await message.answer(t("link_hint", lang, btn=t("btn_submit", lang)))
        return

    if user["is_banned"]:
        await message.answer(t("banned", lang))
        return

    if len(text) < 2:
        await message.answer(t("query_too_short", lang))
        return

    if user["balance"] < SEARCH_PRICE:
        await message.answer(t("insufficient_balance", lang, price=SEARCH_PRICE, balance=user["balance"]))
        return

    results = await db.search_chats(text, MAX_RESULTS)
    if not results:
        await message.answer(t("no_results", lang, query=text))
        return

    await db.update_balance(user_id, -SEARCH_PRICE, reason=f"поиск: «{text}»")
    search_cache[user_id] = results
    page_state[user_id] = 0
    await db.log_search(user_id, text, len(results))

    # Реферальный бонус рефереру — платится ровно один раз, при первом реальном
    # (оплаченном) поиске приглашённого, а не при простой регистрации.
    referrer_id = await db.pay_referral_bonus_if_due(user_id, REFERRAL_BONUS)
    if referrer_id:
        try:
            referrer = await db.get_user(referrer_id)
            referrer_lang = resolve_lang(referrer)
            await message.bot.send_message(
                referrer_id, t("referral_first_search", referrer_lang, bonus=REFERRAL_BONUS))
        except Exception:
            pass

    updated = await db.get_user(user_id)
    await message.answer(t("search_charged", lang, price=SEARCH_PRICE, balance=updated["balance"]))
    await send_page(message, user_id, lang)


async def send_page(source, user_id: int, lang: str = None):
    target = source.message if isinstance(source, CallbackQuery) else source
    if lang is None:
        user = await db.get_user(user_id)
        lang = resolve_lang(user)

    results = search_cache.get(user_id, [])
    page = page_state.get(user_id, 0)
    per_page = 10
    total_pages = max(1, (len(results) + per_page - 1) // per_page)
    chunk = results[page * per_page:(page + 1) * per_page]

    kb = InlineKeyboardBuilder()
    for chat in chunk:
        kb.button(text=f"💬 {chat['title']}", callback_data=f"chat:{chat['username']}")
    kb.adjust(1)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data="page:prev"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data="page:next"))
    if nav:
        kb.row(*nav)
    kb.row(InlineKeyboardButton(text=t("btn_download_txt", lang), callback_data="txt"))
    kb.row(InlineKeyboardButton(text=t("btn_new_search", lang), callback_data="search"))

    await target.answer(t("results_list_header", lang), reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("page:"))
async def paginate(call: CallbackQuery):
    user_id = call.from_user.id
    direction = call.data.split(":")[1]
    page = page_state.get(user_id, 0)
    per_page = 10
    total_pages = max(1, (len(search_cache.get(user_id, [])) + per_page - 1) // per_page)

    if direction == "next" and page < total_pages - 1:
        page_state[user_id] = page + 1
    elif direction == "prev" and page > 0:
        page_state[user_id] = page - 1

    try:
        await call.message.delete()
    except Exception:
        pass
    await send_page(call, user_id)
    await call.answer()


def chat_link(chat) -> str:
    """Ссылка на чат: настоящий invite_link для приватных, t.me/username для публичных."""
    if chat["is_private"] and chat["invite_link"]:
        return chat["invite_link"]
    return f"https://t.me/{chat['username']}"


@router.callback_query(F.data.startswith("chat:"))
async def show_chat_card(call: CallbackQuery):
    user = await db.get_user(call.from_user.id)
    lang = resolve_lang(user)

    username = call.data.split(":", 1)[1]
    results = search_cache.get(call.from_user.id, [])
    chat = next((c for c in results if c["username"] == username), None)
    if chat:
        link = chat_link(chat)
        lock = "🔒 " if chat["is_private"] else ""
        members_line = t("members_count", lang, count=chat["member_count"]) if not chat["is_private"] else ""
        kb = InlineKeyboardBuilder()
        kb.button(text=t("btn_open_chat", lang), url=link)
        kb.button(text=t("btn_report", lang), callback_data=f"report:{username}")
        kb.adjust(1)
        await call.message.answer(
            f"{lock}<b>{chat['title']}</b>\n"
            f"{members_line}"
            f"🔗 {link}",
            reply_markup=kb.as_markup())
    await call.answer()


@router.callback_query(F.data == "noop")
async def noop(call: CallbackQuery):
    await call.answer()


@router.callback_query(F.data == "txt")
async def send_txt(call: CallbackQuery):
    user = await db.get_user(call.from_user.id)
    lang = resolve_lang(user)

    user_id = call.from_user.id
    results = search_cache.get(user_id, [])
    if not results:
        await call.answer(t("no_results_alert", lang), show_alert=True)
        return
    lines = [t("txt_export_header", lang), ""]
    for i, chat in enumerate(results, 1):
        lines.append(f"{i}. {chat['title']} — {chat_link(chat)}")
    path = f"results_{user_id}.txt"
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    await call.message.answer_document(FSInputFile(path), caption=t("txt_export_caption", lang))
    os.remove(path)
    await call.answer()


# ═══════════ СДАЧА ЧАТА ═══════════

def parse_links_from_text(raw: str) -> list[dict]:
    """Разбирает текст на уникальные ссылки (по одной на строку).
    Каждый элемент — dict от parse_chat_link: {"type": "public"/"private", ...}."""
    entries = []
    seen = set()
    for line in raw.splitlines():
        entry = parse_chat_link(line)
        if not entry:
            continue
        key = ("public", entry["username"]) if entry["type"] == "public" else ("private", entry["hash"])
        if key in seen:
            continue
        seen.add(key)
        entries.append(entry)
    return entries


def _entries_dedup_key(entry: dict):
    return ("public", entry["username"]) if entry["type"] == "public" else ("private", entry["hash"])


def parse_links_from_message(message: Message) -> list[dict]:
    """Как parse_links_from_text, но ДОПОЛНИТЕЛЬНО достаёт ссылки из скрытых
    гиперссылок (Telegram-форматирование вида "видимый текст" -> URL под
    капотом, entity type='text_link') — например, когда в сообщении видно
    название чата, а сама t.me-ссылка спрятана под этим текстом и не
    присутствует в message.text как обычная строка."""
    entries = parse_links_from_text(message.text or "")
    seen = {_entries_dedup_key(e) for e in entries}

    all_entities = list(message.entities or []) + list(message.caption_entities or [])
    for entity in all_entities:
        if entity.type != "text_link" or not entity.url:
            continue
        entry = parse_chat_link(entity.url)
        if not entry:
            continue
        key = _entries_dedup_key(entry)
        if key in seen:
            continue
        seen.add(key)
        entries.append(entry)

    return entries


async def _enqueue_submission(message: Message, state: FSMContext, entries: list[dict]):
    """Ставит список ссылок в очередь на фоновую проверку и сразу же освобождает
    пользователя — он может продолжать пользоваться ботом, пока проверка идёт в фоне.
    Результат придёт отдельным сообщением, когда всё будет готово."""
    user_id = message.from_user.id
    user = await db.get_user(user_id)
    lang = resolve_lang(user)

    if user and user["is_banned"]:
        await state.clear()
        await message.answer(t("banned", lang))
        return

    ok, reason = await db.check_submit_cooldown(user_id, SUBMIT_COOLDOWN_SEC)
    if not ok:
        await state.clear()
        await message.answer(reason)
        return

    if await db.has_active_submit_job(user_id):
        await state.clear()
        await message.answer(t("already_queued", lang))
        return

    job_id = await db.create_submit_job(user_id, entries)
    await submit_queue.enqueue_job(job_id)
    await state.clear()

    await message.answer(t("queued_confirmation", lang, count=len(entries)))


@router.callback_query(F.data == "submit")
async def start_submit(call: CallbackQuery, state: FSMContext):
    user = await db.get_user(call.from_user.id)
    lang = resolve_lang(user)

    private_reward = (t("submit_intro_private_reward", lang, amount=REWARD_PER_PRIVATE_CHAT)
                      if REWARD_PER_PRIVATE_CHAT else t("submit_intro_private_no_reward", lang))
    await call.message.answer(
        t("submit_intro", lang, min_members=MIN_MEMBERS, reward=REWARD_PER_CHAT,
          private_reward=private_reward))
    await state.set_state(SubmitStates.waiting_link)
    await call.answer()


@router.message(SubmitStates.waiting_link, Command("cancel"))
async def cancel_submit(message: Message, state: FSMContext):
    user = await db.get_user(message.from_user.id)
    lang = resolve_lang(user)
    await state.clear()
    await message.answer(t("submit_cancelled", lang), reply_markup=reply_menu_kb(lang))


@router.message(SubmitStates.waiting_link, F.document)
async def process_submit_txt(message: Message, state: FSMContext, bot: Bot):
    user = await db.get_user(message.from_user.id)
    lang = resolve_lang(user)

    doc = message.document
    if not (doc.file_name or "").lower().endswith(".txt"):
        await message.answer(t("file_wrong_type", lang))
        return
    if doc.file_size and doc.file_size > 2 * 1024 * 1024:
        await message.answer(t("file_too_large", lang))
        return

    try:
        file = await bot.get_file(doc.file_id)
        buf = await bot.download_file(file.file_path)
        raw = buf.read().decode("utf-8", errors="ignore")
    except Exception:
        await message.answer(t("file_read_error", lang))
        return

    entries = parse_links_from_text(raw)
    if not entries:
        await message.answer(t("no_links_in_file", lang))
        return

    await _enqueue_submission(message, state, entries)


@router.message(SubmitStates.waiting_link, F.text)
async def process_submit(message: Message, state: FSMContext, bot: Bot):
    user = await db.get_user(message.from_user.id)
    lang = resolve_lang(user)

    entries = parse_links_from_message(message)
    if not entries:
        await message.answer(t("invalid_link_format", lang))
        return

    await _enqueue_submission(message, state, entries)


# ═══════════ ЖАЛОБЫ ═══════════

@router.callback_query(F.data.startswith("report:"))
async def report_handler(call: CallbackQuery):
    user = await db.get_user(call.from_user.id)
    lang = resolve_lang(user)

    user_id = call.from_user.id
    chat_username = call.data.split(":", 1)[1]

    new_count = await db.add_report(user_id, chat_username)
    if new_count is None:
        await call.answer(t("already_reported", lang), show_alert=True)
        return

    if new_count >= REPORTS_TO_REMOVE:
        chat = await db.get_chat_by_username(chat_username)
        submitted_by = chat["submitted_by"] if chat else None
        await db.delete_chat_by_username(chat_username)
        if submitted_by:
            await db.update_balance(submitted_by, -REPORT_PENALTY,
                                    reason=f"штраф за жалобы на @{chat_username}")
        await call.answer(t("chat_removed_alert", lang, count=new_count), show_alert=True)
    else:
        await call.answer(
            t("report_accepted_alert", lang, count=new_count, max=REPORTS_TO_REMOVE), show_alert=True)


# ═══════════ ПРОФИЛЬ (inline-кнопка) ═══════════

@router.callback_query(F.data == "profile")
async def profile(call: CallbackQuery):
    user = await db.get_user(call.from_user.id)
    lang = resolve_lang(user)
    if not user:
        await call.answer(t("profile_not_found", lang), show_alert=True)
        return
    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{call.from_user.id}"
    kb = InlineKeyboardBuilder()
    kb.button(text=t("btn_share_link", lang),
              url=f"https://t.me/share/url?url={ref_link}&text={t('share_text', lang)}")
    kb.adjust(1)
    await call.message.answer(
        t("profile_text", lang, id=call.from_user.id, balance=user["balance"],
          lang_name=LANGUAGE_NAMES[lang], bonus=REFERRAL_BONUS, link=ref_link),
        reply_markup=kb.as_markup())
    await call.answer()
