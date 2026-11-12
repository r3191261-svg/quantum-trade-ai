import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.exceptions import TelegramAPIError


# ==================================================
# НАСТРОЙКИ
# ==================================================

TOKEN_USER = os.getenv("TOKEN_USER", "").strip()
TOKEN_ADMIN = os.getenv("TOKEN_ADMIN", "").strip()

OWNER_ID = 770710937
DEFAULT_ADMIN_ID = 5232049751

DB_PATH = "quantum.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("QUANTUM_TRADE_AI")


# ==================================================
# БАЗА ДАННЫХ
# ==================================================

def db():
    return sqlite3.connect(DB_PATH)


def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                status TEXT DEFAULT 'active',
                created_at TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_id INTEGER,
                action TEXT,
                target_id INTEGER,
                created_at TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                request TEXT,
                status TEXT DEFAULT 'new',
                created_at TEXT
            )
        """)

        conn.execute(
            "INSERT OR IGNORE INTO admins (user_id) VALUES (?)",
            (DEFAULT_ADMIN_ID,)
        )


def register_user(user):
    with db() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO users
            (user_id, username, full_name, status, created_at)
            VALUES (?, ?, ?, 'active', ?)
        """, (
            user.id,
            user.username or "",
            user.full_name or "",
            datetime.now(timezone.utc).isoformat()
        ))

        conn.execute("""
            UPDATE users
            SET username = ?, full_name = ?
            WHERE user_id = ?
        """, (
            user.username or "",
            user.full_name or "",
            user.id
        ))


def get_status(user_id):
    with db() as conn:
        row = conn.execute(
            "SELECT status FROM users WHERE user_id = ?",
            (user_id,)
        ).fetchone()

    return row[0] if row else "active"


