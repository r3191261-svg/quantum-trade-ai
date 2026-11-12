import asyncio
import logging
import os
import sqlite3

from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.exceptions import TelegramAPIError


# ==========================================
# QUANTUM TRADE AI
# ==========================================

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

user_dp = Dispatcher()
admin_dp = Dispatcher()


# ==========================================
# БАЗА ДАННЫХ
# ==========================================

def connect_db():
    return sqlite3.connect(DB_PATH, timeout=30)


def now():
    return datetime.now(timezone.utc).isoformat()


def init_db():
    with connect_db() as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT DEFAULT '',
                full_name TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                notifications INTEGER DEFAULT 1,
                language TEXT DEFAULT 'ru',
                created_at TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instrument TEXT,
                direction TEXT,
                timeframe TEXT,
                details TEXT,
                created_at TEXT,
                created_by INTEGER
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

        conn.execute(
            "INSERT OR IGNORE INTO admins VALUES (?)",
            (DEFAULT_ADMIN_ID,)
        )


def register_user(user):

    with connect_db() as conn:

        conn.execute("""
            INSERT OR IGNORE INTO users
            (user_id, username, full_name, status,
             notifications, language, created_at)
            VALUES (?, ?, ?, 'active', 1, 'ru', ?)
        """, (
            user.id,
            user.username or "",
            user.full_name or "",
            now()
        ))

        conn.execute("""
            UPDATE users
            SET username=?, full_name=?
            WHERE user_id=?
        """, (
            user.username or "",
            user.full_name or "",
            user.id
        ))


def get_user(user_id):

    with connect_db() as conn:

        return conn.execute(
            "SELECT * FROM users WHERE user_id=?",
            (user_id,)
        ).fetchone()


def get_status(user_id):

    user = get_user(user_id)

    return user[3] if user else "active"


def set_status(user_id, status):

    with connect_db() as conn:

        conn.execute("""
            INSERT OR IGNORE INTO users
            (user_id, status, created_at)
            VALUES (?, ?, ?)
        """, (user_id, status, now()))

        conn.execute(
            "UPDATE users SET status=? WHERE user_id=?",
            (status, user_id)
        )


def is_admin(user_id):

    if user_id == OWNER_ID:
        return True

    with connect_db() as conn:

        result = conn.execute(
            "SELECT 1 FROM admins WHERE user_id=?",
            (user_id,)
        ).fetchone()

    return result is not None


def audit(actor, action, target=None):

    with connect_db() as conn:

        conn.execute("""
            INSERT INTO audit
            (actor_id, action, target_id, created_at)
            VALUES (?, ?, ?, ?)
        """, (actor, action, target, now()))


# ==========================================
# КЛАВИАТУРА
# ==========================================

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
            KeyboardButton(text="🕘 История сигналов")
        ],
        [
            KeyboardButton(text="🤖 Автоматический бот"),
            KeyboardButton(text="👤 Мой профиль")
        ],
        [
            KeyboardButton(text="⚙️ Настройки")
        ]
    ],
    resize_keyboard=True
)


def settings_keyboard(enabled):

    notification_text = (
        "🔔 Уведомления: ВКЛ"
        if enabled else
        "🔕 Уведомления: ВЫКЛ"
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=notification_text,
                    callback_data="toggle_notifications"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🇷🇺 Русский",
                    callback_data="lang_ru"
                ),
                InlineKeyboardButton(
                    text="🇬🇧 English",
                    callback_data="lang_en"
                )
            ],
            [
                InlineKeyboardButton(
                    text="👤 Мой профиль",
                    callback_data="profile"
                )
            ]
        ]
    )


def admin_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 Статистика",
                    callback_data="admin_stats"
                ),
                InlineKeyboardButton(
                    text="👥 Пользователи",
                    callback_data="admin_users"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📨 Сигналы",
                    callback_data="admin_signals"
                ),
                InlineKeyboardButton(
                    text="📋 Журнал",
                    callback_data="admin_audit"
                )
            ],
            [
                InlineKeyboardButton(
                    text="ℹ️ Помощь",
                    callback_data="admin_help"
                )
            ]
        ]
    )


