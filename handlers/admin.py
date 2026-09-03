
import os
import asyncio
from aiogram import Router, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramAPIError

import database as db
from config import ADMIN_IDS
from services.chat_checker import extract_username
from services import subscription

router = Router()

PAGE_SIZE = 10
BROADCAST_DELAY_SEC = 0.05  # ~20 сообщений/сек — с запасом относительно лимитов Telegram


class AdminStates(StatesGroup):
    waiting_channel = State()
    waiting_broadcast = State()
    waiting_coinlog_query = State()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


@router.message(Command("admin"))
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        return
    await _render_admin_panel(message)


async def _render_admin_panel(target):
    """target — Message или CallbackQuery.message, у обоих есть .answer()."""
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Статистика", callback_data="adm_stats")
    kb.button(text="💬 Все чаты", callback_data="adm_chats:0")
    kb.button(text="🔒 Приватные чаты", callback_data="adm_private:0")
    kb.button(text="⛔ Забанить юзера", callback_data="adm_ban")
    kb.button(text="✅ Разбанить юзера", callback_data="adm_unban")
    kb.button(text="🩺 Проверить живость базы", callback_data="adm_healthcheck")
    kb.button(text="🌐 Определить языки чатов", callback_data="adm_langdetect")
    kb.button(text="📢 Обязательная подписка", callback_data="sub_menu")
    kb.button(text="📣 Рассылка", callback_data="adm_broadcast")
    kb.button(text="📤 Экспорт базы чатов", callback_data="adm_export")
    kb.button(text="💰 Логи монет", callback_data="adm_coinlog")
    kb.adjust(2, 2, 2, 1, 2, 1)
    await target.answer("🛠 <b>Админ-панель</b>", reply_markup=kb.as_markup())


