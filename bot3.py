# -*- coding: utf-8 -*-
"""
Vehicle OSINT Bot (Pydroid-friendly)
- Old UI with bottom reply keyboard
- API: https://api-vehicle-osint.vercel.app/?rc=
- Credits: ₹10 = 10 credits; 1 search = 10 credits
- Payment flow with confirmations (Amount -> Screenshot -> UTR)
- Admin approval queue
- Code generation and redemption system
"""

import os
import json
import time
import random
import string
import logging
import requests
from typing import Dict, Any, Optional

# Import telegram bot components with error handling
try:
    from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
    # Import telegram classes needed for keyboards
    from telegram import ReplyKeyboardMarkup, KeyboardButton
except ImportError as e:
    print(f"❌ ImportError: {e}")
    print("Please install python-telegram-bot library")
    print("Run: pip install python-telegram-bot")
    exit(1)

# ================== CONFIG ==================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8400752699:AAH_dgoJARayhGGOy0jGEEd_YURkzehy0q0")
OWNER_ID = 8120431402
DATA_FILE = "users.json"

API_ENDPOINT = "https://rtdb-2.onrender.com/vehicle?rc="

# Payments & Credits
CREDITS_PER_SEARCH = 10       # 1 search costs 10 credits
UPI_ID = "http://t.me/OSINTSUPPORTsBOT"
QR_IMAGE_URL = "https://t.me/Vechialosint"   # not a direct image; we show as text link
BUY_PRICE_TEXT = f"💳 Price: 10₹ = 10 credits\n({CREDITS_PER_SEARCH} credits = 1 search)"

# ================== LOGGING ==================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("vehicle-bot")

# ================== STORAGE ==================
def load_data():
    if not os.path.exists(DATA_FILE):
        return {}, [], {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict) and "users" in data:
                return data.get("users", {}), data.get("payments", []), data.get("codes", {})
            elif isinstance(data, dict):
                return data, [], {}
            else:
                return {}, [], {}
    except Exception as e:
        log.exception("load_data failed")
        return {}, [], {}

def save_data():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({"users": users, "payments": payments, "codes": codes}, f, indent=2, ensure_ascii=False)
    except Exception:
        log.exception("save_data failed")

users, payments, codes = load_data()

def get_user(uid: int) -> Dict[str, Any]:
    suid = str(uid)
    if suid not in users:
        users[suid] = {"credits": 0, "blocked": False, "searches": 0}
        save_data()
    return users[suid]

def new_payment_id() -> str:
    return f"P{int(time.time())}{random.randint(100,999)}"

def generate_code() -> str:
    """Generate a code in XXX-XXX-XXX format"""
    chars = string.ascii_uppercase + string.digits
    part1 = ''.join(random.choices(chars, k=3))
    part2 = ''.join(random.choices(chars, k=3))
    part3 = ''.join(random.choices(chars, k=3))
    return f"{part1}-{part2}-{part3}"

# ================== KEYBOARDS ==================
def kb_main(uid: int):
    rows = [
        [KeyboardButton("🔍 Vehicle Lookup"), KeyboardButton("💳 Buy Credits")],
        [KeyboardButton("📊 My Balance"), KeyboardButton("👤 Profile")],
        [KeyboardButton("ℹ️ Help")]
    ]
    if uid == OWNER_ID:
        rows.append([KeyboardButton("⚙️ Admin Panel")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def kb_back():
    return ReplyKeyboardMarkup([[KeyboardButton("⬅️ Back to Menu")]], resize_keyboard=True)

def kb_buy_main():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("✅ Payment Done")],[KeyboardButton("⬅️ Back to Menu")]],
        resize_keyboard=True
    )

def kb_amount_confirm():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("✅ Confirm Amount")],
            [KeyboardButton("✏️ Change Amount")],
            [KeyboardButton("⬅️ Back to Menu")],
        ], resize_keyboard=True
    )