# ==========================================
# ПРОВЕРКА ДОСТУПА
# ==========================================

async def check_user(message):

    if not message.from_user:
        return False

    register_user(message.from_user)

    if get_status(message.from_user.id) in (
        "blocked",
        "suspended"
    ):

        await message.answer(
            "⛔ Доступ временно ограничен.\n"
            "Обратитесь в поддержку."
        )

        return False

    return True


async def check_admin(message):

    if not message.from_user:
        return False

    if not is_admin(message.from_user.id):

        await message.answer(
            "⛔ Нет прав администратора."
        )

        return False

    return True


async def check_owner(message):

    if not message.from_user:
        return False

    if message.from_user.id != OWNER_ID:

        await message.answer(
            "⛔ Команда доступна только владельцу."
        )

        return False

    return True


# ==========================================
# ГЛАВНОЕ ПРИВЕТСТВИЕ
# ==========================================

async def show_main_menu(message):

    await message.answer(
        "💠 QUANTUM TRADE AI\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Добро пожаловать в будущее "
        "интеллектуальной торговли!\n\n"
        "📊 FOREX — аналитика валютного рынка\n"
        "⚡ Бинарные опционы\n"
        "📰 Новости финансового рынка\n"
        "📅 Экономический календарь\n"
        "📈 Торговая статистика\n"
        "🕘 История сигналов\n"
        "🤖 Автоматическая торговля\n"
        "👤 Личный кабинет\n"
        "⚙️ Персональные настройки\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Выберите нужный раздел:",
        reply_markup=main_keyboard
    )


@user_dp.message(Command("start"))
async def start_handler(message: Message):

    register_user(message.from_user)

    if not await check_user(message):
        return

    loading = await message.answer(
        "💠 QUANTUM TRADE AI\n\n"
        "Инициализация системы ░░░░░░ 0%"
    )

    stages = [
        "Загрузка ядра системы ▓░░░░░ 20%",
        "Подключение модулей ▓▓▓░░░ 50%",
        "Проверка профиля ▓▓▓▓▓░ 80%",
        "Система готова ▓▓▓▓▓▓ 100%"
    ]

    for stage in stages:

        await asyncio.sleep(0.5)

        await loading.edit_text(
            "💠 QUANTUM TRADE AI\n\n" + stage
        )

    await show_main_menu(message)


# ==========================================
# FOREX
# ==========================================

@user_dp.message(F.text == "📊 FOREX")
async def forex_handler(message: Message):

    if not await check_user(message):
        return

    await message.answer(
        "📊 QUANTUM FOREX AI\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🌍 АНАЛИТИКА ВАЛЮТНОГО РЫНКА\n\n"
        "💱 Валютные пары\n"
        "📈 Анализ рынка\n"
        "🎯 Торговые сигналы\n"
        "📊 Статистика\n\n"
        "🟡 Источник реальных котировок "
        "пока не подключён."
    )


# ==========================================
# БИНАРНЫЕ ОПЦИОНЫ
# ==========================================

@user_dp.message(F.text == "⚡ Бинарные опционы")
async def options_handler(message: Message):

    if not await check_user(message):
        return

    await message.answer(
        "⚡ QUANTUM OPTIONS AI\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🎯 АНАЛИТИКА БИНАРНЫХ ОПЦИОНОВ\n\n"
        "📊 Анализ инструментов\n"
        "🔔 Торговые сигналы\n"
        "⏱ Таймфреймы M1 / M5 / M15\n"
        "📈 История сигналов\n"
        "📉 Статистика\n\n"
        "🟡 Источник сигналов пока не подключён."
    )


# ==========================================
# НОВОСТИ
# ==========================================

