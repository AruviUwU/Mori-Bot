"""
main.py
Bot Discord "Teman Nongkrong" — merespons saat di-mention di channel tertentu,
pake Gemini sebagai otak (SDK google.genai terbaru), dan inget percakapan tiap user via SQLite.
"""

import os
import json
import random
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
GEMINI_MODEL = "gemini-flash-latest"

SYSTEM_PROMPT = """Kamu adalah Mori, teman ngobrol Discord.

# Kepribadian
- Santai, ramah, asik diajak ngobrol.
- Humornya receh dan kadang usil.
- Boleh roasting ringan yang lucu, tapi jangan menghina fisik, SARA, atau hal sensitif.
- Gunakan bahasa Indonesia kasual seperti orang nongkrong di Discord.
- Sesekali gunakan "wkwk", "jir", "lah", "anjir", "bjir", "😭", "😂", "😌", secukupnya.
- Variasikan gaya bahasa. Jangan terpaku pada satu pola kalimat.
- Jangan terdengar seperti customer service atau AI formal.

# Cara Menjawab
- Jawab sesuai konteks percakapan.
- Jangan menyalin contoh percakapan secara mentah.
- Gunakan contoh yang diberikan hanya sebagai referensi gaya bicara dan kepribadian.
- Jika ada beberapa contoh yang mirip, gabungkan gayanya lalu buat respons yang baru.
- Balasan biasanya 1–4 kalimat, kecuali pengguna meminta penjelasan panjang.
- Sering ajukan pertanyaan balik agar percakapan tetap mengalir.

# Prioritas
1. Ikuti system prompt ini.
2. Gunakan riwayat chat untuk menjaga konteks.
3. Gunakan contoh percakapan sebagai referensi gaya, bukan sebagai jawaban yang harus disalin.
4. Balas pesan pengguna secara natural.

# Larangan
- Jangan mengaku melakukan sesuatu yang tidak bisa kamu lakukan.
- Jangan mengarang fakta.
- Jangan mengulang kalimat yang sama terus-menerus.
- Jangan menjawab persis sama dengan contoh kecuali memang sangat diperlukan.

# Pencarian Web
- Kamu punya akses ke pencarian web buat info terkini (sekarang tahun 2026).
- Kalau pakai info dari hasil pencarian, sampaikan secara natural layaknya orang ngobrol biasa.
- Jangan tampilkan angka referensi/kutipan atau link sumber mentah-mentah di balasan."""


EXAMPLES_PATH = os.getenv("EXAMPLES_PATH", "example_conversations.json")

# Berapa banyak contoh yang diambil SECARA ACAK dari example_conversations.json
# tiap kali bot bikin request ke Gemini. Diambil sebagian (bukan semua) biar:
# 1) kombinasi konteks beda-beda tiap request -> ngurangin resiko jawaban "nempel"
#    ke satu contoh spesifik
# 2) hemat token dibanding ngirim semua contoh tiap kali
EXAMPLE_SAMPLE_SIZE = int(os.getenv("EXAMPLE_SAMPLE_SIZE", "10"))

# Sedikit di atas default biar variasi kata makin kerasa, tapi masih cukup
# koheren buat obrolan santai (bukan tugas yang butuh presisi tinggi).
GEMINI_TEMPERATURE = float(os.getenv("GEMINI_TEMPERATURE", "0.9"))


def _load_raw_examples(path: str = EXAMPLES_PATH) -> list[dict]:
    """Baca example_conversations.json, return list mentah (belum diformat)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"⚠️ File contoh percakapan ({path}) nggak ketemu, lanjut tanpa contoh.")
        return []
    except json.JSONDecodeError as e:
        print(f"⚠️ File contoh percakapan ({path}) gagal di-parse: {e}")
        return []

    examples = data.get("examples", [])
    valid = [
        ex for ex in examples
        if str(ex.get("user", "")).strip() and str(ex.get("mori", "")).strip()
    ]
    print(f"✅ {len(valid)} contoh percakapan berhasil dimuat dari {path}")
    return valid


_ALL_EXAMPLES = _load_raw_examples()


def build_system_prompt(sample_size: int = EXAMPLE_SAMPLE_SIZE) -> str:
    """
    Ambil sample acak dari contoh percakapan dan sambungin ke SYSTEM_PROMPT.
    Dipanggil tiap request (bukan sekali pas startup) biar sample-nya beda-beda.
    """
    if not _ALL_EXAMPLES:
        return SYSTEM_PROMPT

    sample = random.sample(_ALL_EXAMPLES, min(sample_size, len(_ALL_EXAMPLES)))
    lines = [f"User: {ex['user'].strip()}\nMori: {ex['mori'].strip()}" for ex in sample]
    example_block = (
        "# Contoh Percakapan (referensi gaya bicara — JANGAN disalin mentah)\n\n"
        + "\n\n".join(lines)
    )
    return SYSTEM_PROMPT + "\n\n" + example_block

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


MAX_MESSAGE_LENGTH = 1950  # buffer dari limit Discord 2000


def chunk_message(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> list[str]:
    """
    Pecah teks panjang jadi beberapa pesan, coba potong di batas paragraf/kalimat
    dulu (bukan asal potong di tengah kata) supaya tetap enak dibaca.
    """
    if len(text) <= max_length:
        return [text]

    chunks = []
    remaining = text.strip()

    while len(remaining) > max_length:
        window = remaining[:max_length]

        # Coba cari titik potong paling natural: paragraf > kalimat > spasi
        split_at = window.rfind("\n\n")
        if split_at == -1 or split_at < max_length * 0.4:
            split_at = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
            if split_at != -1:
                split_at += 1  # sertakan tanda baca
        if split_at == -1 or split_at < max_length * 0.4:
            split_at = window.rfind(" ")
        if split_at == -1 or split_at < max_length * 0.4:
            split_at = max_length  # kepepet, potong aja

        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()

    if remaining:
        chunks.append(remaining)

    return chunks


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
                    system_instruction=build_system_prompt(),
                    temperature=GEMINI_TEMPERATURE,
                    thinking_config=types.ThinkingConfig(
                        thinking_level="low",
                    ),
                    # Dimatiin sementara: kuota grounding/google_search di akun ini masih 0
                    # (butuh billing aktif dulu). Tinggal uncomment baris di bawah kalau
                    # udah siap, dan hapus catatan "Pencarian Web" di SYSTEM_PROMPT kalau
                    # mau dimatiin permanen.
                    # tools=[types.Tool(google_search=types.GoogleSearch())],
                ),
            )
            response = await chat.send_message(user_text)
            reply_text = response.text.strip()

            # Simpan pesan user dan balasan bot ke memory
            database.save_message(user_id, "user", user_text)
            database.save_message(user_id, "assistant", reply_text)

            # Discord limit 2000 karakter per pesan — pecah jadi beberapa pesan
            # berurutan kalau kepanjangan, bukan dipotong/di-truncate.
            chunks = chunk_message(reply_text)

            first, rest = chunks[0], chunks[1:]
            await message.reply(first, mention_author=False)
            for chunk in rest:
                await message.channel.send(chunk)

        except Exception as e:
            print(f"⚠️ Error: {e}")
            await message.reply(
                "Aduh, ada yang error nih di otak gue. Coba tanya lagi bentar ya 😅",
                mention_author=False,
            )


if __name__ == "__main__":
    client.run(DISCORD_TOKEN)