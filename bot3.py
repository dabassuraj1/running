#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Vehicle Info Telegram Bot
- Credit system (SQLite)
- Fancy report output (box + emoji) — EXACT TEMPLATE
- User menu + Admin panel (inline buttons)
- Admin guided flows (add/remove credits, set price, broadcast)
- Logs + simple analytics
"""

import os
import re
import csv
import time
import uuid
import sqlite3
import logging
import requests
from datetime import datetime

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    filters, ContextTypes
)

# ---------------- CONFIG ----------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "7596706471:AAHaVeFYHy7hlNamSf-u1_ZYkLXVbLrH4FU")
ADMINS = {7922285746}  # <-- put your numeric Telegram user IDs here
DB_FILE = os.getenv("DB_FILE", "vehicle_bot.db")
API_URL = "https://rtdb-2.onrender.com/vehicle?rc="
DEFAULT_CREDIT_COST = 1
INITIAL_USER_CREDITS = 0  # new users start with 0 (change if you want freebies)

# ---------------- LOGGING ----------------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO
)
log = logging.getLogger("vehicle-bot")

# ---------------- DB LAYER ----------------
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        first_name TEXT,
        username TEXT,
        credits INTEGER DEFAULT 0,
        banned INTEGER DEFAULT 0,
        created_at TEXT,
        updated_at TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS logs (
        id TEXT PRIMARY KEY,
        user_id INTEGER,
        rc TEXT,
        ok INTEGER,
        cost INTEGER,
        created_at TEXT
    )
    """)
    cur.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('credit_cost', ?)", (str(DEFAULT_CREDIT_COST),))
    conn.commit()
    conn.close()

def now_iso():
    return datetime.utcnow().isoformat()

def get_setting(key, default=None):
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = cur.fetchone()
    conn.close()
    return row["value"] if row else default

def set_setting(key, value):
    conn = db(); cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, str(value)))
    conn.commit(); conn.close()

def upsert_user(user):
    conn = db(); cur = conn.cursor()
    cur.execute("""
    INSERT INTO users(user_id, first_name, username, credits, banned, created_at, updated_at)
    VALUES(?,?,?,?,0,?,?)
    ON CONFLICT(user_id) DO UPDATE SET
        first_name=excluded.first_name,
        username=excluded.username,
        updated_at=excluded.updated_at
    """, (
        user.id,
        user.first_name or "",
        user.username or "",
        INITIAL_USER_CREDITS,
        now_iso(),
        now_iso(),
    ))
    conn.commit(); conn.close()

def get_user(user_id):
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row

def add_credits(user_id, amount):
    conn = db(); cur = conn.cursor()
    cur.execute("UPDATE users SET credits = COALESCE(credits,0) + ?, updated_at=? WHERE user_id=?",
                (amount, now_iso(), user_id))
    conn.commit(); conn.close()

def change_ban(user_id, banned: bool):
    conn = db(); cur = conn.cursor()
    cur.execute("UPDATE users SET banned=?, updated_at=? WHERE user_id=?",
                (1 if banned else 0, now_iso(), user_id))
    conn.commit(); conn.close()

def list_users(limit=50, offset=0):
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT * FROM users ORDER BY created_at ASC LIMIT ? OFFSET ?", (limit, offset))
    rows = cur.fetchall()
    conn.close()
    return rows

def count_users():
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM users")
    c = cur.fetchone()["c"]
    conn.close()
    return c

def log_lookup(user_id, rc, ok, cost):
    conn = db(); cur = conn.cursor()
    cur.execute("""
    INSERT INTO logs(id, user_id, rc, ok, cost, created_at)
    VALUES(?,?,?,?,?,?)
    """, (str(uuid.uuid4()), user_id, rc, 1 if ok else 0, cost, now_iso()))
    conn.commit(); conn.close()

def stats_summary():
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM users"); users = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) AS c FROM logs"); lookups = cur.fetchone()["c"]
    cur.execute("SELECT SUM(cost) AS s FROM logs"); spent = cur.fetchone()["s"]
    conn.close()
    return {"users": users or 0, "lookups": lookups or 0, "credits_spent": spent or 0}