@user_dp.message(F.text == "📰 Новости")
async def news_handler(message: Message):

    if not await check_user(message):
        return

    await message.answer(
        "📰 QUANTUM MARKET NEWS\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "💵 Валютный рынок\n"
        "₿ Криптовалюты\n"
        "🏦 Центральные банки\n"
        "📈 Фондовые рынки\n"
        "🌍 Мировая экономика\n\n"
        "🟡 Новостной источник пока не подключён."
    )


# ==========================================
# ЭКОНОМИЧЕСКИЙ КАЛЕНДАРЬ
# ==========================================

@user_dp.message(F.text == "📅 Экономический календарь")
async def calendar_handler(message: Message):

    if not await check_user(message):
        return

    await message.answer(
        "📅 ECONOMIC CALENDAR\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🔴 Высокая важность\n"
        "🟡 Средняя важность\n"
        "🟢 Низкая важность\n\n"
        "В календаре будут отображаться:\n"
        "• Время события\n"
        "• Страна и валюта\n"
        "• Название события\n"
        "• Прогноз\n"
        "• Фактическое значение\n\n"
        "🟡 Источник календаря пока не подключён."
    )


# ==========================================
# СТАТИСТИКА
# ==========================================

@user_dp.message(F.text == "📈 Статистика")
async def statistics_handler(message: Message):

    if not await check_user(message):
        return

    with connect_db() as conn:

        total = conn.execute(
            "SELECT COUNT(*) FROM signals"
        ).fetchone()[0]

    await message.answer(
        "📈 QUANTUM PERFORMANCE\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"📨 Опубликовано сигналов: {total}\n\n"
        "Результаты WIN / LOSS и процент успешности "
        "будут рассчитываться после подключения "
        "учёта фактических исходов.\n\n"
        "⚠️ Непроверенные результаты не отображаются."
    )


# ==========================================
# ИСТОРИЯ СИГНАЛОВ
# ==========================================

@user_dp.message(F.text == "🕘 История сигналов")
async def history_handler(message: Message):

    if not await check_user(message):
        return

    with connect_db() as conn:

        rows = conn.execute("""
            SELECT id, instrument, direction,
                   timeframe, details, created_at
            FROM signals
            ORDER BY id DESC
            LIMIT 10
        """).fetchall()

    if not rows:

        await message.answer(
            "🕘 История сигналов пока пуста."
        )

        return

    text = "🕘 ИСТОРИЯ СИГНАЛОВ\n━━━━━━━━━━━━━━━━━━\n"

    for row in rows:

        text += (
            f"\n#{row[0]} | {row[1]}\n"
            f"Направление: {row[2]}\n"
            f"Таймфрейм: {row[3]}\n"
            f"Комментарий: {row[4]}\n"
            f"Время UTC: {row[5]}\n"
            "──────────────\n"
        )

    await message.answer(text)


# ==========================================
# АВТОМАТИЧЕСКИЙ БОТ
# ==========================================

@user_dp.message(F.text == "🤖 Автоматический бот")
async def autotrade_handler(message: Message):

    if not await check_user(message):
        return

    await message.answer(
        "🤖 QUANTUM TRADE AI — АВТОТРЕЙД\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Для подключения необходимо быть "
        "партнёром брокера Intrade Bar.\n\n"
        "🆔 Партнёрский ID: 14659\n\n"
        "Если у вас уже есть аккаунт, "
        "обратитесь в поддержку брокера и попросите "
        "перевести аккаунт под ID 14659.\n\n"
        "Если аккаунта нет, регистрация:\n"
        "https://go.intrade.bar/n4FmpAFBYfvE\n\n"
        "📩 Поддержка: support@intrade.bar"
    )


# ==========================================
# ЛИЧНЫЙ ПРОФИЛЬ
# ==========================================

