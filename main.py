
import os
import asyncio
import sqlite3
import threading
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
MAIN_BOT_TOKEN = os.environ.get("BOT_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
PORT = int(os.environ.get("PORT", 8080))

UPDATE_CHANNEL_URL = "https://t.me/Ss_GodX"
MAIN_BOT_USERNAME = ""  # कोड चालू होते ही अपने आप भर जाएगा

DB_FILE = "link_changer.db"

# --- DATABASE ENGINE (WAL MODE) ---
def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=60.0, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

def init_db():
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS bots (
            token TEXT PRIMARY KEY,
            owner_id INTEGER,
            username TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS bot_channels (
            token TEXT PRIMARY KEY,
            channel_id INTEGER
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)""")
        conn.commit()

init_db()

# --- WEB SERVER FOR 24/7 UPTIME ---
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args):
        pass

def run_web_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    server.serve_forever()

# --- AUTO-DELETE JOB (59s) ---
async def delete_job(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    chat_id = job_data["chat_id"]
    msg_ids = job_data["msg_ids"]
    for mid in msg_ids:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception:
            pass

# --- UI & BUTTON BUILDERS ---
def get_start_keyboard(is_clone: bool = False):
    buttons = [
        [InlineKeyboardButton("📢 ᴜᴘᴅᴀᴛᴇ ᴄʜᴀɴɴᴇʟ", url=UPDATE_CHANNEL_URL)]
    ]
    
    # अगर यह किसी का क्लोन बॉट है, तो तुम्हारे मेन बॉट का क्लोन मेकर बटन जुड़ेगा
    if is_clone and MAIN_BOT_USERNAME:
        clone_promo_url = f"https://t.me/{MAIN_BOT_USERNAME}?start=clone"
        buttons.append([
            InlineKeyboardButton("🤖 ᴄʀᴇᴀᴛᴇ ʏᴏᴜʀ ᴏᴡɴ ʙᴏᴛ", url=clone_promo_url)
        ])

    buttons.append([
        InlineKeyboardButton("🔗 ɢᴇᴛ ɪɴᴠɪᴛᴇ ʟɪɴᴋ", callback_data="get_link"),
        InlineKeyboardButton("✖️ ᴄʟᴏsᴇ", callback_data="close_msg")
    ])
    
    return InlineKeyboardMarkup(buttons)

# --- COMMON BOT HANDLERS ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_chat.type != "private":
        return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    token = context.bot.token
    is_clone = (token != MAIN_BOT_TOKEN)

    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO users VALUES (?)", (user_id,))
        conn.commit()

    if is_clone:
        welcome_text = (
            "╭─ ⚡ <b>ʟɪɴᴋ ᴄʜᴀɴɢᴇʀ • ᴄʟᴏɴᴇ ᴇᴅɪᴛɪᴏɴ</b>\n"
            "│\n"
            "├ 👋 <i>ʜᴇʟʟᴏ! ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ᴛʜɪs ʙᴏᴛ.</i>\n"
            "├ 🛡️ <b>sᴛᴀᴛᴜs:</b> ᴏɴʟɪɴᴇ (24/7 sᴇᴄᴜʀᴇ)\n"
            "├ 🤖 <i>यह एक क्लोन बॉट है! अपना खुद का बॉट बनाने</i>\n"
            "│   <i>के लिए नीचे दिए गए बटन पर क्लिक करें।</i>\n"
            "│\n"
            "╰─ ⏳ <i>ᴛʜɪs ᴍᴇssᴀɢᴇ ᴡɪʟʟ ᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇ ɪɴ 59 sᴇᴄᴏɴᴅs...</i>"
        )
    else:
        welcome_text = (
            "╭─ ⚡ <b>ʟɪɴᴋ ᴄʜᴀɴɢᴇʀ • ᴍᴀsᴛᴇʀ ᴇᴅɪᴛɪᴏɴ</b>\n"
            "│\n"
            "├ 👋 <i>ʜᴇʟʟᴏ! ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ᴏᴜʀ ᴏғғɪᴄɪᴀʟ ʙᴏᴛ.</i>\n"
            "├ 🛡️ <b>sᴛᴀᴛᴜs:</b> ᴏɴʟɪɴᴇ (24/7 sᴇᴄᴜʀᴇ)\n"
            "├ 💡 <i>ᴄʟɪᴄᴋ ᴛʜᴇ ʙᴜᴛᴛᴏɴs ʙᴇʟᴏᴡ ᴛᴏ ɴᴀᴠɪɢᴀᴛᴇ.</i>\n"
            "│\n"
            "╰─ ⏳ <i>ᴛʜɪs ᴍᴇssᴀɢᴇ ᴡɪʟʟ ᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇ ɪɴ 59 sᴇᴄᴏɴᴅs...</i>"
        )

    s_msg = await update.message.reply_text(
        welcome_text,
        reply_markup=get_start_keyboard(is_clone=is_clone),
        parse_mode="HTML",
        protect_content=True
    )
    context.job_queue.run_once(delete_job, 59, data={"chat_id": chat_id, "msg_ids": [s_msg.message_id, update.message.message_id]})

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    chat_id = query.message.chat_id
    token = context.bot.token

    if data == "close_msg":
        await query.answer()
        try:
            await query.message.delete()
        except Exception:
            pass

    elif data == "get_link":
        await query.answer()
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT channel_id FROM bot_channels WHERE token = ?", (token,))
            row = c.fetchone()

        if not row:
            err_text = (
                "╭─ ⚠️ <b>ᴄʜᴀɴɴᴇʟ ɴᴏᴛ ᴄᴏɴғɪɢᴜʀᴇᴅ!</b>\n"
                "│\n"
                "╰─ 💡 एडमिन ने अभी तक चैनल सेट नहीं किया है।"
            )
            msg = await query.message.reply_text(err_text, parse_mode="HTML")
            context.job_queue.run_once(delete_job, 15, data={"chat_id": chat_id, "msg_ids": [msg.message_id]})
            return

        target_channel = row[0]
        try:
            invite = await context.bot.create_chat_invite_link(
                chat_id=target_channel,
                member_limit=1
            )
            invite_url = invite.invite_link

            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔷 ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ 🔷", url=invite_url)],
                [InlineKeyboardButton("✖️ ᴄʟᴏsᴇ", callback_data="close_msg")]
            ])

            res_text = (
                "╭─ ⚡ <b>ʏᴏᴜʀ ɪɴᴠɪᴛᴇ ʟɪɴᴋ ɪs ʀᴇᴀᴅʏ!</b>\n"
                "│\n"
                f"├ 🔗 <b>ʟɪɴᴋ:</b> <code>{invite_url}</code>\n"
                "│\n"
                "├ 💡 <i>ᴛᴀᴘ ᴏɴ ᴛʜᴇ ʟɪɴᴋ ᴛᴏ ᴄᴏᴘʏ ᴏʀ ᴜsᴇ ʙᴜᴛᴛᴏɴ!</i>\n"
                "╰─ ⏳ <i>ᴛʜɪs ᴍᴇssᴀɢᴇ ᴡɪʟʟ ᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇ ɪɴ 59 sᴇᴄᴏɴᴅs...</i>"
            )

            res_msg = await query.message.reply_text(res_text, reply_markup=markup, parse_mode="HTML", protect_content=True)
            context.job_queue.run_once(delete_job, 59, data={"chat_id": chat_id, "msg_ids": [res_msg.message_id]})
        except Exception as e:
            logger.error(f"Invite Link Error: {e}")
            err = await query.message.reply_text("❌ <b>Error:</b> बॉट को चैनल में Admin (Add Users rights) बनायें!", parse_mode="HTML")
            context.job_queue.run_once(delete_job, 15, data={"chat_id": chat_id, "msg_ids": [err.message_id]})

# --- BOT CONFIGURATION COMMANDS ---
async def setchannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    token = context.bot.token

    is_authorized = False
    if user_id == OWNER_ID:
        is_authorized = True
    else:
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT owner_id FROM bots WHERE token = ?", (token,))
            row = c.fetchone()
            if row and row[0] == user_id:
                is_authorized = True

    if not is_authorized:
        return

    if not context.args:
        await update.message.reply_text("╭─ ᴇʀʀᴏʀ\n╰ ᴜsᴀɢᴇ: /setchannel -100xxxxxxxxxx")
        return

    try:
        ch_id = int(context.args[0])
        with get_db() as conn:
            conn.execute("INSERT OR REPLACE INTO bot_channels VALUES (?, ?)", (token, ch_id))
            conn.commit()

        await update.message.reply_text(
            "╭─ ᴄʜᴀɴɴᴇʟ ᴄᴏɴғɪɢᴜʀᴇᴅ\n"
            "│\n"
            f"├ 🆔 <b>ᴄʜᴀɴɴᴇʟ ɪᴅ:</b> <code>{ch_id}</code>\n"
            "╰─ ✅ <b>सफलतापूर्वक सेव कर दिया गया!</b>",
            parse_mode="HTML"
        )
    except ValueError:
        await update.message.reply_text("❌ कृपया सही न्यूमेरिक ID (-100...) दर्ज करें।")

# --- MYBOT STATUS (FOR CLONE OWNERS) ---
async def mybot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    token = context.bot.token

    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT owner_id, username FROM bots WHERE token = ?", (token,))
        bot_row = c.fetchone()
        c.execute("SELECT channel_id FROM bot_channels WHERE token = ?", (token,))
        ch_row = c.fetchone()

    ch_text = f"<code>{ch_row[0]}</code>" if ch_row else "ɴᴏᴛ sᴇᴛ (ᴜsᴇ /setchannel)"
    bot_name = f"@{bot_row[1]}" if bot_row else f"@{context.bot.username}"

    res = (
        "╭─ ⚙️ <b>ʏᴏᴜʀ ʙᴏᴛ sᴇᴛᴛɪɴɢs</b>\n"
        "│\n"
        f"├ 🤖 <b>ʙᴏᴛ:</b> {bot_name}\n"
        f"├ 📢 <b>ᴄʜᴀɴɴᴇʟ:</b> {ch_text}\n"
        "├ ⏱️ <b>ᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇ:</b> 59 sᴇᴄᴏɴᴅs\n"
        "│\n"
        "╰─ 💡 /setchannel <i>सेंड करके कभी भी चैनल बदल सकते हैं।</i>"
    )
    await update.message.reply_text(res, parse_mode="HTML")

# --- PUBLIC CLONE COMMAND (/clone) ---
async def clone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not context.args:
        help_msg = (
            "╭─ 🤖 <b>ᴄʟᴏɴᴇ ʏᴏᴜʀ ᴏᴡɴ ʙᴏᴛ</b>\n"
            "│\n"
            "├ 1. @BotFather पर जाकर नया बॉट बनाएँ।\n"
            "├ 2. अपना बॉट टोकन कॉपी करें।\n"
            "├ 3. यहाँ भेजें: <code>/clone YOUR_BOT_TOKEN</code>\n"
            "│\n"
            "╰─ ⚡ <i>आपका अपना लिंक चेंजर बॉट तुरंत लाइव हो जाएगा!</i>"
        )
        await update.message.reply_text(help_msg, parse_mode="HTML")
        return

    new_token = context.args[0].strip()

    try:
        temp_app = ApplicationBuilder().token(new_token).build()
        await temp_app.initialize()
        bot_info = await temp_app.bot.get_me()

        clone_commands = [
            BotCommand("start", "⚡ sᴛᴀʀᴛ ᴛʜᴇ ʙᴏᴛ"),
            BotCommand("setchannel", "📢 sᴇᴛ ʏᴏᴜʀ ᴄʜᴀɴɴᴇʟ ɪᴅ"),
            BotCommand("mybot", "⚙️ ᴠɪᴇᴡ ʏᴏᴜʀ ʙᴏᴛ sᴇᴛᴛɪɴɢs"),
        ]
        await temp_app.bot.set_my_commands(clone_commands)
        await temp_app.shutdown()

        with get_db() as conn:
            conn.execute("INSERT OR REPLACE INTO bots VALUES (?, ?, ?)", (new_token, user_id, bot_info.username))
            conn.commit()

        asyncio.create_task(run_cloned_bot(new_token))

        res = (
            "╭─ 🎉 <b>ʙᴏᴛ ᴄʟᴏɴᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n"
            "│\n"
            f"├ 🤖 <b>ʙᴏᴛ:</b> @{bot_info.username}\n"
            f"├ 👑 <b>ᴏᴡɴᴇʀ ɪᴅ:</b> <code>{user_id}</code>\n"
            "├ 📋 <b>साइड मेन्यू कमांड्स:</b> ऑटोमैटिक सेट हो गईं!\n"
            "│\n"
            "├ <b>अगला कदम:</b>\n"
            f"├ 1. अपने बॉट @{bot_info.username} को अपने चैनल में एडमिन बनाएँ।\n"
            "├ 2. अपने बॉट में जाकर कमांड दें:\n"
            "│     <code>/setchannel -100xxxxxxxxxx</code>\n"
            "│\n"
            "╰─ 🚀 <b>आपका बॉट पूरी तरह तैयार है!</b>"
        )
        await update.message.reply_text(res, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Clone error: {e}")
        await update.message.reply_text("❌ <b>अमान्य टोकन!</b> कृपया @BotFather से सही टोकन कॉपी करें।", parse_mode="HTML")

# --- CLONE BOT RUNNER ---
async def run_cloned_bot(token: str):
    try:
        clone_app = ApplicationBuilder().token(token).concurrent_updates(True).build()
        clone_app.add_handler(CommandHandler("start", start_handler))
        clone_app.add_handler(CommandHandler("setchannel", setchannel))
        clone_app.add_handler(CommandHandler("mybot", mybot))
        clone_app.add_handler(CallbackQueryHandler(callback_handler))

        await clone_app.initialize()
        
        clone_commands = [
            BotCommand("start", "⚡ sᴛᴀʀᴛ ᴛʜᴇ ʙᴏᴛ"),
            BotCommand("setchannel", "📢 sᴇᴛ ʏᴏᴜʀ ᴄʜᴀɴɴᴇʟ ɪᴅ"),
            BotCommand("mybot", "⚙️ ᴠɪᴇᴡ ʏᴏᴜʀ ʙᴏᴛ sᴇᴛᴛɪɴɢs"),
        ]
        try:
            await clone_app.bot.set_my_commands(clone_commands)
        except Exception:
            pass

        await clone_app.start()
        await clone_app.updater.start_polling(drop_pending_updates=True)
        logger.info(f"Cloned bot started successfully: {token[:10]}***")
    except Exception as e:
        logger.error(f"Failed to start cloned bot {token[:10]}***: {e}")

# --- STARTUP LOGIC ---
async def start_all_bots(main_app):
    global MAIN_BOT_USERNAME
    await main_app.initialize()

    bot_info = await main_app.bot.get_me()
    MAIN_BOT_USERNAME = bot_info.username

    main_commands = [
        BotCommand("start", "⚡ sᴛᴀʀᴛ ᴛʜᴇ ʙᴏᴛ"),
        BotCommand("clone", "🤖 ᴄʟᴏɴᴇ ʏᴏᴜʀ ᴏᴡɴ ʙᴏᴛ"),
        BotCommand("setchannel", "📢 sᴇᴛ ᴍᴀɪɴ ᴄʜᴀɴɴᴇʟ ɪᴅ"),
    ]
    try:
        await main_app.bot.set_my_commands(main_commands)
    except Exception as e:
        logger.error(f"Could not set main commands: {e}")

    await main_app.start()
    await main_app.updater.start_polling(drop_pending_updates=True)

    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT token FROM bots")
        saved_bots = c.fetchall()

    for row in saved_bots:
        asyncio.create_task(run_cloned_bot(row[0]))

    logger.info("Main bot and all cloned bots are running.")

def main():
    threading.Thread(target=run_web_server, daemon=True).start()

    main_app = (
        ApplicationBuilder()
        .token(MAIN_BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )

    main_app.add_handler(CommandHandler("start", start_handler))
    main_app.add_handler(CommandHandler("setchannel", setchannel))
    main_app.add_handler(CommandHandler("clone", clone))
    main_app.add_handler(CallbackQueryHandler(callback_handler))

    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_all_bots(main_app))
    loop.run_forever()

if __name__ == "__main__":
    main()