def kb_ss_confirm():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("✅ Confirm Screenshot")],
            [KeyboardButton("📤 Re-upload Screenshot")],
            [KeyboardButton("⬅️ Back to Menu")],
        ], resize_keyboard=True
    )

def kb_utr_confirm():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("✅ Confirm UTR")],
            [KeyboardButton("✏️ Change UTR")],
            [KeyboardButton("⬅️ Back to Menu")],
        ], resize_keyboard=True
    )

def kb_admin():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📬 Pending Payments"), KeyboardButton("📈 Stats")],
            [KeyboardButton("🎫 Generate Codes"), KeyboardButton("📋 View Codes")],
            [KeyboardButton("⬅️ Back to Menu")]
        ], resize_keyboard=True
    )

# ================== HELPERS ==================
def sanitize(val, default="NA"):
    if val in [None, "", "null", "Null", "NULL"]:
        return default
    return str(val)

def render_vehicle_card(rc: str, data: Dict[str, Any]) -> str:
    owner_name = sanitize(data.get("owner_name"))
    father_name = sanitize(data.get("father_name"))
    address = sanitize(data.get("address"))
    phone = sanitize(data.get("phone"))
    rto = sanitize(data.get("rto"))

    model = sanitize(data.get("model_name"))
    variant = sanitize(data.get("maker_model"))
    vclass = sanitize(data.get("vehicle_class"))
    fuel = sanitize(data.get("fuel_type"))
    reg_date = sanitize(data.get("registration_date"))

    ins_co = sanitize(data.get("insurance_company", "None"), "None")
    ins_no = sanitize(data.get("insurance_no"))
    ins_valid = sanitize(data.get("insurance_upto") or data.get("insurance_expiry"), "None")

    fitness = sanitize(data.get("fitness_upto"))
    tax = sanitize(data.get("tax_upto"))
    puc = sanitize(data.get("puc_upto"))

    if ins_co == "NA": ins_co = "None"
    if ins_valid == "NA": ins_valid = "None"

    return f"""🚗 Vehicle Details for {rc}

👤 Owner Information
• Name: {owner_name}
• Father's Name: {father_name}
• Address: {address}
• Phone: {phone}
• RTO: {rto}

🚘 Vehicle Details
• Model: {model}
• Variant: {variant}
• Class: {vclass}
• Fuel: {fuel}
• Reg Date: {reg_date}

📄 Insurance Details
• Company: {ins_co}
• Policy No: {ins_no}
• Valid Until: {ins_valid}

📑 Other Documents
• Fitness Valid Until: {fitness}
• Tax Paid Until: {tax}
• PUC Valid Until: {puc}

👑 RA BROs"""

def fetch_vehicle(rc: str) -> Dict[str, Any]:
    try:
        url = f"{API_ENDPOINT}{rc}"
        log.info(f"Fetching vehicle data from: {url}")
        r = requests.get(url, timeout=20)
        log.info(f"API Response status: {r.status_code}")
        
        if r.status_code != 200:
            raise RuntimeError(f"API HTTP {r.status_code}")
        
        data = r.json()
        log.info(f"API Response data type: {type(data)}")
        log.info(f"API Response data: {str(data)[:200]}...")
        
        if isinstance(data, list) and data:
            data = data[0]
        if not isinstance(data, dict):
            raise RuntimeError("Unexpected API response format")
        
        # Check if the response contains error or empty data
        if not data or data.get("error") or not data.get("owner_name"):
            raise RuntimeError("No vehicle data found or invalid registration number")
            
        return data
    except requests.exceptions.RequestException as e:
        log.error(f"Network error while fetching vehicle data: {e}")
        raise RuntimeError(f"Network error: {str(e)}")
    except json.JSONDecodeError as e:
        log.error(f"JSON decode error: {e}")
        raise RuntimeError("Invalid response format from API")
    except Exception as e:
        log.error(f"Unexpected error in fetch_vehicle: {e}")
        raise RuntimeError(f"Unexpected error: {str(e)}")

