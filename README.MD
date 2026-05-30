# SmartClinic CRM AI (Hana)

AI Chatbot backend for SmartClinic - hybrid routing between Rasa NLP (structured intents) and Groq LLM (contextual/complaint handling), delivered via WhatsApp through Fonnte and `wa-service`.
> **Developer**:
>
> - Raja Zhafif Raditya Harahap
> - MHD. Rafy Firdaus
> - Wahyu Hardiyantara


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
  - File: `App/app.py` - inisialisasi FastAPI, daftarkan semua router, dan start campaign scheduler.
  - OpenAPI / Swagger UI tersedia di `/docs` ketika server berjalan.

- **Routers** (lokasi: `App/routers/`)
  - `webhook.py` - `GET /` (health) dan `POST /webhook` (entrypoint inbound dari Fonnte).
  - `patients.py` - Proxy CRUD pasien ke SmartClinic RME API (`/api/patients`). Setelah create pasien, aplikasi mengisi mapping ke tabel Supabase `patients`. Ada juga lookup `GET /api/patients/by-phone`.
  - `schedules.py` - Proxy jadwal dokter ke SmartClinic RME API (`/api/schedules`, `/api/schedules/weekly`, `/api/schedules/slots`).
  - `appointments.py` - Proxy janji temu dan antrian ke SmartClinic RME API. Flow booking: lookup `rme_patient_id` by `phone_number` dari Supabase lalu kirim ke endpoint appointment/queue.
  - `chatbot_settings.py` - Konfigurasi AI chatbot (`GET /api/chatbot-settings`, `PUT /api/chatbot-settings`). Data disimpan di tabel Supabase `chatbot_settings` dan row default dibuat otomatis kalau tabel kosong.
  - `messages.py` - SSE realtime untuk sidebar/chat (`/api/messages/latest`, `/api/messages/{phone_number}`).
  - `send.py` - Kirim pesan manual dan broadcast (`/api/send`, `/api/send/broadcast`).
  - `handoff.py` - Manajemen sesi handoff/admin (`/api/handoff`).
  - `campaign.py` - Marketing/campaigns (`/api/marketing/campaigns`).
  - `feedback.py` - Feedback pasien dan dashboard ringkasan (`/api/feedback`, `/api/feedback/dashboard`).
  - `auth/router.py` - Login, logout, dan refresh token (`/api/auth/login`, `/api/auth/logout`, `/api/auth/refresh`).
  - `users.py` - Manajemen user internal untuk admin (`/api/users`).
  - `activity.py` - Audit log, notifications, dan login history (`/api/activity`, `/api/activity/notifications`, `/api/activity/audit`, `/api/activity/logins`).
  - `status.py` - Helper endpoints menuju wa-service dan pengecekan status token SmartClinic.

- **SmartClinic RME Integration** (lokasi: `App/smartclinic_auth.py`)
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
  - Bootstrap user awal disimpan langsung di `seed_bootstrap_users.py`.

---

## 🗄 Database (Supabase)

### Tabel yang digunakan

| Tabel | Keterangan |
|-------|------------|
| `patients` | Mapping pasien — `id`, `rme_patient_id`, `phone_number`, `name`, `created_at`, `is_handoff` |
| `messages` | Semua pesan inbound/outbound |
| `campaigns` | Data campaign marketing |
| `chatbot_settings` | Konfigurasi AI chatbot (single row) — `ai_name`, `primary_language`, `conversation_tone`, `handoff_threshold`, `handoff_message`, `ai_badge_enabled` |
| `feedback` | Feedback pasien — `id_user`, `rating`, `ulasan` |
| `users` | Profil user internal yang dipasangkan ke Supabase Auth |
| `activity_logs` | Audit log, notifikasi, dan histori login |


## 🛠 Tech Stack

| Component        | Technology                       |
| ---------------- | -------------------------------- |
| Language         | Python 3.9+                      |
| API Framework    | FastAPI + Uvicorn                |
| NLP              | Rasa 3.6.15                      |
| LLM              | Groq Cloud API                   |
| Database         | Supabase (PostgreSQL)            |
| WhatsApp Gateway | Fonnte API                       |
| RME Integration  | SmartClinic API                  |
| Bot Runtime      | Node.js + Express + whatsapp-web.js |
| Containerization | Docker + Docker Compose          |
| Logs             | Dozzle                           |
| CI/CD            | GitHub Actions                   |

---

## 📁 Project Structure

```
smartclinic/
├── App/
│   ├── app.py
│   ├── activity_logger.py
│   ├── campaign_scheduler.py
│   ├── config.py                   # Semua konstanta & env variables
│   ├── handoff_manager.py          # State handoff + auto timeout logic
│   ├── helpers.py                  # Helper functions (Supabase, JSON, Rasa, dll)
│   ├── models.py                   # Semua Pydantic request/response models
│   ├── queue_manager.py            # Fonnte message queue dengan delay
│   ├── smartclinic_auth.py         # get_smartclinic_token() — auto login & token cache
│   ├── auth/
│   │   ├── dependencies.py
│   │   └── router.py               # /api/auth/login, /logout, /refresh
│   └── routers/
│       ├── __init__.py
│       ├── activity.py             # /api/activity
│       ├── appointments.py         # /api/appointment
│       ├── campaign.py             # /api/marketing/campaigns
│       ├── chatbot_settings.py     # /api/chatbot-settings
│       ├── feedback.py             # /api/feedback
│       ├── handoff.py              # /api/handoff
│       ├── messages.py             # /api/messages
│       ├── patients.py             # /api/patients
│       ├── schedules.py            # /api/schedules
│       ├── send.py                 # /api/send + /api/send/broadcast
│       ├── status.py               # /api/status
│       ├── users.py                # /api/users
│       └── webhook.py              # GET / + POST /webhook
├── LLM/
│   ├── groq_service.py
│   └── guardrail.py
├── rasa/
│   ├── actions/
│   │   └── actions.py
│   ├── data/
│   ├── models/
│   └── config.yml
├── chat_history/
├── chat_state/
├── handoff_state/
├── wa-service/
│   ├── Dockerfile
│   ├── index.js
│   └── package.json
├── .github/
│   └── workflows/
│       └── deploy.yml
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── seed_bootstrap_users.py        # Bootstrap user awal: 4 role, hardcoded
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
SUPABASE_JWT_SECRET=your_supabase_jwt_secret
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_secret

# Bootstrap user awal tidak pakai env. Datanya ada di seed_bootstrap_users.py.

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
notepad .env  # isi semua value dari bagian Environment Variables

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
- `wa_service` — WhatsApp gateway di localhost port 3001
- `dozzle_log_viewer` — log viewer di port 8080

Bootstrap user awal bisa di-seed manual lewat `seed_bootstrap_users.py`. Role dan kredensial awalnya ada langsung di file itu.

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