"""Chorvador PRO — chorvachilikni boshqarish uchun Telegram bot (aiogram 3 + SQLite)."""
import asyncio
import logging
import os
import sqlite3
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F, Router, BaseMiddleware
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           KeyboardButton, Message, ReplyKeyboardMarkup)
from dotenv import load_dotenv

load_dotenv()
# ⬇⬇⬇ Tokenni shu yerga qo'ying (tirnoq ichiga). Bo'sh qoldirsangiz .env dagi BOT_TOKEN ishlatiladi.
BOT_TOKEN_HERE = "8989091973:AAG2UG6eurjHpqROt8bKX1umvUinO05tjdE"
TOKEN = (BOT_TOKEN_HERE or os.getenv("BOT_TOKEN", "")).strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)  # e'lonlarni tasdiqlovchi admin (ixtiyoriy)
DB_PATH = os.getenv("DB_PATH", "chorvador.db")
TZ = ZoneInfo("Asia/Tashkent")

MENU = ["🐄 Mening chorvam", "🌾 Yem-xashak hisobi", "💉 Veterinariya xizmati", "🥛 Sut hisobi",
        "💰 Daromad va xarajatlar", "🛒 Chorva bozori", "⏰ Eslatmalar", "📊 Hisobotlar",
        "⚙️ Sozlamalar", "❓ Yordam"]

router = Router()


# ---------------------------------------------------------------- yordamchilar
def today() -> date:
    return datetime.now(TZ).date()


def db(sql, args=(), fetch=None):
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        cur = con.execute(sql, args)
        res = cur.fetchone() if fetch == "one" else cur.fetchall() if fetch == "all" else cur.lastrowid
        con.commit()
        return res
    finally:
        con.close()