# ---------------- HELPERS ----------------
def format_date_safe(s: str):
    """Return parsed date dd-Mon-YYYY if possible, else original."""
    if not s or s in ("None", "N/A"):
        return "N/A"
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%d-%b-%Y")
        except Exception:
            pass
    return s

def sanitize(val):
    if val is None:
        return "N/A"
    s = str(val).strip()
    if s == "" or s.lower() == "none":
        return "N/A"
    return s

def format_vehicle_report(data: dict) -> str:
    """
    EXACTLY the layout you requested.
    Hides: ok, note, error
    """
    # Remove fields we must NOT show
    for k in ("ok", "note", "error"):
        data.pop(k, None)

    rc = sanitize(data.get("rc"))
    owner_name = sanitize(data.get("owner_name"))
    father_name = sanitize(data.get("father_name"))
    owner_serial_no = sanitize(data.get("owner_serial_no"))
    model_name = sanitize(data.get("model_name"))
    maker_model = sanitize(data.get("maker_model"))
    vehicle_class = sanitize(data.get("vehicle_class"))
    fuel_type = sanitize(data.get("fuel_type"))
    fuel_norms = sanitize(data.get("fuel_norms"))
    reg_date = format_date_safe(sanitize(data.get("reg_date")))
    insurance_company = sanitize(data.get("insurance_company"))
    insurance_no = sanitize(data.get("insurance_no"))
    insurance_expiry = format_date_safe(sanitize(data.get("insurance_expiry")))
    insurance_upto = format_date_safe(sanitize(data.get("insurance_upto")))
    fitness_upto = format_date_safe(sanitize(data.get("fitness_upto")))
    tax_upto = sanitize(data.get("tax_upto"))
    puc_no = sanitize(data.get("puc_no"))  # not shown in this exact layout
    puc_upto = format_date_safe(sanitize(data.get("puc_upto")))  # not shown in this exact layout
    financier_name = sanitize(data.get("financier_name"))  # not shown here
    rto = sanitize(data.get("rto"))
    address = sanitize(data.get("address"))
    city = sanitize(data.get("city"))
    phone = sanitize(data.get("phone"))

    lines = []
    lines.append("╔════════════════════════════════════════╗")
    lines.append("║       🚗  🎯 Vehicle Detailed Report  🛠️")
    lines.append("╚════════════════════════════════════════╗")
    lines.append("")
    lines.append("┏━━━━━━━━━━━━━━━━━━━━━━━━━┓")
    lines.append("┃    📋 PRIMARY INFORMATION    ┃")
    lines.append("┗━━━━━━━━━━━━━━━━━━━━━━━━━┛")
    lines.append(f"👤 Owner Name: {owner_name}")
    lines.append(f"👨‍👦 Father's Name: {father_name}")
    lines.append(f"🏠 Address: {address}")
    lines.append(f"🌆 City: {city}")
    lines.append(f"📞 Phone: {phone}")
    lines.append(f"📇 Owner Serial No: {owner_serial_no}")
    lines.append(f"🏷️ Vehicle Class: {vehicle_class}")
    lines.append("")
    lines.append("┏━━━━━━━━━━━━━━━━━━━━━━━━━┓")
    lines.append("┃    🚙 VEHICLE DETAILS    ┃")
    lines.append("┗━━━━━━━━━━━━━━━━━━━━━━━━━┛")
    lines.append(f"📄 Registration No: {rc}")
    lines.append(f"📅 Registration Date: {reg_date}")
    lines.append(f"🏢 RTO Office: {rto}")
    lines.append(f"⚙️ Maker Model: {maker_model}")
    lines.append(f"🏷 Model Name: {model_name}")
    lines.append(f"⛽ Fuel Type: {fuel_type}")
    lines.append(f"🛢 Fuel Norms: {fuel_norms}")
    lines.append(f"🔧 Fitness Valid Upto: {fitness_upto}")
    lines.append(f"💸 Tax Valid Upto: {tax_upto}")
    lines.append("")
    lines.append("┏━━━━━━━━━━━━━━━━━━━━━━━━━┓")
    lines.append("┃    🛡️ INSURANCE DETAILS    ┃")
    lines.append("┗━━━━━━━━━━━━━━━━━━━━━━━━━┛")
    lines.append(f"🏢 Insurance Company: {insurance_company}")
    lines.append(f"📜 Policy No: {insurance_no}")
    lines.append(f"📆 Insurance Expiry: {insurance_expiry}")
    lines.append(f"📅 Insurance Valid Upto: {insurance_upto}")
    lines.append("")
    lines.append("┏━━━━━━━━━━━━━━━━━━━━━━━━━┓")
    lines.append("┃    🛠️ ADDITIONAL DETAILS    ┃")
    lines.append("┗━━━━━━━━━━━━━━━━━━━━━━━━━┛")
    lines.append("")  # keep empty as per your sample
    lines.append("╚════════════════════════════════════════╝")
    body = "\n".join(lines)
    # Wrap in code block for perfect alignment in Telegram
    return f"```\n{body}\n```"

