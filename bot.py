# QUANTUM TRADE AI — user bot + admin bot (один файл, одна база)
import asyncio, html, logging, os, secrets, sqlite3, time
from datetime import datetime, timezone

import aiohttp
import feedparser
from aiogram import BaseMiddleware, Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton as IB, InlineKeyboardMarkup as IM, Message

logging.basicConfig(level=logging.INFO)
TOKEN_USER = os.environ["TOKEN_USER"]
TOKEN_ADMIN = os.environ["TOKEN_ADMIN"]
OWNER_ID = 770710937
ADMIN_ID = 5232049751
AUTOTRADE_ID = "14659"
BROKER_LINK = "https://go.intrade.bar/n4FmpAFBYfvE"
SUPPORT_URL = os.environ.get("SUPPORT_URL", f"tg://user?id={ADMIN_ID}")
WELCOME_PHOTO = os.environ.get("WELCOME_PHOTO", "")  # file_id или URL картинки (необязательно)

# ───────────────────────── БАЗА ─────────────────────────
os.makedirs("data", exist_ok=True)
db = sqlite3.connect("data/bot.db", check_same_thread=False)
db.row_factory = sqlite3.Row
db.executescript("""
create table if not exists users(id integer primary key, name text, username text,
 status text default 'active', role text default 'user', until integer default 0,
 news integer default 1, joined integer);
create table if not exists audit(id integer primary key autoincrement, ts integer, actor integer, target integer, action text, details text);
create table if not exists requests(id integer primary key autoincrement, uid integer, status text default 'pending', ts integer);
create table if not exists signals(id integer primary key autoincrement, ts integer, pair text, dir text, exp text, result text default '');
create table if not exists seen(link text primary key);
create table if not exists transfers(id integer primary key autoincrement, old integer, new integer, status text, ts integer);
""")

def now(): return int(time.time())
def q(sql, *a):
    c = db.execute(sql, a); db.commit(); return c
def one(sql, *a): return db.execute(sql, a).fetchone()
def rows(sql, *a): return db.execute(sql, a).fetchall()
def tfmt(ts): return datetime.fromtimestamp(ts, timezone.utc).strftime("%d.%m %H:%M")

q("insert or ignore into users(id,name,role,joined) values(?,?,?,?)", OWNER_ID, "-", "owner", now())
q("insert or ignore into users(id,name,role,joined) values(?,?,?,?)", ADMIN_ID, "-", "admin", now())

def register(u):
    q("insert or ignore into users(id,joined) values(?,?)", u.id, now())
    q("update users set name=?, username=? where id=?", u.full_name, u.username or "", u.id)

def get(uid):
    r = one("select * from users where id=?", uid)
    if r and r["status"] == "suspended" and r["until"] and r["until"] < now():
        q("update users set status='active', until=0 where id=?", uid)
        r = one("select * from users where id=?", uid)
    return r

def arole(uid):
    r = get(uid)
    return r["role"] if r and r["status"] == "active" else "user"

def log(actor, target, action, det=""):
    q("insert into audit(ts,actor,target,action,details) values(?,?,?,?,?)", now(), actor, target, action, det)

def fu(r):
    un = f"@{r['username']}" if r["username"] else ""
    return f"<code>{r['id']}</code> {html.escape(r['name'] or '-')} {un} [{r['status']}/{r['role']}]"

def btn(text, data=None, url=None, style=None):
    kw = {"text": text}
    if data: kw["callback_data"] = data
    if url: kw["url"] = url
    if style: kw["style"] = style  # цвет кнопки: success / primary / danger
    return IB(**kw)

def kb(r): return IM(inline_keyboard=r)

ub: Bot = None
ab: Bot = None
ur, ar = Router(), Router()

