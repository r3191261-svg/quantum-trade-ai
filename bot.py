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
    InlineKeyboardButton,
    FSInputFile,
)
from aiogram.exceptions import TelegramAPIError


# =========================================================
# QUANTUM TRADE AI — CONFIGURATION
# =========================================================

TOKEN_USER = os.getenv("TOKEN_USER", "").strip()
TOKEN_ADMIN = os.getenv("TOKEN_ADMIN", "").strip()

OWNER_ID = 770710937
DEFAULT_ADMIN_ID = 5232049751

# Numeric ID of the source Telegram channel SIGNALS PRO.
SOURCE_CHANNEL_ID = -1003979525371

DB_PATH = os.getenv("DB_PATH", "quantum.db")
INTRO_GIF_PATH = os.getenv("INTRO_GIF_PATH", "assets/quantum_trade_ai_intro.gif")
INTRO_GIF_FILE_ID = os.getenv("INTRO_GIF_FILE_ID", "").strip()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("QUANTUM_TRADE_AI")

user_dp = Dispatcher()
admin_dp = Dispatcher()


# =========================================================
# DATABASE
# =========================================================

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
        # Keeps source-channel post IDs to prevent duplicate broadcasts.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS source_posts (
                message_id INTEGER PRIMARY KEY,
                text TEXT DEFAULT '',
                created_at TEXT
            )
        """)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "signals_consent" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN signals_consent INTEGER DEFAULT -1")
        conn.execute(
            "INSERT OR IGNORE INTO admins (user_id) VALUES (?)",
            (DEFAULT_ADMIN_ID,),
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
            now(),
        ))
        conn.execute("""
            UPDATE users
            SET username=?, full_name=?
            WHERE user_id=?
        """, (
            user.username or "",
            user.full_name or "",
            user.id,
        ))


def get_user(user_id):
    with connect_db() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()


def get_status(user_id):
    user = get_user(user_id)
    return user[3] if user else "active"


def set_status(user_id, status):
    with connect_db() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO users (user_id, status, created_at)
            VALUES (?, ?, ?)
        """, (user_id, status, now()))
        conn.execute(
            "UPDATE users SET status=? WHERE user_id=?",
            (status, user_id),
        )


def is_admin(user_id):
    if user_id == OWNER_ID:
        return True
    with connect_db() as conn:
        result = conn.execute(
            "SELECT 1 FROM admins WHERE user_id=?",
            (user_id,),
        ).fetchone()
    return result is not None


def audit(actor, action, target=None):
    with connect_db() as conn:
        conn.execute("""
            INSERT INTO audit (actor_id, action, target_id, created_at)
            VALUES (?, ?, ?, ?)
        """, (actor, action, target, now()))


# =========================================================
# KEYBOARDS
# =========================================================

# New user menu. Old Forex and calendar handlers are retained below,
# but these two sections are no longer shown in the main keyboard.
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="⚡ БИНАРНЫЕ ОПЦИОНЫ")],
        [KeyboardButton(text="🌐 НОВОСТИ")],
        [
            KeyboardButton(text="📊 СТАТИСТИКА"),
            KeyboardButton(text="🕘 ИСТОРИЯ СИГНАЛОВ"),
        ],
        [KeyboardButton(text="🤖 АВТОМАТИЧЕСКИЙ БОТ")],
        [
            KeyboardButton(text="👤 МОЙ ПРОФИЛЬ"),
            KeyboardButton(text="⚙️ НАСТРОЙКИ"),
        ],
    ],
    resize_keyboard=True,
)


def colored_button(text, callback_data, style="primary"):
    return InlineKeyboardButton(text=text, callback_data=callback_data, style=style)


def settings_keyboard(enabled):
    notification_text = "🔔 Уведомления: ВКЛ" if enabled else "🔕 Уведомления: ВЫКЛ"
    return InlineKeyboardMarkup(inline_keyboard=[
        [colored_button(notification_text, "toggle_notifications", "primary")],
        [
            colored_button("🇷🇺 Русский", "lang_ru", "primary"),
            colored_button("🇬🇧 English", "lang_en", "primary"),
        ],
        [colored_button("👤 Мой профиль", "profile", "primary")],
    ])