# ================== COMMANDS ==================
async def cmd_start(update, ctx):
    uid = update.effective_user.id
    u = get_user(uid)
    if u["blocked"]:
        await update.message.reply_text("🚫 You are blocked from using this bot.")
        return
    ctx.user_data.clear()
    await update.message.reply_text("👋 Welcome to OSINT Vehicle Bot!", reply_markup=kb_main(uid))

async def cmd_help(update, ctx):
    uid = update.effective_user.id
    await update.message.reply_text(
        "ℹ️ Help\n\n"
        f"- Each search costs {CREDITS_PER_SEARCH} credits.\n"
        "- Buy credits via 💳 Buy Credits (send screenshot & UTR).\n"
        "- Use /redeem CODE to redeem gift codes.\n"
        "- Admin reviews payments within 10–25 minutes.\n\n"
        f"UPI: {UPI_ID}\nQR message: {QR_IMAGE_URL}",
        reply_markup=kb_main(uid)
    )

async def cmd_add(update, ctx):
    if update.effective_user.id != OWNER_ID:
        return
    try:
        target = str(ctx.args[0])
        amount = int(ctx.args[1])
    except Exception:
        await update.message.reply_text("Usage: /add <user_id> <credits>")
        return
    u = get_user(int(target))
    u["credits"] += amount
    save_data()
    await update.message.reply_text(f"✅ Added {amount} credits to {target} (balance: {u['credits']}).")

async def cmd_block(update, ctx):
    if update.effective_user.id != OWNER_ID:
        return
    try:
        target = str(ctx.args[0])
    except Exception:
        await update.message.reply_text("Usage: /block <user_id>")
        return
    u = get_user(int(target))
    u["blocked"] = True
    save_data()
    await update.message.reply_text(f"🚫 Blocked {target}")

async def cmd_unblock(update, ctx):
    if update.effective_user.id != OWNER_ID:
        return
    try:
        target = str(ctx.args[0])
    except Exception:
        await update.message.reply_text("Usage: /unblock <user_id>")
        return
    u = get_user(int(target))
    u["blocked"] = False
    save_data()
    await update.message.reply_text(f"✅ Unblocked {target}")

async def cmd_users(update, ctx):
    if update.effective_user.id != OWNER_ID:
        return
    await update.message.reply_text(f"👥 Users: {len(users)} | Payments: {len(payments)} | Codes: {len(codes)}")

async def cmd_approve(update, ctx):
    if update.effective_user.id != OWNER_ID:
        return
    try:
        pay_id = ctx.args[0]
        add_credits = int(ctx.args[1])
    except Exception:
        await update.message.reply_text("Usage: /approve <payment_id> <credits_to_add>")
        return
    match = None
    for p in payments:
        if p["id"] == pay_id:
            match = p
            break
    if not match:
        await update.message.reply_text("❌ Payment ID not found.")
        return
    if match.get("status") != "pending":
        await update.message.reply_text("ℹ️ Payment already processed.")
        return

    u = get_user(int(match["user_id"]))
    u["credits"] += add_credits
    match["status"] = "approved"
    match["approved_credits"] = add_credits
    match["approved_ts"] = int(time.time())
    save_data()

    await update.message.reply_text(f"✅ Approved {pay_id}. Added {add_credits} credits to {match['user_id']} (bal: {u['credits']}).")
    try:
        await ctx.bot.send_message(
            chat_id=match["user_id"],
            text=f"✅ Your payment `{pay_id}` has been approved.\n💰 Credits added: {add_credits}\n💳 Balance: {u['credits']}",
            parse_mode="Markdown"
        )
    except Exception:
        pass