# ───────────────────────── КУРСЫ ─────────────────────────
CUR = ["EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "JPY", "RUB", "TRY", "CNY"]
PAIRS = [(a, b) for i, a in enumerate(CUR) for b in CUR[i + 1:]]
MAJORS = [("EUR","USD"),("GBP","USD"),("USD","JPY"),("USD","CHF"),("AUD","USD"),("USD","CAD"),
          ("NZD","USD"),("EUR","JPY"),("GBP","JPY"),("EUR","GBP")]
ORDER = MAJORS + [p for p in PAIRS if p not in MAJORS]
_rc = {"t": 0, "d": {}}

async def rates():
    if _rc["d"] and time.time() - _rc["t"] < 60: return _rc["d"]
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
            async with s.get("https://open.er-api.com/v6/latest/USD") as r:
                j = await r.json()
        _rc.update(t=time.time(), d=j["rates"])
    except Exception as e:
        logging.warning("rates: %s", e)
    return _rc["d"]

def fp(x): return f"{x:.3f}" if x >= 20 else f"{x:.5f}"
def tv(a, b): return f"https://www.tradingview.com/chart/?symbol=FX:{a}{b}"

# ───────────────────────── НОВОСТИ ─────────────────────────
FEEDS = [
    "https://ru.investing.com/rss/news.rss",
    "https://ru.investing.com/rss/news_1.rss",
    "https://ru.investing.com/rss/news_301.rss",
    "https://news.google.com/rss/search?q=форекс+OR+валюты+OR+нефть&hl=ru&gl=RU&ceid=RU:ru",
]

async def fetch_news():
    items, seen = [], set()
    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}, timeout=aiohttp.ClientTimeout(total=20)) as s:
        for u in FEEDS:
            try:
                async with s.get(u) as r: t = await r.text()
                f = await asyncio.to_thread(feedparser.parse, t)
                for e in f.entries[:12]:
                    if e.link not in seen:
                        seen.add(e.link)
                        items.append((e.get("published_parsed") or time.gmtime(0), e.title, e.link))
            except Exception as ex:
                logging.warning("feed %s: %s", u, ex)
    items.sort(key=lambda x: x[0], reverse=True)
    return items

async def bcast(text, only_news=False):
    n = 0
    sql = "select id from users where status='active'" + (" and news=1" if only_news else "")
    for r in rows(sql):
        try:
            await ub.send_message(r["id"], text); n += 1
        except Exception: pass
        await asyncio.sleep(0.05)
    return n

async def news_loop():
    first = not one("select 1 from seen limit 1")
    while True:
        try:
            items = await fetch_news()
            new = [i for i in items if not one("select 1 from seen where link=?", i[2])]
            for i in new: q("insert or ignore into seen values(?)", i[2])
            if not first:
                for _, title, link in new[:3]:
                    await bcast(f"🔴 <b>Новое:</b> {html.escape(title)}\n{link}", only_news=True)
            first = False
        except Exception as e:
            logging.warning("news_loop: %s", e)
        await asyncio.sleep(300)

# ───────────────────────── USER BOT ─────────────────────────
WELCOME = (
    "⚡ <b>QUANTUM TRADE AI</b>\n\n<b>Добро пожаловать в мир интеллектуальной торговли!</b>\n\n"
    "QUANTUM TRADE AI — современная аналитическая платформа, объединяющая искусственный интеллект, "
    "финансовые рынки и передовые технологии.\n\n🤖 <b>ЧТО ДОСТУПНО НА ПЛАТФОРМЕ:</b>\n\n"
    "📊 FOREX — анализ валютных рынков\n⚡ BINARY OPTIONS — торговые сигналы\n"
    "📰 NEWS — свежие финансовые новости 24/7\n📅 ECONOMIC CALENDAR — календарь событий\n"
    "📈 STATISTICS — статистика сигналов\n🤖 AUTO TRADE — автоматизированная торговля\n"
    "🔐 PERSONAL ACCOUNT — личный кабинет\n\n━━━━━━━━━━━━━━━━━━\n"
    "Выбери раздел в меню.\n\n<i>Интеллект. Технологии. Новые возможности.</i>"
)
RISK = "⚠️ <i>Торговля рискованна, сигналы не гарантируют прибыль. Торгуйте только теми средствами, потерю которых можете себе позволить.</i>"

def menu():
    return [
        [btn("📊 Форекс", "m:fx:0", style="success"), btn("⚡ Бинарные опционы", "m:bin", style="primary")],
        [btn("📰 Новости", "m:news"), btn("📈 Статистика", "m:stat")],
        [btn("🤖 Автоматический бот (Автотрейд)", "m:auto", style="primary")],
        [btn("📅 Календарь", "m:cal"), btn("📉 Графики", "m:chart")],
        [btn("⚙️ Настройки", "m:set"), btn("👤 Мой профиль", "m:prof")],
    ]