@user_dp.message(F.text == "👤 Мой профиль")
async def profile_handler(message: Message):

    if not await check_user(message):
        return

    user = get_user(message.from_user.id)

    username = (
        "@" + user[1]
        if user[1]
        else "не указан"
    )

    registration = user[6].replace("T", " ")[:16]

    status = {
        "active": "🟢 ACTIVE",
        "blocked": "🔴 BLOCKED",
        "suspended": "🟡 SUSPENDED"
    }.get(user[3], user[3])

    await message.answer(
        "👤 ЛИЧНЫЙ КАБИНЕТ\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 ID: {user[0]}\n"
        f"👤 Имя: {user[2]}\n"
        f"🌐 Username: {username}\n"
        f"📅 Регистрация: {registration} UTC\n"
        f"🔐 Статус: {status}\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "💠 QUANTUM TRADE AI"
    )


# ==========================================
# НАСТРОЙКИ
# ==========================================

@user_dp.message(F.text == "⚙️ Настройки")
async def settings_handler(message: Message):

    if not await check_user(message):
        return

    user = get_user(message.from_user.id)

    await message.answer(
        "⚙️ QUANTUM SETTINGS\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Персональные настройки аккаунта:",
        reply_markup=settings_keyboard(bool(user[4]))
    )


@user_dp.callback_query(F.data == "toggle_notifications")
async def toggle_notifications(callback: CallbackQuery):

    if get_status(callback.from_user.id) != "active":
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    user = get_user(callback.from_user.id)

    enabled = not bool(user[4])

    with connect_db() as conn:

        conn.execute(
            "UPDATE users SET notifications=? WHERE user_id=?",
            (int(enabled), callback.from_user.id)
        )

    user = get_user(callback.from_user.id)

    await callback.message.edit_reply_markup(
        reply_markup=settings_keyboard(bool(user[4]))
    )

    await callback.answer(
        "Уведомления включены."
        if enabled else
        "Уведомления отключены."
    )


@user_dp.callback_query(F.data.in_(["lang_ru", "lang_en"]))
async def language_handler(callback: CallbackQuery):

    language = (
        "ru" if callback.data == "lang_ru"
        else "en"
    )

    with connect_db() as conn:

        conn.execute(
            "UPDATE users SET language=? WHERE user_id=?",
            (language, callback.from_user.id)
        )

    await callback.answer(
        "Выбран русский язык."
        if language == "ru"
        else "English selected. Full translation will be added separately."
    )


@user_dp.callback_query(F.data == "profile")
async def profile_callback(callback: CallbackQuery):

    user = get_user(callback.from_user.id)

    if not user:
        await callback.answer("Сначала нажмите /start.", show_alert=True)
        return

    username = "@" + user[1] if user[1] else "не указан"

    await callback.message.answer(
        "👤 МОЙ ПРОФИЛЬ\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 ID: {user[0]}\n"
        f"👤 Имя: {user[2]}\n"
        f"🌐 Username: {username}\n"
        f"🔐 Статус: {user[3]}\n"
        f"📅 Регистрация: {user[6]}"
    )

    await callback.answer()


# ==========================================
# АДМИНИСТРАТИВНЫЙ БОТ
# ==========================================

@admin_dp.message(Command("start", "panel"))
async def admin_start(message: Message):

    if not await check_admin(message):
        return

    await message.answer(
        "🛡 QUANTUM TRADE AI\n"
        "ПАНЕЛЬ УПРАВЛЕНИЯ\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Выберите нужный раздел:",
        reply_markup=admin_keyboard()
    )


@admin_dp.message(Command("help"))
async def admin_help(message: Message):

    if not await check_admin(message):
        return

    await message.answer(
        "🛡 КОМАНДЫ АДМИНИСТРАТОРА\n\n"
        "/panel — панель управления\n"
        "/stats — статистика\n"
        "/users — пользователи\n"
        "/signal — публикация сигнала\n"
        "/broadcast — рассылка\n"
        "/ban ID — блокировка\n"
        "/unban ID — разблокировка\n"
        "/suspend ID — приостановка\n"
        "/restore ID — восстановление\n"
        "/audit — журнал\n\n"
        "Команды владельца:\n"
        "/addadmin ID\n"
        "/removeadmin ID\n"
        "/adminlist"
    )