def user_menu_kb(is_admin: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🚘 Get Vehicle Info", callback_data="u:get")],
        [InlineKeyboardButton("💳 Check Credits", callback_data="u:credits"),
         InlineKeyboardButton("➕ Buy Credits", callback_data="u:buy")],
        [InlineKeyboardButton("💰 Price", callback_data="u:price"),
         InlineKeyboardButton("ℹ️ Help", callback_data="u:help")]
    ]
    if is_admin:
        rows.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="a:panel")])
    return InlineKeyboardMarkup(rows)

def admin_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Users", callback_data="a:users"),
         InlineKeyboardButton("📊 Stats", callback_data="a:stats")],
        [InlineKeyboardButton("➕ Add Credits", callback_data="a:add"),
         InlineKeyboardButton("➖ Remove Credits", callback_data="a:sub")],
        [InlineKeyboardButton("💳 Check Credits", callback_data="a:check"),
         InlineKeyboardButton("⚙️ Set Price", callback_data="a:setprice")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="a:broadcast"),
         InlineKeyboardButton("🚫 Ban/Unban", callback_data="a:ban")],
        [InlineKeyboardButton("📤 Export Users CSV", callback_data="a:export")],
        [InlineKeyboardButton("⬅️ Back", callback_data="a:back")]
    ])

# ---------------- BOT HANDLERS ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    upsert_user(user)
    is_admin = user.id in ADMINS
    urow = get_user(user.id)
    credits = urow["credits"] if urow else 0
    await update.message.reply_text(
        f"👋 Hello {user.first_name}!\n"
        f"Welcome to the Vehicle Info Bot.\n\n"
        f"🔑 Credits: {credits}\n"
        f"Use the menu below.",
        reply_markup=user_menu_kb(is_admin)
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_admin = update.effective_user.id in ADMINS
    if is_admin:
        text = (
            "📖 *Help – Admin*\n\n"
            "User commands:\n"
            "• /start – open menu\n"
            "• /vehicle <RC> – fetch details\n"
            "• /credits – show credits\n"
            "• /help – this help\n\n"
            "Admin commands:\n"
            "• /admin – open admin panel\n"
            "• /setprice <amount> – set lookup price\n"
            "• /addcredits <user_id> <amount>\n"
            "• /removecredits <user_id> <amount>\n"
            "• /checkcredits <user_id>\n"
            "• /broadcast <message>\n"
            "• /ban <user_id>  /unban <user_id>\n"
            "• /users – first 50 users\n"
            "• /stats – summary\n"
        )
    else:
        text = (
            "📖 *Help – User*\n\n"
            "• /start – open menu\n"
            "• /vehicle <RC> – get vehicle details (uses credits)\n"
            "• /credits – check your credits\n"
            "• /help – this help\n"
            "Need more credits? Tap *Buy Credits*."
        )
    await update.message.reply_text(text, parse_mode="Markdown")

async def credits_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    upsert_user(update.effective_user)
    urow = get_user(update.effective_user.id)
    await update.message.reply_text(f"💳 Your credits: {urow['credits']}")

async def vehicle_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    upsert_user(user)
    urow = get_user(user.id)
    if urow["banned"]:
        await update.message.reply_text("🚫 You are banned from using this bot.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /vehicle <RC_NUMBER>")
        return
    rc = re.sub(r"[^A-Z0-9]", "", context.args[0].upper())

    # price
    cost = int(get_setting("credit_cost", DEFAULT_CREDIT_COST))
    if urow["credits"] < cost:
        await update.message.reply_text(
            f"⚠️ Not enough credits. Price per lookup: {cost}. Tap *Buy Credits*.",
            parse_mode="Markdown",
            reply_markup=user_menu_kb(user.id in ADMINS)
        )
        return

    # call API
    try:
        res = requests.get(API_URL + rc, timeout=15)
        data = res.json()
    except Exception as e:
        await update.message.reply_text(f"❌ API error: {e}")
        return

    ok = bool(data.get("ok"))
    if ok:
        add_credits(user.id, -cost)
    log_lookup(user.id, rc, ok, cost if ok else 0)

    if ok:
        text = format_vehicle_report(dict(data))
        # Send with Markdown so the ``` block is monospaced
        await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)
        newu = get_user(user.id)
        await update.message.reply_text(f"✅ Lookup done. Remaining credits: {newu['credits']}")
    else:
        await update.message.reply_text(f"❌ No data found for *{rc}*.", parse_mode="Markdown")