BACK = [btn("⬅️ Меню", "m:home")]

class UserGate(BaseMiddleware):
    async def __call__(self, h, ev, data):
        register(ev.from_user)
        if get(ev.from_user.id)["status"] != "active":
            t = "🚫 Доступ к аккаунту ограничен."
            if isinstance(ev, CallbackQuery): await ev.answer(t, show_alert=True)
            else: await ev.answer(t)
            return
        return await h(ev, data)

async def show(cb, text, r):
    try:
        await cb.message.edit_text(text, reply_markup=kb(r))
    except Exception as e:
        if "not modified" not in str(e):
            await cb.message.answer(text, reply_markup=kb(r))
    await cb.answer()

@ur.message(CommandStart())
async def u_start(m: Message):
    if WELCOME_PHOTO:
        try:
            await m.answer_photo(WELCOME_PHOTO, caption=WELCOME, reply_markup=kb(menu())); return
        except Exception as e: logging.warning("photo: %s", e)
    await m.answer(WELCOME, reply_markup=kb(menu()))

@ur.callback_query(lambda c: c.data == "m:home")
async def u_home(c: CallbackQuery):
    try: await c.message.delete()
    except Exception: pass
    await c.message.answer("⚡ <b>QUANTUM TRADE AI</b>\nВыберите раздел:", reply_markup=kb(menu())); await c.answer()

@ur.callback_query(lambda c: c.data.startswith("m:fx:"))
async def u_fx(c: CallbackQuery):
    p = int(c.data.split(":")[2]); per = 14
    r = await rates()
    if not r: return await c.answer("Курсы временно недоступны", show_alert=True)
    part = ORDER[p * per:(p + 1) * per]
    lines = [f"<code>{a}/{b}</code>  <b>{fp(r[b] / r[a])}</b>" for a, b in part if a in r and b in r]
    pages = (len(ORDER) + per - 1) // per
    nav = []
    if p > 0: nav.append(btn("◀️", f"m:fx:{p-1}"))
    nav.append(btn(f"{p+1}/{pages}", "m:noop"))
    if p < pages - 1: nav.append(btn("▶️", f"m:fx:{p+1}"))
    await show(c, f"📊 <b>Форекс — все валютные пары</b>\n\n" + "\n".join(lines) + "\n\n<i>Обновление раз в минуту</i>",
               [nav, [btn("💱 Курсы к рублю", "m:cash"), btn("📉 Графики", "m:chart")], BACK])

@ur.callback_query(lambda c: c.data == "m:noop")
async def u_noop(c: CallbackQuery): await c.answer()

@ur.callback_query(lambda c: c.data == "m:cash")
async def u_cash(c: CallbackQuery):
    r = await rates()
    if not r: return await c.answer("Курсы временно недоступны", show_alert=True)
    L = [f"{x}: <b>{r['RUB'] / r[x]:.2f} ₽</b>" for x in ["USD", "EUR", "GBP", "CHF", "JPY", "CNY", "TRY", "CAD", "AUD"]]
    await show(c, "💱 <b>Курсы валют к рублю</b>\n\n" + "\n".join(L), [[btn("📊 Все пары", "m:fx:0")], BACK])

@ur.callback_query(lambda c: c.data == "m:chart")
async def u_chart(c: CallbackQuery):
    r, row = [], []
    for a, b in MAJORS:
        row.append(btn(f"{a}/{b}", url=tv(a, b)))
        if len(row) == 2: r.append(row); row = []
    r.append([btn("📺 Investing.com — котировки", url="https://ru.investing.com/currencies/streaming-forex-rates-majors")])
    r.append(BACK)
    await show(c, "📉 <b>Живые графики</b> (TradingView)\nВыберите пару:", r)

@ur.callback_query(lambda c: c.data == "m:cal")
async def u_cal(c: CallbackQuery):
    await show(c, "📅 <b>Экономический календарь</b>\nВажные события, прогнозы и факты в реальном времени.",
               [[btn("📅 Investing.com", url="https://ru.investing.com/economic-calendar/")],
                [btn("📅 TradingView", url="https://ru.tradingview.com/economic-calendar/")], BACK])

