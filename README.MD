# SmartClinic CRM AI (Hana)

AI Chatbot backend for SmartClinic — hybrid routing between Rasa NLP (structured intents) and Groq LLM (contextual/complaint handling), delivered via WhatsApp through Fonnte.

> **Developer**:
>
> - Raja Zhafif Raditya Harahap
> - MHD. Rafy Firdaus
> - Wahyu Hardiyantara

---

## 🏗 Architecture

```
WhatsApp (Patient)
       │
       ▼
  Fonnte Gateway
       │  POST /webhook
       ▼
  FastAPI (Hybrid Router)
       │
       ├──► [Handoff?] ──► Bot diam, admin balas dari Dashboard
       │
       ├──► Rasa NLP ──► High confidence + trusted intent ──► Reply langsung
       │
       └──► Groq LLM ──► Low confidence / complaint / kontekstual
       │
       ▼
  Fonnte Queue (anti-spam delay 3–5 detik)
       │
       ▼
WhatsApp (Patient)
```

---

## 📦 Modules & Major Components

Berikut ringkasan modul utama dan bagaimana mereka terhubung di kode (file referensi ada di paren):

- FastAPI router (entrypoint)
     - File: `App/app.py` — inisialisasi FastAPI, daftarkan semua router, dan start background scheduler.
     - OpenAPI / Swagger UI tersedia di `/docs` ketika server berjalan. Untuk eksplorasi interaktif gunakan: https://ai-crm.brotherzhafif.my.id/docs

