# SmartClinic CRM AI (Hana)

AI Chatbot backend for SmartClinic — hybrid routing between Rasa NLP (structured intents) and Groq LLM (contextual/complaint handling), delivered via WhatsApp through Fonnte.

> **Developer**: 
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
  Fonnte Queue (anti-spam delay 3–7 detik)
       │
       ▼
WhatsApp (Patient)
```

---

## 📦 Modules

### 1. FastAPI Router (`app.py` + `App/routers/`)
Entry point utama. Tipis — hanya inisialisasi FastAPI dan register semua router.

**Endpoints:**

| Method | Endpoint | Router File | Description |
|--------|----------|-------------|-------------|
| `GET` | `/` | `webhook.py` | Health check |
| `POST` | `/webhook` | `webhook.py` | Terima pesan masuk dari Fonnte |
| `GET` | `/api/patients` | `patients.py` | Ambil semua pasien terdaftar |
| `POST` | `/api/patients` | `patients.py` | Daftarkan pasien baru (upsert) |
| `DELETE` | `/api/patients/{number}` | `patients.py` | Hapus pasien |
| `GET` | `/api/messages` | `messages.py` | Ambil semua pesan (`?limit=N`) |
| `GET` | `/api/messages/{number}` | `messages.py` | Ambil pesan per nomor |
| `POST` | `/api/send` | `send.py` | Kirim pesan ke satu nomor |
| `POST` | `/api/send/broadcast` | `send.py` | Broadcast ke semua pasien |
| `GET` | `/api/handoff` | `handoff.py` | Daftar sesi handoff aktif |
| `POST` | `/api/handoff/{number}` | `handoff.py` | Mulai handoff manual |
| `DELETE` | `/api/handoff/{number}` | `handoff.py` | Akhiri handoff, bot aktif kembali |
| `POST` | `/api/handoff/{number}/reply` | `handoff.py` | Admin balas pesan ke pasien |

---

### 2. Rasa NLP Module (`rasa/`)
Menangani intent terstruktur dengan confidence threshold **0.75**.

**Trusted intents** (dijawab langsung tanpa LLM):
`greet`, `goodbye`, `ask_schedule`, `ask_queue`, `ask_services`, `ask_location`, `ask_cost`, `request_human_agent`, `emergency`, `affirm`, `deny`, `intent_ingin_booking`, `intent_berikan_rating`

**Custom Actions:**
- `action_fetch_schedule` — jadwal dokter realtime
- `action_fetch_queue` — status antrian pasien

---

### 3. Groq LLM Module (`LLM/groq_service.py`)
Menangani pesan kontekstual dan keluhan menggunakan Groq Cloud API (Llama 3).

**Roles:**
- `default` — info umum klinik
- `triage` — keluhan kesehatan (trigger by keyword: `sakit`, `demam`, `nyeri`, dll)

**Memory:** 5 percakapan terakhir per nomor, disimpan di `chat_history/` sebagai JSON lokal.

---

### 4. Handoff Manager (`App/handoff_manager.py`)
Mengelola mode handoff per nomor HP.

**Flow:**
- Pasien ketik keyword (`admin`, `cs`, `manusia`, dll) → bot berhenti, admin handle dari dashboard
- Bot gagal jawab 3x berturut-turut → auto handoff dengan notif ke pasien
- Admin tidak balas dalam **15 menit** → otomatis kembali ke bot
- Admin klik "Serahkan ke Bot" di dashboard → `DELETE /api/handoff/{number}`

State disimpan di `handoff_state/` sebagai file JSON per nomor.

---

### 5. Queue Manager (`App/queue_manager.py`)
Anti-spam: delay acak 3–7 detik sebelum setiap pesan terkirim ke Fonnte, mensimulasikan perilaku ketik manusia.

---

## 🛠 Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.9+ |
| API Framework | FastAPI + Uvicorn |
| NLP | Rasa 3.6.15 |
| LLM | Groq Cloud API (Llama 3) |
| Database | Supabase (PostgreSQL) |
| WhatsApp Gateway | Fonnte API |
| Containerization | Docker + Docker Compose |
| Tunnel | Cloudflare Tunnel |
| CI/CD | GitHub Actions |
| Hosting | Oracle VPS (Ubuntu 20.04, ARM64) |

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

| Secret | Value |
|--------|-------|
| `VPS_HOST` | IP VPS |
| `VPS_USER` | SSH username (`ubuntu`) |
| `VPS_SSH_KEY` | Private SSH key |
| `VPS_APP_DIR` | Path project di VPS (`/home/ubuntu/smartclinic`) |
| `ENV_FILE` | Seluruh isi `.env` |

Untuk update env (misal rotate Fonnte token): update secret `ENV_FILE` di GitHub → **Actions → Deploy to VPS → Run workflow**.