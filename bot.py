# =====================================================
#          QUANTUM TRADE AI
#       MAIN BOT + ADMIN BOT
# =====================================================

import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

# =====================================================
# CONFIGURATION
# =====================================================

TOKEN_USER = os.getenv("TOKEN_USER", "").strip()
TOKEN_ADMIN = os.getenv("TOKEN_ADMIN", "").strip()

OWNER_ID = 770710937
ADMIN_ID = 5232049751

BROKER_ID = "14659"
BROKER_LINK = "https://go.intrade.bar/n4FmpAFBYfvE"
SUPPORT_EMAIL = "support@intrade.bar"

DB_PATH = "data/quantum.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# =====================================================
# DATABASE
# =====================================================

def database():
    os.makedirs("data", exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_database():
    with database() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                status TEXT DEFAULT 'active',
                joined TEXT
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                name TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        db.execute(
            "INSERT OR IGNORE INTO admins VALUES (?)",
            (ADMIN_ID,)
        )

        db.execute(
            "INSERT OR IGNORE INTO settings VALUES (?, ?)",
            ("owner_id", str(OWNER_ID))
        )


def owner_id():
    with database() as db:
        row = db.execute(
            "SELECT value FROM settings WHERE name='owner_id'"
        ).fetchone()
        return int(row[0])


def is_admin(user_id):
    if user_id == owner_id():
        return True

    with database() as db:
        row = db.execute(
            "SELECT user_id FROM admins WHERE user_id=?",
            (user_id,)
        ).fetchone()

    return row is not None


def save_user(user):
    with database() as db:
        db.execute("""
            INSERT OR IGNORE INTO users
            (user_id, username, first_name, joined)
            VALUES (?, ?, ?, ?)
        """, (
            user.id,
            user.username or "",
            user.first_name or "",
            datetime.now(timezone.utc).isoformat()
        ))


def user_status(user_id):
    with database() as db:
        row = db.execute(
            "SELECT status FROM users WHERE user_id=?",
            (user_id,)
        ).fetchone()

    return row[0] if row else "active"


def change_status(user_id, status):
    with database() as db:
        db.execute("""
            UPDATE users SET status=?
            WHERE user_id=?
        """, (status, user_id))


# =====================================================
# KEYBOARDS
# =====================================================

def main_keyboard():

    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="💱 Форекс"),
                KeyboardButton(text="📈 Бинарные опционы")
            ],
            [
                KeyboardButton(text="📰 Новости"),
                KeyboardButton(text="📊 Статистика")
            ],
            [
                KeyboardButton(text="🤖 Автоматический бот")
            ],
            [
                KeyboardButton(text="⚙️ Настройки"),
                KeyboardButton(text="👤 Мой профиль")
            ]
        ],
        resize_keyboard=True
    )


def admin_keyboard():

    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📊 Статистика пользователей")
            ],
            [
                KeyboardButton(text="🚫 Заблокировать"),
                KeyboardButton(text="🔓 Разблокировать")
            ],
            [
                KeyboardButton(text="⏸ Приостановить"),
                KeyboardButton(text="▶️ Восстановить")
            ],
            [
                KeyboardButton(text="👑 Управление администраторами")
            ],
            [
                KeyboardButton(text="🔙 Выход")
            ]
        ],
        resize_keyboard=True
    )


# =====================================================
# MAIN BOT
# =====================================================

user_bot = Bot(token=TOKEN_USER) if TOKEN_USER else None
user_dp = Dispatcher()