@ur.callback_query(lambda c: c.data == "m:news")
async def u_news(c: CallbackQuery):
    items = await fetch_news()
    if not items: return await c.answer("Новости временно недоступны", show_alert=True)
    L = [f"• <a href=\"{l}\">{html.escape(t)}</a>" for _, t, l in items[:8]]
    await show(c, "📰 <b>Свежие новости</b>\n\n" + "\n\n".join(L), [[btn("🔄 Обновить", "m:news")], BACK])

@ur.callback_query(lambda c: c.data == "m:bin")
async def u_bin(c: CallbackQuery):
    s = rows("select * from signals order by id desc limit 5")
    L = []
    for x in s:
        res = {"win": "✅", "loss": "❌"}.get(x["result"], "⏳")
        L.append(f"{res} #{x['id']} <b>{x['pair']}</b> {'⬆️ ВВЕРХ' if x['dir']=='UP' else '⬇️ ВНИЗ'} · {x['exp']} · {tfmt(x['ts'])}")
    txt = "⚡ <b>Бинарные опционы — сигналы</b>\n\n" + ("\n".join(L) if L else "Пока нет сигналов. Новые придут автоматически.") + "\n\n" + RISK
    await show(c, txt, [[btn("📈 Статистика", "m:stat")], BACK])

def stat_text():
    t = one("select count(*) n, sum(result='win') w, sum(result='loss') l from signals")
    w, l = t["w"] or 0, t["l"] or 0
    wr = f"{w * 100 / (w + l):.1f}%" if w + l else "—"
    return f"📈 <b>Статистика сигналов</b>\n\nВсего: <b>{t['n']}</b>\n✅ Плюс: <b>{w}</b>\n❌ Минус: <b>{l}</b>\n🎯 Винрейт: <b>{wr}</b>"

@ur.callback_query(lambda c: c.data == "m:stat")
async def u_stat(c: CallbackQuery): await show(c, stat_text(), [BACK])

@ur.callback_query(lambda c: c.data == "m:auto")
async def u_auto(c: CallbackQuery):
    txt = (f"🤖 <b>АВТОМАТИЧЕСКИЙ БОТ (АВТОТРЕЙД)</b>\n\nЧтобы подключить автобота, нужно быть партнёром у брокера Intrade Bar.\n\n"
           f"1️⃣ Напишите в поддержку брокера Intrade Bar и попросите перевести вас под ID: <code>{AUTOTRADE_ID}</code>\n\n"
           f"2️⃣ Если нет регистрации — ссылка:\n{BROKER_LINK}\n\n3️⃣ Затем нажмите «Подать заявку».")
    await show(c, txt, [[btn("📨 Подать заявку", "m:req", style="success")], [btn("🎧 Написать в поддержку", url=SUPPORT_URL)], BACK])

@ur.callback_query(lambda c: c.data == "m:req")
async def u_req(c: CallbackQuery):
    uid = c.from_user.id
    if one("select 1 from requests where uid=? and status='pending'", uid):
        return await c.answer("Ваша заявка уже на рассмотрении ⏳", show_alert=True)
    rid = q("insert into requests(uid,ts) values(?,?)", uid, now()).lastrowid
    for r in rows("select id from users where role in ('admin','owner') and status='active'"):
        try:
            await ab.send_message(r["id"], f"📨 Новая заявка автотрейд #{rid}\n{fu(get(uid))}",
                                  reply_markup=kb([[btn("✅ Одобрить", f"r:ok:{rid}", style="success"), btn("❌ Отклонить", f"r:no:{rid}", style="danger")]]))
        except Exception: pass
    await c.answer("Заявка отправлена ✅", show_alert=True)

@ur.callback_query(lambda c: c.data == "m:set")
async def u_set(c: CallbackQuery):
    on = get(c.from_user.id)["news"]
    await show(c, "⚙️ <b>Настройки</b>", [[btn(f"🔔 Новости: {'ВКЛ' if on else 'ВЫКЛ'}", "m:tn")], BACK])

@ur.callback_query(lambda c: c.data == "m:tn")
async def u_tn(c: CallbackQuery):
    q("update users set news=1-news where id=?", c.from_user.id); await u_set(c)