# ==========================================
# СТАТИСТИКА АДМИНИСТРАТОРА
# ==========================================

@admin_dp.message(Command("stats"))
async def admin_stats(message: Message):

    if not await check_admin(message):
        return

    with connect_db() as conn:

        total = conn.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        active = conn.execute(
            "SELECT COUNT(*) FROM users WHERE status='active'"
        ).fetchone()[0]

        blocked = conn.execute(
            "SELECT COUNT(*) FROM users WHERE status='blocked'"
        ).fetchone()[0]

        signals = conn.execute(
            "SELECT COUNT(*) FROM signals"
        ).fetchone()[0]

    await message.answer(
        "📊 СТАТИСТИКА ПЛАТФОРМЫ\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Всего пользователей: {total}\n"
        f"🟢 Активных: {active}\n"
        f"🔴 Заблокированных: {blocked}\n"
        f"📨 Сигналов: {signals}"
    )


# ==========================================
# ПОЛЬЗОВАТЕЛИ
# ==========================================

@admin_dp.message(Command("users"))
async def admin_users(message: Message):

    if not await check_admin(message):
        return

    with connect_db() as conn:

        rows = conn.execute("""
            SELECT user_id, username, full_name, status
            FROM users
            ORDER BY created_at DESC
            LIMIT 30
        """).fetchall()

    if not rows:

        await message.answer("Пользователей пока нет.")

        return

    text = "👥 ПОЛЬЗОВАТЕЛИ\n━━━━━━━━━━━━━━━━━━\n"

    for row in rows:

        text += (
            f"\nID: {row[0]}\n"
            f"Имя: {row[2]}\n"
            f"Username: @{row[1] or 'нет'}\n"
            f"Статус: {row[3]}\n"
        )

    await message.answer(text)


# ==========================================
# ПУБЛИКАЦИЯ СИГНАЛОВ
# ==========================================

