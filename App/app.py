# File ini berisikan logika Hybrid Routing:
# Fonnte Webhook ==> Flask (Router) ==> Rasa (Data Pasti / API) ATAU Groq LLM (Keluhan / Kontekstual)
# Rasa menjawab jika confidence tinggi (>= 0.75) untuk intent terstruktur (jadwal, antrian, FAQ).
# Groq LLM menjawab jika Rasa tidak yakin, atau jika pesan bersifat keluhan/kontekstual.

import os
import requests
import json
from flask import Flask, request, jsonify
from datetime import datetime
from LLM.groq_service import GroqService
from dotenv import load_dotenv
from App.queue_manager import fonnte_queue

load_dotenv()
app = Flask(__name__)

# Import API Groq LLM
groq = GroqService()

@app.route('/')
def home():
    return "Chatbot Server is Running! 🚀 (Use /webhook for API calls)"

# ── Konfigurasi Rasa ─────────────────────────────────────────────────────────
RASA_URL = os.getenv("RASA_URL", "http://rasa:5005")
RASA_CONFIDENCE_THRESHOLD = 0.75

# Hanya intent berikut yang boleh dijawab langsung oleh Rasa.
# Intent di luar daftar ini akan dilempar ke Groq LLM.
RASA_TRUSTED_INTENTS = {
    "greet", "goodbye",
    "ask_schedule", "ask_queue",
    "ask_services", "ask_location", "ask_cost",
    "request_human_agent", "emergency",
    "affirm", "deny", "intent_ingin_booking",
    "intent_berikan_rating",
}

# ── Konfigurasi Folder Penyimpanan JSON ──────────────────────────────────────
HISTORY_DIR = 'chat_history'
if not os.path.exists(HISTORY_DIR):
    os.makedirs(HISTORY_DIR)


# ── FUNGSI: Ambil Riwayat Chat ───────────────────────────────────────────────
def get_chat_history(no_hp, limit=5):
    """Mengambil riwayat chat terakhir dari file JSON"""
    file_path = os.path.join(HISTORY_DIR, f"{no_hp}.json")
    if not os.path.exists(file_path):
        return []

    try:
        with open(file_path, 'r') as f:
            full_history = json.load(f)
            # Ambil pesan terakhir sesuai limit untuk memori AI
            return full_history[-limit:]
    except Exception as e:
        print(f"Error membaca history chat {no_hp}: {e}")
        return []


# ── FUNGSI: Simpan Chat ke JSON ──────────────────────────────────────────────
def save_chat_to_json(no_hp, pesan_user, pesan_bot, source="groq"):
    """Menyimpan chat baru ke dalam file JSON nomor HP"""
    file_path = os.path.join(HISTORY_DIR, f"{no_hp}.json")
    waktu = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    entry_baru = {
        "waktu": waktu,
        "user": pesan_user,
        "bot": pesan_bot,
        "source": source  # "rasa" atau "groq" — untuk tracking
    }

    current_data = []
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r') as f:
                current_data = json.load(f)
        except:
            current_data = []

    current_data.append(entry_baru)

    with open(file_path, 'w') as f:
        json.dump(current_data, f, indent=4)


# ── FUNGSI: Kirim Pesan ke Fonnte ────────────────────────────────────────────
def send_to_fonnte(target, message):
    """Mengirim pesan ke WhatsApp melalui API Fonnte"""
    url = "https://api.fonnte.com/send"
    token = os.getenv('FONNTE_TOKEN')

    payload = {
        'target': target,
        'message': message,
        'countryCode': '62'
    }
    headers = {
        'Authorization': token.strip() if token else ""
    }

    try:
        response = requests.post(url, data=payload, headers=headers)
        print(f"--- RESPONS FONNTE: {response.text} ---")
        return response.json()
    except Exception as e:
        print(f"--- ERROR FONNTE: {str(e)} ---")
        return None


# ── FUNGSI: Query Rasa NLU ───────────────────────────────────────────────────
def query_rasa(message, sender):
    """
    Kirim pesan ke Rasa dan kembalikan dict berisi reply, confidence, dan intent.
    Mengembalikan None jika Rasa tidak tersedia atau error.
    """
    try:
        # Step 1: Kirim pesan ke Rasa webhook untuk mendapatkan respons bot
        resp = requests.post(
            f"{RASA_URL}/webhooks/rest/webhook",
            json={"sender": sender, "message": message},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        if data and len(data) > 0:
            bot_reply = "\n\n".join([item.get("text", "") for item in data if "text" in item])

            # Step 2: Parse pesan untuk mendapatkan confidence dan intent
            parse_resp = requests.post(
                f"{RASA_URL}/model/parse",
                json={"text": message},
                timeout=10,
            )
            parse_data = parse_resp.json()
            confidence = parse_data.get("intent", {}).get("confidence", 0.0)
            intent_name = parse_data.get("intent", {}).get("name", "")

            return {
                "reply": bot_reply,
                "confidence": confidence,
                "intent": intent_name,
            }

        return None
    except Exception as e:
        print(f"[Rasa Error] {e}")
        return None


# ── WEBHOOK: Endpoint utama dari Fonnte ──────────────────────────────────────
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        no_hp = data.get('sender')
        input_pesan = data.get('message')
        waktu = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if not no_hp or not input_pesan:
            return jsonify({"status": "error", "message": "No data"}), 400

        print(f"\n[INCOMING] Dari: {no_hp} | Pesan: {input_pesan}")

        # Ambil history dari JSON
        chat_history = get_chat_history(no_hp, limit=5)

        reply = ""
        source = ""

        # ── Step 1: Coba Rasa dulu ────────────────────────────────────────
        rasa_result = query_rasa(input_pesan, no_hp)

        if rasa_result:
            print(f"[DEBUG] Rasa intent: '{rasa_result['intent']}', confidence: {rasa_result['confidence']:.4f}")

        if (
            rasa_result
            and rasa_result["confidence"] >= RASA_CONFIDENCE_THRESHOLD
            and rasa_result["intent"] in RASA_TRUSTED_INTENTS
            and rasa_result["reply"]
        ):
            # ✅ Rasa yakin — jawab langsung (hemat token Groq)
            reply = rasa_result["reply"]
            source = "rasa"
            print(f"[DEBUG] → Answered by: RASA ✅")
        else:
            # ✨ Groq LLM ambil alih — untuk keluhan, konteks, atau pertanyaan kompleks
            role = "triage" if any(x in input_pesan.lower() for x in [
                "sakit", "pusing", "nyeri", "gejala", "demam", "batuk",
                "gatel", "gatal", "mual", "muntah", "sesak", "lemas",
                "pilek", "flu", "diare", "panas", "bengkak", "luka"
            ]) else "default"
            reply = groq.get_response(input_pesan, role_type=role, chat_history=chat_history)
            source = "groq"
            print(f"[DEBUG] → Answered by: GROQ LLM ✨ (role: {role})")

        # Kirim balasan ke Fonnte (Output)
        fonnte_queue.add_to_queue(no_hp, reply)
        print(f"[DEBUG] Pesan untuk {no_hp} masuk diantrian")

        # Simpan chat ke JSON
        save_chat_to_json(no_hp, input_pesan, reply, source=source)

        # Nanti bisa ditambahkan logic untuk cek no_hp pelanggan di db rekam medis

        print(f"[{waktu}] Sukses memproses chat dari {no_hp} (source: {source})")
        return jsonify({"status": "ok", "source": source})

    except Exception as e:
        print(f"--- ERROR WEBHOOK: {str(e)} ---")
        return jsonify({"status": "error", "message": str(e)}), 500


# Port untuk akses flask API
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)