@ur.callback_query(lambda c: c.data == "m:prof")
async def u_prof(c: CallbackQuery):
    r = get(c.from_user.id)
    lab = {"owner": "👑 Владелец", "admin": "🔐 Администратор", "user": "Пользователь"}[r["role"]]
    await show(c, f"👤 <b>Мой профиль</b>\n\nID: <code>{r['id']}</code>\nИмя: {html.escape(r['name'] or '-')}\nСтатус: {lab}\nС нами с: {tfmt(r['joined'])}", [BACK])

# ───────────────────────── ADMIN BOT ─────────────────────────
pend = {}

class AdminGate(BaseMiddleware):
    async def __call__(self, h, ev, data):
        uid = ev.from_user.id
        if isinstance(ev, CallbackQuery) and (ev.data or "").startswith("t:"): return await h(ev, data)
        if arole(uid) in ("admin", "owner"): return await h(ev, data)
        if isinstance(ev, CallbackQuery): await ev.answer("⛔ Нет доступа", show_alert=True)
        else: await ev.answer("⛔ Нет доступа.")

def is_owner(uid): return arole(uid) == "owner"

def can_act(actor, t):
    if actor == t: return False, "⛔ Нельзя применить к себе."
    r = one("select role from users where id=?", t)
    if r and r["role"] == "owner": return False, "⛔ Нельзя трогать владельца."
    if r and r["role"] == "admin" and not is_owner(actor): return False, "⛔ Только владелец управляет администраторами."
    return True, ""

def tid(c: CommandObject):
    try: return int(c.args.split()[0])
    except Exception: return None

async def confirm(m, act, args, text):
    tok = secrets.token_hex(4)
    pend[tok] = (act, args, m.from_user.id, time.time())
    await m.answer(f"⚠️ <b>Подтвердите действие</b>\n\n{text}",
                   reply_markup=kb([[btn("✅ Подтвердить", f"c:{tok}:y", style="success"), btn("❌ Отмена", f"c:{tok}:n", style="danger")]]))

async def execute(act, a, actor):
    if act in ("ban", "unban", "suspend", "restore"):
        t = a[0]; ok, msg = can_act(actor, t)
        if not ok: return msg
        if not get(t): return "❌ Пользователь не найден."
        if act == "ban": q("update users set status='banned', until=0 where id=?", t)
        elif act == "suspend": q("update users set status='suspended', until=? where id=?", now() + a[1] * 3600, t)
        else: q("update users set status='active', until=0 where id=?", t)
        log(actor, t, act, str(a[1:])); return f"✅ {act}: {t}"
    if act == "addadmin":
        if not is_owner(actor): return "⛔ Только владелец."
        t = a[0]
        if arole(t) == "owner": return "Это владелец."
        q("insert or ignore into users(id,joined) values(?,?)", t, now())
        q("update users set role='admin' where id=?", t); log(actor, t, "addadmin"); return f"✅ Администратор назначен: {t}"
    if act == "removeadmin":
        if not is_owner(actor): return "⛔ Только владелец."
        t = a[0]
        if one("select role from users where id=?", t)["role"] == "owner": return "⛔ Нельзя снять владельца."
        q("update users set role='user' where id=?", t); log(actor, t, "removeadmin"); return f"✅ Права сняты: {t}"
    if act == "broadcast":
        n = await bcast(a[0]); log(actor, 0, "broadcast", a[0][:100]); return f"📢 Отправлено: {n}"
    if act == "own1":
        tok = secrets.token_hex(4); pend[tok] = ("own2", a, actor, time.time())
        await ab.send_message(actor, f"🚨 <b>ВТОРОЕ подтверждение</b>\nПередать владение платформой <code>{a[0]}</code>?\nВы потеряете статус владельца.",
                              reply_markup=kb([[btn("✅ ДА, передать", f"c:{tok}:y", style="danger"), btn("❌ Отмена", f"c:{tok}:n")]]))
        return "Запрошено второе подтверждение."
    if act == "own2":
        if not is_owner(actor): return "⛔ Только владелец."
        new = a[0]
        tr = q("insert into transfers(old,new,status,ts) values(?,?,?,?)", actor, new, "pending", now()).lastrowid
        try:
            await ab.send_message(new, f"👑 Вам предлагают стать <b>владельцем</b> QUANTUM TRADE AI.\nОт: <code>{actor}</code>\nПринять?",
                                  reply_markup=kb([[btn("✅ Принять", f"t:acc:{tr}", style="success"), btn("❌ Отказаться", f"t:dec:{tr}", style="danger")]]))
        except Exception:
            q("update transfers set status='failed' where id=?", tr)
            return "❌ Новый владелец должен сначала нажать /start в админ-боте."
        log(actor, new, "ownertransfer_request"); return "📨 Запрос отправлен. Ждём принятия."
    return "?"

