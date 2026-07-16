"""
main.py
Bot Discord "Teman Nongkrong" — merespons saat di-mention di channel tertentu,
pake Gemini sebagai otak (SDK google.genai terbaru), dan inget percakapan tiap user via SQLite.
"""

import os
import discord
from google import genai
from google.genai import types
from dotenv import load_dotenv

import database

# ----- Load config dari environment variables -----
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Bisa lebih dari 1 channel, pisahin pakai koma di .env
# Contoh: ALLOWED_CHANNEL_IDS=123456789012345678,987654321098765432
_raw_channel_ids = os.getenv("ALLOWED_CHANNEL_IDS", "")
ALLOWED_CHANNEL_IDS = [
    int(cid.strip()) for cid in _raw_channel_ids.split(",") if cid.strip()
]

if not DISCORD_TOKEN or not GEMINI_API_KEY or not ALLOWED_CHANNEL_IDS:
    raise RuntimeError(
        "Pastikan DISCORD_TOKEN, GEMINI_API_KEY, dan ALLOWED_CHANNEL_IDS sudah diset di .env"
    )

# ----- Setup Gemini (SDK baru: google.genai) -----
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# Ganti di sini kalau mau pindah model lain dari hasil ListModels kamu,
# misal "gemini-flash-latest" atau "gemini-2.5-flash-lite"
# (gemini-2.5-flash sudah ditarik dari akses user baru, per Juli 2026)
GEMINI_MODEL = "gemini-3.1-flash-lite"

SYSTEM_PROMPT = """Kamu adalah "Teman Nongkrong", bot Discord yang jadi teman ngobrol di server komunitas.

Kepribadian kamu:
- Santai, kasual, pakai bahasa gaul Indonesia sehari-hari (gue-lu atau aku-kamu, natural aja)
- Asyik diajak bercanda, ramah, responsif
- Bisa diajak ngobrol topik apa aja — dari hal random sampai diskusi teknis kayak desain avatar,
  simulasi komponen, atau mekanik board game
- Jawaban ringkas dan ngalir kayak chat beneran, jangan kaku atau kayak robot corporate
- Anggap user sebagai teman main kamu sendiri

Jangan pakai format artikel atau bullet list kecuali user emang minta dijelasin detail teknis."""

# ----- Setup Discord client -----
intents = discord.Intents.default()
intents.message_content = True  # WAJIB diaktifkan juga di Discord Developer Portal

client = discord.Client(intents=intents)


def build_gemini_history(history: list[dict]) -> list[types.Content]:
    """Convert history dari SQLite (role: user/assistant) ke format Content SDK baru."""
    gemini_history = []
    for msg in history:
        role = "model" if msg["role"] == "assistant" else "user"
        gemini_history.append(
            types.Content(role=role, parts=[types.Part.from_text(text=msg["content"])])
        )
    return gemini_history


@client.event
async def on_ready():
    database.init_db()
    print(f"✅ Login sebagai {client.user} — siap nongkrong!")


@client.event
async def on_message(message: discord.Message):
    # Jangan respon ke diri sendiri atau bot lain
    if message.author.bot:
        return

    # Cuma aktif di channel-channel yang ditentuin (public + testing)
    if message.channel.id not in ALLOWED_CHANNEL_IDS:
        return

    # Cuma respon kalau di-mention
    if client.user not in message.mentions:
        return

    # Bersihin teks mention dari isi pesan
    user_text = message.content.replace(f"<@{client.user.id}>", "").strip()
    user_text = user_text.replace(f"<@!{client.user.id}>", "").strip()

    if not user_text:
        user_text = "Halo!"

    user_id = str(message.author.id)

    async with message.channel.typing():
        try:
            history = database.get_history(user_id, limit=30)
            gemini_history = build_gemini_history(history)

            chat = gemini_client.aio.chats.create(
                model=GEMINI_MODEL,
                history=gemini_history,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    thinking_config=types.ThinkingConfig(
                        thinking_level="low",
                    ),
                ),
            )
            response = await chat.send_message(user_text)
            reply_text = response.text.strip()

            # Simpan pesan user dan balasan bot ke memory
            database.save_message(user_id, "user", user_text)
            database.save_message(user_id, "assistant", reply_text)

            # Discord limit 2000 karakter per pesan
            if len(reply_text) > 1900:
                reply_text = reply_text[:1900] + "..."

            await message.reply(reply_text, mention_author=False)

        except Exception as e:
            print(f"⚠️ Error: {e}")
            await message.reply(
                "Aduh, ada yang error nih di otak gue. Coba tanya lagi bentar ya 😅",
                mention_author=False,
            )


if __name__ == "__main__":
    client.run(DISCORD_TOKEN)