@router.callback_query(F.data == "adm_stats")
async def adm_stats(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    users, chats, searches, balance, purchases = await db.get_stats()
    private_chats = await db.count_chats(private_only=True)
    pending_jobs = len(await db.get_pending_job_ids())
    pending_payments = len(await db.get_pending_payments())
    await call.message.answer(
        f"📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: {users}\n"
        f"💬 Чатов в базе: {chats} (из них приватных: {private_chats})\n"
        f"🔍 Поисков сделано: {searches}\n"
        f"🪙 Коинов у юзеров: {balance}\n"
        f"💎 Оплаченных покупок: {purchases}\n\n"
        f"⏳ Заявок на проверку в очереди: {pending_jobs}\n"
        f"💳 Неоплаченных счетов: {pending_payments}")
    await call.answer()


async def _render_chats_page(call: CallbackQuery, page: int, private_only: bool):
    total = await db.count_chats(private_only=private_only)
    if total == 0:
        label = "приватных " if private_only else ""
        await call.message.answer(f"База {label}чатов пуста.")
        await call.answer()
        return

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    chats = await db.all_chats(limit=PAGE_SIZE, offset=page * PAGE_SIZE, private_only=private_only)

    prefix = "adm_private" if private_only else "adm_chats"
    kb = InlineKeyboardBuilder()
    for c in chats:
        lock = "🔒 " if c["is_private"] else ""
        kb.button(text=f"🗑 {lock}{c['title']} ({c['reports_count']}⚠)",
                  callback_data=f"adm_del:{c['username']}")
    kb.adjust(1)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"{prefix}:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"{prefix}:{page+1}"))
    if nav:
        kb.row(*nav)

    title = "🔒 Приватные чаты" if private_only else "💬 Все чаты"
    text = f"{title} — всего {total} (нажмите для удаления):"
    try:
        await call.message.edit_text(text, reply_markup=kb.as_markup())
    except Exception:
        await call.message.answer(text, reply_markup=kb.as_markup())
    await call.answer()


@router.callback_query(F.data.startswith("adm_chats:"))
async def adm_chats(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    page = int(call.data.split(":")[1])
    await _render_chats_page(call, page, private_only=False)


@router.callback_query(F.data.startswith("adm_private:"))
async def adm_private(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    page = int(call.data.split(":")[1])
    await _render_chats_page(call, page, private_only=True)


@router.callback_query(F.data.startswith("adm_del:"))
async def adm_del(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    username = call.data.split(":", 1)[1]
    await db.delete_chat_by_username(username)
    await call.answer(f"🗑 Чат @{username} удалён.", show_alert=True)


@router.callback_query(F.data == "adm_healthcheck")
async def adm_healthcheck(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    await call.answer("🩺 Запускаю проверку в фоне…")
    await call.message.answer(
        "🩺 Проверка живости базы запущена — на большой базе это может занять "
        "время (идёт через общий лимит запросов вместе с обычной проверкой сдаваемых "
        "ссылок). Пришлю итог сюда, когда закончу.")

    from services import health_check
    checked, removed, updated = await health_check.run_health_check()
    await call.message.answer(
        f"✅ Проверка живости базы завершена.\n"
        f"Проверено: {checked}\nОбновлено (участники/название): {updated}\n"
        f"Удалено недоступных: {removed}")


@router.callback_query(F.data == "adm_langdetect")
async def adm_langdetect(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    await call.answer("🌐 Считаю языки…")

    chats = await db.get_chats_missing_language()
    if not chats:
        await call.message.answer(
            "🌐 У всех публичных чатов уже определён язык (или база пуста). "
            "Ничего делать не нужно.")
        return

    await call.message.answer(
        f"🌐 Определяю язык для {len(chats)} чатов — это только локальные "
        "вычисления, без обращений к Telegram, должно быть быстро.")

    from services.language_detect import detect_language
    detected, unknown = 0, 0
    for c in chats:
        language = detect_language(c["title"], c["description"])
        await db.set_chat_language(c["username"], language)
        if language:
            detected += 1
        else:
            unknown += 1

    await call.message.answer(
        f"✅ Готово.\n\n"
        f"🌐 Язык определён: {detected}\n"
        f"❓ Не удалось определить (слишком короткое/неоднозначное название): {unknown}")


@router.callback_query(F.data.in_({"adm_ban", "adm_unban"}))
async def adm_ban_prompt(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    action = "забанить" if call.data == "adm_ban" else "разбанить"
    await call.message.answer(f"Пришлите ID пользователя, чтобы {action}: (/ban 123456)")
    await call.answer()


@router.message(Command("ban"))
async def ban_cmd(message: Message):
    if not is_admin(message.from_user.id):
        return
    try:
        target = int(message.text.split()[1])
    except (IndexError, ValueError):
        await message.answer("Формат: /ban 123456789")
        return
    await db.set_banned(target, True)
    await message.answer(f"⛔ Юзер {target} забанен.")


@router.message(Command("unban"))
async def unban_cmd(message: Message):
    if not is_admin(message.from_user.id):
        return
    try:
        target = int(message.text.split()[1])
    except (IndexError, ValueError):
        await message.answer("Формат: /unban 123456789")
        return
    await db.set_banned(target, False)
    await message.answer(f"✅ Юзер {target} разбанен.")


# ═══════════ ОБЯЗАТЕЛЬНАЯ ПОДПИСКА ═══════════
# Если переключатель выключен ИЛИ каналов не задано — бот НЕ требует подписку,
# всё работает как обычно (см. middlewares/subscription.py).

async def _render_sub_menu(target):
    """target — Message или CallbackQuery.message, у обоих есть .answer()."""
    enabled = await db.is_force_subscribe_enabled()
    channels = await db.list_required_channels()

    status = "✅ ВКЛЮЧЕНА" if enabled else "❌ ВЫКЛЮЧЕНА"
    text = f"📢 <b>Обязательная подписка</b>\n\nСтатус: {status}\n"
    if channels:
        text += "\nКаналы:\n" + "\n".join(f"• {c['title']}" for c in channels)
    else:
        text += "\nКаналы пока не добавлены — даже при включении подписка не " \
                "будет запрашиваться, пока не добавите хотя бы один канал."

    kb = InlineKeyboardBuilder()
    kb.button(text="🔴 Выключить" if enabled else "🟢 Включить", callback_data="sub_toggle")
    kb.button(text="➕ Добавить канал", callback_data="sub_add")
    for c in channels:
        kb.button(text=f"🗑 {c['title']}", callback_data=f"sub_del:{c['id']}")
    kb.button(text="📊 Статистика подписки", callback_data="sub_stats")
    kb.button(text="⬅️ Назад", callback_data="adm_back")
    kb.adjust(1)

    await target.answer(text, reply_markup=kb.as_markup())


@router.callback_query(F.data == "sub_menu")
async def sub_menu(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    await _render_sub_menu(call.message)
    await call.answer()


@router.callback_query(F.data == "adm_back")
async def adm_back(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    await _render_admin_panel(call.message)
    await call.answer()


@router.callback_query(F.data == "sub_toggle")
async def sub_toggle(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    enabled = await db.is_force_subscribe_enabled()
    await db.set_force_subscribe(not enabled)
    subscription.clear_cache()
    channels = await db.list_required_channels()
    if not enabled and not channels:
        await call.answer(
            "⚠️ Включено, но каналов пока нет — подписка фактически не "
            "запрашивается, пока вы не добавите хотя бы один канал.",
            show_alert=True)
    else:
        await call.answer("✅ Готово")
    await _render_sub_menu(call.message)


@router.callback_query(F.data == "sub_add")
async def sub_add(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await call.message.answer(
        "📎 Пришлите @username канала (бот должен быть добавлен в канал "
        "администратором — иначе не сможет проверять подписчиков) либо "
        "перешлите сюда любой пост из этого канала.\n\n"
        "❌ Отмена: /cancel")
    await state.set_state(AdminStates.waiting_channel)
    await call.answer()


@router.message(AdminStates.waiting_channel, Command("cancel"))
async def sub_add_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Добавление канала отменено.")


@router.message(AdminStates.waiting_channel, F.forward_from_chat)
async def sub_add_forwarded(message: Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    chat = message.forward_from_chat
    await _try_add_channel(message, state, bot, chat_id=chat.id,
                           username=chat.username, title=chat.title)


@router.message(AdminStates.waiting_channel, F.text)
async def sub_add_username(message: Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id):
        return
    username = extract_username(message.text)
    if not username:
        await message.answer(
            "❌ Не похоже на @username канала. Пришлите вида @channelname, "
            "либо перешлите пост из канала. Отмена: /cancel")
        return

    try:
        chat = await bot.get_chat(f"@{username}")
    except TelegramAPIError as e:
        await message.answer(
            f"❌ Не удалось получить канал: {e}\n\n"
            "Убедитесь, что бот добавлен в канал администратором, и попробуйте снова.")
        return

    await _try_add_channel(message, state, bot, chat_id=chat.id,
                           username=chat.username, title=chat.title or username)


async def _try_add_channel(message: Message, state: FSMContext, bot: Bot,
                           chat_id: int, username: str | None, title: str):
    # Проверяем, что бот действительно может проверять подписчиков этого канала —
    # без этого требование подписки будет молча не работать для всех.
    try:
        await bot.get_chat_member(chat_id, bot.id)
    except TelegramAPIError as e:
        await message.answer(
            f"❌ Бот не может получить доступ к каналу «{title}»: {e}\n\n"
            "Добавьте бота в канал администратором и попробуйте снова.")
        return

    await db.add_required_channel(chat_id, username, title)
    subscription.clear_cache()
    await state.clear()
    await message.answer(f"✅ Канал «{title}» добавлен в список обязательной подписки.")
    await _render_sub_menu(message)


@router.callback_query(F.data.startswith("sub_del:"))
async def sub_del(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    channel_id = int(call.data.split(":")[1])
    channel = await db.get_required_channel(channel_id)
    await db.remove_required_channel(channel_id)
    subscription.clear_cache()
    name = channel["title"] if channel else str(channel_id)
    await call.answer(f"🗑 Канал «{name}» удалён из списка.", show_alert=True)
    await _render_sub_menu(call.message)


@router.callback_query(F.data == "sub_stats")
async def sub_stats(call: CallbackQuery, bot: Bot):
    if not is_admin(call.from_user.id):
        return
    channels = await db.list_required_channels()
    if not channels:
        await call.answer("Каналы не добавлены.", show_alert=True)
        return

    await call.answer()
    lines = ["📊 <b>Статистика по каналам</b>\n"]
    for c in channels:
        try:
            count = await bot.get_chat_member_count(c["chat_id"])
            lines.append(f"📢 {c['title']} — {count} участников")
        except TelegramAPIError:
            lines.append(f"📢 {c['title']} — не удалось получить число участников")
    text = "\n".join(lines)

    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Проверить всех пользователей бота", callback_data="sub_scan")
    kb.adjust(1)
    await call.message.answer(text, reply_markup=kb.as_markup())


@router.callback_query(F.data == "sub_scan")
async def sub_scan(call: CallbackQuery, bot: Bot):
    if not is_admin(call.from_user.id):
        return
    if not await db.is_force_subscribe_enabled():
        await call.answer("Подписка сейчас выключена — статистика по пользователям не считается.",
                          show_alert=True)
        return
    await call.answer("🔄 Запускаю проверку по всей базе пользователей…")
    await call.message.answer(
        "🔄 Проверяю подписку всех пользователей бота — на большой базе это "
        "может занять время. Пришлю итог сюда.")

    subscribed, not_subscribed, total = await subscription.scan_user_base(bot)
    if total == 0:
        await call.message.answer("В базе нет пользователей для проверки.")
        return
    pct = round(subscribed / total * 100) if total else 0
    await call.message.answer(
        f"✅ Проверка завершена.\n\n"
        f"👥 Всего пользователей: {total}\n"
        f"✅ Подписаны на всё: {subscribed} ({pct}%)\n"
        f"❌ Не подписаны: {not_subscribed}")


# ═══════════ РАССЫЛКА ═══════════
# Копирует ЛЮБОЕ сообщение админа (текст, фото, документ и т.д.) всем не
# забаненным пользователям бота, с задержкой между отправками, чтобы не
# упереться в лимиты Telegram на большой базе.

@router.callback_query(F.data == "adm_broadcast")
async def adm_broadcast_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await call.message.answer(
        "📣 Пришлите сообщение для рассылки (текст, фото, документ — что угодно, "
        "оно будет отправлено как есть всем пользователям).\n\n❌ Отмена: /cancel")
    await state.set_state(AdminStates.waiting_broadcast)
    await call.answer()


@router.message(AdminStates.waiting_broadcast, Command("cancel"))
async def adm_broadcast_input_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Рассылка отменена.")


@router.message(AdminStates.waiting_broadcast)
async def adm_broadcast_preview(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.update_data(broadcast_chat_id=message.chat.id,
                            broadcast_message_id=message.message_id)
    total = len(await db.get_all_user_ids())

    kb = InlineKeyboardBuilder()
    kb.button(text=f"✅ Разослать ({total} чел.)", callback_data="adm_broadcast_go")
    kb.button(text="❌ Отмена", callback_data="adm_broadcast_stop")
    kb.adjust(1)
    await message.answer(
        f"Выше — предпросмотр сообщения. Разослать его {total} пользователям?",
        reply_markup=kb.as_markup())
    # Состояние намеренно НЕ сбрасываем — на случай, если админ передумает и
    # решит прислать другое сообщение вместо подтверждения/отмены.


@router.callback_query(F.data == "adm_broadcast_stop")
async def adm_broadcast_stop(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.clear()
    await call.message.answer("❌ Рассылка отменена.")
    await call.answer()


@router.callback_query(F.data == "adm_broadcast_go")
async def adm_broadcast_go(call: CallbackQuery, state: FSMContext, bot: Bot):
    if not is_admin(call.from_user.id):
        return
    data = await state.get_data()
    await state.clear()
    from_chat_id = data.get("broadcast_chat_id")
    message_id = data.get("broadcast_message_id")
    if not from_chat_id or not message_id:
        await call.answer("❌ Сообщение для рассылки потеряно, начните заново.", show_alert=True)
        return

    await call.answer("📣 Рассылка запущена в фоне…")
    await call.message.answer(
        "📣 Рассылка запущена — на большой базе это может занять время. "
        "Пришлю итог сюда, когда закончу.")

    asyncio.create_task(_run_broadcast(bot, from_chat_id, message_id, call.from_user.id))


async def _run_broadcast(bot: Bot, from_chat_id: int, message_id: int, admin_id: int):
    user_ids = await db.get_all_user_ids()
    sent, failed = 0, 0
    for user_id in user_ids:
        try:
            await bot.copy_message(chat_id=user_id, from_chat_id=from_chat_id, message_id=message_id)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(BROADCAST_DELAY_SEC)

    try:
        await bot.send_message(
            admin_id,
            f"✅ Рассылка завершена.\n\nОтправлено: {sent}\nНе удалось (заблокировали бота и т.п.): {failed}")
    except Exception:
        pass


# ═══════════ ЭКСПОРТ БАЗЫ ЧАТОВ ═══════════

@router.callback_query(F.data == "adm_export")
async def adm_export(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    await call.answer("📤 Формирую файл…")

    chats = await db.get_all_chats_for_export()
    if not chats:
        await call.message.answer("База чатов пуста — экспортировать нечего.")
        return

    lines = []
    for c in chats:
        link = c["invite_link"] if c["is_private"] and c["invite_link"] else f"https://t.me/{c['username']}"
        lines.append(f"{c['title']} — {link}")

    path = f"admin_export_{call.from_user.id}.txt"
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    try:
        await call.message.answer_document(
            FSInputFile(path), caption=f"📤 Экспорт базы — {len(chats)} чатов")
    finally:
        os.remove(path)


# ═══════════ ЛОГИ МОНЕТ ═══════════

@router.callback_query(F.data == "adm_coinlog")
async def adm_coinlog_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await call.message.answer(
        "💰 Пришлите ID пользователя или его @username, чтобы посмотреть журнал "
        "начислений/списаний коинов.\n\n❌ Отмена: /cancel")
    await state.set_state(AdminStates.waiting_coinlog_query)
    await call.answer()


@router.message(AdminStates.waiting_coinlog_query, Command("cancel"))
async def adm_coinlog_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Отменено.")


@router.message(AdminStates.waiting_coinlog_query, F.text)
async def adm_coinlog_lookup(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    query = message.text.strip()

    user = None
    if query.lstrip("@").isdigit():
        user = await db.get_user(int(query.lstrip("@")))
    if user is None:
        user = await db.find_user_by_username(query)

    if user is None:
        await message.answer(
            "❌ Пользователь не найден. Пришлите числовой ID или @username "
            "(так, как он записан при регистрации). Отмена: /cancel")
        return

    await state.clear()
    entries = await db.get_balance_log(user["user_id"], limit=30)

    header = (f"💰 <b>Журнал коинов</b>\n"
             f"👤 @{user['username']} (id {user['user_id']})\n"
             f"💵 Текущий баланс: <b>{user['balance']} 🪙</b>\n")

    if not entries:
        await message.answer(header + "\nЗаписей пока нет.")
        return

    lines = [header, ""]
    for e in entries:
        sign = "+" if e["delta"] >= 0 else ""
        when = e["created_at"].split("T")[0] if e["created_at"] else "?"
        reason = e["reason"] or "без причины"
        lines.append(f"{when} · {sign}{e['delta']} 🪙 — {reason}")

    text = "\n".join(lines)
    if len(entries) == 30:
        text += "\n\n(показаны последние 30 записей)"
    await message.answer(text)
