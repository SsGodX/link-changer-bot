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
    ChatJoinRequestHandler,
    ContextTypes,
)

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
MAIN_BOT_TOKEN = os.environ.get("BOT_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
PORT = int(os.environ.get("PORT", 8080))
UPDATE_CHANNEL_URL = "https://t.me/Ss_GodX"
MAIN_BOT_USERNAME = ""

DB_FILE = "link_changer.db"

# --- DATABASE SETUP (WAL MODE) ---
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
            username TEXT,
            header_pic TEXT,
            auto_approve INTEGER DEFAULT 1,
            approval_delay INTEGER DEFAULT 0
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS channels (
            token TEXT,
            channel_id INTEGER,
            channel_title TEXT,
            auto_approve INTEGER DEFAULT 1,
            PRIMARY KEY(token, channel_id)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS users (
            token TEXT,
            user_id INTEGER,
            PRIMARY KEY(token, user_id)
        )""")
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

# --- HELPER: AUTHORIZATION ---
def is_bot_admin(token: str, user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT owner_id FROM bots WHERE token = ?", (token,))
        row = c.fetchone()
        return bool(row and row[0] == user_id)

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

# --- START KEYBOARD ---
def get_start_markup(is_clone: bool):
    buttons = [
        [InlineKeyboardButton("📢 ᴜᴘᴅᴀᴛᴇ ᴄʜᴀɴɴᴇʟ", url=UPDATE_CHANNEL_URL)]
    ]
    if is_clone and MAIN_BOT_USERNAME:
        buttons.append([
            InlineKeyboardButton("🤖 ᴄʟᴏɴᴇ ʏᴏᴜʀ ᴏᴡɴ ʙᴏᴛ", url=f"https://t.me/{MAIN_BOT_USERNAME}?start=clone")
        ])
    else:
        buttons.append([
            InlineKeyboardButton("🤖 ᴄʟᴏɴᴇ ʏᴏᴜʀ ᴏᴡɴ ʙᴏᴛ", callback_data="clone_info")
        ])

    buttons.append([
        InlineKeyboardButton("🔗 ɢᴇᴛ ɪɴᴠɪᴛᴇ ʟɪɴᴋ", callback_data="get_link"),
        InlineKeyboardButton("✖️ ᴄʟᴏsᴇ", callback_data="close_msg")
    ])
    return InlineKeyboardMarkup(buttons)

# --- COMMAND: /start ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_chat.type != "private":
        return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    token = context.bot.token
    is_clone = (token != MAIN_BOT_TOKEN)

    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO users VALUES (?, ?)", (token, user_id))
        conn.commit()

    # Deep-link handling (?start=req_xxx or ?start=join_xxx)
    if context.args:
        arg = context.args[0]
        if arg == "clone":
            clone_help = (
                "╭── 🤖 <b>ᴄʟᴏɴᴇ ʏᴏᴜʀ ᴏᴡɴ ʙᴏᴛ</b>\n"
                "│\n"
                "├── 💡 <b>ʏᴏᴜ ᴄᴀɴ ᴄʟᴏɴᴇ ᴜɴʟɪᴍɪᴛᴇᴅ ʙᴏᴛs ғʀᴏᴍ ᴛʜɪs ʙᴏᴛ!</b>\n"
                "│\n"
                "├── 1. ᴏᴘᴇɴ @BotFather ᴀɴᴅ ᴄʀᴇᴀᴛᴇ ᴀ ɴᴇᴡ ʙᴏᴛ.\n"
                "├── 2. ᴄᴏᴘʏ ʏᴏᴜʀ ʙᴏᴛ ᴀᴘɪ ᴛᴏᴋᴇɴ.\n"
                "├── 3. sᴇɴᴅ: <code>/clone YOUR_BOT_TOKEN</code>\n"
                "│\n"
                "╰── ⚡ <i>ʏᴏᴜʀ ᴘᴇʀsᴏɴᴀʟ ʙᴏᴛ ᴡɪʟʟ sᴛᴀʀᴛ ɪɴsᴛᴀɴᴛʟʏ!</i>"
            )
            await update.message.reply_text(clone_help, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close_msg")]]), parse_mode="HTML")
            return

        if arg.startswith("req_") or arg.startswith("join_"):
            is_req = arg.startswith("req_")
            raw_ch = arg.replace("req_", "").replace("join_", "")
            try:
                ch_id = int(f"-100{raw_ch}") if not raw_ch.startswith("-100") else int(raw_ch)
            except ValueError:
                return

            try:
                invite = await context.bot.create_chat_invite_link(
                    chat_id=ch_id,
                    creates_join_request=is_req,
                    member_limit=0 if is_req else 1,
                    expire_date=int(asyncio.get_event_loop().time()) + 59 if not is_req else None
                )
                markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("• JOIN CHANNEL •", url=invite.invite_link)]
                ])
                m1 = await update.message.reply_text(
                    "HERE IS YOUR LINK! CLICK BELOW TO PROCEED",
                    reply_markup=markup,
                    protect_content=True
                )
                m2 = await update.message.reply_text(
                    "<u>Note: If the link is expired, please click the post link again to get a new one.</u>",
                    parse_mode="HTML",
                    protect_content=True
                )
                context.job_queue.run_once(delete_job, 59, data={"chat_id": chat_id, "msg_ids": [m1.message_id, m2.message_id, update.message.message_id]})
                return
            except Exception as e:
                logger.error(f"Invite creation failed: {e}")
                err_text = "╭── ᴇʀʀᴏʀ\n╰─ ᴜsᴀɢᴇ: ᴍᴀᴋᴇ sᴜʀᴇ ʙᴏᴛ ɪs ᴀᴅᴍɪɴ ɪɴ ᴄʜᴀɴɴᴇʟ"
                err = await update.message.reply_text(err_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close_msg")]]))
                context.job_queue.run_once(delete_job, 15, data={"chat_id": chat_id, "msg_ids": [err.message_id]})
                return

    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT header_pic FROM bots WHERE token = ?", (token,))
        row = c.fetchone()
        header_pic = row[0] if row else None

    if is_clone:
        text = (
            "╭── 🤖 <b>ʟɪɴᴋ ᴄʜᴀɴɢᴇʀ • ᴄʟᴏɴᴇ ᴇᴅɪᴛɪᴏɴ</b>\n"
            "│\n"
            "├── 👋 <i>ʜᴇʟʟᴏ! ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ᴛʜɪs ʙᴏᴛ.</i>\n"
            "├── 🛡️ <b>sᴛᴀᴛᴜs:</b> ᴏɴʟɪɴᴇ (24/7 sᴇᴄᴜʀᴇ)\n"
            "├── ✨ <b>ʏᴏᴜ ᴄᴀɴ ᴄʟᴏɴᴇ ᴜɴʟɪᴍɪᴛᴇᴅ ʙᴏᴛs ғʀᴏᴍ ᴛʜɪs ʙᴏᴛ!</b>\n"
            "├── 💡 <i>ᴄʟɪᴄᴋ ᴛʜᴇ ʙᴜᴛᴛᴏɴ ʙᴇʟᴏᴡ ᴛᴏ ᴍᴀᴋᴇ ʏᴏᴜʀ ᴏᴡɴ ʙᴏᴛ.</i>\n"
            "│\n"
            "╰── ⏳ <i>ᴛʜɪs ᴍᴇssᴀɢᴇ ᴡɪʟʟ ᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇ ɪɴ 59 sᴇᴄᴏɴᴅs...</i>"
        )
    else:
        text = (
            "╭── ⚡ <b>ʟɪɴᴋ ᴄʜᴀɴɢᴇʀ • ᴍᴀsᴛᴇʀ ᴇᴅɪᴛɪᴏɴ</b>\n"
            "│\n"
            "├── 👋 <i>ʜᴇʟʟᴏ! ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ᴏᴜʀ ᴏғғɪᴄɪᴀʟ ʙᴏᴛ.</i>\n"
            "├── 🛡️ <b>sᴛᴀᴛᴜs:</b> ᴏɴʟɪɴᴇ (24/7 sᴇᴄᴜʀᴇ)\n"
            "├── ✨ <b>ʏᴏᴜ ᴄᴀɴ ᴄʟᴏɴᴇ ᴜɴʟɪᴍɪᴛᴇᴅ ʙᴏᴛs ғʀᴏᴍ ᴛʜɪs ʙᴏᴛ!</b>\n"
            "├── 💡 <i>ᴄʟɪᴄᴋ ᴛʜᴇ ʙᴜᴛᴛᴏɴs ʙᴇʟᴏᴡ ᴛᴏ ɴᴀᴠɪɢᴀᴛᴇ.</i>\n"
            "│\n"
            "╰── ⏳ <i>ᴛʜɪs ᴍᴇssᴀɢᴇ ᴡɪʟʟ ᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇ ɪɴ 59 sᴇᴄᴏɴᴅs...</i>"
        )

    markup = get_start_markup(is_clone)
    if header_pic:
        try:
            s_msg = await update.message.reply_photo(photo=header_pic, caption=text, reply_markup=markup, parse_mode="HTML", protect_content=True)
        except Exception:
            s_msg = await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML", protect_content=True)
    else:
        s_msg = await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML", protect_content=True)

    context.job_queue.run_once(delete_job, 59, data={"chat_id": chat_id, "msg_ids": [s_msg.message_id, update.message.message_id]})

# --- COMMAND: /addch ---
async def addch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    token = context.bot.token
    if not is_bot_admin(token, user_id):
        return

    if not context.args:
        text = "╭── ᴇʀʀᴏʀ\n╰─ ᴜsᴀɢᴇ: /addch -100xxxxxxxxxx"
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close_msg")]]))
        return

    try:
        ch_id = int(context.args[0])
        chat_info = await context.bot.get_chat(ch_id)
        title = chat_info.title or "Channel"
        
        with get_db() as conn:
            conn.execute("INSERT OR REPLACE INTO channels (token, channel_id, channel_title, auto_approve) VALUES (?, ?, ?, 1)", (token, ch_id, title))
            conn.commit()

        b_user = context.bot.username
        clean_id = str(ch_id).replace("-100", "")
        req_link = f"https://t.me/{b_user}?start=req_{clean_id}"
        join_link = f"https://t.me/{b_user}?start=join_{clean_id}"

        res = (
            f"╭── ᴄʜᴀɴɴᴇʟ ᴀᴅᴅᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ\n"
            f"│\n"
            f"├── 📢 <b>ᴄʜᴀɴɴᴇʟ:</b> {title}\n"
            f"├── 🆔 <b>ᴄʜᴀɴɴᴇʟ ɪᴅ:</b> <code>{ch_id}</code>\n"
            f"│\n"
            f"├── 🔗 <b>ɪɴғɪɴɪᴛᴇ ᴘᴏsᴛ ʟɪɴᴋs:</b>\n"
            f"├── 1. <b>ʀᴇǫᴜᴇsᴛ ʟɪɴᴋ:</b>\n"
            f"│   {req_link}\n"
            f"│\n"
            f"├── 2. <b>ᴅɪʀᴇᴄᴛ ᴊᴏɪɴ ʟɪɴᴋ:</b>\n"
            f"│   {join_link}\n"
            f"│\n"
            f"╰── <b>ɴᴏᴛᴇ: ᴘᴇʀᴍᴀɴᴇɴᴛ ʟɪɴᴋ ɪs ғᴜʟʟʏ ʜɪᴅᴅᴇɴ</b>"
        )
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("ᴛᴇsᴛ ʀᴇǫᴜᴇsᴛ ʟɪɴᴋ", url=req_link)],
            [InlineKeyboardButton("ᴛᴇsᴛ ᴊᴏɪɴ ʟɪɴᴋ", url=join_link)],
            [InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close_msg")]
        ])
        await update.message.reply_text(res, reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Addch error: {e}")
        text = f"╭── ᴇʀʀᴏʀ\n╰─ ᴜsᴀɢᴇ: ᴇɴsᴜʀᴇ ʙᴏᴛ ɪs ᴀᴅᴍɪɴ ɪɴ ᴄʜᴀɴɴᴇʟ!\n<code>{e}</code>"
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close_msg")]]), parse_mode="HTML")

# --- COMMAND: /delch ---
async def delch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    token = context.bot.token
    if not is_bot_admin(token, user_id):
        return

    if not context.args:
        text = "╭── ᴇʀʀᴏʀ\n╰─ ᴜsᴀɢᴇ: /delch -100xxxxxxxxxx"
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close_msg")]]))
        return

    try:
        ch_id = int(context.args[0])
        with get_db() as conn:
            conn.execute("DELETE FROM channels WHERE token = ? AND channel_id = ?", (token, ch_id))
            conn.commit()
        await update.message.reply_text(f"╭── sᴜᴄᴄᴇss\n╰─ ᴜɴʟɪɴᴋᴇᴅ ᴄʜᴀɴɴᴇʟ: <code>{ch_id}</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close_msg")]]), parse_mode="HTML")
    except ValueError:
        await update.message.reply_text("╭── ᴇʀʀᴏʀ\n╰─ ᴜsᴀɢᴇ: ɪɴᴠᴀʟɪᴅ ᴄʜᴀɴɴᴇʟ ɪᴅ", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close_msg")]]))

# --- COMMAND: /channels ---
async def channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    token = context.bot.token
    if not is_bot_admin(token, user_id):
        return

    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT channel_id, channel_title FROM channels WHERE token = ?", (token,))
        rows = c.fetchall()

    if not rows:
        await update.message.reply_text("╭── ᴇʀʀᴏʀ\n╰─ ɴᴏ ᴄᴏɴɴᴇᴄᴛᴇᴅ ᴄʜᴀɴɴᴇʟs. ᴜsᴇ /addch", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close_msg")]]))
        return

    b_user = context.bot.username
    res = "╭── ᴀʟʟ ᴄᴏɴɴᴇᴄᴛᴇᴅ ᴄʜᴀɴɴᴇʟs\n│\n"
    buttons = []
    for ch_id, title in rows:
        clean_id = str(ch_id).replace("-100", "")
        req_link = f"https://t.me/{b_user}?start=req_{clean_id}"
        res += f"├── • {title} (<code>{ch_id}</code>)\n│    {req_link}\n"
        buttons.append([InlineKeyboardButton(f"ᴏᴘᴇɴ {title}", url=req_link)])

    res += f"│\n╰── <b>ᴛᴏᴛᴀʟ ᴀᴄᴛɪᴠᴇ ɴᴏᴅᴇs: {len(rows)}</b>"
    buttons.append([InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close_msg")])

    await update.message.reply_text(res, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML", disable_web_page_preview=True)

# --- COMMAND: /status ---
async def status_msg(token: str, bot_obj):
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM channels WHERE token = ?", (token,))
        ch_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE token = ?", (token,))
        u_count = c.fetchone()[0]
        c.execute("SELECT header_pic, auto_approve, approval_delay FROM bots WHERE token = ?", (token,))
        row = c.fetchone()
        pic, auto_app, delay = (row[0], row[1], row[2]) if row else (None, 1, 0)

    branding = "sᴇᴛ" if pic else "ɴᴏᴛ sᴇᴛ"
    app_status = "ᴏɴ" if auto_app else "ᴏғғ"

    text = (
        "╭── sʏsᴛᴇᴍ sᴛᴀᴛᴜs ᴏᴠᴇʀᴠɪᴇᴡ\n"
        "│\n"
        "├── ⚡ <b>ᴄᴏʀᴇ ᴇɴɢɪɴᴇ:</b> ᴏɴʟɪɴᴇ (ᴄᴏɴᴄᴜʀʀᴇɴᴛ)\n"
        f"├── 📢 <b>ᴄᴏɴɴᴇᴄᴛᴇᴅ ᴄʜᴀɴɴᴇʟs:</b> {ch_count}\n"
        f"├── 👥 <b>ᴛᴏᴛᴀʟ ᴜsᴇʀs:</b> {u_count}\n"
        f"├── 🖼️ <b>ᴄᴜsᴛᴏᴍ ʙʀᴀɴᴅɪɴɢ:</b> {branding}\n"
        f"├── ⚙️ <b>ᴀᴜᴛᴏ-ᴀᴘᴘʀᴏᴠᴀʟ:</b> {app_status}\n"
        f"├── ⏱️ <b>ᴀᴘᴘʀᴏᴠᴀʟ ᴅᴇʟᴀʏ:</b> {delay}s\n"
        "│\n"
        "╰── <b>ᴅᴀᴛᴀʙᴀsᴇ: ᴡᴀʟ-ᴍᴏᴅᴇ ᴀᴄᴛɪᴠᴇ</b>"
    )
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("ʀᴇғʀᴇsʜ sᴛᴀᴛs", callback_data="refresh_stats")],
        [InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close_msg")]
    ])
    return text, markup

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    token = context.bot.token
    if not is_bot_admin(token, user_id):
        return
    text, markup = await status_msg(token, context.bot)
    await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")

# --- COMMANDS: /approveon & /approveoff ---
async def approve_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE, status_val: int):
    user_id = update.effective_user.id
    token = context.bot.token
    if not is_bot_admin(token, user_id):
        return

    cmd = "approveon" if status_val == 1 else "approveoff"
    if not context.args:
        text = f"╭── ᴇʀʀᴏʀ\n╰─ ᴜsᴀɢᴇ: /{cmd} -100xxxxxxxxxx"
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close_msg")]]))
        return

    try:
        ch_id = int(context.args[0])
        with get_db() as conn:
            conn.execute("UPDATE channels SET auto_approve = ? WHERE token = ? AND channel_id = ?", (status_val, token, ch_id))
            conn.commit()
        s_text = "ᴇɴᴀʙʟᴇᴅ" if status_val == 1 else "ᴅɪsᴀʙʟᴇᴅ"
        await update.message.reply_text(f"╭── ᴀᴜᴛᴏ-ᴀᴘᴘʀᴏᴠᴀʟ\n╰─ ᴀᴜᴛᴏ-ᴀᴘᴘʀᴏᴠᴀʟ {s_text} ғᴏʀ: <code>{ch_id}</code>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close_msg")]]), parse_mode="HTML")
    except ValueError:
        await update.message.reply_text("╭── ᴇʀʀᴏʀ\n╰─ ᴜsᴀɢᴇ: ɪɴᴠᴀʟɪᴅ ᴄʜᴀɴɴᴇʟ ɪᴅ", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close_msg")]]))

# --- AUTO APPROVAL JOIN REQUEST HANDLER ---
async def join_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    req = update.chat_join_request
    chat_id = req.chat.id
    token = context.bot.token

    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT auto_approve FROM channels WHERE token = ? AND channel_id = ?", (token, chat_id))
        ch_row = c.fetchone()
        c.execute("SELECT auto_approve, approval_delay FROM bots WHERE token = ?", (token,))
        bot_row = c.fetchone()

    ch_auto = ch_row[0] if ch_row else 1
    bot_auto, delay = (bot_row[0], bot_row[1]) if bot_row else (1, 0)

    if ch_auto and bot_auto:
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            await req.approve()
        except Exception as e:
            logger.error(f"Join approval error: {e}")

# --- COMMAND: /setpic & /unsetpic ---
async def setpic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    token = context.bot.token
    if not is_bot_admin(token, user_id):
        return

    if update.message.reply_to_message and update.message.reply_to_message.photo:
        file_id = update.message.reply_to_message.photo[-1].file_id
        with get_db() as conn:
            conn.execute("UPDATE bots SET header_pic = ? WHERE token = ?", (file_id, token))
            conn.commit()
        await update.message.reply_text("╭── sᴜᴄᴄᴇss\n╰─ ᴄᴜsᴛᴏᴍ ʙʀᴀɴᴅɪɴɢ ʜᴇᴀᴅᴇʀ ɪᴍᴀɢᴇ sᴇᴛ!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close_msg")]]))
    else:
        await update.message.reply_text("╭── ᴇʀʀᴏʀ\n╰─ ᴜsᴀɢᴇ: ʀᴇᴘʟʏ ᴛᴏ ᴀ ᴘʜᴏᴛᴏ ᴡɪᴛʜ /setpic", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close_msg")]]))

async def unsetpic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    token = context.bot.token
    if not is_bot_admin(token, user_id):
        return

    with get_db() as conn:
        conn.execute("UPDATE bots SET header_pic = NULL WHERE token = ?", (token,))
        conn.commit()
    await update.message.reply_text("╭── sᴜᴄᴄᴇss\n╰─ ᴄᴜsᴛᴏᴍ ʙʀᴀɴᴅɪɴɢ ʜᴇᴀᴅᴇʀ ɪᴍᴀɢᴇ ʀᴇᴍᴏᴠᴇᴅ!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close_msg")]]))

# --- COMMAND: /reqtime & /reqmode ---
async def reqtime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    token = context.bot.token
    if not is_bot_admin(token, user_id):
        return
    if not context.args:
        await update.message.reply_text("╭── ᴇʀʀᴏʀ\n╰─ ᴜsᴀɢᴇ: /reqtime <seconds>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close_msg")]]))
        return
    try:
        sec = int(context.args[0])
        with get_db() as conn:
            conn.execute("UPDATE bots SET approval_delay = ? WHERE token = ?", (sec, token))
            conn.commit()
        await update.message.reply_text(f"╭── sᴜᴄᴄᴇss\n╰─ ᴀᴘᴘʀᴏᴠᴀʟ ʙᴜғғᴇʀ ᴅᴇʟᴀʏ sᴇᴛ ᴛᴏ: {sec}s", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close_msg")]]))
    except ValueError:
        await update.message.reply_text("╭── ᴇʀʀᴏʀ\n╰─ ᴜsᴀɢᴇ: ɪɴᴠᴀʟɪᴅ sᴇᴄᴏɴᴅs ᴠᴀʟᴜᴇ", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close_msg")]]))

async def reqmode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    token = context.bot.token
    if not is_bot_admin(token, user_id):
        return
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT auto_approve FROM bots WHERE token = ?", (token,))
        row = c.fetchone()
        cur = row[0] if row else 1
        new_val = 0 if cur == 1 else 1
        conn.execute("UPDATE bots SET auto_approve = ? WHERE token = ?", (new_val, token))
        conn.commit()
    await update.message.reply_text(f"╭── ᴀᴜᴛᴏ-ᴀᴘᴘʀᴏᴠᴀʟ\n╰─ ɢʟᴏʙᴀʟ ᴍᴏᴅᴇ: {'ᴏɴ' if new_val == 1 else 'ᴏғғ'}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close_msg")]]))

# --- CALLBACK ROUTER ---
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    elif data == "clone_info":
        await query.answer()
        clone_help = (
            "╭── 🤖 <b>ᴄʟᴏɴᴇ ʏᴏᴜʀ ᴏᴡɴ ʙᴏᴛ</b>\n"
            "│\n"
            "├── 💡 <b>ʏᴏᴜ ᴄᴀɴ ᴄʟᴏɴᴇ ᴜɴʟɪᴍɪᴛᴇᴅ ʙᴏᴛs ғʀᴏᴍ ᴛʜɪs ʙᴏᴛ!</b>\n"
            "│\n"
            "├── 1. ᴏᴘᴇɴ @BotFather ᴀɴᴅ ᴄʀᴇᴀᴛᴇ ᴀ ɴᴇᴡ ʙᴏᴛ.\n"
            "├── 2. ᴄᴏᴘʏ ʏᴏᴜʀ ʙᴏᴛ ᴀᴘɪ ᴛᴏᴋᴇɴ.\n"
            "├── 3. sᴇɴᴅ ʜᴇʀᴇ: <code>/clone YOUR_BOT_TOKEN</code>\n"
            "│\n"
            "╰── ⚡ <i>ʏᴏᴜʀ ᴘᴇʀsᴏɴᴀʟ ʙᴏᴛ ᴡɪʟʟ sᴛᴀʀᴛ ɪɴsᴛᴀɴᴛʟʏ!</i>"
        )
        await query.message.reply_text(clone_help, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close_msg")]]), parse_mode="HTML")

    elif data == "refresh_stats":
        await query.answer("Refreshing stats...")
        text, markup = await status_msg(token, context.bot)
        try:
            await query.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
        except Exception:
            pass

    elif data == "get_link":
        await query.answer()
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT channel_id FROM channels WHERE token = ? LIMIT 1", (token,))
            row = c.fetchone()

        if not row:
            msg = await query.message.reply_text("╭── ᴇʀʀᴏʀ\n╰─ ᴜsᴀɢᴇ: ɴᴏ ᴄʜᴀɴɴᴇʟ ᴄᴏɴғɪɢᴜʀᴇᴅ ʏᴇᴛ.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close_msg")]]))
            context.job_queue.run_once(delete_job, 15, data={"chat_id": chat_id, "msg_ids": [msg.message_id]})
            return

        try:
            invite = await context.bot.create_chat_invite_link(chat_id=row[0], member_limit=1, expire_date=int(asyncio.get_event_loop().time()) + 59)
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("• JOIN CHANNEL •", url=invite.invite_link)]])
            m1 = await context.bot.send_message(chat_id=chat_id, text="HERE IS YOUR LINK! CLICK BELOW TO PROCEED", reply_markup=markup, protect_content=True)
            m2 = await context.bot.send_message(chat_id=chat_id, text="<u>Note: If the link is expired, please click the post link again to get a new one.</u>", parse_mode="HTML", protect_content=True)
            context.job_queue.run_once(delete_job, 59, data={"chat_id": chat_id, "msg_ids": [m1.message_id, m2.message_id]})
        except Exception as e:
            logger.error(f"Link gen error: {e}")
            err = await query.message.reply_text("╭── ᴇʀʀᴏʀ\n╰─ ᴜsᴀɢᴇ: ɢɪᴠᴇ 'ᴀᴅᴅ ᴜsᴇʀs' ʀɪɢʜᴛs ᴛᴏ ʙᴏᴛ", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close_msg")]]))
            context.job_queue.run_once(delete_job, 15, data={"chat_id": chat_id, "msg_ids": [err.message_id]})

# --- COMMAND: /clone ---
async def clone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        text = (
            "╭── 🤖 <b>ᴄʟᴏɴᴇ ʏᴏᴜʀ ᴏᴡɴ ʙᴏᴛ</b>\n"
            "│\n"
            "├── 💡 <b>ʏᴏᴜ ᴄᴀɴ ᴄʟᴏɴᴇ ᴜɴʟɪᴍɪᴛᴇᴅ ʙᴏᴛs ғʀᴏᴍ ᴛʜɪs ʙᴏᴛ!</b>\n"
            "│\n"
            "├── 1. ᴏᴘᴇɴ @BotFather ᴀɴᴅ ᴄʀᴇᴀᴛᴇ ᴀ ɴᴇᴡ ʙᴏᴛ.\n"
            "├── 2. ᴄᴏᴘʏ ᴛʜᴇ ᴀᴘɪ ᴛᴏᴋᴇɴ.\n"
            "├── 3. sᴇɴᴅ ʜᴇʀᴇ: <code>/clone YOUR_BOT_TOKEN</code>\n"
            "│\n"
            "╰── ⚡ <i>ʏᴏᴜʀ ᴘᴇʀsᴏɴᴀʟ ʙᴏᴛ ᴡɪʟʟ ʙᴇ ʟɪᴠᴇ ɪɴsᴛᴀɴᴛʟʏ!</i>"
        )
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close_msg")]]), parse_mode="HTML")
        return

    new_token = context.args[0].strip()
    try:
        temp_app = ApplicationBuilder().token(new_token).build()
        await temp_app.initialize()
        bot_info = await temp_app.bot.get_me()
        await temp_app.shutdown()

        with get_db() as conn:
            conn.execute("INSERT OR REPLACE INTO bots (token, owner_id, username, auto_approve, approval_delay) VALUES (?, ?, ?, 1, 0)", (new_token, user_id, bot_info.username))
            conn.commit()

        asyncio.create_task(run_cloned_bot(new_token))
        res = (
            "╭── 🎉 <b>ʙᴏᴛ ᴄʟᴏɴᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n"
            "│\n"
            f"├── 🤖 <b>ʙᴏᴛ:</b> @{bot_info.username}\n"
            f"├── 👑 <b>ᴏᴡɴᴇʀ ɪᴅ:</b> <code>{user_id}</code>\n"
            "├── 📋 <b>sɪᴅᴇ ᴍᴇɴᴜ ᴄᴏᴍᴍᴀɴᴅs:</b> ᴄᴏɴғɪɢᴜʀᴇᴅ ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ!\n"
            "│\n"
            "├── <b>ɴᴇxᴛ sᴛᴇᴘs:</b>\n"
            f"├── 1. ᴘʀᴏᴍᴏᴛᴇ @{bot_info.username} ᴛᴏ ᴀᴅᴍɪɴ ɪɴ ʏᴏᴜʀ ᴄʜᴀɴɴᴇʟ.\n"
            "├── 2. sᴇɴᴅ <code>/addch -100xxxxxxxxxx</code> ɪɴsɪᴅᴇ ʏᴏᴜʀ ʙᴏᴛ.\n"
            "│\n"
            "╰── 🚀 <i>ʏᴏᴜʀ ᴄʟᴏɴᴇ ɪs ᴏɴʟɪɴᴇ 24/7!</i>"
        )
        await update.message.reply_text(res, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close_msg")]]), parse_mode="HTML")
    except Exception as e:
        logger.error(f"Clone error: {e}")
        await update.message.reply_text("╭── ᴇʀʀᴏʀ\n╰─ ᴜsᴀɢᴇ: ɪɴᴠᴀʟɪᴅ ᴛᴏᴋᴇɴ ғʀᴏᴍ @BotFather", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close_msg")]]))

# --- ATTACH HANDLERS ---
def attach_handlers(app):
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("addch", addch))
    app.add_handler(CommandHandler("delch", delch))
    app.add_handler(CommandHandler("channels", channels))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("approveon", lambda u, c: approve_toggle(u, c, 1)))
    app.add_handler(CommandHandler("approveoff", lambda u, c: approve_toggle(u, c, 0)))
    app.add_handler(CommandHandler("reqmode", reqmode))
    app.add_handler(CommandHandler("reqtime", reqtime))
    app.add_handler(CommandHandler("setpic", setpic))
    app.add_handler(CommandHandler("unsetpic", unsetpic))
    app.add_handler(CommandHandler("clone", clone))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(ChatJoinRequestHandler(join_request_handler))

# --- COMMAND MENU LIST ---
MENU_COMMANDS = [
    BotCommand("start", "START BOT & GET INSTANT ACCESS LINK"),
    BotCommand("addch", "REGISTER NEW SECURE CHANNEL ENDPOINT"),
    BotCommand("delch", "UNLINK CHANNEL ENDPOINT FROM SYSTEM"),
    BotCommand("channels", "VIEW ALL PROTECTED CHANNELS & LINKS"),
    BotCommand("status", "CHECK LIVE ENGINE HEALTH & STATS"),
    BotCommand("approveon", "ENABLE AUTOMATIC JOIN ACCEPTANCE"),
    BotCommand("approveoff", "DISABLE AUTOMATIC JOIN ACCEPTANCE"),
    BotCommand("reqmode", "TOGGLE GLOBAL AUTO-APPROVAL MODE"),
    BotCommand("reqtime", "CONFIGURE APPROVAL BUFFER DELAY"),
    BotCommand("setpic", "REPLY TO IMAGE TO SET BRANDING HEADER"),
    BotCommand("unsetpic", "REMOVE CUSTOM BRANDING HEADER"),
    BotCommand("clone", "CLONE YOUR OWN LINK CHANGER BOT"),
]

# --- RUNNER FOR CLONES ---
async def run_cloned_bot(token: str):
    try:
        clone_app = ApplicationBuilder().token(token).concurrent_updates(True).build()
        attach_handlers(clone_app)
        await clone_app.initialize()
        try:
            await clone_app.bot.set_my_commands(MENU_COMMANDS)
        except Exception:
            pass
        await clone_app.start()
        await clone_app.updater.start_polling(drop_pending_updates=True)
        logger.info(f"Cloned bot started: {token[:10]}***")
    except Exception as e:
        logger.error(f"Failed starting cloned bot {token[:10]}***: {e}")

# --- STARTUP LOGIC ---
async def start_all_bots(main_app):
    global MAIN_BOT_USERNAME
    await main_app.initialize()

    bot_info = await main_app.bot.get_me()
    MAIN_BOT_USERNAME = bot_info.username

    try:
        await main_app.bot.set_my_commands(MENU_COMMANDS)
    except Exception as e:
        logger.error(f"Main menu command set error: {e}")

    await main_app.start()
    await main_app.updater.start_polling(drop_pending_updates=True)

    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT token FROM bots WHERE token != ?", (MAIN_BOT_TOKEN,))
        saved_clones = c.fetchall()

    for row in saved_clones:
        asyncio.create_task(run_cloned_bot(row[0]))

    logger.info("Main bot & all clone nodes are online.")

def main():
    threading.Thread(target=run_web_server, daemon=True).start()

    main_app = (
        ApplicationBuilder()
        .token(MAIN_BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )
    attach_handlers(main_app)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_all_bots(main_app))
    loop.run_forever()

if __name__ == "__main__":
    main()
