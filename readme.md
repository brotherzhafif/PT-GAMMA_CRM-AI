# SmartClinic CRM AI (Hana1)

AI Chatbot backend for SmartClinic — hybrid routing between Rasa NLP (structured intents) and Groq LLM (contextual/complaint handling), delivered via WhatsApp through Fonnte.

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
       ├──► Rasa NLP ──► High confidence + trusted intent? ──► Reply directly
       │
       └──► Groq LLM ──► Low confidence / complaint / contextual ──► Reply with context
       │
       ▼
  Fonnte Queue (anti-spam delay)
       │
       ▼
WhatsApp (Patient)
```

---

## 📦 Modules

### 1. FastAPI Router (`App/app.py`)

Main entry point. Receives webhook from Fonnte, routes to Rasa or Groq, saves messages to Supabase, and queues replies via Fonnte.

**Endpoints:**

| Method   | Endpoint                       | Description                                   |
| -------- | ------------------------------ | --------------------------------------------- |
| `GET`    | `/`                            | Health check                                  |
| `POST`   | `/webhook`                     | Receive incoming WhatsApp message from Fonnte |
| `GET`    | `/api/patients`                | Get all registered patients                   |
| `POST`   | `/api/patients`                | Register new patient (upsert by phone number) |
| `DELETE` | `/api/patients/{phone_number}` | Delete a patient                              |
| `GET`    | `/api/messages`                | Get all messages (supports `?limit=N`)        |
| `GET`    | `/api/messages/{phone_number}` | Get message history by phone number           |
| `POST`   | `/api/send`                    | Send a message to one number                  |
| `POST`   | `/api/send/broadcast`          | Broadcast message to all registered patients  |

**Onboarding flow:** First-time senders are greeted and asked for their name before being registered as patients. If skipped, the number is saved without a name.

---

### 2. Rasa NLP Module (`rasa/`)

Handles structured, predefined conversational flows.

**Trusted intents** (answered directly without LLM):
`greet`, `goodbye`, `ask_schedule`, `ask_queue`, `ask_services`, `ask_location`, `ask_cost`, `request_human_agent`, `emergency`, `affirm`, `deny`, `intent_ingin_booking`, `intent_berikan_rating`

**Custom Actions:**

- `action_fetch_schedule` — retrieves real-time doctor availability
- `action_fetch_queue` — retrieves current patient queue status

Confidence threshold: **0.75** — below this, Groq LLM takes over.

---

### 3. Groq LLM Module (`LLM/groq_service.py`)

Handles contextual, complaint-based, or unrecognized queries using the Groq Cloud API (Llama 3).

**Roles:**

- `default` — general clinic info (schedule, location, services)
- `triage` — health complaints and early symptom identification (triggered by keywords like `sakit`, `demam`, `nyeri`, etc.)

**Memory:** Last 5 conversations per WhatsApp number, stored locally in `chat_history/` as JSON files.

---

### 4. Queue Manager (`App/queue_manager.py`)

Prevents WhatsApp number from being blocked due to rapid message sending. Adds a randomized 3–7 second human-like delay before each outbound message.

---

## 🛠 Tech Stack

| Component              | Technology                       |
| ---------------------- | -------------------------------- |
| Language               | Python 3.9+                      |
| API Framework          | FastAPI + Uvicorn                |
| NLP                    | Rasa 3.6.15                      |
| LLM                    | Groq Cloud API (Llama 3)         |
| Database               | Supabase (PostgreSQL)            |
| WhatsApp Gateway       | Fonnte API                       |
| Containerization       | Docker + Docker Compose          |
| Tunnel / Reverse Proxy | Cloudflare Tunnel                |
| CI/CD                  | GitHub Actions                   |
| Hosting                | Oracle VPS (Ubuntu 20.04, ARM64) |

---

## ⚙️ Environment Variables

Create a `.env` file in the root folder:

```env
# Groq LLM
GROQ_API_KEY=your_groq_api_key

# Fonnte WhatsApp Gateway
FONNTE_TOKEN=your_fonnte_token

# Supabase
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_ANON_KEY=your_supabase_anon_key

# Rasa (leave default if using Docker)
RASA_URL=http://rasa:5005
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
nano .env  # fill in your keys

# 3. Build and run all services
docker compose up -d --build

# 4. Check status
docker compose ps
docker compose logs -f app
```

Services started:

- `fastapi_chatbot` — FastAPI app on port 5000
- `rasa_server` — Rasa on port 5005
- `rasa_action_server` — Rasa action server on port 5055

---

### Rasa — Local Development

```bash
# Install Rasa
pip install rasa==3.6.15

# Train model
cd rasa && rasa train

# Run action server
rasa run actions

# Test via CLI
rasa shell
```

---

### Train Rasa via Docker

```bash
docker run --rm \
  -v $(pwd)/rasa:/app \
  rasa/rasa:3.6.15-full train
```

---

## 🔄 CI/CD

Every push to `main` automatically deploys to VPS via GitHub Actions.

**Required GitHub Secrets:**

| Secret        | Value                                                 |
| ------------- | ----------------------------------------------------- |
| `VPS_HOST`    | VPS IP address                                        |
| `VPS_USER`    | SSH username (e.g. `ubuntu`)                          |
| `VPS_SSH_KEY` | Private SSH key                                       |
| `VPS_APP_DIR` | Project path on VPS (e.g. `/home/ubuntu/smartclinic`) |
| `ENV_FILE`    | Full contents of `.env` file                          |

To update environment variables (e.g. rotate Fonnte token): update `ENV_FILE` secret in GitHub → manually trigger workflow from **Actions → Deploy to VPS → Run workflow**.

---

## 📁 Project Structure

```
smartclinic/
├── App/
│   ├── app.py                  # FastAPI router & all endpoints
│   └── queue_manager.py        # Fonnte message queue with delay
├── LLM/
│   ├── groq_service.py         # Groq LLM integration
│   └── requirements.txt
├── rasa/
│   ├── actions/
│   │   └── actions.py          # Custom Rasa actions
│   ├── data/                   # NLU training data & stories
│   ├── models/                 # Trained Rasa models
│   └── config.yml
├── chat_history/               # Local JSON chat memory (per number)
├── chat_state/                 # Onboarding state (per number)
├── .github/
│   └── workflows/
│       └── deploy.yml          # GitHub Actions CI/CD
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env
```