@ar.callback_query(lambda c: c.data.startswith("c:"))
async def a_confirm(c: CallbackQuery):
    _, tok, ans = c.data.split(":")
    p = pend.get(tok)
    if not p or p[2] != c.from_user.id or time.time() - p[3] > 300:
        return await c.answer("Запрос устарел", show_alert=True)
    pend.pop(tok)
    if ans == "n": await c.message.edit_text("❌ Отменено."); return await c.answer()
    res = await execute(p[0], p[1], p[2])
    await c.message.edit_text(res); await c.answer()

@ar.callback_query(lambda c: c.data.startswith("t:"))
async def a_transfer(c: CallbackQuery):
    _, ans, tr = c.data.split(":")
    r = one("select * from transfers where id=?", int(tr))
    if not r or r["status"] != "pending" or r["new"] != c.from_user.id:
        return await c.answer("Недействительно", show_alert=True)
    if ans == "dec":
        q("update transfers set status='declined' where id=?", r["id"]); log(r["new"], r["old"], "ownertransfer_declined")
        await c.message.edit_text("❌ Вы отказались."); await ab.send_message(r["old"], "❌ Передача владения отклонена."); return
    if not is_owner(r["old"]): return await c.answer("Отправитель уже не владелец", show_alert=True)
    q("insert or ignore into users(id,joined) values(?,?)", r["new"], now())
    q("update users set role='user' where id=?", r["old"])
    q("update users set role='owner', status='active', until=0 where id=?", r["new"])
    q("update transfers set status='done' where id=?", r["id"]); log(r["old"], r["new"], "ownertransfer_done")
    await c.message.edit_text("👑 Вы теперь ВЛАДЕЛЕЦ платформы.")
    try: await ab.send_message(r["old"], f"✅ Владение передано <code>{r['new']}</code>. Ваш статус: пользователь.")
    except Exception: pass
    await c.answer()

HELP = ("🔐 <b>Команды</b>\n/admin /users /user ID /ban ID /unban ID /suspend ID [часы] /restore ID\n"
        "/stats /signals /broadcast текст /requests /audit /admins /help\n"
        "/signal ПАРА UP|DOWN ЭКСП — выдать сигнал\n/result ID win|loss — результат\n\n"
        "👑 <b>Владелец</b>\n/addadmin ID /removeadmin ID /adminlist /ownertransfer ID /ownerinfo")

def panel(uid):
    r = [[btn("👥 Пользователи", "p:users", style="primary"), btn("📊 Статистика", "p:stats", style="primary")],
         [btn("📨 Заявки", "p:req", style="success"), btn("📋 Журнал", "p:audit")],
         [btn("👥 Админы", "p:admins"), btn("❓ Помощь", "p:help")]]
    return kb(r)

def users_text():
    L = [fu(r) for r in rows("select * from users order by joined desc limit 30")]
    return f"👥 <b>Пользователи</b> (последние 30)\n\n" + "\n".join(L)

def stats_text():
    t = one("select count(*) n, sum(status='active') a, sum(status='banned') b, sum(status='suspended') s from users")
    rq = one("select count(*) n from requests where status='pending'")["n"]
    return (f"📊 <b>Статистика платформы</b>\n\nПользователей: <b>{t['n']}</b>\nАктивных: {t['a']}\nЗаблокировано: {t['b']}\n"
            f"Приостановлено: {t['s']}\nЗаявок автотрейд в ожидании: {rq}\n\n" + stat_text())