def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [colored_button("📊 Статистика", "admin_stats", "primary")],
        [colored_button("👥 Пользователи", "admin_users", "primary")],
        [colored_button("📨 Управление сигналами", "admin_signals", "primary")],
        [colored_button("📢 Рассылка", "admin_broadcast", "primary")],
        [colored_button("🚫 Блокировки", "admin_blocks", "danger")],
        [colored_button("🛡 Администраторы", "admin_manage", "primary")],
        [colored_button("📋 Журнал действий", "admin_audit", "primary")],
        [colored_button("⚙️ Настройки бота", "admin_settings", "primary")],
    ])


# =========================================================
# ACCESS CHECKS
# =========================================================

async def check_user(message):
    if not message.from_user:
        return False

    register_user(message.from_user)

    if get_status(message.from_user.id) in ("blocked", "suspended"):
        await message.answer(
            "⛔ Доступ временно ограничен.\nОбратитесь в поддержку."
        )
        return False

    return True


async def check_admin(message):
    if not message.from_user:
        return False
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Нет прав администратора.")
        return False
    return True


async def check_owner(message):
    if not message.from_user:
        return False
    if message.from_user.id != OWNER_ID:
        await message.answer("⛔ Команда доступна только владельцу.")
        return False
    return True


# =========================================================
# USER START AND MAIN MENU
# =========================================================

async def show_main_menu(message):
    await message.answer(
        "💠 QUANTUM TRADE AI\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Добро пожаловать в интеллектуальную торговую платформу!\n\n"
        "⚡ Бинарные опционы\n"
        "🌐 Новости финансового рынка\n"
        "📊 Торговая статистика\n"
        "🕘 История сигналов\n"
        "🤖 Автоматическая торговля\n"
        "👤 Личный кабинет\n"
        "⚙️ Персональные настройки\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Выберите нужный раздел:",
        reply_markup=main_keyboard,
    )


@user_dp.message(Command("start"))
async def start_handler(message: Message):
    if not message.from_user:
        return
    register_user(message.from_user)
    if not await check_user(message):
        return

    try:
        if INTRO_GIF_FILE_ID:
            await message.answer_animation(
                INTRO_GIF_FILE_ID, caption="💠 <b>QUANTUM TRADE AI</b>"
            )
        elif os.path.isfile(INTRO_GIF_PATH):
            await message.answer_animation(
                FSInputFile(INTRO_GIF_PATH), caption="💠 <b>QUANTUM TRADE AI</b>"
            )
        else:
            log.warning("Intro GIF not found: %s", INTRO_GIF_PATH)
    except TelegramAPIError:
        log.exception("Could not send intro GIF")

    await message.answer(
        "⚡ <b>QUANTUM TRADE AI</b>\n\n"
        "<b>Добро пожаловать в интеллектуальную торговую платформу!</b>\n\n"
        "Хотите получать торговые сигналы?"
    )

    user = get_user(message.from_user.id)
    consent = user[7] if user and len(user) > 7 else -1
    if consent in (0, 1):
        status = "🟢 СИГНАЛЫ ВКЛЮЧЕНЫ" if consent == 1 else "🔴 СИГНАЛЫ ОТКЛЮЧЕНЫ"
        await message.answer(status, reply_markup=main_keyboard)
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [colored_button("✅ ПРИНЯТЬ", "signals_accept", "success")],
        [colored_button("❌ ОТКЛОНИТЬ", "signals_decline", "danger")],
    ])
    await message.answer(
        "🔔 <b>Выберите, хотите ли вы получать сигналы.</b>",
        reply_markup=keyboard,
    )