async def cmd_gen(update, ctx):
    """Generate redemption codes. Usage: /gen <number_of_users> <credits_per_code>"""
    if update.effective_user.id != OWNER_ID:
        return
    
    try:
        num_users = int(ctx.args[0])
        credits_per_code = int(ctx.args[1])
    except Exception:
        await update.message.reply_text("Usage: /gen <number_of_users> <credits_per_code>\nExample: /gen 5 100")
        return
    
    if num_users <= 0 or credits_per_code <= 0:
        await update.message.reply_text("❌ Both numbers must be greater than 0.")
        return
    
    if num_users > 50:
        await update.message.reply_text("❌ Maximum 50 codes can be generated at once.")
        return
    
    generated_codes = []
    for _ in range(num_users):
        code = generate_code()
        # Ensure code is unique
        while code in codes:
            code = generate_code()
        
        codes[code] = {
            "credits": credits_per_code,
            "created_by": update.effective_user.id,
            "created_ts": int(time.time()),
            "redeemed": False,
            "redeemed_by": None,
            "redeemed_ts": None
        }
        generated_codes.append(code)
    
    save_data()
    
    codes_text = "\n".join([f"`{code}`" for code in generated_codes])
    await update.message.reply_text(
        f"✅ Generated {num_users} codes, each worth {credits_per_code} credits:\n\n{codes_text}",
        parse_mode="Markdown"
    )

async def cmd_redeem(update, ctx):
    """Redeem a code. Usage: /redeem XXX-XXX-XXX"""
    uid = update.effective_user.id
    u = get_user(uid)
    
    if u["blocked"]:
        await update.message.reply_text("🚫 You are blocked from using this bot.")
        return
    
    try:
        code = ctx.args[0].upper().strip()
    except Exception:
        await update.message.reply_text("Usage: /redeem XXX-XXX-XXX\nExample: /redeem ABC-123-XYZ")
        return
    
    # Validate code format
    if not code or len(code) != 11 or code.count('-') != 2:
        await update.message.reply_text("❌ Invalid code format. Use XXX-XXX-XXX format.")
        return
    
    if code not in codes:
        await update.message.reply_text("❌ Invalid or expired code.")
        return
    
    code_data = codes[code]
    if code_data["redeemed"]:
        await update.message.reply_text("❌ This code has already been redeemed.")
        return
    
    # Redeem the code
    credits_to_add = code_data["credits"]
    u["credits"] += credits_to_add
    
    code_data["redeemed"] = True
    code_data["redeemed_by"] = uid
    code_data["redeemed_ts"] = int(time.time())
    
    save_data()
    
    await update.message.reply_text(
        f"✅ Code redeemed successfully!\n💰 Credits added: {credits_to_add}\n💳 New balance: {u['credits']} credits"
    )
    
    # Notify admin
    try:
        await ctx.bot.send_message(
            chat_id=OWNER_ID,
            text=f"🎫 Code redeemed:\nCode: `{code}`\nUser: {uid}\nCredits: {credits_to_add}",
            parse_mode="Markdown"
        )
    except Exception:
        pass