def audit_text():
    L = [f"{tfmt(r['ts'])} · {r['actor']} → {r['target']} · <b>{r['action']}</b> {html.escape(r['details'] or '')}"
         for r in rows("select * from audit order by id desc limit 20")]
    return "📋 <b>Журнал действий</b>\n\n" + ("\n".join(L) or "Пусто")

def admins_text():
    return "👥 <b>Администраторы</b>\n\n" + "\n".join(fu(r) for r in rows("select * from users where role in ('owner','admin')"))

def req_data():
    rs = rows("select * from requests where status='pending' order by id limit 10")
    if not rs: return "📨 Заявок нет.", None
    btns = [[btn(f"✅ #{r['id']} · {r['uid']}", f"r:ok:{r['id']}", style="success"), btn(f"❌ #{r['id']}", f"r:no:{r['id']}", style="danger")] for r in rs]
    return "📨 <b>Заявки на автотрейд</b>", kb(btns)

@ar.message(CommandStart())
@ar.message(Command("admin"))
async def a_admin(m: Message):
    await m.answer("⚡ <b>QUANTUM TRADE AI — ADMIN PANEL</b>\nИнтеллект. Контроль. Технологии.", reply_markup=panel(m.from_user.id))

@ar.message(Command("help"))
async def a_help(m: Message): await m.answer(HELP)

@ar.callback_query(lambda c: c.data.startswith("p:"))
async def a_panel(c: CallbackQuery):
    k = c.data[2:]
    if k == "req":
        t, mk = req_data(); await c.message.answer(t, reply_markup=mk)
    else:
        t = {"users": users_text, "stats": stats_text, "audit": audit_text, "admins": admins_text}.get(k, lambda: HELP)()
        await c.message.answer(t)
    await c.answer()

@ar.message(Command("users"))
async def a_users(m: Message): await m.answer(users_text())
@ar.message(Command("stats"))
async def a_stats(m: Message): await m.answer(stats_text())
@ar.message(Command("signals"))
async def a_signals(m: Message): await m.answer(stat_text())
@ar.message(Command("audit"))
async def a_audit(m: Message): await m.answer(audit_text())
@ar.message(Command("admins"))
async def a_admins(m: Message): await m.answer(admins_text())

@ar.message(Command("user"))
async def a_user(m: Message, command: CommandObject):
    t = tid(command); r = get(t) if t else None
    if not r: return await m.answer("Использование: /user ID (не найден)")
    await m.answer(fu(r) + f"\nС: {tfmt(r['joined'])}" + (f"\nДо: {tfmt(r['until'])}" if r["until"] else ""))

def mk_cmd(name, label):
    @ar.message(Command(name))
    async def h(m: Message, command: CommandObject):
        t = tid(command)
        if not t: return await m.answer(f"Использование: /{name} ID")
        ok, msg = can_act(m.from_user.id, t)
        if not ok: return await m.answer(msg)
        hours = 24
        if name == "suspend":
            try: hours = int(command.args.split()[1])
            except Exception: pass
        args = (t, hours) if name == "suspend" else (t,)
        if name in ("ban", "suspend"): await confirm(m, name, args, f"{label} <code>{t}</code>" + (f" на {hours} ч." if name == "suspend" else ""))
        else: await m.answer(await execute(name, args, m.from_user.id))
for n, l in [("ban", "🔴 Заблокировать"), ("unban", "🟢 Разблокировать"), ("suspend", "🟡 Приостановить"), ("restore", "♻️ Восстановить")]:
    mk_cmd(n, l)

@ar.message(Command("broadcast"))
async def a_bc(m: Message, command: CommandObject):
    if not command.args: return await m.answer("Использование: /broadcast текст")
    await confirm(m, "broadcast", (command.args,), f"📢 Рассылка всем активным:\n\n{html.escape(command.args)}")

@ar.message(Command("requests"))
async def a_req(m: Message):
    t, mk = req_data(); await m.answer(t, reply_markup=mk)