@user_dp.callback_query(F.data.in_({"signals_accept", "signals_decline"}))
async def signal_consent_handler(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    if not user or user[3] != "active":
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    accepted = callback.data == "signals_accept"
    enabled = 1 if accepted else 0
    with connect_db() as conn:
        conn.execute(
            "UPDATE users SET signals_consent=?, notifications=? WHERE user_id=?",
            (enabled, enabled, callback.from_user.id),
        )

    status = (
        "🟢 <b>СИГНАЛЫ ВКЛЮЧЕНЫ</b>\nВы будете получать новые сигналы."
        if accepted else
        "🔴 <b>СИГНАЛЫ ОТКЛЮЧЕНЫ</b>\nСигналы отправляться не будут."
    )
    await callback.message.edit_text(status)
    await callback.answer("Выбор сохранён")
    await callback.message.answer(
        "💠 <b>Главное меню QUANTUM TRADE AI</b>",
        reply_markup=main_keyboard,
    )


# =========================================================
# LEGACY FOREX HANDLER — KEPT, NOT SHOWN IN NEW MENU
# =========================================================

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
        "🟡 Источник реальных котировок пока не подключён."
    )


# =========================================================
# BINARY OPTIONS
# =========================================================

@user_dp.message(F.text.in_({
    "⚡ БИНАРНЫЕ ОПЦИОНЫ",
    "⚡ Бинарные опционы",
}))
async def options_handler(message: Message):
    if not await check_user(message):
        return

    await message.answer(
        "⚡ QUANTUM OPTIONS AI\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🎯 АНАЛИТИКА БИНАРНЫХ ОПЦИОНОВ\n\n"
        "📊 Анализ инструментов\n"
        "🔔 Торговые сигналы из SIGNALS PRO\n"
        "⏱ Таймфреймы M1 / M5 / M15\n"
        "📈 История сигналов\n"
        "📉 Статистика\n\n"
        "Новые публикации SIGNALS PRO будут автоматически "
        "поступать в этот бот."
    )


# =========================================================
# NEWS
# =========================================================

@user_dp.message(F.text.in_({"🌐 НОВОСТИ", "📰 Новости"}))
async def news_handler(message: Message):
    if not await check_user(message):
        return

    await message.answer(
        "🌐 QUANTUM MARKET NEWS\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "💵 Валютный рынок\n"
        "₿ Криптовалюты\n"
        "🏦 Центральные банки\n"
        "📈 Фондовые рынки\n"
        "🌍 Мировая экономика\n\n"
        "🟡 Новостной источник пока не подключён."
    )


# =========================================================
# LEGACY ECONOMIC CALENDAR — KEPT, NOT SHOWN IN NEW MENU
# =========================================================

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


# =========================================================
# STATISTICS
# =========================================================

@user_dp.message(F.text.in_({"📊 СТАТИСТИКА", "📈 Статистика"}))
async def statistics_handler(message: Message):
    if not await check_user(message):
        return

    with connect_db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM signals"
        ).fetchone()[0]
        source_total = conn.execute(
            "SELECT COUNT(*) FROM source_posts"
        ).fetchone()[0]

    await message.answer(
        "📊 QUANTUM PERFORMANCE\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"📨 Всего записей сигналов: {total}\n"
        f"📡 Публикаций из SIGNALS PRO: {source_total}\n\n"
        "Результаты WIN / LOSS не рассчитываются без "
        "достоверной фиксации исходов."
    )


# =========================================================
# SIGNAL HISTORY
# =========================================================

@user_dp.message(F.text.in_({
    "🕘 ИСТОРИЯ СИГНАЛОВ",
    "🕘 История сигналов",
}))
async def history_handler(message: Message):
    if not await check_user(message):
        return

    with connect_db() as conn:
        channel_rows = conn.execute("""
            SELECT message_id, text, created_at
            FROM source_posts
            ORDER BY message_id DESC
            LIMIT 10
        """).fetchall()

        manual_rows = conn.execute("""
            SELECT id, instrument, direction, timeframe, details, created_at
            FROM signals
            WHERE created_by != 0 OR created_by IS NULL
            ORDER BY id DESC
            LIMIT 10
        """).fetchall()

    if not channel_rows and not manual_rows:
        await message.answer("🕘 История сигналов пока пуста.")
        return

    text = "🕘 ИСТОРИЯ СИГНАЛОВ\n━━━━━━━━━━━━━━━━━━\n"

    for row in channel_rows:
        body = (row[1] or "[Публикация без текста]").strip()
        if len(body) > 500:
            body = body[:500] + "…"
        text += (
            f"\n📡 SIGNALS PRO | пост {row[0]}\n"
            f"{body}\n"
            "──────────────\n"
        )

    for row in manual_rows:
        text += (
            f"\n#{row[0]} | {row[1]}\n"
            f"Направление: {row[2]}\n"
            f"Таймфрейм: {row[3]}\n"
            f"Комментарий: {row[4]}\n"
            f"Время UTC: {row[5]}\n"
            "──────────────\n"
        )

    await message.answer(text[:4000])