@user_dp.message(CommandStart())
async def start(message: Message):

    save_user(message.from_user)

    status = user_status(message.from_user.id)

    if status == "blocked":
        await message.answer(
            "🚫 Ваш аккаунт заблокирован."
        )
        return

    if status == "paused":
        await message.answer(
            "⏸ Ваш аккаунт временно приостановлен."
        )
        return

    text = (
        "⚡ <b>QUANTUM TRADE AI</b>\n\n"
        "👋 Добро пожаловать в будущее "
        "интеллектуальной торговли!\n\n"
        "🤖 Анализ рынка с помощью ИИ.\n"
        "📊 Отслеживание рыночных движений.\n"
        "⚡ Торговые сигналы и аналитика.\n"
        "📈 Мониторинг финансовых активов.\n"
        "🔐 Удобный личный кабинет.\n\n"
        "<b>Умные технологии. "
        "Новый взгляд на торговлю.</b>"
    )

    await message.answer(
        text,
        reply_markup=main_keyboard(),
        parse_mode="HTML"
    )


@user_dp.message(F.text == "💱 Форекс")
async def forex(message: Message):

    await message.answer(
        "💱 <b>QUANTUM TRADE AI — FOREX</b>\n\n"
        "Раздел валютного рынка.\n\n"
        "📊 Здесь будут размещаться "
        "аналитика и торговые сигналы.",
        parse_mode="HTML"
    )


@user_dp.message(F.text == "📈 Бинарные опционы")
async def binary(message: Message):

    await message.answer(
        "📈 <b>БИНАРНЫЕ ОПЦИОНЫ</b>\n\n"
        "⚡ Торговые сигналы.\n"
        "📊 Анализ валютных пар.\n"
        "₿ Анализ BTC/USDT.\n\n"
        "Информация о сигналах будет "
        "появляться в этом разделе.",
        parse_mode="HTML"
    )


@user_dp.message(F.text == "📰 Новости")
async def news(message: Message):

    await message.answer(
        "📰 <b>ФИНАНСОВЫЕ НОВОСТИ</b>\n\n"
        "Здесь будут публиковаться:\n\n"
        "💱 Новости Forex.\n"
        "₿ Новости криптовалют.\n"
        "📊 Фондовый рынок.\n"
        "🛢 Сырьевые товары.\n"
        "📅 Экономический календарь.\n\n"
        "Источник новостей будет подключён отдельно.",
        parse_mode="HTML"
    )


@user_dp.message(F.text == "📊 Статистика")
async def statistics(message: Message):

    with database() as db:
        total = db.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        active = db.execute(
            "SELECT COUNT(*) FROM users WHERE status='active'"
        ).fetchone()[0]

    await message.answer(
        "📊 <b>СТАТИСТИКА QUANTUM TRADE AI</b>\n\n"
        f"👥 Всего пользователей: {total}\n"
        f"🟢 Активных пользователей: {active}\n\n"
        "⚡ QUANTUM TRADE AI",
        parse_mode="HTML"
    )