def init_db():
    con = sqlite3.connect(DB_PATH)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, username TEXT, region TEXT DEFAULT '',
        farm TEXT DEFAULT '', low_feed REAL DEFAULT 50, last_low TEXT DEFAULT '', last_milk TEXT DEFAULT '');
    CREATE TABLE IF NOT EXISTS animals(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, kind TEXT, sex TEXT,
        age TEXT, weight REAL, status TEXT DEFAULT 'faol', created TEXT, out_day TEXT);
    CREATE TABLE IF NOT EXISTS feed(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT,
        stock REAL DEFAULT 0, avg_price REAL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS feed_log(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT,
        amount REAL, day TEXT);
    CREATE TABLE IF NOT EXISTS milk(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, day TEXT,
        liters REAL, sold REAL, price REAL);
    CREATE TABLE IF NOT EXISTS vet(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, animal_id INTEGER,
        kind TEXT, day TEXT, cost REAL DEFAULT 0, done INTEGER DEFAULT 0, notified INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS finance(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, day TEXT,
        type TEXT, category TEXT, amount REAL, note TEXT);
    CREATE TABLE IF NOT EXISTS ads(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, category TEXT,
        title TEXT, details TEXT, price REAL, region TEXT, photo TEXT, contact TEXT,
        status TEXT DEFAULT 'faol', created TEXT);
    """)
    con.commit()
    con.close()


def fmt(n) -> str:
    return f"{float(n):,.0f}".replace(",", " ") + " so'm"


def num(text):
    try:
        v = float(text.replace(",", ".").replace(" ", ""))
        return v if v >= 0 else None
    except (ValueError, AttributeError):
        return None


def parse_date(text):
    t = (text or "").strip().lower()
    if t in ("bugun", "today"):
        return today()
    for f in ("%d.%m.%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(t, f).date()
        except ValueError:
            pass
    return None


def menu_kb():
    rows = [MENU[i:i + 2] for i in range(0, len(MENU), 2)]
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=t) for t in r] for r in rows], resize_keyboard=True)


def ik(buttons, per_row=2):
    rows = [[InlineKeyboardButton(text=t, callback_data=d) for t, d in buttons[i:i + per_row]]
            for i in range(0, len(buttons), per_row)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def add_finance(uid, day, typ, cat, amount, note=""):
    if amount and amount > 0:
        db("INSERT INTO finance(user_id,day,type,category,amount,note) VALUES(?,?,?,?,?,?)",
           (uid, str(day), typ, cat, amount, note))


CANCEL_HINT = "\n\n(Bekor qilish: /cancel yoki menyudan biror tugmani bosing)"


class S(StatesGroup):
    an_age = State(); an_weight = State(); an_sold = State()
    fd_name = State(); fd_qty = State(); fd_total = State(); fu_qty = State()
    vt_date = State(); vt_cost = State()
    mk_liters = State(); mk_sold = State(); mk_price = State()
    fn_amount = State(); fn_note = State()
    ad_title = State(); ad_details = State(); ad_price = State(); ad_region = State()
    ad_photo = State(); ad_contact = State()
    st_value = State()


class EnsureUser(BaseMiddleware):
    async def __call__(self, handler, event, data):
        u = getattr(event, "from_user", None)
        if u and not db("SELECT 1 FROM users WHERE id=?", (u.id,), "one"):
            db("INSERT INTO users(id,name,username) VALUES(?,?,?)", (u.id, u.full_name, u.username))
        return await handler(event, data)


router.message.outer_middleware(EnsureUser())
router.callback_query.outer_middleware(EnsureUser())


# ---------------------------------------------------------------- start / bekor qilish
@router.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Assalomu alaykum! 🐄 Chorvador PRO botiga xush kelibsiz.\n"
                   "Chorva, yem, sut, xarajat va veterinariya hisobini shu yerda yuriting.\n"
                   "Quyidagi menyudan tanlang 👇", reply_markup=menu_kb())


@router.message(Command("cancel"))
async def cancel(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Bekor qilindi.", reply_markup=menu_kb())


# ---------------------------------------------------------------- 1. Mening chorvam
@router.message(F.text == MENU[0])
async def m_animals(m: Message, state: FSMContext):
    await state.clear()
    rows = db("SELECT kind,COUNT(*) c FROM animals WHERE user_id=? AND status='faol' GROUP BY kind",
              (m.from_user.id,), "all")
    txt = "🐄 Mening chorvam\n" + ("\n".join(f"• {r['kind']}: {r['c']} bosh" for r in rows)
                                  if rows else "Hali hayvon qo'shilmagan.")
    await m.answer(txt, reply_markup=ik([("➕ Hayvon qo'shish", "an:add"), ("📋 Ro'yxat", "an:list")]))


@router.callback_query(F.data == "an:add")
async def an_add(cb: CallbackQuery):
    await cb.answer()
    await cb.message.answer("Hayvon turini tanlang:", reply_markup=ik(
        [(k, f"ak:{k}") for k in ("Sigir", "Buqa", "Qo'y", "Echki")]))


@router.callback_query(F.data.startswith("ak:"))
async def an_kind(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.update_data(kind=cb.data[3:])
    await cb.message.answer("Jinsi:", reply_markup=ik([("Urg'ochi", "as:Urg'ochi"), ("Erkak", "as:Erkak")]))


@router.callback_query(F.data.startswith("as:"))
async def an_sex(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.update_data(sex=cb.data[3:])
    await state.set_state(S.an_age)
    await cb.message.answer("Yoshi? (masalan: 2 yosh yoki 6 oy)" + CANCEL_HINT)


@router.message(S.an_age, F.text)
async def an_age(m: Message, state: FSMContext):
    await state.update_data(age=m.text.strip())
    await state.set_state(S.an_weight)
    await m.answer("Vazni (kg)? Bilmasangiz 0 yozing.")


@router.message(S.an_weight, F.text)
async def an_weight(m: Message, state: FSMContext):
    w = num(m.text)
    if w is None:
        return await m.answer("Iltimos, raqam kiriting (masalan: 350).")
    d = await state.get_data()
    aid = db("INSERT INTO animals(user_id,kind,sex,age,weight,created) VALUES(?,?,?,?,?,?)",
             (m.from_user.id, d["kind"], d["sex"], d["age"], w, str(today())))
    await state.clear()
    await m.answer(f"✅ Saqlandi: #{aid} {d['kind']}, {d['sex']}, {d['age']}, {w:g} kg", reply_markup=menu_kb())


@router.callback_query(F.data == "an:list")
async def an_list(cb: CallbackQuery):
    await cb.answer()
    rows = db("SELECT * FROM animals WHERE user_id=? AND status='faol' ORDER BY id LIMIT 30",
              (cb.from_user.id,), "all")
    if not rows:
        return await cb.message.answer("Ro'yxat bo'sh.")
    for r in rows:
        await cb.message.answer(f"#{r['id']} {r['kind']} • {r['sex']} • {r['age']} • {r['weight']:g} kg",
                                reply_markup=ik([("💰 Sotildi", f"an:sold:{r['id']}"),
                                                 ("🚪 Chiqarish", f"an:out:{r['id']}")]))


@router.callback_query(F.data.startswith("an:sold:"))
async def an_sold(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.update_data(aid=int(cb.data.split(":")[2]))
    await state.set_state(S.an_sold)
    await cb.message.answer("Qancha narxga sotdingiz (so'm)?" + CANCEL_HINT)


@router.message(S.an_sold, F.text)
async def an_sold_price(m: Message, state: FSMContext):
    p = num(m.text)
    if p is None:
        return await m.answer("Iltimos, raqam kiriting.")
    aid = (await state.get_data())["aid"]
    db("UPDATE animals SET status='sotilgan', out_day=? WHERE id=? AND user_id=?", (str(today()), aid, m.from_user.id))
    add_finance(m.from_user.id, today(), "daromad", "Chorva savdosi", p, f"Hayvon #{aid}")
    await state.clear()
    await m.answer(f"✅ #{aid} sotilgan deb belgilandi, {fmt(p)} daromadga qo'shildi.", reply_markup=menu_kb())


@router.callback_query(F.data.startswith("an:out:"))
async def an_out(cb: CallbackQuery):
    aid = int(cb.data.split(":")[2])
    db("UPDATE animals SET status='chiqarilgan', out_day=? WHERE id=? AND user_id=?", (str(today()), aid, cb.from_user.id))
    await cb.answer("Chiqarildi")
    await cb.message.edit_text(f"#{aid} xo'jalikdan chiqarildi.")


# ---------------------------------------------------------------- 2. Yem-xashak
@router.message(F.text == MENU[1])
async def m_feed(m: Message, state: FSMContext):
    await state.clear()
    rows = db("SELECT * FROM feed WHERE user_id=? ORDER BY name", (m.from_user.id,), "all")
    txt = "🌾 Yem-xashak zaxirasi\n" + ("\n".join(f"• {r['name']}: {r['stock']:g} kg (o'rtacha {fmt(r['avg_price'])}/kg)"
                                              for r in rows) if rows else "Hali yem kiritilmagan.")
    await m.answer(txt, reply_markup=ik([("🛒 Yem sotib olish", "fd:buy"), ("🍽 Yem sarfi", "fd:use")]))


@router.callback_query(F.data == "fd:buy")
async def fd_buy(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(S.fd_name)
    await cb.message.answer("Yem turi? (masalan: beda, arpa, omuxta yem)" + CANCEL_HINT)


@router.message(S.fd_name, F.text)
async def fd_name(m: Message, state: FSMContext):
    await state.update_data(name=m.text.strip().capitalize())
    await state.set_state(S.fd_qty)
    await m.answer("Necha kg sotib oldingiz (yoki mavjud miqdor)?")


@router.message(S.fd_qty, F.text)
async def fd_qty(m: Message, state: FSMContext):
    q = num(m.text)
    if not q:
        return await m.answer("Iltimos, 0 dan katta raqam kiriting.")
    await state.update_data(qty=q)
    await state.set_state(S.fd_total)
    await m.answer("Jami necha so'm to'ladingiz? (mavjud yem bo'lsa 0)")


@router.message(S.fd_total, F.text)
async def fd_total(m: Message, state: FSMContext):
    total = num(m.text)
    if total is None:
        return await m.answer("Iltimos, raqam kiriting.")
    d = await state.get_data()
    uid = m.from_user.id
    row = db("SELECT * FROM feed WHERE user_id=? AND lower(name)=lower(?)", (uid, d["name"]), "one")
    if row:
        new_stock = row["stock"] + d["qty"]
        avg = (row["stock"] * row["avg_price"] + total) / new_stock if new_stock else 0
        db("UPDATE feed SET stock=?, avg_price=? WHERE id=?", (new_stock, avg, row["id"]))
    else:
        db("INSERT INTO feed(user_id,name,stock,avg_price) VALUES(?,?,?,?)", (uid, d["name"], d["qty"], total / d["qty"]))
    add_finance(uid, today(), "xarajat", "Yem-xashak", total, d["name"])
    await state.clear()
    await m.answer(f"✅ {d['name']}: +{d['qty']:g} kg qo'shildi.", reply_markup=menu_kb())


@router.callback_query(F.data == "fd:use")
async def fd_use(cb: CallbackQuery):
    await cb.answer()
    rows = db("SELECT * FROM feed WHERE user_id=? AND stock>0", (cb.from_user.id,), "all")
    if not rows:
        return await cb.message.answer("Zaxirada yem yo'q.")
    await cb.message.answer("Qaysi yem sarflandi?", reply_markup=ik([(r["name"], f"fu:{r['id']}") for r in rows]))


@router.callback_query(F.data.startswith("fu:"))
async def fu_pick(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.update_data(fid=int(cb.data[3:]))
    await state.set_state(S.fu_qty)
    await cb.message.answer("Necha kg sarflandi?" + CANCEL_HINT)


@router.message(S.fu_qty, F.text)
async def fu_qty(m: Message, state: FSMContext):
    q = num(m.text)
    if not q:
        return await m.answer("Iltimos, 0 dan katta raqam kiriting.")
    fid = (await state.get_data())["fid"]
    row = db("SELECT * FROM feed WHERE id=? AND user_id=?", (fid, m.from_user.id), "one")
    if not row or q > row["stock"]:
        return await m.answer(f"Zaxirada faqat {row['stock']:g} kg bor. Kamroq kiriting." if row else "Yem topilmadi.")
    db("UPDATE feed SET stock=stock-? WHERE id=?", (q, fid))
    db("INSERT INTO feed_log(user_id,name,amount,day) VALUES(?,?,?,?)", (m.from_user.id, row["name"], q, str(today())))
    await state.clear()
    await m.answer(f"✅ {row['name']}: -{q:g} kg. Qoldi: {row['stock'] - q:g} kg.", reply_markup=menu_kb())


# ---------------------------------------------------------------- 3. Veterinariya
@router.message(F.text == MENU[2])
async def m_vet(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("💉 Veterinariya xizmati", reply_markup=ik(
        [("➕ Tadbir qo'shish", "vt:add"), ("📅 Rejalar", "vt:plan"), ("📜 Tarix", "vt:hist")]))


@router.callback_query(F.data == "vt:add")
async def vt_add(cb: CallbackQuery):
    await cb.answer()
    rows = db("SELECT * FROM animals WHERE user_id=? AND status='faol' ORDER BY id LIMIT 30", (cb.from_user.id,), "all")
    btns = [("Umumiy (butun podaga)", "va:0")] + [(f"#{r['id']} {r['kind']}", f"va:{r['id']}") for r in rows]
    await cb.message.answer("Qaysi hayvon uchun?", reply_markup=ik(btns))


@router.callback_query(F.data.startswith("va:"))
async def vt_animal(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.update_data(animal=int(cb.data[3:]))
    await cb.message.answer("Tadbir turi:", reply_markup=ik(
        [(k, f"vk:{k}") for k in ("Emlash", "Veterinar ko'rigi", "Davolash", "Boshqa")]))


@router.callback_query(F.data.startswith("vk:"))
async def vt_kind(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.update_data(kind=cb.data[3:])
    await state.set_state(S.vt_date)
    await cb.message.answer("Sana? (KK.OO.YYYY, masalan 25.10.2026, yoki 'bugun')" + CANCEL_HINT)


@router.message(S.vt_date, F.text)
async def vt_date(m: Message, state: FSMContext):
    d = parse_date(m.text)
    if not d:
        return await m.answer("Sana tushunarsiz. Masalan: 25.10.2026")
    await state.update_data(day=str(d))
    await state.set_state(S.vt_cost)
    await m.answer("Xarajat (so'm)? Yo'q bo'lsa 0.")


@router.message(S.vt_cost, F.text)
async def vt_cost(m: Message, state: FSMContext):
    c = num(m.text)
    if c is None:
        return await m.answer("Iltimos, raqam kiriting.")
    d = await state.get_data()
    done = 1 if date.fromisoformat(d["day"]) <= today() else 0
    db("INSERT INTO vet(user_id,animal_id,kind,day,cost,done) VALUES(?,?,?,?,?,?)",
       (m.from_user.id, d["animal"], d["kind"], d["day"], c, done))
    add_finance(m.from_user.id, d["day"], "xarajat", "Veterinariya", c, d["kind"])
    await state.clear()
    await m.answer("✅ Saqlandi." + ("" if done else " Sana yaqinlashganda eslataman ⏰"), reply_markup=menu_kb())


@router.callback_query(F.data == "vt:plan")
async def vt_plan(cb: CallbackQuery):
    await cb.answer()
    rows = db("SELECT * FROM vet WHERE user_id=? AND done=0 ORDER BY day LIMIT 20", (cb.from_user.id,), "all")
    if not rows:
        return await cb.message.answer("Rejalashtirilgan tadbir yo'q.")
    for r in rows:
        who = f"hayvon #{r['animal_id']}" if r["animal_id"] else "umumiy"
        await cb.message.answer(f"📅 {r['day']} — {r['kind']} ({who})",
                                reply_markup=ik([("✅ Bajarildi", f"vd:{r['id']}")]))


@router.callback_query(F.data.startswith("vd:"))
async def vt_done(cb: CallbackQuery):
    db("UPDATE vet SET done=1 WHERE id=? AND user_id=?", (int(cb.data[3:]), cb.from_user.id))
    await cb.answer("Bajarildi")
    await cb.message.edit_text("✅ Bajarildi.")


@router.callback_query(F.data == "vt:hist")
async def vt_hist(cb: CallbackQuery):
    await cb.answer()
    rows = db("SELECT * FROM vet WHERE user_id=? AND done=1 ORDER BY day DESC LIMIT 15", (cb.from_user.id,), "all")
    if not rows:
        return await cb.message.answer("Tarix bo'sh.")
    await cb.message.answer("📜 So'nggi tadbirlar:\n" + "\n".join(
        f"• {r['day']} — {r['kind']} ({'#' + str(r['animal_id']) if r['animal_id'] else 'umumiy'}), {fmt(r['cost'])}"
        for r in rows))


# ---------------------------------------------------------------- 4. Sut hisobi
def milk_sum(uid, d1, d2):
    r = db("SELECT COALESCE(SUM(liters),0) l, COALESCE(SUM(sold),0) s, COALESCE(SUM(sold*price),0) inc "
           "FROM milk WHERE user_id=? AND day BETWEEN ? AND ?", (uid, str(d1), str(d2)), "one")
    return r["l"], r["s"], r["inc"]


@router.message(F.text == MENU[3])
async def m_milk(m: Message, state: FSMContext):
    await state.clear()
    l, s, inc = milk_sum(m.from_user.id, today(), today())
    await m.answer(f"🥛 Bugun: {l:g} l sog'ildi, {s:g} l sotildi, daromad {fmt(inc)}",
                   reply_markup=ik([("➕ Sut kiritish", "mk:add"), ("📊 Statistika", "mk:stat")]))


@router.callback_query(F.data == "mk:add")
async def mk_add(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(S.mk_liters)
    await cb.message.answer("Necha litr sut sog'ildi?" + CANCEL_HINT)


@router.message(S.mk_liters, F.text)
async def mk_liters(m: Message, state: FSMContext):
    v = num(m.text)
    if v is None:
        return await m.answer("Iltimos, raqam kiriting.")
    await state.update_data(liters=v)
    await state.set_state(S.mk_sold)
    await m.answer("Shundan necha litri sotildi? (sotilmagan bo'lsa 0)")


@router.message(S.mk_sold, F.text)
async def mk_sold(m: Message, state: FSMContext):
    v = num(m.text)
    if v is None:
        return await m.answer("Iltimos, raqam kiriting.")
    d = await state.get_data()
    if v > d["liters"]:
        return await m.answer("Sotilgan sut sog'ilganidan ko'p bo'lishi mumkin emas.")
    await state.update_data(sold=v)
    if v == 0:
        return await mk_save(m, state, 0)
    await state.set_state(S.mk_price)
    await m.answer("1 litr sut narxi (so'm)?")


@router.message(S.mk_price, F.text)
async def mk_price(m: Message, state: FSMContext):
    p = num(m.text)
    if p is None:
        return await m.answer("Iltimos, raqam kiriting.")
    await mk_save(m, state, p)


async def mk_save(m: Message, state: FSMContext, price: float):
    d = await state.get_data()
    db("INSERT INTO milk(user_id,day,liters,sold,price) VALUES(?,?,?,?,?)",
       (m.from_user.id, str(today()), d["liters"], d["sold"], price))
    add_finance(m.from_user.id, today(), "daromad", "Sut sotuvi", d["sold"] * price, f"{d['sold']:g} l")
    await state.clear()
    await m.answer(f"✅ {d['liters']:g} l saqlandi. Sotuvdan: {fmt(d['sold'] * price)}", reply_markup=menu_kb())


@router.callback_query(F.data == "mk:stat")
async def mk_stat(cb: CallbackQuery):
    await cb.answer()
    t = today()
    out = ["📊 Sut statistikasi"]
    for name, d1 in (("Bugun", t), ("So'nggi 7 kun", t - timedelta(days=6)), ("Shu oy", t.replace(day=1))):
        l, s, inc = milk_sum(cb.from_user.id, d1, t)
        out.append(f"{name}: {l:g} l sog'ildi, {s:g} l sotildi, {fmt(inc)}")
    await cb.message.answer("\n".join(out))


# ---------------------------------------------------------------- 5. Daromad va xarajatlar
def fin_sum(uid, d1, d2):
    inc = db("SELECT COALESCE(SUM(amount),0) a FROM finance WHERE user_id=? AND type='daromad' AND day BETWEEN ? AND ?",
             (uid, str(d1), str(d2)), "one")["a"]
    exp = db("SELECT COALESCE(SUM(amount),0) a FROM finance WHERE user_id=? AND type='xarajat' AND day BETWEEN ? AND ?",
             (uid, str(d1), str(d2)), "one")["a"]
    return inc, exp


@router.message(F.text == MENU[4])
async def m_fin(m: Message, state: FSMContext):
    await state.clear()
    inc, exp = fin_sum(m.from_user.id, today().replace(day=1), today())
    await m.answer(f"💰 Shu oy: daromad {fmt(inc)}, xarajat {fmt(exp)}, sof natija {fmt(inc - exp)}",
                   reply_markup=ik([("➕ Daromad", "fn:daromad"), ("➖ Xarajat", "fn:xarajat"), ("📊 Tafsilot", "fn:sum")]))


@router.callback_query(F.data.in_({"fn:daromad", "fn:xarajat"}))
async def fn_add(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.update_data(type=cb.data[3:])
    await state.set_state(S.fn_amount)
    await cb.message.answer("Summa (so'm)?" + CANCEL_HINT)


@router.message(S.fn_amount, F.text)
async def fn_amount(m: Message, state: FSMContext):
    v = num(m.text)
    if not v:
        return await m.answer("Iltimos, 0 dan katta raqam kiriting.")
    await state.update_data(amount=v)
    await state.set_state(S.fn_note)
    await m.answer("Izoh (nima uchun)?")


@router.message(S.fn_note, F.text)
async def fn_note(m: Message, state: FSMContext):
    d = await state.get_data()
    add_finance(m.from_user.id, today(), d["type"], "Boshqa", d["amount"], m.text.strip())
    await state.clear()
    await m.answer(f"✅ {d['type'].capitalize()}: {fmt(d['amount'])} saqlandi.", reply_markup=menu_kb())


@router.callback_query(F.data == "fn:sum")
async def fn_sum(cb: CallbackQuery):
    await cb.answer()
    await cb.message.answer(category_report(cb.from_user.id, today().replace(day=1), today(), "Shu oy"))


def category_report(uid, d1, d2, title):
    inc, exp = fin_sum(uid, d1, d2)
    lines = [f"💰 {title}: daromad {fmt(inc)}, xarajat {fmt(exp)}, sof natija {fmt(inc - exp)}"]
    for typ in ("daromad", "xarajat"):
        rows = db("SELECT category, SUM(amount) a FROM finance WHERE user_id=? AND type=? AND day BETWEEN ? AND ? "
                  "GROUP BY category ORDER BY a DESC", (uid, typ, str(d1), str(d2)), "all")
        if rows:
            lines.append(f"{typ.capitalize()}lar:" if typ == "daromad" else "Xarajatlar:")
            lines += [f"  • {r['category']}: {fmt(r['a'])}" for r in rows]
    return "\n".join(lines)


# ---------------------------------------------------------------- 6. Chorva bozori
AD_CATS = ["Chorva", "Yem-xashak", "Jihoz"]


@router.message(F.text == MENU[5])
async def m_market(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("🛒 Chorva bozori", reply_markup=ik(
        [("📢 E'lon joylash", "ad:new"), ("🔎 E'lonlarni ko'rish", "ad:browse"), ("🗂 Mening e'lonlarim", "ad:mine")]))


@router.callback_query(F.data == "ad:new")
async def ad_new(cb: CallbackQuery):
    await cb.answer()
    await cb.message.answer("E'lon turi:", reply_markup=ik([(c, f"ac:{c}") for c in AD_CATS]))


@router.callback_query(F.data.startswith("ac:"))
async def ad_cat(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.update_data(category=cb.data[3:])
    await state.set_state(S.ad_title)
    await cb.message.answer("Sarlavha? (masalan: Sigir sotiladi / Beda sotiladi)" + CANCEL_HINT)


@router.message(S.ad_title, F.text)
async def ad_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text.strip())
    await state.set_state(S.ad_details)
    await m.answer("Tafsilot: hayvon bo'lsa turi, yoshi, vazni; boshqasi uchun miqdori va sifati.")


@router.message(S.ad_details, F.text)
async def ad_details(m: Message, state: FSMContext):
    await state.update_data(details=m.text.strip())
    await state.set_state(S.ad_price)
    await m.answer("Narxi (so'm)?")


@router.message(S.ad_price, F.text)
async def ad_price(m: Message, state: FSMContext):
    p = num(m.text)
    if not p:
        return await m.answer("Iltimos, raqam kiriting.")
    await state.update_data(price=p)
    await state.set_state(S.ad_region)
    default = db("SELECT region FROM users WHERE id=?", (m.from_user.id,), "one")["region"]
    await m.answer("Hudud (viloyat, tuman)?" + (f"\nOxirgi sozlamangiz: {default} — shuni yozing yoki yangisini kiriting." if default else ""))


@router.message(S.ad_region, F.text)
async def ad_region(m: Message, state: FSMContext):
    await state.update_data(region=m.text.strip())
    await state.set_state(S.ad_photo)
    await m.answer("Surat yuboring 📷 (surat bo'lmasa 'yo'q' deb yozing).")


@router.message(S.ad_photo)
async def ad_photo(m: Message, state: FSMContext):
    if m.photo:
        await state.update_data(photo=m.photo[-1].file_id)
    elif m.text:
        await state.update_data(photo="")
    else:
        return await m.answer("Surat yoki 'yo'q' deb yozing.")
    await state.set_state(S.ad_contact)
    await m.answer("Aloqa uchun telefon raqamingiz?")


def ad_text(a, username=None):
    c = a["contact"] + (f" / @{username}" if username else "")
    return f"📢 {a['title']}\n{a['details']}\n💰 {fmt(a['price'])}\n📍 {a['region']}\n📞 {c}"


@router.message(S.ad_contact, F.text)
async def ad_contact(m: Message, state: FSMContext, bot: Bot):
    d = await state.get_data()
    status = "kutilmoqda" if ADMIN_ID else "faol"
    aid = db("INSERT INTO ads(user_id,category,title,details,price,region,photo,contact,status,created) "
             "VALUES(?,?,?,?,?,?,?,?,?,?)",
             (m.from_user.id, d["category"], d["title"], d["details"], d["price"], d["region"],
              d["photo"], m.text.strip(), status, str(today())))
    await state.clear()
    if ADMIN_ID:
        await m.answer("✅ E'lon moderatsiyaga yuborildi. Tasdiqlangach bozorda ko'rinadi.", reply_markup=menu_kb())
        a = db("SELECT * FROM ads WHERE id=?", (aid,), "one")
        kb = ik([("✅ Tasdiqlash", f"aa:ok:{aid}"), ("❌ Rad etish", f"aa:no:{aid}")])
        text = "Yangi e'lon:\n\n" + ad_text(a, m.from_user.username)
        try:
            if a["photo"]:
                await bot.send_photo(ADMIN_ID, a["photo"], caption=text, reply_markup=kb)
            else:
                await bot.send_message(ADMIN_ID, text, reply_markup=kb)
        except Exception:
            logging.exception("admin ga yuborilmadi")
    else:
        await m.answer("✅ E'lon joylandi!", reply_markup=menu_kb())


@router.callback_query(F.data.startswith("aa:"))
async def ad_admin(cb: CallbackQuery, bot: Bot):
    if cb.from_user.id != ADMIN_ID:
        return await cb.answer("Ruxsat yo'q", show_alert=True)
    _, act, aid = cb.data.split(":")
    a = db("SELECT * FROM ads WHERE id=?", (int(aid),), "one")
    if not a:
        return await cb.answer("Topilmadi")
    db("UPDATE ads SET status=? WHERE id=?", ("faol" if act == "ok" else "rad", a["id"]))
    await cb.answer("Bajarildi")
    try:
        await bot.send_message(a["user_id"], "✅ E'loningiz tasdiqlandi." if act == "ok" else "❌ E'loningiz rad etildi.")
    except Exception:
        pass


@router.callback_query(F.data == "ad:browse")
async def ad_browse(cb: CallbackQuery):
    await cb.answer()
    await cb.message.answer("Qaysi bo'lim?", reply_markup=ik([(c, f"ab:{c}") for c in AD_CATS]))


@router.callback_query(F.data.startswith("ab:"))
async def ad_list(cb: CallbackQuery):
    await cb.answer()
    rows = db("SELECT ads.*, users.username FROM ads JOIN users ON users.id=ads.user_id "
              "WHERE category=? AND status='faol' ORDER BY ads.id DESC LIMIT 10", (cb.data[3:],), "all")
    if not rows:
        return await cb.message.answer("Hozircha e'lon yo'q.")
    for a in rows:
        if a["photo"]:
            await cb.message.answer_photo(a["photo"], caption=ad_text(a, a["username"]))
        else:
            await cb.message.answer(ad_text(a, a["username"]))


@router.callback_query(F.data == "ad:mine")
async def ad_mine(cb: CallbackQuery):
    await cb.answer()
    rows = db("SELECT * FROM ads WHERE user_id=? AND status IN ('faol','kutilmoqda') ORDER BY id DESC LIMIT 10",
              (cb.from_user.id,), "all")
    if not rows:
        return await cb.message.answer("Sizda faol e'lon yo'q.")
    for a in rows:
        await cb.message.answer(f"[{a['status']}]\n" + ad_text(a), reply_markup=ik([("🗑 O'chirish", f"ad:del:{a['id']}")]))


@router.callback_query(F.data.startswith("ad:del:"))
async def ad_del(cb: CallbackQuery):
    db("UPDATE ads SET status='ochirilgan' WHERE id=? AND user_id=?", (int(cb.data.split(":")[2]), cb.from_user.id))
    await cb.answer("O'chirildi")
    await cb.message.edit_text("🗑 E'lon o'chirildi.")


# ---------------------------------------------------------------- 7. Eslatmalar
@router.message(F.text == MENU[6])
async def m_remind(m: Message, state: FSMContext):
    await state.clear()
    uid = m.from_user.id
    out = ["⏰ Eslatmalar"]
    vets = db("SELECT * FROM vet WHERE user_id=? AND done=0 ORDER BY day LIMIT 10", (uid,), "all")
    out += [f"💉 {v['day']} — {v['kind']}" for v in vets] or ["💉 Rejalashtirilgan veterinariya tadbiri yo'q"]
    u = db("SELECT low_feed FROM users WHERE id=?", (uid,), "one")
    low = db("SELECT * FROM feed WHERE user_id=? AND stock<?", (uid, u["low_feed"]), "all")
    out += [f"🌾 {f['name']} kam qoldi: {f['stock']:g} kg" for f in low]
    if not db("SELECT 1 FROM milk WHERE user_id=? AND day=?", (uid, str(today())), "one"):
        out.append("🥛 Bugungi sut hali kiritilmagan")
    out.append("\nBot avtomatik ravishda ham eslatma yuboradi: emlash sanasidan 1 kun oldin, yem kamayganda (soat 08:00) va sut kiritilmasa (soat 19:00).")
    await m.answer("\n".join(out))


async def run_reminders(bot: Bot):
    now = datetime.now(TZ)
    t = now.date()
    for v in db("SELECT * FROM vet WHERE done=0 AND notified<2", (), "all"):
        days = (date.fromisoformat(v["day"]) - t).days
        stage, msg = None, None
        if days < 0:
            stage, msg = 2, f"⚠️ Muddati o'tdi: {v['kind']} ({v['day']}). Bajarilgan bo'lsa Veterinariya > Rejalar'da belgilang."
        elif days <= 1 and v["notified"] == 0:
            stage, msg = 1, f"💉 Eslatma: {v['kind']} — {'bugun' if days == 0 else 'ertaga'} ({v['day']})."
        if stage:
            db("UPDATE vet SET notified=? WHERE id=?", (stage, v["id"]))
            await safe_send(bot, v["user_id"], msg)
    if now.hour >= 8:
        for u in db("SELECT * FROM users WHERE last_low<>?", (str(t),), "all"):
            low = db("SELECT * FROM feed WHERE user_id=? AND stock<?", (u["id"], u["low_feed"]), "all")
            if low:
                await safe_send(bot, u["id"], "🌾 Yem zaxirasi kam:\n" + "\n".join(f"• {f['name']}: {f['stock']:g} kg" for f in low))
            db("UPDATE users SET last_low=? WHERE id=?", (str(t), u["id"]))
    if now.hour >= 19:
        for u in db("SELECT * FROM users WHERE last_milk<>?", (str(t),), "all"):
            has_cow = db("SELECT 1 FROM animals WHERE user_id=? AND status='faol' AND kind='Sigir'", (u["id"],), "one")
            has_milk = db("SELECT 1 FROM milk WHERE user_id=? AND day=?", (u["id"], str(t)), "one")
            if has_cow and not has_milk:
                await safe_send(bot, u["id"], "🥛 Bugungi sut hisobini kiritishni unutmang.")
            db("UPDATE users SET last_milk=? WHERE id=?", (str(t), u["id"]))


async def safe_send(bot: Bot, uid, text):
    try:
        await bot.send_message(uid, text)
    except Exception:
        logging.warning("xabar yuborilmadi: %s", uid)


async def reminder_loop(bot: Bot):
    while True:
        try:
            await run_reminders(bot)
        except Exception:
            logging.exception("eslatma xatosi")
        await asyncio.sleep(600)


# ---------------------------------------------------------------- 8. Hisobotlar
@router.message(F.text == MENU[7])
async def m_reports(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("📊 Qaysi hisobot?", reply_markup=ik([("Kunlik", "rp:d"), ("Haftalik", "rp:w"), ("Oylik", "rp:m")], 3))


@router.callback_query(F.data.startswith("rp:"))
async def rp(cb: CallbackQuery):
    await cb.answer()
    uid, t = cb.from_user.id, today()
    kind = cb.data[3:]
    d1, title = {"d": (t, "Kunlik hisobot"), "w": (t - timedelta(days=6), "Haftalik hisobot (7 kun)"),
                 "m": (t.replace(day=1), "Oylik hisobot")}[kind]
    out = [f"📊 {title}: {d1} — {t}", ""]
    animals = db("SELECT kind,COUNT(*) c FROM animals WHERE user_id=? AND status='faol' GROUP BY kind", (uid,), "all")
    out.append("🐄 Chorva: " + (", ".join(f"{r['kind']} {r['c']}" for r in animals) or "yo'q"))
    added = db("SELECT COUNT(*) c FROM animals WHERE user_id=? AND created BETWEEN ? AND ?", (uid, str(d1), str(t)), "one")["c"]
    gone = db("SELECT COUNT(*) c FROM animals WHERE user_id=? AND out_day BETWEEN ? AND ?", (uid, str(d1), str(t)), "one")["c"]
    out.append(f"   Davr ichida: +{added} qo'shildi, -{gone} chiqdi/sotildi")
    l, s, inc = milk_sum(uid, d1, t)
    out.append(f"\n🥛 Sut: {l:g} l sog'ildi, {s:g} l sotildi, {fmt(inc)}")
    feeds = db("SELECT name, SUM(amount) a FROM feed_log WHERE user_id=? AND day BETWEEN ? AND ? GROUP BY name",
               (uid, str(d1), str(t)), "all")
    out.append("🌾 Yem sarfi: " + (", ".join(f"{f['name']} {f['a']:g} kg" for f in feeds) or "kiritilmagan"))
    out.append("\n" + category_report(uid, d1, t, "Moliya"))
    await cb.message.answer("\n".join(out))


# ---------------------------------------------------------------- 9. Sozlamalar
SETTINGS = {"name": "Ismingiz", "region": "Hudud (viloyat, tuman)", "farm": "Xo'jalik nomi",
            "low_feed": "Yem zaxirasi necha kg dan kamayganda eslatilsin? (raqam)"}


@router.message(F.text == MENU[8])
async def m_settings(m: Message, state: FSMContext):
    await state.clear()
    u = db("SELECT * FROM users WHERE id=?", (m.from_user.id,), "one")
    await m.answer(f"⚙️ Sozlamalar\nIsm: {u['name']}\nHudud: {u['region'] or '—'}\nXo'jalik: {u['farm'] or '—'}\n"
                   f"Yem chegarasi: {u['low_feed']:g} kg",
                   reply_markup=ik([("👤 Ism", "st:name"), ("📍 Hudud", "st:region"),
                                    ("🏡 Xo'jalik", "st:farm"), ("📦 Yem chegarasi", "st:low_feed")]))


@router.callback_query(F.data.startswith("st:"))
async def st_pick(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    field = cb.data[3:]
    await state.update_data(field=field)
    await state.set_state(S.st_value)
    await cb.message.answer(SETTINGS[field] + "?" + CANCEL_HINT)


@router.message(S.st_value, F.text)
async def st_value(m: Message, state: FSMContext):
    field = (await state.get_data())["field"]
    val = m.text.strip()
    if field == "low_feed":
        val = num(val)
        if val is None:
            return await m.answer("Iltimos, raqam kiriting.")
    db(f"UPDATE users SET {field}=? WHERE id=?", (val, m.from_user.id))  # field faqat SETTINGS kalitlaridan
    await state.clear()
    await m.answer("✅ Saqlandi.", reply_markup=menu_kb())


# ---------------------------------------------------------------- 10. Yordam
@router.message(F.text == MENU[9])
async def m_help(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("❓ Yordam\n\n"
                   "🐄 Chorva — hayvonlarni qo'shing, sotilganini belgilang.\n"
                   "🌾 Yem — sotib olingan va sarflangan yemni yuriting.\n"
                   "💉 Veterinariya — emlash/ko'rik sanalarini kiriting, bot eslatadi.\n"
                   "🥛 Sut — har kuni sog'ilgan va sotilgan sutni kiriting.\n"
                   "💰 Moliya — daromad/xarajat avtomatik hisoblanadi.\n"
                   "🛒 Bozor — e'lon joylang yoki boshqalarning e'lonlarini ko'ring.\n\n"
                   "Jarayonni to'xtatish: /cancel\nMuammo bo'lsa, bot egasiga murojaat qiling.")


# ---------------------------------------------------------------- ishga tushirish
async def main():
    logging.basicConfig(level=logging.INFO)
    if not TOKEN:
        raise SystemExit("BOT_TOKEN topilmadi. .env faylini tekshiring.")
    init_db()
    bot = Bot(TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    task = asyncio.create_task(reminder_loop(bot))
    try:
        await dp.start_polling(bot)
    finally:
        task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
