# SmartClinic CRM AI (Hana)

AI Chatbot backend for SmartClinic, combining Rasa (NLP) for structured intents and an LLM for unstructured queries.

## 🏗 Architecture & Modules

### 1. Rasa NLP Module
Handles structured conversational flows, API integrations, and predefined intents.

- **Core Intents**: `greet`, `ask_schedule`, `ask_queue`, `ask_services`, `emergency`, `nlu_fallback`.
- **Custom Actions (`rasa/actions.py`)**:
  - `action_fetch_schedule`: Retrieves real-time doctor availability via `/schedules` API.
  - `action_fetch_queue`: Retrieves current patient queue status via `/queues` API.
- **Dialog Management**: Handled via Rules (single-turn/strict) and Stories (multi-turn).

### 2. LLM Module (WIP)
> *[TODO: Tambahkan dokumentasi arsitektur LLM, prompt engineering, dan setup di sini]*

- Handles unstructured queries triggered by Rasa's `nlu_fallback`.
- ...

### 3. Webhook & API Gateway (WIP)
> *[TODO: Tambahkan dokumentasi integrasi Fonnte/WhatsApp, Flask routing, dan setup ngrok di sini]*

- Routes incoming WhatsApp messages to the NLP/LLM pipeline.
- ...

## 🚀 Local Setup (Rasa)

Ensure Python 3.x is installed.

```bash
# 1. Install Dependencies
pip install rasa

# 2. Train Model
cd rasa && rasa train

# 3. Run Action Server (Backend API Bridge)
rasa run actions

# 4. Run CLI Interface
rasa shell
```
