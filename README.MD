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

Berikut ringkasan modul utama dan bagaimana mereka terhubung di kode:

- **FastAPI router (entrypoint)**
  - File: `App/app.py` — inisialisasi FastAPI, daftarkan semua router, dan start background scheduler.
  - OpenAPI / Swagger UI tersedia di `/docs` ketika server berjalan: https://ai-crm.brotherzhafif.my.id/docs

- **Routers** (lokasi: `App/routers/`)
  - `webhook.py` — `GET /` (health) dan `POST /webhook` (entrypoint inbound dari Fonnte).
  - `patients.py` — Proxy CRUD pasien ke SmartClinic RME API (`/api/v1/patients`). Setelah create pasien, otomatis insert mapping ke tabel Supabase `patients`. Includes endpoint `GET /api/v1/patients/by-phone` untuk AI agent lookup pasienId by nomor HP.
  - `schedules.py` — Proxy jadwal dokter ke SmartClinic RME API (`/api/v1/schedules`, `/api/v1/schedules/weekly`, `/api/v1/schedules/slots`).
  - `appointments.py` — Proxy janji temu & antrian ke SmartClinic RME API. Flow booking: lookup `rme_patient_id` by `phone_number` dari Supabase → hit `POST /api/v1/queues/appointments`. Includes `GET /api/v1/queues` untuk board antrian perawat/dokter.
  - `chatbot_settings.py` — Konfigurasi AI chatbot (`GET /api/v1/chatbot-settings`, `PUT /api/v1/chatbot-settings`). Data disimpan di tabel Supabase `chatbot_settings`.
  - `messages.py` — SSE realtime untuk sidebar/chat (`/api/messages/latest`, `/api/messages/{phone_number}`), tampil di grup OpenAPI `Unified Chat`.
  - `send.py` — kirim pesan manual dan broadcast (`/api/send`, `/api/send/broadcast`).
  - `handoff.py` — manajemen sesi handoff/admin (`/api/handoff`), tampil di grup OpenAPI `Unified Chat`.
  - `campaign.py` — marketing/campaigns (`/api/marketing/campaigns` prefix).
  - `status.py` — helper endpoints menuju wa-service (status, qr-stream).

- **SmartClinic RME Integration** (lokasi: `App/smartclinic/`)
  - Semua request ke SmartClinic RME menggunakan Bearer token dari `get_smartclinic_token()`.
  - Token di-fetch via login otomatis menggunakan kredensial di `.env` (`SMARTCLINIC_EMAIL`, `SMARTCLINIC_PASSWORD`).
  - Seluruh request dikirim sebagai role **ADMIN**.

- **Rasa NLP** (lokasi: `rasa/`)
  - Framework: Rasa — custom actions di `rasa/actions/actions.py`.
  - Trusted intents (handled directly): greetings, scheduling queries, simple FAQs, booking/rating intents.

- **Groq LLM** (lokasi: `LLM/groq_service.py`)
  - Fallback untuk teks kontekstual/keluhan.
  - Roles: `default` (informasi klinik) dan `triage` (keluhan kesehatan — dipicu keyword seperti `sakit`, `demam`, `nyeri`).
  - Chat memory: 5 percakapan terakhir per nomor di `chat_history/`.

- **Handoff manager** (`App/handoff_manager.py`)
  - State handoff per nomor, timeout otomatis, helper untuk dashboard/admin.
  - Default timeout via env var `HANDOFF_TIMEOUT_MINUTES`.

- **Queue manager** (`App/queue_manager.py`)
  - Antrean pengiriman ke Fonnte dengan delay acak (3–7 detik).

- **Campaign scheduler** (`App/campaign_scheduler.py`)
  - Background worker untuk campaign terjadwal dari tabel `campaigns`.

- **Persistence & helpers**
  - Supabase client/config di `App/config.py`, helper functions di `App/helpers.py`.
  - Local state: `chat_history/`, `chat_state/`, `handoff_state/`.

---

## 🗄 Database (Supabase)

### Tabel yang digunakan

| Tabel | Keterangan |
|-------|------------|
| `patients` | Mapping pasien — `id` (auto), `rme_patient_id` (UUID dari SmartClinic), `phone_number`, `name`, `created_at`, `is_handoff` |
| `messages` | Semua pesan inbound/outbound |
| `campaigns` | Data campaign marketing |
| `chatbot_settings` | Konfigurasi AI chatbot (single row) — `ai_name`, `primary_language`, `conversation_tone`, `handoff_threshold`, `handoff_message`, `ai_badge_enabled` |


## 🛠 Tech Stack

| Component        | Technology                       |
| ---------------- | -------------------------------- |
| Language         | Python 3.9+                      |
| API Framework    | FastAPI + Uvicorn                |
| NLP              | Rasa 3.6.15                      |
| LLM              | Groq Cloud API (Llama 3)         |
| Database         | Supabase (PostgreSQL)            |
| WhatsApp Gateway | Fonnte API                       |
| RME Integration  | SmartClinic API                  |
| Containerization | Docker + Docker Compose          |
| Tunnel           | Cloudflare Tunnel                |
| CI/CD            | GitHub Actions                   |
| Hosting          | Oracle VPS (Ubuntu 20.04, ARM64) |

---

## 📁 Project Structure

```
smartclinic/
├── app.py
├── App/
│   ├── __init__.py
│   ├── config.py                   # Semua konstanta & env variables
│   ├── models.py                   # Semua Pydantic request/response models
│   ├── helpers.py                  # Helper functions (Supabase, JSON, Rasa, dll)
│   ├── handoff_manager.py          # State handoff + auto timeout logic
│   ├── queue_manager.py            # Fonnte message queue dengan delay
│   ├── smartclinic/
│   │   ├── __init__.py
│   │   └── auth.py                 # get_smartclinic_token() — auto login & token cache
│   └── routers/
│       ├── __init__.py
│       ├── webhook.py              # GET / + POST /webhook
│       ├── patients.py             # /api/v1/patients + /api/v1/patients/by-phone
│       ├── schedules.py            # /api/v1/schedules + /weekly + /slots
│       ├── appointments.py         # /api/v1/queues/appointments + /api/v1/queues
│       ├── chatbot_settings.py     # /api/v1/chatbot-settings
│       ├── messages.py             # /api/messages
│       ├── send.py                 # /api/send + /api/send/broadcast
│       ├── handoff.py              # /api/handoff
│       ├── campaign.py             # /api/marketing/campaigns
│       └── wa.py                   # wa-service helpers
├── LLM/
│   ├── groq_service.py
│   └── requirements.txt
├── rasa/
│   ├── actions/
│   │   └── actions.py
│   ├── data/
│   ├── models/
│   └── config.yml
├── chat_history/
├── chat_state/
├── handoff_state/
├── .github/
│   └── workflows/
│       └── deploy.yml
├── supabase_setup.sql
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env
```

---

## ⚙️ Environment Variables

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

# SmartClinic RME API
SMARTCLINIC_BASE_URL=https://smartclinic-rekam-medis.onrender.com/api/v1
SMARTCLINIC_EMAIL=your_rme_email
SMARTCLINIC_PASSWORD=your_rme_password
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

Untuk update env: update secret `ENV_FILE` di GitHub → **Actions → Deploy to VPS → Run workflow**.