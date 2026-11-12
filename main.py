import asyncio
import os
import json
import aiohttp
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
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
MY_OWNER_ID = int(os.environ.get("MY_OWNER_ID", 0))

# ─── AI CONFIG (HARDCODED KEYS) ───
AI_CONFIG = {
    "api_keys": [
        "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",
        "gsk_ty99zG83cjuRmL0NyR5XWgdyb3FYWCKXdKDpIHtqktbWVjp8byhWZ",
        "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"
    ],
    "base_url": "https://api.groq.com/openai/v1",
    "models": ["openai/gpt-oss-20b", "llama3-8b-8192"],
    "system_prompt": (
        "You are a helpful assistant replying to Telegram messages. "
        "Keep replies short, natural, and conversational — usually 1-3 sentences. "
        "Match the language of the user (Hindi, Hinglish, English). "
        "Never reveal that you are an AI unless directly asked."
    ),
    "max_history": 8,
    "max_tokens": 400,
    "temperature": 0.7,
    "timeout": 20,
}

bot = TelegramClient("price_qr_bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)
user_states = {}
active_sessions = {}
user_configs = {}

# Default configuration
DEFAULT_CONFIG = {
    "keywords": {},  
    "ignored_words": [],
    "greetings": [],          
    "greeted_users": [],
    "ai_enabled": False,
    "ai_scope": "all",
    "personality": ""
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

# ══════════════════════════════════════════════════════════════
# AI ENGINE (Multi-Key + Multi-Model Fallback)
# ══════════════════════════════════════════════════════════════
class AIEngine:
    def __init__(self, cfg):
        self.cfg = cfg
        self.keys = cfg.get("api_keys", [])
        self.history = {}
        self.current_key_idx = 0
        self.current_model_idx = 0

    async def ask(self, chat_id, user_text, sender_name=None):
        if not self.keys:
            return None, "No API keys available."

        final_prompt = self.cfg["system_prompt"]
        config = load_user_config(chat_id)
        if config.get("personality"):
            final_prompt += f"\nIMPORTANT EXTRA BEHAVIOR: {config['personality']}"

        history = self.history.setdefault(str(chat_id), [])
        prefix = f"[{sender_name}]: " if sender_name else ""
        history.append({"role": "user", "content": prefix + user_text})

        max_msgs = self.cfg["max_history"] * 2
        if len(history) > max_msgs:
            history[:] = history[-max_msgs:]

        messages = [{"role": "system", "content": final_prompt}] + history
        url = self.cfg["base_url"].rstrip("/") + "/chat/completions"

        max_attempts = len(self.keys) * len(self.cfg["models"])
        last_error = ""

        for attempt in range(max_attempts):
            current_key = self.keys[self.current_key_idx]
            current_model = self.cfg["models"][self.current_model_idx]

            headers = {"Authorization": f"Bearer {current_key}", "Content-Type": "application/json"}
            body = {"model": current_model, "messages": messages, "max_tokens": self.cfg["max_tokens"], "temperature": self.cfg["temperature"]}

            try:
                async with aiohttp.ClientSession() as sess:
                    async with sess.post(url, headers=headers, json=body, timeout=aiohttp.ClientTimeout(total=self.cfg["timeout"])) as r:
                        if r.status == 200:
                            data = await r.json()
                            reply = data["choices"][0]["message"]["content"].strip()
                            history.append({"role": "assistant", "content": reply})
                            return reply, None
                        
                        if r.status in (401, 429, 403):
                            self.current_key_idx = (self.current_key_idx + 1) % len(self.keys)
                            last_error = f"HTTP {r.status}"
                            await asyncio.sleep(1) 
                            continue
                        
                        self.current_model_idx = (self.current_model_idx + 1) % len(self.cfg["models"])
                        last_error = f"HTTP {r.status}"
                        await asyncio.sleep(1)
                        continue

            except asyncio.TimeoutError:
                self.current_key_idx = (self.current_key_idx + 1) % len(self.keys)
                last_error = "Timeout"
                continue
            except Exception as e:
                last_error = str(e)
                continue

        return None, f"All APIs failed. Last error: {last_error}"

    def reset(self, chat_id):
        self.history.pop(str(chat_id), None)


# ══════════════════════════════════════════════════════════════
# CONFIG MANAGEMENT
# ══════════════════════════════════════════════════════════════
def load_user_config(chat_id):
    try:
        if os.path.exists(f"config_{chat_id}.json"):
            with open(f"config_{chat_id}.json", "r") as f:
                config = json.load(f)
                config.setdefault("keywords", {})
                config.setdefault("ignored_words", [])
                config.setdefault("greetings", [])
                config.setdefault("greeted_users", [])
                config.setdefault("ai_enabled", False)
                config.setdefault("ai_scope", "all")
                config.setdefault("personality", "")
                
                for k, v in list(config["keywords"].items()):
                    if isinstance(v, str):
                        config["keywords"][k] = [v]
                return config
    except:
        pass
    return DEFAULT_CONFIG.copy()


def save_user_config(chat_id, config):
    try:
        with open(f"config_{chat_id}.json", "w") as f:
            json.dump(config, f, indent=4)
        return True
    except:
        return False


def get_greeting_media_path(chat_id, index, ext):
    return os.path.join(GREETING_DIR, f"greeting_{chat_id}_{index}{ext}")

def clear_all_greeting_media(chat_id):
    for fname in os.listdir(GREETING_DIR):
        if fname.startswith(f"greeting_{chat_id}_"):
            try: os.remove(os.path.join(GREETING_DIR, fname))
            except: pass


# ─── MAIN BOT EVENTS ───
@bot.on(events.NewMessage(pattern="/start"))
async def start_handler(event):
    await event.reply(
        "━━━〔 ✦ 👑 Ultimate Hybrid Bot 👑 ✦ 〕━━━\n\n"
        "Welcome! Apna userbot chalu karne ke liye `/login` command bhejen.\n\n"
        "📌 **Features:**\n"
        "• 📝 Advanced Keywords\n"
        "• 🤖 AI Auto-Reply (Groq Multi-API)\n"
        "• 👋 Multiple Greetings\n"
        "• 📱 QR Code Image\n\n"
        "⚙️ **Commands:**\n"
        "`/ai` commands userbot me chalayen.\n"
        "`/addkeyword`, `/setgreeting`, `/setqr` etc.\n\n"
        "🚪 **Logout:** `/logout`"
    )

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

# ─── KEYWORD & OTHER COMMANDS (Main Bot) ───
@bot.on(events.NewMessage(pattern=r'^/addkeyword\s+(.+?)\s*=\s*([\s\S]+)$'))
async def add_keyword_handler(event):
    chat_id = event.chat_id
    if chat_id not in active_sessions: return await event.reply("❌ **Pehle login karein!** `/login`")
    
    triggers_str = event.pattern_match.group(1).strip()
    replies_str = event.pattern_match.group(2).strip()
    
    triggers = [t.strip().lower() for t in triggers_str.split(',') if t.strip()]
    replies = [r.strip() for r in replies_str.split('\n') if r.strip()]
    
    if not triggers or not replies:
        return await event.reply("❌ **Format galat hai.** Aise likhein:\n`/addkeyword hello, hi = Reply 1`\n`Reply 2`")

    config = load_user_config(chat_id)
    for word in triggers:
        if word not in config["keywords"]:
            config["keywords"][word] = []
        config["keywords"][word].extend(replies)
        
    save_user_config(chat_id, config)
    msg = f"✅ **Keywords Added!**\n\n**Triggers:** `{', '.join(triggers)}`\n**Replies:**\n"
    for r in replies:
        msg += f"👉 *{r}*\n"
    await event.reply(msg)

@bot.on(events.NewMessage(pattern="/removekeyword"))
async def remove_keyword_handler(event):
    chat_id = event.chat_id
    if chat_id not in active_sessions: return await event.reply("❌ **Pehle login karein!** `/login`")
    args = event.raw_text.split(maxsplit=1)
    if len(args) < 2: return await event.reply("❌ **Usage:** `/removekeyword <word>`")
    
    word = args[1].lower().strip()
    config = load_user_config(chat_id)
    if word not in config["keywords"]: return await event.reply(f"❌ **Keyword '{word}' not found!**")
    
    del config["keywords"][word]
    save_user_config(chat_id, config)
    await event.reply(f"✅ **Keyword Removed:** `{word}`")

@bot.on(events.NewMessage(pattern="/listkeywords"))
async def list_keywords_handler(event):
    chat_id = event.chat_id
    if chat_id not in active_sessions: return await event.reply("❌ **Pehle login karein!** `/login`")
    config = load_user_config(chat_id)
    if not config["keywords"]: return await event.reply("📋 **No Keywords Found!**\nUse `/addkeyword` to add one.")
    
    kw_list = "📋 **Your Keywords**\n━━━━━━━━━━━━━━━\n\n"
    for idx, (word, replies) in enumerate(config["keywords"].items(), 1):
        kw_list += f"{idx}. **{word}**\n"
        for r in replies:
            kw_list += f"   └─ `{r[:80]}...`\n"
        kw_list += "\n"
    kw_list += f"📊 **Total:** {len(config['keywords'])} keywords"
    await event.reply(kw_list)

# ─── GREETINGS COMMANDS (Main Bot) ───
@bot.on(events.NewMessage(pattern="/setgreeting"))
async def set_greeting_handler(event):
    chat_id = event.chat_id
    if chat_id not in active_sessions: return await event.reply("❌ **Pehle login karein!** `/login`")
    config = load_user_config(chat_id)

    if event.is_reply:
        replied = await event.get_reply_message()
        saved = await save_greeting_from_message(chat_id, replied, config)
        if saved:
            save_user_config(chat_id, config)
            await event.reply(f"✅ **Greeting #{len(config['greetings'])} added!**")
        else:
            await event.reply("❌ **Reply mein media nahi mila.**")
        return

    args = event.raw_text.split(maxsplit=1)
    if len(args) >= 2 and args[1].strip():
        config["greetings"].append({"type": "text", "value": args[1].strip()})
        save_user_config(chat_id, config)
        await event.reply(f"✅ **Text Greeting Added!**\n📝 `{args[1].strip()}`")
        return

    user_states[chat_id] = {"step": "AWAITING_GREETING"}
    await event.reply(
        "👋 **Add New Greeting**\n\n"
        "Jo bhi bhejenge woh greeting ban jayega:\n"
        "• 📝 **Text**\n• 🎨 **Sticker**\n• 🎞️ **GIF**\n• 🖼️ **Photo**\n• 🎬 **Video**\n\n"
        "❌ Cancel: `/cancel`"
    )

async def save_greeting_from_message(chat_id, msg, config):
    if msg is None: return None
    next_index = len(config["greetings"])

    if msg.sticker:
        ext = ".tgs" if msg.sticker.mime_type == "application/x-tgsticker" else ".webp"
        path = get_greeting_media_path(chat_id, next_index, ext)
        await bot.download_media(msg, file=path)
        g = {"type": "sticker", "value": path}
        config["greetings"].append(g)
        return g

    if msg.document:
        mime = (msg.document.mime_type or "").lower()
        if "gif" in mime or "video" in mime:
            path = get_greeting_media_path(chat_id, next_index, ".mp4")
            await bot.download_media(msg, file=path)
            g = {"type": "gif", "value": path}
            config["greetings"].append(g)
            return g

    if msg.video:
        path = get_greeting_media_path(chat_id, next_index, ".mp4")
        await bot.download_media(msg, file=path)
        g = {"type": "video", "value": path}
        config["greetings"].append(g)
        return g

    if msg.photo:
        path = get_greeting_media_path(chat_id, next_index, ".jpg")
        await bot.download_media(msg, file=path)
        g = {"type": "photo", "value": path}
        config["greetings"].append(g)
        return g

    if msg.text and not msg.text.startswith("/"):
        g = {"type": "text", "value": msg.text.strip()}
        config["greetings"].append(g)
        return g
    return None

@bot.on(events.NewMessage)
async def greeting_media_listener(event):
    chat_id = event.chat_id
    if chat_id not in user_states: return
    if user_states[chat_id].get("step") != "AWAITING_GREETING": return

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
        await event.reply(f"✅ **Greeting #{len(config['greetings'])} Saved!**")
    else:
        await event.reply("❌ **Unsupported type.**")

# ─── LOGIN MESSAGE HANDLER ───
@bot.on(events.NewMessage)
async def message_handler(event):
    chat_id = event.chat_id
    text = event.text.strip() if event.text else ""
    if chat_id not in user_states or (text.startswith("/")): return

    state = user_states[chat_id]
    if state.get("step") == "AWAITING_GREETING": return

    if state["step"] == "NUMBER":
        await event.reply("⏳ Connecting...")
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        await client.connect()
        try:
            send_code = await client.send_code_request(text)
            state.update({"client": client, "phone": text, "phone_code_hash": send_code.phone_code_hash, "step": "OTP"})
            await event.reply("📩 **STEP 2:** OTP bhejen.")
        except Exception as e:
            await event.reply(f"❌ Error: `{str(e)}`")
            user_states.pop(chat_id, None)

    elif state["step"] == "OTP":
        client = state["client"]
        try:
            await client.sign_in(phone=state["phone"], code=text, phone_code_hash=state["phone_code_hash"])
            session_str = client.session.save()
            await event.reply("✅ **Login Kamyab!** Userbot start ho raha hai...")
            asyncio.create_task(run_user_bot(session_str, chat_id))
            user_states.pop(chat_id, None)
        except SessionPasswordNeededError:
            state["step"] = "PASSWORD"
            await event.reply("🔒 **2-Step Verification:** Apna 2FA password bhejen.")
        except Exception as e:
            await event.reply(f"❌ Error: `{str(e)}`")
            user_states.pop(chat_id, None)

    elif state["step"] == "PASSWORD":
        client = state["client"]
        try:
            await client.sign_in(password=text)
            session_str = client.session.save()
            await event.reply("✅ **Login Kamyab!** Userbot start ho raha hai...")
            asyncio.create_task(run_user_bot(session_str, chat_id))
            user_states.pop(chat_id, None)
        except Exception as e:
            await event.reply(f"❌ Error: `{str(e)}`")
            user_states.pop(chat_id, None)

# ─── USERBOT CORE ENGINE WITH ALL AI FEATURES ───
async def run_user_bot(session_string, chat_id):
    try:
        user_bot = TelegramClient(StringSession(session_string), API_ID, API_HASH, auto_reconnect=True)
        await user_bot.start()

        active_sessions[chat_id] = user_bot
        me = await user_bot.get_me()
        USER_ID = me.id
        
        ai_engine = AIEngine(AI_CONFIG)
        ai_processing = set()

        async def safe_edit(event, text):
            try: return await event.edit(text)
            except: 
                try: return await event.reply(text)
                except: return

        # ─── ALL AI CONTROL COMMANDS (Via Userbot) ───
        @user_bot.on(events.NewMessage(pattern=r'^\.ai(?:\s+(.+))?$', outgoing=True))
        async def ai_control(event):
            if event.sender_id != USER_ID: return
            arg = (event.pattern_match.group(1) or "").strip().lower()
            config = load_user_config(chat_id)

            if arg == "on":
                config["ai_enabled"] = True
                save_user_config(chat_id, config)
                await safe_edit(event, f"🤖 **AI ON** (scope: `{config['ai_scope']}`)")
            elif arg == "off":
                config["ai_enabled"] = False
                save_user_config(chat_id, config)
                await safe_edit(event, "🛑 **AI OFF**")
            elif arg == "clear":
                ai_engine.reset(event.chat_id)
                await safe_edit(event, "🧹 **Chat Memory Cleared.**")
            elif arg == "dm":
                config["ai_scope"] = "dm"
                save_user_config(chat_id, config)
                await safe_edit(event, "📩 **AI Scope → DMs only**")
            elif arg == "groups":
                config["ai_scope"] = "groups"
                save_user_config(chat_id, config)
                await safe_edit(event, "👥 **AI Scope → Groups only**")
            elif arg == "all":
                config["ai_scope"] = "all"
                save_user_config(chat_id, config)
                await safe_edit(event, "🌐 **AI Scope → All chats**")
            elif arg == "status":
                active_key = ai_engine.keys[ai_engine.current_key_idx][:8] + "..."
                await safe_edit(event,
                    f"🤖 **AI Status**\n"
                    f"enabled: `{config['ai_enabled']}`\n"
                    f"scope: `{config['ai_scope']}`\n"
                    f"active key: `{active_key}`")
            else:
                await safe_edit(event, "Commands: `.ai on` `.ai off` `.ai clear` `.ai status` `.ai dm` `.ai groups` `.ai all`")

        @user_bot.on(events.NewMessage(pattern=r'^\.ignore\s+(.+)$', outgoing=True))
        async def ignore_cmd(event):
            if event.sender_id != USER_ID: return
            words_str = event.pattern_match.group(1).strip()
            words = [w.strip().lower() for w in words_str.split(',') if w.strip()]
            config = load_user_config(chat_id)
            
            added = []
            for word in words:
                if word not in config["ignored_words"]:
                    config["ignored_words"].append(word)
                    added.append(word)
            save_user_config(chat_id, config)
            
            if added:
                await safe_edit(event, f"🙈 **Ignored:** `{', '.join(added)}`")
            else:
                await safe_edit(event, "⚠️ Already in ignore list.")

        @user_bot.on(events.NewMessage(pattern=r'^\.personality\s+(.+)$', outgoing=True))
        async def personality_cmd(event):
            if event.sender_id != USER_ID: return
            prompt = event.pattern_match.group(1).strip()
            config = load_user_config(chat_id)
            config["personality"] = prompt
            save_user_config(chat_id, config)
            await safe_edit(event, f"🎭 **Personality Updated!**\n*{prompt}*")

        # ─── AUTO REPLY HANDLER ───
        @user_bot.on(events.NewMessage(incoming=True))
        async def handle_incoming_messages(event):
            if not event.is_private and not event.mentioned and not event.is_reply: return # Ignore random group chat
            
            sender = await event.get_sender()
            if sender.id == USER_ID: return

            message_text = (event.raw_text or "").lower().strip()
            config = load_user_config(chat_id)

            try:
                # 1. GREETINGS (Only in private DMs)
                if event.is_private:
                    sender_id_str = str(sender.id)
                    greeted = config.get("greeted_users", [])
                    greetings = config.get("greetings", [])
                    if greetings and sender_id_str not in greeted:
                        for g in greetings:
                            try:
                                if g["type"] == "text":
                                    personalized = g["value"].replace("{name}", sender.first_name or "there")
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
                                await asyncio.sleep(0.5)
                            except Exception as ge:
                                print(f"Greeting error: {ge}")
                        greeted.append(sender_id_str)
                        config["greeted_users"] = greeted
                        save_user_config(chat_id, config)

                # 2. IGNORE LIST (Only if AI enabled)
                if config.get("ai_enabled"):
                    for bad_word in config.get("ignored_words", []):
                        if bad_word in message_text:
                            return

                # 3. KEYWORDS
                keyword_matched = False
                for trigger, replies_list in config["keywords"].items():
                    if trigger in message_text: 
                        if replies_list:
                            keyword_matched = True
                            for reply_text in replies_list:
                                await event.reply(reply_text)
                                await asyncio.sleep(1.5)
                        break
                
                if keyword_matched: return 

                # 4. AI ENGINE
                if config.get("ai_enabled"):
                    scope = config.get("ai_scope", "all")
                    if scope == "dm" and not event.is_private: return
                    if scope == "groups" and event.is_private: return

                    chat_key = event.chat_id
                    if chat_key in ai_processing: return
                    ai_processing.add(chat_key)

                    try:
                        await user_bot.send_read_acknowledge(event.chat_id)
                        reply, err = await ai_engine.ask(event.chat_id, event.raw_text, sender_name=sender.first_name)

                        if err:
                            print(f"[AI] {err}")
                            return
                        if not reply: return

                        try:
                            async with user_bot.action(event.chat_id, "typing"):
                                await asyncio.sleep(min(2, len(reply) / 40))
                        except Exception: pass

                        await event.reply(reply)
                    except Exception as e:
                        print(f"[AI] handler error: {e}")
                    finally:
                        ai_processing.discard(chat_key)
                    return

                # 5. QR
                if message_text == QR_CONFIG['keyword']:
                    await event.reply(f"📱 Here is your QR Code:\n\n{QR_CONFIG['qr_image_url']}\n\n{QR_CONFIG['caption']}")

            except Exception as e:
                print(f"Handler error: {e}")

        await bot.send_message(chat_id, f"🔥 **Ultimate Hybrid Bot Active!**\n👤 User: {me.first_name}\n\nSend `.ai on` in any chat to enable AI.\nSend `/start` to main bot to view commands.")
        await user_bot.run_until_disconnected()

    except Exception as e:
        print(f"Crash: {e}")
        if chat_id in active_sessions: active_sessions.pop(chat_id, None)
        try: await bot.send_message(chat_id, f"⚠️ Bot Stopped. Error: `{str(e)[:80]}`")
        except: pass

# ─── START BOT AND WEB SERVER ───
async def main():
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    await bot.run_until_disconnected()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