@user_dp.message(F.text == "🤖 Автоматический бот")
async def autotrade(message: Message):

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📋 Скопировать ID брокера: 14659",
                    callback_data="broker_id"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📝 Регистрация у брокера",
                    url=BROKER_LINK
                )
            ],
            [
                InlineKeyboardButton(
                    text="📩 Поддержка брокера",
                    url="mailto:" + SUPPORT_EMAIL
                )
            ]
        ]
    )

    await message.answer(
        "🤖 <b>АВТОМАТИЧЕСКИЙ БОТ</b>\n\n"
        "Для подключения автоматической торговли "
        "необходимо быть нашим партнёром у брокера "
        "<b>Intrade Bar</b>.\n\n"
        "1️⃣ Напишите в поддержку брокера.\n\n"
        "Попросите перевести ваш аккаунт "
        "под партнёрский ID:\n\n"
        "<code>14659</code>\n\n"
        "2️⃣ Если у вас нет регистрации, "
        "воспользуйтесь ссылкой ниже.\n\n"
        "3️⃣ После перевода аккаунта обратитесь "
        "к администратору для подключения.\n\n"
        "⚠️ Автоматическая торговля связана "
        "с риском потери средств.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@user_dp.callback_query(F.data == "broker_id")
async def broker_id_callback(callback):

    await callback.answer(
        "Партнёрский ID: 14659",
        show_alert=True
    )


@user_dp.message(F.text == "👤 Мой профиль")
async def profile(message: Message):

    user = message.from_user

    status = user_status(user.id)

    await message.answer(
        "👤 <b>МОЙ ПРОФИЛЬ</b>\n\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"👤 Имя: {user.first_name}\n"
        f"📛 Username: @{user.username or 'не указан'}\n"
        f"🟢 Статус: {status}\n\n"
        "⚡ QUANTUM TRADE AI",
        parse_mode="HTML"
    )


@user_dp.message(F.text == "⚙️ Настройки")
async def settings(message: Message):

    await message.answer(
        "⚙️ <b>НАСТРОЙКИ</b>\n\n"
        "Управление уведомлениями и настройками "
        "будет доступно здесь.",
        parse_mode="HTML"
    )


# =====================================================
# ADMIN BOT
# =====================================================

admin_bot = Bot(token=TOKEN_ADMIN) if TOKEN_ADMIN else None
admin_dp = Dispatcher()


@admin_dp.message(CommandStart())
async def admin_start(message: Message):

    if not is_admin(message.from_user.id):
        await message.answer(
            "⛔ Доступ запрещён."
        )
        return

    await message.answer(
        "👑 <b>QUANTUM TRADE AI</b>\n"
        "АДМИНИСТРАТИВНАЯ ПАНЕЛЬ\n\n"
        "Добро пожаловать!",
        reply_markup=admin_keyboard(),
        parse_mode="HTML"
    )


@admin_dp.message(Command("id"))
async def get_id(message: Message):

    await message.answer(
        f"🆔 Ваш Telegram ID: {message.from_user.id}"
    )


@admin_dp.message(Command("stats"))
async def admin_stats(message: Message):

    if not is_admin(message.from_user.id):
        return

    with database() as db:
        total = db.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        active = db.execute(
            "SELECT COUNT(*) FROM users WHERE status='active'"
        ).fetchone()[0]

        blocked = db.execute(
            "SELECT COUNT(*) FROM users WHERE status='blocked'"
        ).fetchone()[0]

        paused = db.execute(
            "SELECT COUNT(*) FROM users WHERE status='paused'"
        ).fetchone()[0]

    await message.answer(
        "📊 <b>СТАТИСТИКА</b>\n\n"
        f"👥 Всего: {total}\n"
        f"🟢 Активных: {active}\n"
        f"🚫 Заблокированных: {blocked}\n"
        f"⏸ Приостановленных: {paused}",
        parse_mode="HTML"
    )


async def set_user_status(message, status):

    if not is_admin(message.from_user.id):
        return

    parts = (message.text or "").split()

    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer(
            "Использование: команда ID_пользователя"
        )
        return

    target_id = int(parts[1])

    if target_id == owner_id():
        await message.answer(
            "⛔ Нельзя менять статус владельца."
        )
        return

    with database() as db:
        exists = db.execute(
            "SELECT user_id FROM users WHERE user_id=?",
            (target_id,)
        ).fetchone()

    if not exists:
        await message.answer(
            "❌ Пользователь не найден в базе."
        )
        return

    change_status(target_id, status)

    await message.answer(
        f"✅ Статус пользователя {target_id}: {status}"
    )


@admin_dp.message(Command("block"))
async def block_user(message: Message):
    await set_user_status(message, "blocked")


@admin_dp.message(Command("unblock"))
async def unblock_user(message: Message):
    await set_user_status(message, "active")


@admin_dp.message(Command("pause"))
async def pause_user(message: Message):
    await set_user_status(message, "paused")


@admin_dp.message(Command("resume"))
async def resume_user(message: Message):
    await set_user_status(message, "active")


# =====================================================
# OWNER COMMANDS
# =====================================================

@admin_dp.message(Command("makeadmin"))
async def make_admin(message: Message):

    if message.from_user.id != owner_id():
        await message.answer("⛔ Только владелец может выдавать админку.")
        return

    parts = (message.text or "").split()

    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Использование: /makeadmin ID")
        return

    target = int(parts[1])

    with database() as db:
        db.execute(
            "INSERT OR IGNORE INTO admins VALUES (?)",
            (target,)
        )

    await message.answer(
        f"👑 Пользователь {target} получил права администратора."
    )


@admin_dp.message(Command("removeadmin"))
async def remove_admin(message: Message):

    if message.from_user.id != owner_id():
        await message.answer("⛔ Только владелец может снимать админку.")
        return

    parts = (message.text or "").split()

    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Использование: /removeadmin ID")
        return

    target = int(parts[1])

    if target == owner_id():
        await message.answer("Нельзя снять права владельца.")
        return

    with database() as db:
        db.execute(
            "DELETE FROM admins WHERE user_id=?",
            (target,)
        )

    await message.answer(
        f"✅ Права администратора сняты с {target}."
    )


@admin_dp.message(Command("transferowner"))
async def transfer_owner(message: Message):

    if message.from_user.id != owner_id():
        await message.answer("⛔ Только текущий владелец может передать права.")
        return

    parts = (message.text or "").split()

    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Использование: /transferowner ID")
        return

    target = int(parts[1])

    if target == owner_id():
        await message.answer("Этот пользователь уже владелец.")
        return

    with database() as db:
        db.execute(
            "UPDATE settings SET value=? WHERE name='owner_id'",
            (str(target),)
        )

    await message.answer(
        f"👑 Полные права владельца переданы пользователю {target}."
    )


# =====================================================
# ADMIN MENU
# =====================================================

@admin_dp.message(F.text == "📊 Статистика пользователей")
async def admin_menu_stats(message: Message):

    await admin_stats(message)


@admin_dp.message(F.text == "🚫 Заблокировать")
async def admin_menu_block(message: Message):

    await message.answer(
        "Для блокировки отправьте:\n/block ID"
    )


@admin_dp.message(F.text == "🔓 Разблокировать")
async def admin_menu_unblock(message: Message):

    await message.answer(
        "Для разблокировки отправьте:\n/unblock ID"
    )


@admin_dp.message(F.text == "⏸ Приостановить")
async def admin_menu_pause(message: Message):

    await message.answer(
        "Для приостановки отправьте:\n/pause ID"
    )


@admin_dp.message(F.text == "▶️ Восстановить")
async def admin_menu_resume(message: Message):

    await message.answer(
        "Для восстановления отправьте:\n/resume ID"
    )


@admin_dp.message(F.text == "👑 Управление администраторами")
async def admin_management(message: Message):

    if message.from_user.id != owner_id():
        await message.answer("⛔ Только владелец.")
        return

    await message.answer(
        "👑 <b>УПРАВЛЕНИЕ АДМИНИСТРАТОРАМИ</b>\n\n"
        "Выдать права:\n"
        "/makeadmin ID\n\n"
        "Снять права:\n"
        "/removeadmin ID\n\n"
        "Передать владение:\n"
        "/transferowner ID",
        parse_mode="HTML"
    )


@admin_dp.message(F.text == "🔙 Выход")
async def admin_exit(message: Message):

    await message.answer(
        "Вы вышли из административной панели."
    )


# =====================================================
# SECURITY MIDDLEWARE
# =====================================================

@user_dp.message()
async def check_user_status(message: Message):

    if message.from_user:
        status = user_status(message.from_user.id)

        if status == "blocked":
            await message.answer("🚫 Ваш аккаунт заблокирован.")
        elif status == "paused":
            await message.answer("⏸ Ваш аккаунт временно приостановлен.")


# =====================================================
# START
# =====================================================

async def main():

    if not TOKEN_USER:
        raise RuntimeError("GitHub Secret TOKEN_USER is missing.")

    if not TOKEN_ADMIN:
        raise RuntimeError("GitHub Secret TOKEN_ADMIN is missing.")

    init_database()

    log.info("Starting QUANTUM TRADE AI...")

    await asyncio.gather(
        user_dp.start_polling(user_bot),
        admin_dp.start_polling(admin_bot)
    )


if __name__ == "__main__":
    asyncio.run(main())