# -------- Inline Button Router --------
async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    user = query.from_user
    upsert_user(user)

    # USER actions
    if data == "u:get":
        await query.edit_message_text(
            "✍️ Send RC using command:\n`/vehicle MH17CR7001`",
            parse_mode="Markdown",
            reply_markup=user_menu_kb(user.id in ADMINS)
        ); return
    if data == "u:credits":
        urow = get_user(user.id)
        await query.edit_message_text(
            f"💳 Your credits: {urow['credits']}",
            reply_markup=user_menu_kb(user.id in ADMINS)
        ); return
    if data == "u:buy":
        price = int(get_setting("credit_cost", DEFAULT_CREDIT_COST))
        await query.edit_message_text(
            f"🛒 *Buy Credits*\n\n"
            f"Current price per lookup: *{price}*\n"
            f"• 10 credits – ₹???\n"
            f"• 50 credits – ₹???\n"
            f"• 100 credits – ₹???\n\n"
            f"Contact admin to purchase.",
            parse_mode="Markdown",
            reply_markup=user_menu_kb(user.id in ADMINS)
        ); return
    if data == "u:price":
        price = int(get_setting("credit_cost", DEFAULT_CREDIT_COST))
        await query.edit_message_text(
            f"💰 Current price per lookup: *{price}* credits.",
            parse_mode="Markdown",
            reply_markup=user_menu_kb(user.id in ADMINS)
        ); return
    if data == "u:help":
        await help_cmd(update, context); return

    # ADMIN actions
    if data == "a:panel":
        if user.id not in ADMINS: return
        await query.edit_message_text("⚙️ Admin Panel", reply_markup=admin_panel_kb()); return

    if data == "a:back":
        await query.edit_message_text("Back to menu.", reply_markup=user_menu_kb(user.id in ADMINS)); return

    if user.id not in ADMINS:
        return

    if data == "a:stats":
        s = stats_summary()
        price = get_setting("credit_cost", DEFAULT_CREDIT_COST)
        await query.edit_message_text(
            f"📊 *Stats*\nUsers: {s['users']}\nLookups: {s['lookups']}\nCredits spent: {s['credits_spent']}\nPrice: {price}",
            parse_mode="Markdown",
            reply_markup=admin_panel_kb()
        ); return

    if data == "a:users":
        rows = list_users(limit=20, offset=0)
        if not rows:
            txt = "No users."
        else:
            lines = ["👥 *Users (first 20)*"]
            for r in rows:
                lines.append(f"{r['user_id']} | {r['first_name']} | @{r['username'] or '-'} | {r['credits']} cr | {'BANNED' if r['banned'] else 'OK'}")
            txt = "\n".join(lines)
        await query.edit_message_text(txt, parse_mode="Markdown", reply_markup=admin_panel_kb()); return

    if data == "a:add":
        context.user_data["admin_mode"] = "add"
        await query.edit_message_text("➕ Send: `user_id amount` (e.g. `123456789 10`)", parse_mode="Markdown", reply_markup=admin_panel_kb()); return

    if data == "a:sub":
        context.user_data["admin_mode"] = "sub"
        await query.edit_message_text("➖ Send: `user_id amount`", parse_mode="Markdown", reply_markup=admin_panel_kb()); return

    if data == "a:check":
        context.user_data["admin_mode"] = "check"
        await query.edit_message_text("💳 Send: `user_id`", parse_mode="Markdown", reply_markup=admin_panel_kb()); return

    if data == "a:setprice":
        context.user_data["admin_mode"] = "price"
        await query.edit_message_text("⚙️ Send new price (integer):", reply_markup=admin_panel_kb()); return

    if data == "a:broadcast":
        context.user_data["admin_mode"] = "broadcast"
        await query.edit_message_text("📢 Send broadcast message text:", reply_markup=admin_panel_kb()); return

    if data == "a:ban":
        context.user_data["admin_mode"] = "ban"
        await query.edit_message_text("🚫 Send: `ban user_id` or `unban user_id`", parse_mode="Markdown", reply_markup=admin_panel_kb()); return

    if data == "a:export":
        path = f"/tmp/users_{int(time.time())}.csv"
        rows = list_users(limit=100000, offset=0)
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["user_id", "first_name", "username", "credits", "banned", "created_at", "updated_at"])
            for r in rows:
                w.writerow([r["user_id"], r["first_name"], r["username"], r["credits"], r["banned"], r["created_at"], r["updated_at"]])
        await query.message.reply_document(InputFile(path), caption="📤 Exported users CSV")
        await query.edit_message_text("Export complete.", reply_markup=admin_panel_kb()); return

