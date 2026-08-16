# Charcoal Outreach Bot

Bot auto-offer WhatsApp/Email untuk lead export charcoal PT Cahaya Woodchar International, jalan
100% di cloud (GitHub Actions) - **tidak butuh device/PC pribadi nyala terus**. Baca & tulis balik
status ke Google Sheet "Export Charcoal Business" (tab `CLIENT`).

## Cara kerja singkat

Tiap 30 menit, bot:
1. Baca semua baris di tab `CLIENT`.
2. Hitung jam lokal tiap negara klien (bukan pakai kolom manual di sheet) - kirim hanya kalau
   **Senin-Jumat, jam 09:00-17:00 waktu lokal klien**.
3. Skip klien yang `FCBK` = `LOST` atau `NO`, atau yang sudah kena 3x offer (`LAST_ROUND` = 3).
4. Kirim **WhatsApp dulu** (via Fonnte) - kalau nomor tidak ada/gagal, **fallback ke Email** (Gmail
   SMTP).
5. Tulis balik ke sheet: kolom offer round terkait = `DONE`, plus `LAST_ROUND` dan `LAST_SENT_AT`.

Detail lengkap ada di `DOCUMENTATION.docx`.

## Setup

1. `pip install -r requirements.txt`
2. Copy `.env.example` ke `.env`, isi:
   - `FONNTE_TOKEN` - daftar gratis di [fonnte.com](https://fonnte.com), scan QR nomor
     `+62 812-2564-6585` sekali di dashboard mereka.
   - `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` - App Password dari
     [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) (butuh 2FA aktif).
   - `GOOGLE_SHEET_ID` / `GOOGLE_SERVICE_ACCOUNT_JSON` - service account Google Cloud, sheet-nya
     harus di-share (role Editor) ke email service account itu.
3. Test dulu: `DRY_RUN=true python main.py` - cek log, gak ada yang benar-benar terkirim.
4. Kalau sudah oke, set semua env var di atas sebagai **GitHub Secrets** di repo ini (Settings >
   Secrets and variables > Actions), termasuk `DRY_RUN=false` kalau sudah siap live.
5. Workflow `.github/workflows/outreach.yml` otomatis jalan tiap 30 menit setelah di-push ke
   GitHub. Bisa juga trigger manual lewat tab Actions > Run workflow.

## File penting

| File | Fungsi |
|---|---|
| `main.py` | orchestrator - loop semua baris, decide kirim/skip |
| `timezone_rules.py` + `country_timezones.py` | hitung jam kerja lokal per negara |
| `sheet_client.py` | baca/tulis Google Sheet |
| `templates.py` | isi pesan WA & Email, personalisasi per klien |
| `send_whatsapp.py` | kirim via Fonnte |
| `send_email.py` | kirim via Gmail SMTP |
| `discovery_main.py` + `discovery/` | cari lead baru (scraping), lihat bagian di bawah |

## Lead discovery (cari lead baru)

`discovery_main.py` (workflow `.github/workflows/lead-discovery.yml`, cron harian) scan sumber-sumber
di bawah, dedup terhadap sheet `CLIENT` yang ada, cari email/kontak dari website lead (kalau ada),
lalu nambah baris baru ke sheet (Company/Country/Contact/Phone/WhatsApp/Email terisi, Role/Product
Interest sengaja dikosongkan buat diisi manual).

- **Google Maps search otomatis** (`discovery/gmaps_search_scraper.py`) - **default aktif, gak
  butuh input apapun.** Search langsung ("charcoal importer in Turkey", dst) ke **semua ~249
  negara** (pycountry, cakupan global penuh - bukan cuma pasar known) x beberapa query
  buyer-intent, tanpa perlu link list manual. Terverifikasi jalan live. Cakupan dibatasi 40 kombo
  query×negara per run, rotasi otomatis berdasarkan tanggal - sapuan penuh (~996 kombo) selesai
  bertahap ~25 hari lewat banyak run cron harian, bukan sekaligus.
- **Google Maps shared list** (`discovery/gmaps_scraper.py`) - opsional, kalau kamu udah punya
  link list spesifik lewat env var `GMAPS_LIST_URLS` (pisah koma), jalan BARENG search otomatis
  di atas (bukan gantiin).
- **Web scraper** (`discovery/web_scraper.py`) - TradeIndia/ExportHub/Kompass/Google search.
  **Status saat ini: semua 4 sumber diblokir bot-detection** (CloudFront/Cloudflare/CAPTCHA) dari
  IP cloud biasa - bukan bug kode, butuh proxy berbayar buat bypass beneran. Tetap ada di kode
  (gagal dengan aman, gak nge-crash run) siapa tahu suatu saat bisa dipakai lagi.

`DISCOVERY_DRY_RUN=true` (default) = preview lead yang ketemu doang, gak nulis ke sheet.

## Rekap harian (tab CORE DATABASE)

Tiap run outreach yang berhasil kirim ≥1 offer, main.py nulis totalnya ke tabel kecil di kolom
X/Y tab `CORE DATABASE` (area kosong, gak nimpa data existing) - satu baris per tanggal (format
DD/MM/YYYY, WIB/Asia Jakarta), increment kalau tanggal itu udah ada (banyak run per hari karena
cron tiap 30 menit), append baris baru kalau ganti hari. Mulai terhitung dari tanggal fitur ini
diaktifkan, bukan direkonstruksi dari histori lama.
