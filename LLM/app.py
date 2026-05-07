# File ini berisikan logika untuk menghubungkan antara Fonnte API ==> Flask API ==> dan Intent Classification Chatbot.
# Sementara ini, hanya dilakukan pengetesan pada API Groq saja, untuk menguji apakah API Groq sudah bisa diakses dengan benar atau belum.

import os
import requests  
import json
from flask import Flask, request, jsonify, session
from datetime import datetime
from groq_service import GroqService
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

# Import API Groq LLM
groq = GroqService()


# Konfigurasi Folder Penyimpanan JSON
HISTORY_DIR = 'chat_history'
if not os.path.exists(HISTORY_DIR):
    os.makedirs(HISTORY_DIR)

# FUNGSI Ambil Input Chat 
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

# FUNGSI Menyimpan Input Chat di local JSON
def save_chat_to_json(no_hp, pesan_user, pesan_bot):
    """Menyimpan chat baru ke dalam file JSON nomor HP"""
    file_path = os.path.join(HISTORY_DIR, f"{no_hp}.json")
    waktu = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    entry_baru = {
        "waktu": waktu,
        "user": pesan_user,
        "bot": pesan_bot
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

# Fungsi untuk mengirim pesan ke Fonnte API (Output)
def send_to_fonnte(target, message):
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
        print(f"--- ERROR : {str(e)} ---")
        return None


# Logika Webhook 
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        no_hp = data.get('sender')
        input_pesan = data.get('message')
        waktu = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if not no_hp or not input_pesan:
            return jsonify({"status": "error", "message": "No data"}), 400

        # Ambil history dari JSON 
        history_history = get_chat_history(no_hp, limit=5)
        
        # Integrasi Groq Cloud dengan menyertakan history
        role = "triage" if any(x in input_pesan.lower() for x in ["sakit", "pusing", "nyeri", "gejala"]) else "default"
        groq_response = groq.get_response(input_pesan, role_type=role, chat_history=history_history)

        # Kirim Balik ke Fonnte (Output)
        send_to_fonnte(no_hp, groq_response)
        
        # Simpan chat ke JSON 
        save_chat_to_json(no_hp, input_pesan, groq_response)
       
        print(f"[{waktu}] Sukses memproses chat dari {no_hp}")
        return jsonify({"status": "ok"})
    

        #Nanti bisa ditambahkan logic untuk cek no_hp pelanggan di db rekam medis

    except Exception as e:
        print(f"--- ERROR WEBHOOK: {str(e)} ---")
        return jsonify({"status": "error", "message": str(e)}), 500

    

# Port untuk akses flask API
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)