# ================== MESSAGE HANDLER ==================
async def on_message(update, ctx):
    if update.message is None:
        return
    uid = update.effective_user.id
    msg = update.message
    text = (msg.text or "").strip()

    u = get_user(uid)
    if u["blocked"]:
        await msg.reply_text("🚫 You are blocked.")
        return

    # Global back
    if text == "⬅️ Back to Menu":
        ctx.user_data.clear()
        await msg.reply_text("🏠 Back to main menu.", reply_markup=kb_main(uid))
        return

    step = ctx.user_data.get("step")

    # ====== Payment: Amount entry ======
    if step == "pay_amount":
        amt_raw = text.lower().replace("rs", "").replace("₹", "").strip()
        if not amt_raw.replace(".", "", 1).isdigit():
            await msg.reply_text("❌ Enter amount in numbers only (e.g., 10).", reply_markup=kb_back())
            return
        amount = float(amt_raw)
        if amount <= 0:
            await msg.reply_text("❌ Amount must be > 0.", reply_markup=kb_back())
            return
        ctx.user_data["amount"] = amount
        ctx.user_data["step"] = "pay_amount_confirm"
        show_amt = int(amount) if float(amount).is_integer() else amount
        await msg.reply_text(
            f"💰 You entered: ₹{show_amt}\nConfirm this amount?",
            reply_markup=kb_amount_confirm()
        )
        return

    # Confirm / change amount
    if text == "✅ Confirm Amount" and step == "pay_amount_confirm":
        ctx.user_data["step"] = "pay_ss"
        await msg.reply_text("📷 Please upload your payment screenshot as a photo.", reply_markup=kb_ss_confirm())
        return
    if text == "✏️ Change Amount" and step in ("pay_amount_confirm", "pay_utr_confirm"):
        ctx.user_data["step"] = "pay_amount"
        await msg.reply_text("✏️ Enter new amount (in ₹):", reply_markup=kb_back())
        return

    # Wait for screenshot (if user types instead)
    if step == "pay_ss":
        await msg.reply_text("📷 Send the screenshot as a photo. Or tap Back.", reply_markup=kb_ss_confirm())
        return

    # Confirm screenshot
    if text == "✅ Confirm Screenshot" and step == "pay_ss_confirm":
        ctx.user_data["step"] = "pay_utr"
        await msg.reply_text("🔑 Now enter your UTR / Transaction ID:", reply_markup=kb_utr_confirm())
        return
    if text == "📤 Re-upload Screenshot" and step in ("pay_ss", "pay_ss_confirm"):
        ctx.user_data["step"] = "pay_ss"
        ctx.user_data.pop("ss_file_id", None)
        await msg.reply_text("📷 Please upload your payment screenshot again.", reply_markup=kb_ss_confirm())
        return

    # Enter UTR
    if step == "pay_utr":
        if not text or len(text) < 4:
            await msg.reply_text("❌ Enter a valid UTR / Transaction ID.", reply_markup=kb_utr_confirm())
            return
        ctx.user_data["utr"] = text
        ctx.user_data["step"] = "pay_utr_confirm"
        await msg.reply_text(f"🔎 You entered UTR: {text}\nConfirm?", reply_markup=kb_utr_confirm())
        return

    # Confirm UTR -> submit payment
    if text == "✅ Confirm UTR" and step == "pay_utr_confirm":
        amount = ctx.user_data.get("amount")
        utr = ctx.user_data.get("utr")
        ss_file_id = ctx.user_data.get("ss_file_id")

        pay_id = new_payment_id()
        record = {
            "id": pay_id,
            "user_id": uid,
            "amount": amount,
            "utr": utr,
            "screenshot_file_id": ss_file_id,
            "status": "pending",
            "ts": int(time.time())
        }
        payments.append(record)
        save_data()

        try:
            caption = (
                f"🧾 Payment Submitted\n"
                f"ID: {pay_id}\nUser: {uid}\n"
                f"Amount: ₹{int(amount) if float(amount).is_integer() else amount}\n"
                f"UTR: {utr}"
            )
            if ss_file_id:
                await ctx.bot.send_photo(OWNER_ID, ss_file_id, caption=caption)
            else:
                await ctx.bot.send_message(OWNER_ID, caption)
            await ctx.bot.send_message(
                OWNER_ID,
                "Admin actions:\n"
                f"/approve {pay_id} <credits_to_add>\n"
                f"/add {uid} <credits>\n"
                f"/block {uid}  |  /unblock {uid}"
            )
        except Exception:
            log.exception("Failed to notify admin")

        ctx.user_data.clear()
        await msg.reply_text(
            "📥 Payment details submitted!\n"
            "⏳ Please wait 10–25 minutes — admin will verify and approve.",
            reply_markup=kb_main(uid)
        )
        return

    # ====== Vehicle lookup ======
    if step == "await_rc":
        rc = text.upper().replace(" ", "")
        if not rc:
            await msg.reply_text("❌ Please enter a valid RC number.", reply_markup=kb_back())
            return

        if u["credits"] < CREDITS_PER_SEARCH:
            ctx.user_data.clear()
            await msg.reply_text(
                f"❌ Not enough credits. Each search costs {CREDITS_PER_SEARCH} credits.",
                reply_markup=kb_main(uid)
            )
            return

        await msg.reply_text(f"🔎 Searching for vehicle: {rc} ...", reply_markup=kb_back())
        try:
            data = fetch_vehicle(rc)
            # Deduct only on success
            u["credits"] -= CREDITS_PER_SEARCH
            u["searches"] += 1
            save_data()
            card = render_vehicle_card(rc, data)
            await msg.reply_text(card, reply_markup=kb_main(uid))
        except Exception as e:
            log.exception("API error")
            await msg.reply_text(f"⚠️ Unable to fetch details right now.\nReason: {e}", reply_markup=kb_main(uid))
        finally:
            ctx.user_data.clear()
        return

    # ================== MAIN BUTTONS ==================
    if text == "🔍 Vehicle Lookup":
        if u["credits"] < CREDITS_PER_SEARCH:
            await msg.reply_text(
                f"⚠️ Not enough credits!\n\n{BUY_PRICE_TEXT}\n\nGo to 💳 Buy Credits.",
                reply_markup=kb_main(uid)
            )
            return
        ctx.user_data.clear()
        ctx.user_data["step"] = "await_rc"
        await msg.reply_text("📮 Send RC number (e.g., BR29AB7794):", reply_markup=kb_back())
        return

    if text == "💳 Buy Credits":
        ctx.user_data.clear()
        await msg.reply_text(
            f"💳 Buy Credits\n\n{BUY_PRICE_TEXT}\n\n"
            f"📌 UPI ID: {UPI_ID}\n"
            f"🖼️ QR Code post: {QR_IMAGE_URL}\n\n"
            "After paying, tap '✅ Payment Done'.",
            reply_markup=kb_buy_main()
        )
        return

    if text == "✅ Payment Done":
        ctx.user_data.clear()
        ctx.user_data["step"] = "pay_amount"
        await msg.reply_text("🔢 Enter the amount you paid (numbers only, e.g., 10):", reply_markup=kb_back())
        return

    if text == "📊 My Balance":
        await msg.reply_text(f"💰 Credits: {u['credits']}", reply_markup=kb_main(uid))
        return

    if text == "👤 Profile":
        await msg.reply_text(
            "👤 Your Profile\n"
            f"• User ID: {uid}\n"
            f"• Credits: {u['credits']}\n"
            f"• Total Searches: {u.get('searches', 0)}",
            reply_markup=kb_main(uid)
        )
        return

    if text == "ℹ️ Help":
        await cmd_help(update, ctx)
        return

    if text == "⚙️ Admin Panel" and uid == OWNER_ID:
        await msg.reply_text(
            "⚙️ Admin Panel\n\n"
            "Commands:\n"
            "• /approve <payment_id> <credits>\n"
            "• /add <user_id> <credits>\n"
            "• /block <user_id>\n"
            "• /unblock <user_id>\n"
            "• /gen <users> <credits>\n"
            "• /users",
            reply_markup=kb_admin()
        )
        return

    if text == "📬 Pending Payments" and uid == OWNER_ID:
        pend = [p for p in payments if p.get("status") == "pending"]
        if not pend:
            await msg.reply_text("✅ No pending payments.", reply_markup=kb_admin())
        else:
            pend_sorted = sorted(pend, key=lambda x: x["ts"], reverse=True)[:12]
            lines = []
            for p in pend_sorted:
                amt = p.get("amount")
                show_amt = int(amt) if float(amt).is_integer() else amt
                lines.append(f"ID: {p['id']} | User: {p['user_id']} | ₹{show_amt} | UTR: {p.get('utr','N/A')}")
            await msg.reply_text("📬 Pending Payments\n" + "\n".join(lines), reply_markup=kb_admin())
        return

    if text == "📈 Stats" and uid == OWNER_ID:
        total_users = len(users)
        total_credits = sum(u2.get("credits", 0) for u2 in users.values())
        total_searches = sum(u2.get("searches", 0) for u2 in users.values())
        pend_count = sum(1 for p in payments if p.get("status") == "pending")
        redeemed_codes = sum(1 for c in codes.values() if c.get("redeemed"))
        active_codes = len(codes) - redeemed_codes
        
        await msg.reply_text(
            "📈 Bot Stats\n"
            f"• Users: {total_users}\n"
            f"• Total Credits: {total_credits}\n"
            f"• Total Searches: {total_searches}\n"
            f"• Pending Payments: {pend_count}\n"
            f"• Active Codes: {active_codes}\n"
            f"• Redeemed Codes: {redeemed_codes}",
            reply_markup=kb_admin()
        )
        return

    if text == "🎫 Generate Codes" and uid == OWNER_ID:
        await msg.reply_text(
            "🎫 Generate Codes\n\n"
            "Use command: /gen <users> <credits>\n"
            "Example: /gen 5 100\n\n"
            "This will create 5 codes, each worth 100 credits.",
            reply_markup=kb_admin()
        )
        return

    if text == "📋 View Codes" and uid == OWNER_ID:
        if not codes:
            await msg.reply_text("📋 No codes found.", reply_markup=kb_admin())
            return
        
        active_codes = []
        redeemed_codes = []
        
        for code, data in codes.items():
            if data.get("redeemed"):
                redeemed_codes.append(f"`{code}` - {data['credits']} credits (Redeemed by {data['redeemed_by']})")
            else:
                active_codes.append(f"`{code}` - {data['credits']} credits")
        
        response = "📋 Codes Status\n\n"
        
        if active_codes:
            response += "🟢 Active Codes:\n" + "\n".join(active_codes[:10])
            if len(active_codes) > 10:
                response += f"\n... and {len(active_codes) - 10} more"
        
        if redeemed_codes:
            response += "\n\n🔴 Recently Redeemed:\n" + "\n".join(redeemed_codes[:5])
            if len(redeemed_codes) > 5:
                response += f"\n... and {len(redeemed_codes) - 5} more"
        
        await msg.reply_text(response, reply_markup=kb_admin(), parse_mode="Markdown")
        return

    # Fallback
    await msg.reply_text("❌ Invalid input. Please use the menu buttons.", reply_markup=kb_main(uid))