- Routers (lokasi: `App/routers/`)
     - `webhook.py` — `GET /` (health) dan `POST /webhook` (entrypoint inbound dari Fonnte). [App/routers/webhook.py](App/routers/webhook.py#L1)
     - `patients.py` — CRUD pasien (`/api/patients`). [App/routers/patients.py](App/routers/patients.py#L1)
     - `messages.py` — SSE realtime untuk sidebar/chat (`/api/messages/latest`, `/api/messages/{phone_number}`), tampil di grup OpenAPI `Unified Chat`. [App/routers/messages.py](App/routers/messages.py#L1)
     - `send.py` — kirim pesan manual dan broadcast (`/api/send`, `/api/send/broadcast`). [App/routers/send.py](App/routers/send.py#L1)
     - `handoff.py` — manajemen sesi handoff/admin (`/api/handoff`), tampil di grup OpenAPI `Unified Chat`. [App/routers/handoff.py](App/routers/handoff.py#L1)
     - `wa.py` — helper endpoints menuju wa-service (status, qr-stream). [App/routers/wa.py](App/routers/wa.py#L1)
     - `campaign.py` — marketing/campaigns (`/api/marketing/campaigns` prefix). [App/routers/campaign.py](App/routers/campaign.py#L1)

- Rasa NLP (lokasi: `rasa/`)
     - Framework: Rasa (use the action server for custom actions in `rasa/actions/actions.py`).
     - Confidence threshold dan trusted intents: Rasa digunakan untuk intent terstruktur; trusted intents (handled directly) mencakup greetings, scheduling queries, simple FAQs, dan booking/rating intents.

- Groq LLM (lokasi: `LLM/groq_service.py`)
     - Digunakan sebagai fallback dan untuk teks kontekstual/keluhan.
     - Roles: `default` (informasi klinik) dan `triage` (keluhan kesehatan — dipicu oleh keyword seperti `sakit`, `demam`, `nyeri`).
     - Chat memory: 5 percakapan terakhir per nomor disimpan sebagai local JSON di `chat_history/` dan digunakan untuk konteks LLM.

- Handoff manager (`App/handoff_manager.py`)
     - Mengatur state handoff per nomor, timeout otomatis, dan helper untuk dashboard/admin.
     - Trigger: keyword oleh pasien atau auto-handoff setelah Groq fallback berulang.
     - Default timeout bisa disesuaikan via env var `HANDOFF_TIMEOUT_MINUTES`.

- Queue manager (`App/queue_manager.py`)
     - Menangani antrean pengiriman ke Fonnte dengan delay acak (3–7 detik) untuk mensimulasikan pengetikan dan mengurangi risiko pemblokiran.

- Campaign scheduler (`App/campaign_scheduler.py`)
     - Background worker yang memicu campaign terjadwal ke tabel `campaigns` dan memasukkannya ke queue untuk dikirim.

- Persistence & helpers
     - Supabase client/config di `App/config.py` dan helper functions di `App/helpers.py` (simpan ke DB, upsert pasien, query Rasa, dsb).
     - Local state folders: `chat_history/`, `chat_state/`, `handoff_state/` untuk menyimpan JSON state per nomor.

---

Jika ingin file-by-file ringkasan (contoh: semua endpoint di tiap router dengan contoh request/response), saya bisa generate halaman dokumentasi Markdown otomatis dari decorator `responses`/`Body(..., examples=...)` di setiap router — beri tahu kalau mau saya generate itu.

## 🛠 Tech Stack

| Component        | Technology                       |
| ---------------- | -------------------------------- |
| Language         | Python 3.9+                      |
| API Framework    | FastAPI + Uvicorn                |
| NLP              | Rasa 3.6.15                      |
| LLM              | Groq Cloud API (Llama 3)         |
| Database         | Supabase (PostgreSQL)            |
| WhatsApp Gateway | Fonnte API                       |
| Containerization | Docker + Docker Compose          |
| Tunnel           | Cloudflare Tunnel                |
| CI/CD            | GitHub Actions                   |
| Hosting          | Oracle VPS (Ubuntu 20.04, ARM64) |

---

## 📁 Project Structure

```
smartclinic/
├── app.py                          # FastAPI init + include_router
├── App/
│   ├── __init__.py
│   ├── config.py                   # Semua konstanta & env variables
│   ├── models.py                   # Semua Pydantic request/response models
│   ├── helpers.py                  # Helper functions (Supabase, JSON, Rasa, dll)
│   ├── handoff_manager.py          # State handoff + auto timeout logic
│   ├── queue_manager.py            # Fonnte message queue dengan delay
│   └── routers/
│       ├── __init__.py
│       ├── webhook.py              # GET / + POST /webhook
│       ├── patients.py             # /api/patients
│       ├── messages.py             # /api/messages
│       ├── send.py                 # /api/send + /api/send/broadcast
│       └── handoff.py              # /api/handoff
├── LLM/
│   ├── groq_service.py             # Groq LLM integration
│   └── requirements.txt
├── rasa/
│   ├── actions/
│   │   └── actions.py              # Custom Rasa actions
│   ├── data/                       # NLU training data & stories
│   ├── models/                     # Trained Rasa models
│   └── config.yml
├── chat_history/                   # Local JSON chat memory (per nomor)
├── chat_state/                     # Onboarding state (per nomor)
├── handoff_state/                  # Handoff state (per nomor)
├── .github/
│   └── workflows/
│       └── deploy.yml              # GitHub Actions CI/CD
├── supabase_setup.sql              # Database setup script
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env
```

---

## ⚙️ Environment Variables

Buat file `.env` di root folder:

```env
# Groq LLM
GROQ_API_KEY=your_groq_api_key

# Fonnte WhatsApp Gateway
FONNTE_TOKEN=your_fonnte_token

# Rasa
RASA_URL=http://rasa:5005

# Supabase
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_ANON_KEY=your_supabase_anon_key

# Handoff timeout (opsional, default: 15 menit)
HANDOFF_TIMEOUT_MINUTES=15

# RME API Credentials
SMARTCLINIC_BASE_URL=https://smartclinic-rekam-medis.onrender.com/api/v1
SMARTCLINIC_EMAIL=AI_RME_email_credentials
SMARTCLINIC_PASSWORD=AI_RME_password_credentials
SMARTCLINIC_ACCESS_TOKEN=your_RME_access_token_from_login
```

---

## 🚀 Setup & Running

### Via Docker (recommended)

```bash
# 1. Clone repo
git clone https://github.com/USERNAME/REPO.git
cd REPO

# 2. Setup environment
cp .env.example .env
nano .env  # isi semua value

# 3. Build dan jalankan semua service
docker compose up -d --build

# 4. Cek status
docker compose ps
docker compose logs -f app
```

Services yang berjalan:

- `fastapi_chatbot` — FastAPI app di port 5000
- `rasa_server` — Rasa di port 5005
- `rasa_action_server` — Rasa action server di port 5055

---

### Rasa — Local Development

```bash
pip install rasa==3.6.15
cd rasa && rasa train
rasa run actions
rasa shell
```

### Train Rasa via Docker

```bash
docker run --rm \
  -v $(pwd)/rasa:/app \
  rasa/rasa:3.6.15-full train
```

---

## 🗄 Database Setup (Supabase)

Jalankan `supabase_setup.sql` di **Supabase Dashboard → SQL Editor**. Script ini membuat:

- Tabel `patients` — nomor & nama pasien (unique by phone_number)
- Tabel `messages` — semua pesan inbound/outbound
- Function `get_latest_messages()` — RPC untuk sidebar CRM
- Index & Row Level Security

---

## 🔄 CI/CD

Setiap push ke `main` otomatis deploy ke VPS via GitHub Actions.

**GitHub Secrets yang diperlukan:**

| Secret        | Value                                            |
| ------------- | ------------------------------------------------ |
| `VPS_HOST`    | IP VPS                                           |
| `VPS_USER`    | SSH username (`ubuntu`)                          |
| `VPS_SSH_KEY` | Private SSH key                                  |
| `VPS_APP_DIR` | Path project di VPS (`/home/ubuntu/smartclinic`) |
| `ENV_FILE`    | Seluruh isi `.env`                               |

Untuk update env (misal rotate Fonnte token): update secret `ENV_FILE` di GitHub → **Actions → Deploy to VPS → Run workflow**.