# =========================================================
# AUTOMATIC BOT
# =========================================================

@user_dp.message(F.text.in_({
    "🤖 АВТОМАТИЧЕСКИЙ БОТ",
    "🤖 Автоматический бот",
}))
async def autotrade_handler(message: Message):
    if not await check_user(message):
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📝 Регистрация в Intrade Bar",
            url="https://go.intrade.bar/n4FmpAFBYfvE",
        )],
        [InlineKeyboardButton(
            text="📩 Поддержка брокера",
            url="https://t.me/copy_broker_BO_bot",
        )],
    ])

    await message.answer(
        "🤖 QUANTUM TRADE AI — АВТОМАТИЧЕСКИЙ БОТ\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Для подключения автоматического бота необходим "
        "аккаунт у брокера Intrade Bar.\n\n"
        "Если у вас ещё нет аккаунта — зарегистрируйтесь "
        "по кнопке ниже.\n\n"
        "Если аккаунт уже есть — напишите в поддержку брокера "
        "и уточните условия подключения к партнёрской программе.\n\n"
        "После этого обратитесь к администратору "
        "QUANTUM TRADE AI за инструкцией.",
        reply_markup=keyboard,
    )


# =========================================================
# PROFILE
# =========================================================

@user_dp.message(F.text.in_({"👤 МОЙ ПРОФИЛЬ", "👤 Мой профиль"}))
async def profile_handler(message: Message):
    if not await check_user(message):
        return

    user = get_user(message.from_user.id)
    username = "@" + user[1] if user[1] else "не указан"
    registration = (user[6] or "").replace("T", " ")[:16]

    status = {
        "active": "🟢 ACTIVE",
        "blocked": "🔴 BLOCKED",
        "suspended": "🟡 SUSPENDED",
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


# =========================================================
# SETTINGS
# =========================================================

@user_dp.message(F.text.in_({"⚙️ НАСТРОЙКИ", "⚙️ Настройки"}))
async def settings_handler(message: Message):
    if not await check_user(message):
        return

    user = get_user(message.from_user.id)
    await message.answer(
        "⚙️ QUANTUM SETTINGS\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Персональные настройки аккаунта:",
        reply_markup=settings_keyboard(bool(user[4])),
    )


@user_dp.callback_query(F.data == "toggle_notifications")
async def toggle_notifications(callback: CallbackQuery):
    user = get_user(callback.from_user.id)

    if not user or user[3] != "active":
        await callback.answer("Доступ ограничен.", show_alert=True)
        return

    enabled = not bool(user[4])

    with connect_db() as conn:
        conn.execute(
            "UPDATE users SET notifications=?, signals_consent=? WHERE user_id=?",
            (int(enabled), int(enabled), callback.from_user.id),
        )

    user = get_user(callback.from_user.id)
    await callback.message.edit_reply_markup(
        reply_markup=settings_keyboard(bool(user[4]))
    )
    await callback.answer(
        "Уведомления включены." if enabled else "Уведомления отключены."
    )


@user_dp.callback_query(F.data.in_(["lang_ru", "lang_en"]))
async def language_handler(callback: CallbackQuery):
    if not get_user(callback.from_user.id):
        await callback.answer("Сначала нажмите /start.", show_alert=True)
        return

    language = "ru" if callback.data == "lang_ru" else "en"

    with connect_db() as conn:
        conn.execute(
            "UPDATE users SET language=? WHERE user_id=?",
            (language, callback.from_user.id),
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


# =========================================================
# SIGNALS PRO CHANNEL AUTO-FORWARDING
# =========================================================

@user_dp.channel_post(F.chat.id == SOURCE_CHANNEL_ID)
async def signals_pro_channel_handler(message: Message, bot: Bot):
    """
    Copies each new channel post from SIGNALS PRO to active users
    who have started the user bot and enabled notifications.

    Original post formatting/media are retained by copy_message.
    """
    post_text = message.text or message.caption or ""

    # Atomic insert protects against duplicate processing of the same post.
    try:
        with connect_db() as conn:
            conn.execute("""
                INSERT INTO source_posts (message_id, text, created_at)
                VALUES (?, ?, ?)
            """, (message.message_id, post_text, now()))
            conn.execute("""
                INSERT INTO signals
                (instrument, direction, timeframe, details, created_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                "SIGNALS PRO",
                "CHANNEL POST",
                "-",
                post_text[:3000],
                now(),
                0,
            ))
    except sqlite3.IntegrityError:
        log.info(
            "SIGNALS PRO post %s was already processed; skipping.",
            message.message_id,
        )
        return
    except sqlite3.Error:
        log.exception("Could not save SIGNALS PRO post.")
        return

    with connect_db() as conn:
        recipients = conn.execute("""
            SELECT user_id
            FROM users
            WHERE status='active' AND notifications=1 AND signals_consent=1
        """).fetchall()

    sent = 0
    failed = 0

    for (user_id,) in recipients:
        try:
            await bot.copy_message(
                chat_id=user_id,
                from_chat_id=SOURCE_CHANNEL_ID,
                message_id=message.message_id,
            )
            sent += 1
            await asyncio.sleep(0.05)
        except TelegramAPIError as error:
            failed += 1
            log.warning(
                "Could not deliver channel post to user %s: %s",
                user_id,
                error,
            )

    log.info(
        "SIGNALS PRO post %s processed. Delivered=%s Failed=%s",
        message.message_id,
        sent,
        failed,
    )


# =========================================================
# ADMIN BOT — PANEL
# =========================================================

@admin_dp.message(Command("start", "panel"))
async def admin_start(message: Message):
    if not await check_admin(message):
        return

    await message.answer(
        "🛡 QUANTUM TRADE AI\n"
        "ПАНЕЛЬ УПРАВЛЕНИЯ\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Выберите нужный раздел:",
        reply_markup=admin_keyboard(),
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


# =========================================================
# ADMIN STATISTICS
# =========================================================

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
        channel_posts = conn.execute(
            "SELECT COUNT(*) FROM source_posts"
        ).fetchone()[0]

    await message.answer(
        "📊 СТАТИСТИКА ПЛАТФОРМЫ\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Всего пользователей: {total}\n"
        f"🟢 Активных: {active}\n"
        f"🔴 Заблокированных: {blocked}\n"
        f"📨 Записей сигналов: {signals}\n"
        f"📡 Публикаций SIGNALS PRO: {channel_posts}"
    )


# =========================================================
# ADMIN USERS
# =========================================================

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

    await message.answer(text[:4000])


# =========================================================
# ADMIN MANUAL SIGNAL PUBLISHING
# =========================================================

@admin_dp.message(Command("signal"))
async def publish_signal(message: Message, bot: Bot):
    if not await check_admin(message):
        return

    parts = (message.text or "").split(maxsplit=4)

    if len(parts) < 4:
        await message.answer(
            "Формат команды:\n\n"
            "/signal BTC/USDT BUY M5 комментарий\n\n"
            "Направление: BUY, SELL, CALL или PUT."
        )
        return

    instrument = parts[1].upper()
    direction = parts[2].upper()
    timeframe = parts[3].upper()
    details = parts[4] if len(parts) > 4 else "Без комментария"

    if direction not in ("BUY", "SELL", "CALL", "PUT"):
        await message.answer(
            "Направление должно быть BUY, SELL, CALL или PUT."
        )
        return

    with connect_db() as conn:
        cursor = conn.execute("""
            INSERT INTO signals
            (instrument, direction, timeframe, details, created_at, created_by)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            instrument,
            direction,
            timeframe,
            details,
            now(),
            message.from_user.id,
        ))
        signal_id = cursor.lastrowid

        recipients = conn.execute("""
            SELECT user_id
            FROM users
            WHERE status='active' AND notifications=1 AND signals_consent=1
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
        "⚠️ Информационный сигнал. Не является гарантией результата."
    )

    sent = 0
    failed = 0

    for (user_id,) in recipients:
        try:
            await bot.send_message(user_id, text)
            sent += 1
            await asyncio.sleep(0.05)
        except TelegramAPIError:
            failed += 1

    audit(message.from_user.id, "publish_signal", signal_id)

    await message.answer(
        f"✅ Сигнал №{signal_id} опубликован.\n\n"
        f"Доставлено: {sent}\n"
        f"Ошибок доставки: {failed}"
    )


# =========================================================
# ADMIN BROADCAST
# =========================================================

@admin_dp.message(Command("broadcast"))
async def broadcast(message: Message, bot: Bot):
    if not await check_admin(message):
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Формат:\n/broadcast Текст сообщения")
        return

    with connect_db() as conn:
        users = conn.execute("""
            SELECT user_id
            FROM users
            WHERE status='active' AND notifications=1 AND signals_consent=1
        """).fetchall()

    sent = 0
    failed = 0

    for (user_id,) in users:
        try:
            await bot.send_message(user_id, parts[1])
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


# =========================================================
# ADMIN USER STATUS MANAGEMENT
# =========================================================

async def change_status(message, status):
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
    audit(message.from_user.id, status, user_id)

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


# =========================================================
# ADMIN AUDIT LOG
# =========================================================

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
        await message.answer("Журнал действий пока пуст.")
        return

    text = "📋 ЖУРНАЛ ДЕЙСТВИЙ\n━━━━━━━━━━━━━━━━━━\n"
    for row in rows:
        text += (
            f"\nАдминистратор: {row[0]}\n"
            f"Действие: {row[1]}\n"
            f"Пользователь: {row[2]}\n"
            f"Дата: {row[3]}\n"
        )

    await message.answer(text[:4000])


# =========================================================
# OWNER ADMIN MANAGEMENT
# =========================================================

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
        await message.answer("Формат: /addadmin ID")
        return

    user_id = int(parts[1])

    with connect_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO admins (user_id) VALUES (?)",
            (user_id,),
        )

    audit(message.from_user.id, "add_admin", user_id)
    await message.answer(f"✅ Администратор {user_id} добавлен.")


@admin_dp.message(Command("removeadmin"))
async def remove_admin(message: Message):
    if not await check_owner(message):
        return

    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Формат: /removeadmin ID")
        return

    user_id = int(parts[1])

    if user_id in (OWNER_ID, DEFAULT_ADMIN_ID):
        await message.answer(
            "Нельзя удалить владельца или администратора по умолчанию."
        )
        return

    with connect_db() as conn:
        conn.execute(
            "DELETE FROM admins WHERE user_id=?",
            (user_id,),
        )

    audit(message.from_user.id, "remove_admin", user_id)
    await message.answer(f"✅ Права администратора {user_id} сняты.")


# =========================================================
# ADMIN PANEL BUTTON CALLBACKS
# =========================================================

@admin_dp.callback_query(F.data.startswith("admin_"))
async def admin_buttons(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(
            "Нет прав администратора.",
            show_alert=True,
        )
        return

    data = callback.data

    if data == "admin_stats":
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
            source_posts = conn.execute(
                "SELECT COUNT(*) FROM source_posts"
            ).fetchone()[0]

        await callback.message.answer(
            "📊 СТАТИСТИКА QUANTUM TRADE AI\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"👥 Пользователей: {total}\n"
            f"🟢 Активных: {active}\n"
            f"🔴 Заблокированных: {blocked}\n"
            f"📨 Записей сигналов: {signals}\n"
            f"📡 Публикаций SIGNALS PRO: {source_posts}"
        )

    elif data == "admin_users":
        await callback.message.answer(
            "👥 УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ\n\n"
            "Используйте команду /users."
        )

    elif data == "admin_signals":
        with connect_db() as conn:
            rows = conn.execute("""
                SELECT id, instrument, direction, timeframe, created_at
                FROM signals
                ORDER BY id DESC
                LIMIT 10
            """).fetchall()

        if not rows:
            await callback.message.answer("Сигналов пока нет.")
        else:
            text = "📨 ПОСЛЕДНИЕ СИГНАЛЫ\n━━━━━━━━━━━━━━━━━━\n"
            for row in rows:
                text += (
                    f"\n#{row[0]} {row[1]} {row[2]} {row[3]}\n"
                    f"{row[4]}\n"
                )
            text += (
                "\nДля ручной публикации:\n"
                "/signal BTC/USDT BUY M5 комментарий"
            )
            await callback.message.answer(text[:4000])

    elif data == "admin_broadcast":
        await callback.message.answer(
            "📢 РАССЫЛКА\n\n"
            "Формат:\n/broadcast Текст сообщения"
        )

    elif data == "admin_blocks":
        await callback.message.answer(
            "🚫 УПРАВЛЕНИЕ ДОСТУПОМ\n\n"
            "🔴 /ban ID — блокировка\n"
            "🟢 /unban ID — снять блокировку\n"
            "🔵 /suspend ID — приостановка\n"
            "🟢 /restore ID — восстановление"
        )

    elif data == "admin_manage":
        if callback.from_user.id != OWNER_ID:
            await callback.answer(
                "Управлять администраторами может только владелец.",
                show_alert=True,
            )
            return

        await callback.message.answer(
            "🛡 УПРАВЛЕНИЕ АДМИНИСТРАТОРАМИ\n\n"
            "/adminlist — список\n"
            "/addadmin ID — добавить\n"
            "/removeadmin ID — удалить"
        )

    elif data == "admin_audit":
        await callback.message.answer(
            "📋 ЖУРНАЛ ДЕЙСТВИЙ\n\nИспользуйте команду /audit."
        )

    elif data == "admin_settings":
        await callback.message.answer(
            "⚙️ НАСТРОЙКИ БОТА\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"📡 Канал SIGNALS PRO:\n{SOURCE_CHANNEL_ID}\n\n"
            "Бот получает новые публикации канала автоматически."
        )

    await callback.answer()


# =========================================================
# RUN BOTH BOTS
# =========================================================

async def main():
    init_db()

    if not TOKEN_USER:
        raise RuntimeError("Не задан GitHub Secret TOKEN_USER")

    if not TOKEN_ADMIN:
        raise RuntimeError("Не задан GitHub Secret TOKEN_ADMIN")

    user_bot = Bot(token=TOKEN_USER)
    admin_bot = Bot(token=TOKEN_ADMIN)

    try:
        user_info, admin_info = await asyncio.gather(
            user_bot.get_me(),
            admin_bot.get_me(),
        )

        log.info("Пользовательский бот: @%s", user_info.username)
        log.info("Административный бот: @%s", admin_info.username)
        log.info("Источник SIGNALS PRO: %s", SOURCE_CHANNEL_ID)

        # Verify that the USER bot is an administrator of the source channel.
        try:
            member = await user_bot.get_chat_member(
                SOURCE_CHANNEL_ID,
                user_info.id,
            )
            log.info("Статус пользовательского бота в канале: %s", member.status)
        except TelegramAPIError:
            log.exception(
                "Не удалось проверить доступ к SIGNALS PRO. "
                "Проверьте ID канала и права пользовательского бота."
            )

        await asyncio.gather(
            user_dp.start_polling(user_bot),
            admin_dp.start_polling(admin_bot),
        )

    finally:
        await user_bot.session.close()
        await admin_bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