@ar.callback_query(lambda c: c.data.startswith("r:"))
async def a_req_cb(c: CallbackQuery):
    _, ans, rid = c.data.split(":")
    r = one("select * from requests where id=?", int(rid))
    if not r or r["status"] != "pending": return await c.answer("Уже обработана", show_alert=True)
    st = "approved" if ans == "ok" else "rejected"
    q("update requests set status=? where id=?", st, r["id"]); log(c.from_user.id, r["uid"], "request_" + st, f"#{r['id']}")
    try:
        await ub.send_message(r["uid"], "✅ Ваша заявка на автотрейд одобрена!" if ans == "ok" else "❌ Ваша заявка на автотрейд отклонена.")
    except Exception: pass
    await c.message.edit_text(f"{'✅ Одобрена' if ans=='ok' else '❌ Отклонена'}: заявка #{r['id']}"); await c.answer()

@ar.message(Command("signal"))
async def a_signal(m: Message, command: CommandObject):
    try:
        pair, d, exp = command.args.split()[:3]; d = d.upper()
        assert d in ("UP", "DOWN")
    except Exception: return await m.answer("Использование: /signal EURUSD UP 5m")
    sid = q("insert into signals(ts,pair,dir,exp) values(?,?,?,?)", now(), pair.upper(), d, exp).lastrowid
    log(m.from_user.id, 0, "signal", f"#{sid}")
    n = await bcast(f"⚡ <b>Новый сигнал #{sid}</b>\n{pair.upper()} {'⬆️ ВВЕРХ' if d=='UP' else '⬇️ ВНИЗ'} · экспирация {exp}\n\n{RISK}")
    await m.answer(f"✅ Сигнал #{sid} разослан: {n}")

@ar.message(Command("result"))
async def a_result(m: Message, command: CommandObject):
    try:
        sid, res = command.args.split()[:2]; assert res in ("win", "loss")
        assert one("select 1 from signals where id=?", int(sid))
    except Exception: return await m.answer("Использование: /result ID win|loss")
    q("update signals set result=? where id=?", res, int(sid)); log(m.from_user.id, 0, "result", f"#{sid} {res}")
    await m.answer("✅ Записано")

@ar.message(Command("addadmin"))
async def a_addadmin(m: Message, command: CommandObject):
    if not is_owner(m.from_user.id): return await m.answer("⛔ Только владелец.")
    t = tid(command)
    if not t: return await m.answer("Использование: /addadmin ID")
    await confirm(m, "addadmin", (t,), f"➕ Назначить администратором <code>{t}</code>")

@ar.message(Command("removeadmin"))
async def a_rmadmin(m: Message, command: CommandObject):
    if not is_owner(m.from_user.id): return await m.answer("⛔ Только владелец.")
    t = tid(command)
    if not t: return await m.answer("Использование: /removeadmin ID")
    await confirm(m, "removeadmin", (t,), f"➖ Снять права администратора с <code>{t}</code>")

@ar.message(Command("adminlist"))
async def a_adminlist(m: Message):
    if not is_owner(m.from_user.id): return await m.answer("⛔ Только владелец.")
    await m.answer(admins_text())

@ar.message(Command("ownerinfo"))
async def a_ownerinfo(m: Message):
    r = one("select * from users where role='owner'"); await m.answer("👑 <b>Владелец</b>\n" + fu(r))

@ar.message(Command("ownertransfer"))
async def a_ownertransfer(m: Message, command: CommandObject):
    if not is_owner(m.from_user.id): return await m.answer("⛔ Только владелец.")
    t = tid(command)
    if not t or t == m.from_user.id: return await m.answer("Использование: /ownertransfer ID")
    if not get(t): return await m.answer("❌ Пользователь не найден в базе (он должен запустить бота).")
    await confirm(m, "own1", (t,), f"🚨 Передать ВСЕ права владельца <code>{t}</code>?\nВы станете обычным пользователем.")

# ───────────────────────── ЗАПУСК ─────────────────────────
async def main():
    global ub, ab
    props = DefaultBotProperties(parse_mode="HTML", link_preview_is_disabled=True)
    ub, ab = Bot(TOKEN_USER, default=props), Bot(TOKEN_ADMIN, default=props)
    ur.message.middleware(UserGate()); ur.callback_query.middleware(UserGate())
    ar.message.middleware(AdminGate()); ar.callback_query.middleware(AdminGate())
    udp, adp = Dispatcher(), Dispatcher()
    udp.include_router(ur); adp.include_router(ar)
    await asyncio.gather(udp.start_polling(ub), adp.start_polling(ab), news_loop())

if __name__ == "__main__":
    asyncio.run(main())