# ================== PHOTO HANDLER ==================
async def on_photo(update, ctx):
    if update.message is None or not update.message.photo:
        return
    step = ctx.user_data.get("step")
    if step not in ("pay_ss", "pay_ss_confirm"):
        return
    photo = update.message.photo[-1]
    ctx.user_data["ss_file_id"] = photo.file_id
    ctx.user_data["step"] = "pay_ss_confirm"
    await update.message.reply_text(
        "✅ Screenshot received.\nConfirm or re-upload?",
        reply_markup=kb_ss_confirm()
    )

# ================== MAIN ==================
def main():
    print("🤖 Bot starting...")
    try:
        app = Application.builder().token(BOT_TOKEN).build()
        
        # Commands
        app.add_handler(CommandHandler("start", cmd_start))
        app.add_handler(CommandHandler("help", cmd_help))
        app.add_handler(CommandHandler("add", cmd_add))
        app.add_handler(CommandHandler("block", cmd_block))
        app.add_handler(CommandHandler("unblock", cmd_unblock))
        app.add_handler(CommandHandler("users", cmd_users))
        app.add_handler(CommandHandler("approve", cmd_approve))
        app.add_handler(CommandHandler("gen", cmd_gen))
        app.add_handler(CommandHandler("redeem", cmd_redeem))
        
        # Message handlers using proper filters
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
        app.add_handler(MessageHandler(filters.PHOTO, on_photo))
        
        print(f"🚀 Bot started! Users: {len(users)} | Payments: {len(payments)} | Codes: {len(codes)}")
        app.run_polling()
    except Exception as e:
        log.exception("Bot startup failed")
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()