# Admin free-text for guided actions
async def admin_free_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMINS:
        return
    mode = context.user_data.get("admin_mode")
    if not mode:
        return
    txt = (update.message.text or "").strip()
    try:
        if mode == "add":
            uid_s, amt_s = txt.split()
            add_credits(int(uid_s), int(amt_s))
            await update.message.reply_text(f"✅ Added {int(amt_s)} credits to {int(uid_s)}.", reply_markup=admin_panel_kb())
        elif mode == "sub":
            uid_s, amt_s = txt.split()
            add_credits(int(uid_s), -abs(int(amt_s)))
            await update.message.reply_text(f"✅ Removed {int(amt_s)} credits from {int(uid_s)}.", reply_markup=admin_panel_kb())
        elif mode == "check":
            uid = int(txt)
            u = get_user(uid)
            if not u:
                await update.message.reply_text("User not found.", reply_markup=admin_panel_kb()); return
            await update.message.reply_text(f"User {uid} → {u['credits']} credits. {'BANNED' if u['banned'] else 'OK'}", reply_markup=admin_panel_kb())
        elif mode == "price":
            price = int(txt)
            set_setting("credit_cost", price)
            await update.message.reply_text(f"✅ Price set to {price} credits per lookup.", reply_markup=admin_panel_kb())
        elif mode == "broadcast":
            msg = txt
            total = 0
            for offset in range(0, count_users(), 100):
                rows = list_users(limit=100, offset=offset)
                for r in rows:
                    try:
                        await context.bot.send_message(r["user_id"], f"📢 {msg}")
                        total += 1
                    except Exception:
                        pass
            await update.message.reply_text(f"✅ Broadcast delivered to ~{total} users.", reply_markup=admin_panel_kb())
        elif mode == "ban":
            parts = txt.split()
            if len(parts) != 2 or parts[0] not in {"ban", "unban"}:
                await update.message.reply_text("Format: `ban user_id` or `unban user_id`", parse_mode="Markdown", reply_markup=admin_panel_kb()); return
            action, uid_s = parts
            uid = int(uid_s)
            change_ban(uid, action == "ban")
            await update.message.reply_text(f"✅ {action.upper()} set for {uid}.", reply_markup=admin_panel_kb())
        else:
            await update.message.reply_text("Unknown admin mode.", reply_markup=admin_panel_kb())
    finally:
        context.user_data["admin_mode"] = None

