"""
main.py
Bot Discord "Teman Nongkrong" — merespons saat di-mention di channel tertentu,
pake Gemini sebagai otak (SDK google.genai terbaru), dan inget percakapan tiap user via SQLite.
"""

import os
import json
import random
import asyncio
import discord
from datetime import datetime
from zoneinfo import ZoneInfo
from google import genai
from google.genai import types
from dotenv import load_dotenv
from ddgs import DDGS
from ddgs.exceptions import DDGSException, RatelimitException, TimeoutException

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

# Timezone dipakai buat nentuin "hari ini"/"sekarang" versi bot. Ganti kalau
# server/majoritas user-nya di zona waktu lain.
BOT_TIMEZONE = ZoneInfo(os.getenv("BOT_TIMEZONE", "Asia/Jakarta"))

_INDO_HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
_INDO_BULAN = [
    "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]


def get_tanggal_sekarang() -> str:
    """String tanggal+jam sekarang dalam Bahasa Indonesia, dipake buat kasih tau Gemini 'hari ini' itu tanggal berapa."""
    now = datetime.now(BOT_TIMEZONE)
    hari = _INDO_HARI[now.weekday()]
    bulan = _INDO_BULAN[now.month]
    return f"{hari}, {now.day} {bulan} {now.year}, pukul {now.strftime('%H:%M')} WIB"


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

# Tanggal & Waktu
- Di awal system prompt ini (bagian paling atas, sebelum kepribadian) ada info tanggal & jam SEKARANG yang sebenarnya. WAJIB pakai itu sebagai patokan tunggal buat "hari ini", "sekarang", "besok", "minggu ini", dst -- JANGAN pernah nebak-nebak atau pakai tanggal dari ingatan/pelatihanmu sendiri, karena itu bisa aja sudah basi.
- Kalau user nanya sesuatu yang sifatnya "hari ini"/"sekarang" (jadwal, pertandingan, acara, dll), SELALU sertakan tanggal spesifik itu ke query pencarian tool `cari_info_terbaru` (misal 'jadwal VCT Pacific 18 Juli 2026', bukan cuma 'jadwal VCT Pacific hari ini' -- tool pencariannya gak ngerti kata 'hari ini', harus tanggal konkret).

# Pencarian Web
- Kamu punya tool bernama `cari_info_terbaru` buat cari info real-time dari internet.
- Panggil tool itu SENDIRI kalau pertanyaan butuh data yang mungkin berubah-ubah atau kejadiannya baru-baru ini — misalnya cuaca hari ini, skor/hasil pertandingan, siapa yang menang/juara sesuatu, berita, harga, jadwal, atau topik apapun yang kamu gak yakin datanya masih akurat.
- Kalau pertanyaannya cuma obrolan santai / gak butuh data terkini, JANGAN panggil tool-nya, jawab langsung aja.
- Buat hal yang time-sensitive (jadwal pertandingan, skor, siapa yang lagi tanding, dst), PRIORITASKAN hasil dari tool dibanding pengetahuan internalmu. Pengetahuan internalmu soal jadwal/stage/matchup itu SANGAT RAWAN sudah usang atau salah stage/tanggal -- jangan dicampur-campur sama hasil pencarian, apalagi kalau ternyata beda. Kalau ada konflik, hasil pencarian yang menang.
- Setelah dapet hasil dari tool, cek dulu apakah itu beneran relevan, spesifik ke tanggal yang ditanya, dan menjawab pertanyaan. Kalau relevan, sampaikan secara natural layaknya orang ngobrol biasa (jangan bilang "menurut hasil pencarian" atau semacamnya).
- Kalau hasil tool TIDAK relevan, TIDAK menjawab pertanyaan, gak match sama tanggal yang ditanya, atau kosong/gagal, JANGAN dipaksain dipakai. Jujur aja bilang kamu udah coba cari tapi gak nemu info yang pas, atau nggak usah nyambung-nyambungin biar keliatan njawab.
- Jangan pernah ngaku-ngaku udah "cek" atau "cari" sesuatu kalau kamu sebenarnya nggak manggil tool `cari_info_terbaru`.
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


async def cari_info_terbaru(query: str, max_results: int = 5) -> str:
    """
    Cari info dari DuckDuckGo dan kembalikan sebagai string.

    Dijalankan lewat asyncio.to_thread supaya panggilan network yang blocking
    dari `ddgs` tidak nge-freeze event loop Discord (penyebab bot lag/putus
    koneksi pas lagi searching).
    """

    def _search():
        with DDGS() as ddgs:
            return list(
                ddgs.text(query, max_results=max_results, region="id-id", backend="auto")
            )

    try:
        results = await asyncio.to_thread(_search)
    except RatelimitException:
        print(f"⚠️ DDGS kena rate limit (query={query!r})")
        return "GAGAL: pencarian lagi kena rate limit, coba lagi nanti."
    except TimeoutException:
        print(f"⚠️ DDGS timeout (query={query!r})")
        return "GAGAL: pencarian timeout."
    except DDGSException as e:
        print(f"⚠️ Error pencarian web (query={query!r}): {e}")
        return "GAGAL: pencarian error."
    except Exception as e:
        print(f"⚠️ Error pencarian web tak terduga (query={query!r}): {e}")
        return "GAGAL: pencarian error."

    if not results:
        print(f"ℹ️ DDGS gak nemu hasil (query={query!r})")
        return "GAGAL: tidak ada hasil pencarian yang ketemu untuk query ini."

    print(f"🔎 DDGS ketemu {len(results)} hasil (query={query!r})")
    info = [f"- {r['title']}: {r['body']}" for r in results]
    return "\n".join(info)


# Tool/function declaration yang dikasih ke Gemini. Gemini sendiri yang mutusin
# kapan perlu manggil ini berdasarkan isi pertanyaan user (tidak ada lagi
# keyword/regex matching manual di sisi bot -- itu gampang meleset: kadang
# ke-trigger di obrolan biasa, kadang malah nggak ke-trigger pas emang perlu).
SEARCH_TOOL = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="cari_info_terbaru",
            description=(
                "Cari informasi terkini/real-time dari internet lewat web search. "
                "Pakai ini kalau pertanyaan butuh data yang mungkin berubah-ubah atau "
                "baru terjadi, misalnya: cuaca hari ini, skor/hasil pertandingan, siapa "
                "yang menang/juara sesuatu, berita, harga barang, jadwal acara, atau "
                "topik apapun yang kejadiannya baru-baru ini sehingga pengetahuanmu "
                "sendiri mungkin sudah usang. Jangan dipakai untuk obrolan santai biasa "
                "atau pertanyaan yang tidak butuh data terkini."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "query": types.Schema(
                        type=types.Type.STRING,
                        description=(
                            "Query pencarian yang jelas, spesifik, dan sudah dibersihkan "
                            "dari basa-basi (bukan copy-paste mentah kalimat user). Kalau "
                            "user nyebut 'hari ini'/'sekarang', GANTI dengan tanggal konkret "
                            "(pakai info tanggal sekarang dari system prompt), misalnya "
                            "'cuaca Karawang 18 Juli 2026' atau 'jadwal VCT Pacific 18 Juli 2026' "
                            "-- jangan kirim kata 'hari ini' apa adanya ke query."
                        ),
                    ),
                },
                required=["query"],
            ),
        )
    ]
)


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
    Tempelin info tanggal/jam sekarang + ambil sample acak dari contoh percakapan,
    sambungin ke SYSTEM_PROMPT. Dipanggil tiap request (bukan sekali pas startup)
    biar tanggal & sample-nya selalu up to date/beda-beda.
    """
    tanggal_block = f"# Info Tanggal & Waktu Sekarang\nSekarang: {get_tanggal_sekarang()}.\n\n"

    if not _ALL_EXAMPLES:
        return tanggal_block + SYSTEM_PROMPT

    sample = random.sample(_ALL_EXAMPLES, min(sample_size, len(_ALL_EXAMPLES)))
    lines = [f"User: {ex['user'].strip()}\nMori: {ex['mori'].strip()}" for ex in sample]
    example_block = (
        "# Contoh Percakapan (referensi gaya bicara — JANGAN disalin mentah)\n\n"
        + "\n\n".join(lines)
    )
    return tanggal_block + SYSTEM_PROMPT + "\n\n" + example_block

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


def _extract_function_call(response):
    """Ambil function_call pertama dari response Gemini, kalau ada. None kalau nggak ada."""
    try:
        parts = response.candidates[0].content.parts or []
    except (AttributeError, IndexError, TypeError):
        return None
    for part in parts:
        fc = getattr(part, "function_call", None)
        if fc is not None:
            return fc
    return None


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
                    tools=[SEARCH_TOOL],
                ),
            )

            response = await chat.send_message(user_text)

            # Loop function-calling manual: Gemini yang mutusin sendiri kapan
            # perlu manggil cari_info_terbaru. Dibatasi biar gak infinite loop
            # kalau modelnya ngotot manggil tool terus.
            for _ in range(3):
                function_call = _extract_function_call(response)
                if function_call is None:
                    break

                if function_call.name == "cari_info_terbaru":
                    query = function_call.args.get("query") or user_text
                    print(f"🔎 Gemini minta search: {query!r}")
                    hasil_search = await cari_info_terbaru(query)
                    function_response_part = types.Part.from_function_response(
                        name="cari_info_terbaru",
                        response={"result": hasil_search},
                    )
                    response = await chat.send_message(function_response_part)
                else:
                    # Tool yang gak dikenal, berhenti aja biar gak nyangkut
                    print(f"⚠️ Gemini minta tool tak dikenal: {function_call.name!r}")
                    break

            reply_text = response.text.strip()

            # PENTING: Simpan user_text ASLI ke memory, BUKAN hasil tool call
            # Biar database nggak kotor sama teks hasil scraping/function response
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