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
<br>


### 2. LLM Module (WIP)
> This module utilizes the Groq Cloud API with the Llama-3 model for fast and efficient natural language processing.

- Dynamic Role Playing:

  - default: Handles general clinic information (schedules, location, services).
  - triage: Handles health complaints and early symptom identification.

- Memory Management (Context Awareness) (Local):

  - Uses a local JSON-based storage system (chat_history/) (This Feature can change depending on the requirement).
  - Capable of remembering up to the last 5 conversations for each WhatsApp number.

- Privacy-First Prompting: The AI is configured to greet users professionally without asking for or forcing personal data (name) unless it is already available in the conversation histor
<br>

- 🛠 Tech Stack
  - Python 3.10+

  - Flask: Webhook gateway for third-party integration

  - Groq SDK: Primary interface to the LLM model (Llama 3).

  - Docker: Containerization for ease of deployment.

  - Fonnte API: WhatsApp Gateway for patient communication.
    
<br>


🚀 Setup & Installation (LLM Branch)
1. Prerequisites
Ensure you have an API Key from Groq Cloud and a token from Fonnte.

2. Environment Variables
Create a .env file in the root folder and fill it as follows:
```env
GROQ_API_KEY=_xxxx_your_key_here
FONNTE_TOKEN=your_fonnte_token_here
APP_SECRET_KEY=your_secret_key
NGROK_AUTHTOKEN:your_ngrok_token
```
3. Running the Module (Local)
```bash
# Install dependencies
pip install -r requirements.txt

# Jalankan server Flask
python app.py
```  
4. Train Rasa via Docker
```bash
docker run --rm -v <PROJECT ROOT> rasa/rasa:3.6.15-full train
```  
<br>


5. Running the Module via Docker
Please make sure you have a docker-compose.yml file:
```bash
docker-compose up --build
```  
<br>


### 3. Webhook & API Gateway (WIP)
Webhook & API Routing
- Endpoint: ***/webhook*** (POST)
  - Fungsi: Receives JSON from Fonnte, checks history in chat_history/, requests a response from Groq, sends the reply to WhatsApp, and updates the chat history.
<br>


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