# ---------------- Admin command shortcuts ----------------
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("❌ Unauthorized"); return
    await update.message.reply_text("⚙️ Admin Panel", reply_markup=admin_panel_kb())

async def setprice_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("❌ Unauthorized"); return
    if not context.args:
        await update.message.reply_text("Usage: /setprice <amount>"); return
    try:
        set_setting("credit_cost", int(context.args[0]))
        await update.message.reply_text(f"✅ Price set to {int(context.args[0])}")
    except ValueError:
        await update.message.reply_text("Amount must be an integer.")

async def addcredits_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("❌ Unauthorized"); return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /addcredits <user_id> <amount>"); return
    add_credits(int(context.args[0]), int(context.args[1]))
    await update.message.reply_text(f"✅ Added {int(context.args[1])} credits to {int(context.args[0])}")

async def removecredits_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("❌ Unauthorized"); return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /removecredits <user_id> <amount>"); return
    add_credits(int(context.args[0]), -abs(int(context.args[1])))
    await update.message.reply_text(f"✅ Removed {int(context.args[1])} credits from {int(context.args[0])}")

async def checkcredits_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("❌ Unauthorized"); return
    if not context.args:
        await update.message.reply_text("Usage: /checkcredits <user_id>"); return
    u = get_user(int(context.args[0]))
    if not u:
        await update.message.reply_text("User not found."); return
    await update.message.reply_text(f"User {u['user_id']} → {u['credits']} credits. {'BANNED' if u['banned'] else 'OK'}")

async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("❌ Unauthorized"); return
    rows = list_users(limit=50, offset=0)
    if not rows:
        await update.message.reply_text("No users."); return
    lines = ["👥 *Users (first 50)*"]
    for r in rows:
        lines.append(f"{r['user_id']} | {r['first_name']} | @{r['username'] or '-'} | {r['credits']} cr | {'BANNED' if r['banned'] else 'OK'}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("❌ Unauthorized"); return
    s = stats_summary()
    price = get_setting("credit_cost", DEFAULT_CREDIT_COST)
    await update.message.reply_text(
        f"📊 Stats\nUsers: {s['users']}\nLookups: {s['lookups']}\nCredits spent: {s['credits_spent']}\nPrice: {price}"
    )

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("❌ Unauthorized"); return
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>"); return
    msg = " ".join(context.args)
    total = 0
    for offset in range(0, count_users(), 100):
        rows = list_users(limit=100, offset=offset)
        for r in rows:
            try:
                await context.bot.send_message(r["user_id"], f"📢 {msg}")
                total += 1
            except Exception:
                pass
    await update.message.reply_text(f"✅ Broadcast sent to ~{total} users.")

async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("❌ Unauthorized"); return
    if not context.args:
        await update.message.reply_text("Usage: /ban <user_id>"); return
    change_ban(int(context.args[0]), True)
    await update.message.reply_text(f"🚫 Banned {int(context.args[0])}")

async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("❌ Unauthorized"); return
    if not context.args:
        await update.message.reply_text("Usage: /unban <user_id>"); return
    change_ban(int(context.args[0]), False)
    await update.message.reply_text(f"✅ Unbanned {int(context.args[0])}")

# -------------- MAIN ----------------
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    # User commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("credits", credits_cmd))
    app.add_handler(CommandHandler("vehicle", vehicle_cmd))

    # Admin commands
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("setprice", setprice_cmd))
    app.add_handler(CommandHandler("addcredits", addcredits_cmd))
    app.add_handler(CommandHandler("removecredits", removecredits_cmd))
    app.add_handler(CommandHandler("checkcredits", checkcredits_cmd))
    app.add_handler(CommandHandler("users", users_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("ban", ban_cmd))
    app.add_handler(CommandHandler("unban", unban_cmd))

    # Buttons & admin guided modes
    app.add_handler(CallbackQueryHandler(button_router))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), admin_free_text))

    app.run_polling(allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    main()