def set_status(user_id, status):
    with db() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO users
            (user_id, status, created_at)
            VALUES (?, ?, ?)
        """, (
            user_id,
            status,
            datetime.now(timezone.utc).isoformat()
        ))

        conn.execute(
            "UPDATE users SET status = ? WHERE user_id = ?",
            (status, user_id)
        )


def is_admin(user_id):
    if user_id == OWNER_ID:
        return True

    with db() as conn:
        row = conn.execute(
            "SELECT 1 FROM admins WHERE user_id = ?",
            (user_id,)
        ).fetchone()

    return row is not None


def add_audit(actor_id, action, target_id=None):
    with db() as conn:
        conn.execute("""
            INSERT INTO audit
            (actor_id, action, target_id, created_at)
            VALUES (?, ?, ?, ?)
        """, (
            actor_id,
            action,
            target_id,
            datetime.now(timezone.utc).isoformat()
        ))


# ==================================================
# КЛАВИАТУРА ПОЛЬЗОВАТЕЛЯ
# ==================================================

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="📊 FOREX"),
            KeyboardButton(text="⚡ Бинарные опционы")
        ],
        [
            KeyboardButton(text="📰 Новости"),
            KeyboardButton(text="📅 Экономический календарь")
        ],
        [
            KeyboardButton(text="📈 Статистика"),
            KeyboardButton(text="🤖 Автоматический бот")
        ],
        [
            KeyboardButton(text="👤 Мой профиль"),
            KeyboardButton(text="⚙️ Настройки")
        ]
    ],
    resize_keyboard=True
)


# ==================================================
# ПРОВЕРКА ДОСТУПА
# ==================================================

async def check_user(message: Message):
    if not message.from_user:
        return False

    user_id = message.from_user.id

    if get_status(user_id) in ("blocked", "suspended"):
        await message.answer(
            "⛔ Доступ к боту временно ограничен. "
            "Обратитесь в поддержку."
        )
        return False

    return True


async def check_admin(message: Message):
    if not message.from_user or not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав администратора.")
        return False

    return True


async def check_owner(message: Message):
    if not message.from_user or message.from_user.id != OWNER_ID:
        await message.answer("⛔ Эта команда доступна только владельцу.")
        return False

    return True


# ==================================================
# ПОЛЬЗОВАТЕЛЬСКИЙ БОТ
# ==================================================

user_dp = Dispatcher()


@user_dp.message(Command("start"))
async def start_handler(message: Message):
    register_user(message.from_user)

    if not await check_user(message):
        return

    await message.answer(
        "🤖 QUANTUM TRADE AI\n\n"
        "Добро пожаловать в будущее интеллектуальной торговли!\n\n"
        "Возможности платформы:\n\n"
        "📊 FOREX — торговая аналитика\n"
        "⚡ Бинарные опционы\n"
        "📰 Новости рынка\n"
        "📅 Экономический календарь\n"
        "📈 Статистика\n"
        "🤖 Автоматический бот\n"
        "👤 Личный профиль\n"
        "⚙️ Настройки\n\n"
        "Выберите нужный раздел в меню.",
        reply_markup=main_keyboard
    )


@user_dp.message(F.text)
async def menu_handler(message: Message):
    if not await check_user(message):
        return

    text = message.text

    if text == "📊 FOREX":
        await message.answer(
            "📊 FOREX\n\n"
            "Раздел аналитики валютного рынка.\n"
            "Подключение реальных котировок и сигналов "
            "требует настройки источника данных."
        )

    elif text == "⚡ Бинарные опционы":
        await message.answer(
            "⚡ БИНАРНЫЕ ОПЦИОНЫ\n\n"
            "Раздел аналитики бинарных опционов.\n"
            "Торговые сигналы появятся после подключения "
            "проверенного источника данных."
        )

    elif text == "📰 Новости":
        await message.answer(
            "📰 Новости рынка\n\n"
            "Раздел новостей будет работать после "
            "подключения новостного источника."
        )

    elif text == "📅 Экономический календарь":
        await message.answer(
            "📅 Экономический календарь\n\n"
            "Здесь будут отображаться важные экономические события."
        )

    elif text == "📈 Статистика":
        await message.answer(
            "📈 Статистика\n\n"
            "Статистика появится после подключения "
            "и сохранения реальных результатов."
        )

    elif text == "🤖 Автоматический бот":
        await message.answer(
            "🤖 QUANTUM TRADE AI — АВТОТРЕЙД\n\n"
            "Для подключения автоматического бота "
            "необходимо быть зарегистрированным партнёром "
            "брокера Intrade Bar.\n\n"
            "🆔 Партнёрский ID: 14659\n\n"
            "Если у вас уже есть аккаунт, напишите "
            "в поддержку брокера и попросите перевести "
            "ваш аккаунт под ID 14659.\n\n"
            "Если аккаунта ещё нет, зарегистрируйтесь "
            "по ссылке:\n"
            "https://go.intrade.bar/n4FmpAFBYfvE\n\n"
            "📩 Поддержка: support@intrade.bar\n\n"
            "После перевода аккаунта можно обратиться "
            "за подключением автотрейда."
        )

    elif text == "👤 Мой профиль":
        user = message.from_user

        await message.answer(
            "👤 МОЙ ПРОФИЛЬ\n\n"
            f"ID: {user.id}\n"
            f"Имя: {user.full_name}\n"
            f"Username: @{user.username or 'не указан'}\n"
            f"Статус: {get_status(user.id)}"
        )

    elif text == "⚙️ Настройки":
        await message.answer(
            "⚙️ Настройки\n\n"
            "Настройки профиля будут доступны здесь."
        )


# ==================================================
# АДМИНИСТРАТИВНЫЙ БОТ
# ==================================================

admin_dp = Dispatcher()


@admin_dp.message(Command("start"))
async def admin_start(message: Message):
    if not await check_admin(message):
        return

    await message.answer(
        "🛡 QUANTUM TRADE AI — ПАНЕЛЬ УПРАВЛЕНИЯ\n\n"
        "Доступные команды:\n\n"
        "/stats — статистика\n"
        "/users — список пользователей\n"
        "/user ID — информация о пользователе\n"
        "/ban ID — заблокировать\n"
        "/unban ID — разблокировать\n"
        "/suspend ID — приостановить\n"
        "/restore ID — восстановить\n"
        "/requests — заявки\n"
        "/audit — журнал действий\n"
        "/broadcast ТЕКСТ — рассылка\n"
        "/help — помощь"
    )


@admin_dp.message(Command("help"))
async def help_handler(message: Message):
    if not await check_admin(message):
        return

    await admin_start(message)


@admin_dp.message(Command("stats"))
async def stats_handler(message: Message):
    if not await check_admin(message):
        return

    with db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        active = conn.execute(
            "SELECT COUNT(*) FROM users WHERE status='active'"
        ).fetchone()[0]

        blocked = conn.execute(
            "SELECT COUNT(*) FROM users WHERE status='blocked'"
        ).fetchone()[0]

        suspended = conn.execute(
            "SELECT COUNT(*) FROM users WHERE status='suspended'"
        ).fetchone()[0]

    await message.answer(
        "📊 СТАТИСТИКА\n\n"
        f"Всего пользователей: {total}\n"
        f"Активных: {active}\n"
        f"Заблокированных: {blocked}\n"
        f"Приостановленных: {suspended}"
    )


@admin_dp.message(Command("users"))
async def users_handler(message: Message):
    if not await check_admin(message):
        return

    with db() as conn:
        rows = conn.execute("""
            SELECT user_id, username, status
            FROM users
            ORDER BY created_at DESC
            LIMIT 30
        """).fetchall()

    if not rows:
        await message.answer("Пользователей пока нет.")
        return

    result = "👥 ПОСЛЕДНИЕ ПОЛЬЗОВАТЕЛИ\n\n"

    for user_id, username, status in rows:
        result += (
            f"ID: {user_id}\n"
            f"Username: @{username or 'нет'}\n"
            f"Статус: {status}\n\n"
        )

    await message.answer(result)


@admin_dp.message(Command("user"))
async def user_info_handler(message: Message):
    if not await check_admin(message):
        return

    parts = (message.text or "").split()

    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Использование: /user ID")
        return

    user_id = int(parts[1])

    with db() as conn:
        row = conn.execute("""
            SELECT user_id, username, full_name, status, created_at
            FROM users WHERE user_id = ?
        """, (user_id,)).fetchone()

    if not row:
        await message.answer("Пользователь не найден.")
        return

    await message.answer(
        "👤 ИНФОРМАЦИЯ О ПОЛЬЗОВАТЕЛЕ\n\n"
        f"ID: {row[0]}\n"
        f"Username: @{row[1] or 'нет'}\n"
        f"Имя: {row[2] or 'нет'}\n"
        f"Статус: {row[3]}\n"
        f"Регистрация: {row[4] or 'неизвестно'}"
    )


async def change_user_status(message: Message, status: str):
    if not await check_admin(message):
        return

    parts = (message.text or "").split()

    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Укажите ID пользователя.")
        return

    user_id = int(parts[1])

    if user_id == OWNER_ID:
        await message.answer("Нельзя изменять статус владельца.")
        return

    set_status(user_id, status)
    add_audit(message.from_user.id, status, user_id)

    await message.answer(
        f"✅ Статус пользователя {user_id}: {status}"
    )


@admin_dp.message(Command("ban"))
async def ban_handler(message: Message):
    await change_user_status(message, "blocked")


@admin_dp.message(Command("unban"))
async def unban_handler(message: Message):
    await change_user_status(message, "active")


@admin_dp.message(Command("suspend"))
async def suspend_handler(message: Message):
    await change_user_status(message, "suspended")


@admin_dp.message(Command("restore"))
async def restore_handler(message: Message):
    await change_user_status(message, "active")


@admin_dp.message(Command("requests"))
async def requests_handler(message: Message):
    if not await check_admin(message):
        return

    with db() as conn:
        rows = conn.execute("""
            SELECT id, user_id, request, status
            FROM requests
            ORDER BY id DESC
            LIMIT 20
        """).fetchall()

    if not rows:
        await message.answer("Новых заявок пока нет.")
        return

    result = "📨 ЗАЯВКИ\n\n"

    for row in rows:
        result += (
            f"Заявка №{row[0]}\n"
            f"Пользователь: {row[1]}\n"
            f"Текст: {row[2]}\n"
            f"Статус: {row[3]}\n\n"
        )

    await message.answer(result)


@admin_dp.message(Command("audit"))
async def audit_handler(message: Message):
    if not await check_admin(message):
        return

    with db() as conn:
        rows = conn.execute("""
            SELECT actor_id, action, target_id, created_at
            FROM audit
            ORDER BY id DESC
            LIMIT 20
        """).fetchall()

    if not rows:
        await message.answer("Журнал пока пуст.")
        return

    result = "📋 ЖУРНАЛ ДЕЙСТВИЙ\n\n"

    for row in rows:
        result += (
            f"Администратор: {row[0]}\n"
            f"Действие: {row[1]}\n"
            f"Пользователь: {row[2]}\n"
            f"Дата: {row[3]}\n\n"
        )

    await message.answer(result)


@admin_dp.message(Command("broadcast"))
async def broadcast_handler(message: Message, bot: Bot):
    if not await check_admin(message):
        return

    parts = (message.text or "").split(maxsplit=1)

    if len(parts) < 2:
        await message.answer(
            "Использование:\n/broadcast Текст сообщения"
        )
        return

    text = parts[1]

    with db() as conn:
        rows = conn.execute(
            "SELECT user_id FROM users WHERE status='active'"
        ).fetchall()

    sent = 0
    failed = 0

    for row in rows:
        try:
            await bot.send_message(row[0], text)
            sent += 1
        except TelegramAPIError:
            failed += 1

        await asyncio.sleep(0.05)

    add_audit(message.from_user.id, "broadcast")

    await message.answer(
        "📢 РАССЫЛКА ЗАВЕРШЕНА\n\n"
        f"Отправлено: {sent}\n"
        f"Ошибок: {failed}"
    )


# ==================================================
# УПРАВЛЕНИЕ АДМИНИСТРАТОРАМИ
# ==================================================

@admin_dp.message(Command("adminlist"))
async def admin_list_handler(message: Message):
    if not await check_owner(message):
        return

    with db() as conn:
        rows = conn.execute(
            "SELECT user_id FROM admins"
        ).fetchall()

    result = "🛡 СПИСОК АДМИНИСТРАТОРОВ\n\n"
    result += f"Владелец: {OWNER_ID}\n"

    for row in rows:
        result += f"Администратор: {row[0]}\n"

    await message.answer(result)


@admin_dp.message(Command("addadmin"))
async def add_admin_handler(message: Message):
    if not await check_owner(message):
        return

    parts = (message.text or "").split()

    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Использование: /addadmin ID")
        return

    user_id = int(parts[1])

    with db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO admins (user_id) VALUES (?)",
            (user_id,)
        )

    add_audit(message.from_user.id, "add_admin", user_id)

    await message.answer(
        f"✅ Пользователь {user_id} назначен администратором."
    )


@admin_dp.message(Command("removeadmin"))
async def remove_admin_handler(message: Message):
    if not await check_owner(message):
        return

    parts = (message.text or "").split()

    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Использование: /removeadmin ID")
        return

    user_id = int(parts[1])

    if user_id == OWNER_ID:
        await message.answer("Нельзя удалить владельца.")
        return

    with db() as conn:
        conn.execute(
            "DELETE FROM admins WHERE user_id = ?",
            (user_id,)
        )

    add_audit(message.from_user.id, "remove_admin", user_id)

    await message.answer(
        f"✅ Права администратора у {user_id} сняты."
    )


# ==================================================
# ЗАПУСК
# ==================================================

async def main():
    init_db()

    if not TOKEN_USER:
        raise RuntimeError("Не задан GitHub Secret TOKEN_USER")

    if not TOKEN_ADMIN:
        raise RuntimeError("Не задан GitHub Secret TOKEN_ADMIN")

    user_bot = Bot(token=TOKEN_USER)
    admin_bot = Bot(token=TOKEN_ADMIN)

    log.info("QUANTUM TRADE AI запускается...")

    try:
        await asyncio.gather(
            user_dp.start_polling(user_bot),
            admin_dp.start_polling(admin_bot)
        )
    finally:
        await user_bot.session.close()
        await admin_bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())