# Teman Nongkrong 🎮 — Mori

Bot Discord teman ngobrol santai (persona: **Mori**), pakai Gemini + memory per-user (SQLite)
dan pencarian web (Google Search grounding) buat info terkini.

## Struktur

```
teman-nongkrong/
├── main.py                     # Logic bot utama
├── database.py                  # SQLite memory per user
├── example_conversations.json   # Contoh percakapan (referensi gaya bicara Mori)
├── requirements.txt
├── Procfile                     # Buat Railway
├── .env
└── .gitignore
```

## Setup Lokal (Testing)

1. Clone/copy folder ini, lalu install dependency:
   ```
   pip install -r requirements.txt
   ```

2. Copy `.env.example` jadi `.env`, isi 3 variable:
   - `DISCORD_TOKEN` — dari Discord Developer Portal > Bot > Token
   - `GEMINI_API_KEY` — dari [Google AI Studio](https://aistudio.google.com/app/apikey)
   - `ALLOWED_CHANNEL_IDS` — ID channel publik dan testing, dipisah koma (klik kanan channel
     dengan Developer Mode ON > Copy Channel ID). Contoh: `ALLOWED_CHANNEL_IDS=111111,222222`

3. Pastikan di Discord Developer Portal, intent **MESSAGE CONTENT INTENT** sudah di-enable
   (Bot tab > Privileged Gateway Intents).

4. Jalankan:
   ```
   python main.py
   ```

5. Test dengan mention bot di channel yang sudah ditentukan: `@Mori halo!`

## Deploy ke Railway

1. Push folder ini ke GitHub repo.
2. Di Railway: New Project > Deploy from GitHub repo.
3. Railway otomatis detect `Procfile` dan `requirements.txt`.
4. Masuk ke tab **Variables**, tambahkan 3 environment variable yang sama kayak di `.env`:
   - `DISCORD_TOKEN`
   - `GEMINI_API_KEY`
   - `ALLOWED_CHANNEL_IDS` (isi kedua channel, dipisah koma)
5. Deploy. Cek log — kalau muncul `✅ Login sebagai ...` berarti bot udah online 24/7.

## Catatan Penting

- **Memory**: disimpan per user_id di SQLite (`bot_memory.db`), unlimited history di database,
  tapi cuma 30 pesan terakhir yang dikirim ke Gemini tiap request (biar hemat token & tetap cepat).
- **Railway punya ephemeral filesystem** di beberapa plan — kalau bot di-redeploy, `bot_memory.db`
  bisa ke-reset. Kalau memory jangka panjang penting banget, nanti kita bisa upgrade ke Railway
  Volume atau pindah ke Postgres. Untuk sekarang (server kecil, testing) SQLite lokal udah cukup.
- **Trigger**: bot cuma respon kalau di-mention DAN channel-nya ada di daftar `ALLOWED_CHANNEL_IDS`
  (public + testing).
- **Search grounding**: bot bisa pakai Google Search lewat Gemini buat jawab hal-hal terkini
  (bukan cuma dari data pelatihan). Hasil pencarian disampaikan natural tanpa nomor kutipan/link.
- **Contoh percakapan**: gaya bicara Mori sebagian direferensiin dari `example_conversations.json`
  (banyak pasang `user` ↔ `mori` per kategori: sapaan, roasting ringan, obrolan receh, dll).
  Bot otomatis nge-load & nyambungin isinya ke system prompt pas start (`load_example_conversations()`
  di `main.py`). Kalau file ini nggak ada, bot tetap jalan normal cuma tanpa contoh tambahan —
  jadi aman buat nge-edit/nambah contoh kapan aja tanpa nyentuh kode.
- **Pesan panjang**: kalau balasan Gemini lebih dari ~1950 karakter, bot otomatis pecah jadi
  beberapa pesan Discord berurutan (dipotong di batas paragraf/kalimat, bukan asal potong/di-truncate).
- Kalau mau reset memory user tertentu, bisa panggil `database.clear_history(user_id)` manual
  atau kita tambahin command khusus nanti (misal `!lupain`).

## Next Steps (Opsional)

- Command `!lupain` buat clear memory sendiri
- Rate limiting per user biar gak spam
- Slash command version (`/ngobrol`) kalau mau lebih modern