@admin_dp.message(Command("signal"))
async def publish_signal(message: Message, bot: Bot):

    if not await check_admin(message):
        return

    parts = (message.text or "").split(maxsplit=4)

    if len(parts) < 4:

        await message.answer(
            "Формат команды:\n\n"
            "/signal BTC/USDT BUY M5 комментарий\n\n"
            "Направление: BUY или SELL."
        )

        return

    instrument = parts[1].upper()
    direction = parts[2].upper()
    timeframe = parts[3].upper()

    details = (
        parts[4]
        if len(parts) > 4
        else "Без комментария"
    )

    if direction not in ("BUY", "SELL", "CALL", "PUT"):

        await message.answer(
            "Направление должно быть BUY, SELL, CALL или PUT."
        )

        return

    with connect_db() as conn:

        cursor = conn.execute("""
            INSERT INTO signals
            (instrument, direction, timeframe, details,
             created_at, created_by)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            instrument,
            direction,
            timeframe,
            details,
            now(),
            message.from_user.id
        ))

        signal_id = cursor.lastrowid

        recipients = conn.execute("""
            SELECT user_id
            FROM users
            WHERE status='active' AND notifications=1
        """).fetchall()

    text = (
        "🔔 НОВЫЙ СИГНАЛ QUANTUM TRADE AI\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 Инструмент: {instrument}\n"
        f"🎯 Направление: {direction}\n"
        f"⏱ Таймфрейм: {timeframe}\n"
        f"📝 Комментарий: {details}\n"
        f"🆔 Сигнал №{signal_id}\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚠️ Информационный сигнал. "
        "Не является гарантией результата."
    )

    sent = 0
    failed = 0

    for recipient in recipients:

        try:

            await bot.send_message(
                recipient[0],
                text
            )

            sent += 1

            await asyncio.sleep(0.05)

        except TelegramAPIError:

            failed += 1

    audit(
        message.from_user.id,
        "publish_signal",
        signal_id
    )

    await message.answer(
        f"✅ Сигнал №{signal_id} опубликован.\n\n"
        f"Доставлено: {sent}\n"
        f"Ошибок доставки: {failed}"
    )


# ==========================================
# РАССЫЛКА
# ==========================================

@admin_dp.message(Command("broadcast"))
async def broadcast(message: Message, bot: Bot):

    if not await check_admin(message):
        return

    parts = (message.text or "").split(maxsplit=1)

    if len(parts) < 2:

        await message.answer(
            "Формат:\n/broadcast Текст сообщения"
        )

        return

    with connect_db() as conn:

        users = conn.execute("""
            SELECT user_id
            FROM users
            WHERE status='active' AND notifications=1
        """).fetchall()

    sent = 0
    failed = 0

    for user in users:

        try:

            await bot.send_message(
                user[0],
                parts[1]
            )

            sent += 1

            await asyncio.sleep(0.05)

        except TelegramAPIError:

            failed += 1

    audit(message.from_user.id, "broadcast")

    await message.answer(
        "📢 РАССЫЛКА ЗАВЕРШЕНА\n\n"
        f"Отправлено: {sent}\n"
        f"Ошибок: {failed}"
    )


# ==========================================
# БЛОКИРОВКА ПОЛЬЗОВАТЕЛЕЙ
# ==========================================

async def change_status(message, status):

    if not await check_admin(message):
        return

    parts = (message.text or "").split()

    if len(parts) != 2 or not parts[1].isdigit():

        await message.answer(
            "Укажите ID пользователя."
        )

        return

    user_id = int(parts[1])

    if user_id == OWNER_ID:

        await message.answer(
            "Нельзя изменять статус владельца."
        )

        return

    set_status(user_id, status)

    audit(
        message.from_user.id,
        status,
        user_id
    )

    await message.answer(
        f"✅ Статус пользователя {user_id}: {status}"
    )


@admin_dp.message(Command("ban"))
async def ban_user(message: Message):
    await change_status(message, "blocked")


@admin_dp.message(Command("unban"))
async def unban_user(message: Message):
    await change_status(message, "active")


@admin_dp.message(Command("suspend"))
async def suspend_user(message: Message):
    await change_status(message, "suspended")


@admin_dp.message(Command("restore"))
async def restore_user(message: Message):
    await change_status(message, "active")


# ==========================================
# ЖУРНАЛ
# ==========================================

@admin_dp.message(Command("audit"))
async def audit_handler(message: Message):

    if not await check_admin(message):
        return

    with connect_db() as conn:

        rows = conn.execute("""
            SELECT actor_id, action, target_id, created_at
            FROM audit
            ORDER BY id DESC
            LIMIT 20
        """).fetchall()

    if not rows:

        await message.answer(
            "Журнал действий пока пуст."
        )

        return

    text = "📋 ЖУРНАЛ ДЕЙСТВИЙ\n━━━━━━━━━━━━━━━━━━\n"

    for row in rows:

        text += (
            f"\nАдминистратор: {row[0]}\n"
            f"Действие: {row[1]}\n"
            f"Пользователь: {row[2]}\n"
            f"Дата: {row[3]}\n"
        )

    await message.answer(text)


# ==========================================
# УПРАВЛЕНИЕ АДМИНИСТРАТОРАМИ
# ==========================================

@admin_dp.message(Command("adminlist"))
async def admin_list(message: Message):

    if not await check_owner(message):
        return

    with connect_db() as conn:

        rows = conn.execute(
            "SELECT user_id FROM admins"
        ).fetchall()

    text = f"👑 Владелец: {OWNER_ID}\n\n"

    for row in rows:

        text += f"🛡 Администратор: {row[0]}\n"

    await message.answer(text)


@admin_dp.message(Command("addadmin"))
async def add_admin(message: Message):

    if not await check_owner(message):
        return

    parts = (message.text or "").split()

    if len(parts) != 2 or not parts[1].isdigit():

        await message.answer(
            "Формат: /addadmin ID"
        )

        return

    user_id = int(parts[1])

    with connect_db() as conn:

        conn.execute(
            "INSERT OR IGNORE INTO admins VALUES (?)",
            (user_id,)
        )

    audit(
        message.from_user.id,
        "add_admin",
        user_id
    )

    await message.answer(
        f"✅ Администратор {user_id} добавлен."
    )


@admin_dp.message(Command("removeadmin"))
async def remove_admin(message: Message):

    if not await check_owner(message):
        return

    parts = (message.text or "").split()

    if len(parts) != 2 or not parts[1].isdigit():

        await message.answer(
            "Формат: /removeadmin ID"
        )

        return

    user_id = int(parts[1])

    if user_id == OWNER_ID:

        await message.answer(
            "Нельзя удалить владельца."
        )

        return

    with connect_db() as conn:

        conn.execute(
            "DELETE FROM admins WHERE user_id=?",
            (user_id,)
        )

    audit(
        message.from_user.id,
        "remove_admin",
        user_id
    )

    await message.answer(
        f"✅ Права администратора {user_id} сняты."
    )


# ==========================================
# КНОПКИ АДМИН-ПАНЕЛИ
# ==========================================

@admin_dp.callback_query(F.data.startswith("admin_"))
async def admin_buttons(callback: CallbackQuery):

    if not is_admin(callback.from_user.id):

        await callback.answer(
            "Нет прав администратора.",
            show_alert=True
        )

        return

    if callback.data == "admin_stats":

        with connect_db() as conn:

            total = conn.execute(
                "SELECT COUNT(*) FROM users"
            ).fetchone()[0]

            signals = conn.execute(
                "SELECT COUNT(*) FROM signals"
            ).fetchone()[0]

        await callback.message.answer(
            f"📊 Пользователей: {total}\n"
            f"📨 Сигналов: {signals}"
        )

    elif callback.data == "admin_users":

        await callback.message.answer(
            "Для просмотра пользователей используйте /users"
        )

    elif callback.data == "admin_signals":

        with connect_db() as conn:

            rows = conn.execute("""
                SELECT id, instrument, direction, timeframe
                FROM signals
                ORDER BY id DESC
                LIMIT 10
            """).fetchall()

        if not rows:

            await callback.message.answer(
                "Сигналов пока нет."
            )

        else:

            text = "📨 ПОСЛЕДНИЕ СИГНАЛЫ\n"

            for row in rows:

                text += (
                    f"\n#{row[0]} "
                    f"{row[1]} "
                    f"{row[2]} "
                    f"{row[3]}"
                )

            await callback.message.answer(text)

    elif callback.data == "admin_audit":

        await callback.message.answer(
            "Для просмотра журнала используйте /audit"
        )

    elif callback.data == "admin_help":

        await callback.message.answer(
            "Используйте /help для списка команд."
        )

    await callback.answer()


# ==========================================
# ЗАПУСК ДВУХ БОТОВ
# ==========================================

async def main():

    init_db()

    if not TOKEN_USER:

        raise RuntimeError(
            "Не задан GitHub Secret TOKEN_USER"
        )

    if not TOKEN_ADMIN:

        raise RuntimeError(
            "Не задан GitHub Secret TOKEN_ADMIN"
        )

    user_bot = Bot(token=TOKEN_USER)

    admin_bot = Bot(token=TOKEN_ADMIN)

    try:

        user_info, admin_info = await asyncio.gather(
            user_bot.get_me(),
            admin_bot.get_me()
        )

        log.info(
            "Пользовательский бот: @%s",
            user_info.username
        )

        log.info(
            "Административный бот: @%s",
            admin_info.username
        )

        log.info(
            "QUANTUM TRADE AI успешно запущен."
        )

        await asyncio.gather(
            user_dp.start_polling(user_bot),
            admin_dp.start_polling(admin_bot)
        )

    finally:

        await user_bot.session.close()
        await admin_bot.session.close()


if __name__ == "__main__":

    asyncio.run(main())