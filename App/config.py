# ======================================================
# SmartClinic CRM AI — config.py
# Semua konfigurasi, konstanta, dan inisialisasi client
#
# Last Change   :   18 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
#                   MHD. Rafy Firdaus
#                   Wahyu Hardiyantara
# ======================================================

import os
from typing import Optional

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

#  Supabase 
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_ANON_KEY")
supabase: Optional[Client] = (
    create_client(supabase_url, supabase_key) if supabase_url and supabase_key else None
)

#  Fonnte 
FONNTE_TOKEN = os.getenv("FONNTE_TOKEN")

#  SmartClinic RME API 
SMARTCLINIC_BASE_URL = os.getenv(
    "SMARTCLINIC_BASE_URL",
    "https://smartclinic-rekam-medis.onrender.com/api/v1",
)
SMARTCLINIC_EMAIL = os.getenv("SMARTCLINIC_EMAIL")
SMARTCLINIC_PASSWORD = os.getenv("SMARTCLINIC_PASSWORD")

#  Rasa 
RASA_URL = os.getenv("RASA_URL", "http://rasa:5005")
RASA_CONFIDENCE_THRESHOLD = 0.75
RASA_TRUSTED_INTENTS = {
    "greet", "goodbye",
    "ask_schedule", "ask_queue",
    "ask_services", "ask_location", "ask_cost",
    "request_human_agent", "emergency",
    "affirm", "deny", "intent_ingin_booking",
    "intent_berikan_rating", "booking_pasien_baru", "booking_pasien_lama",
    "booking_konfirmasi", "booking_ubah_data",
    "booking_batalkan", "booking_reschedule",
}

# Gejala umum — Groq triage tanpa handoff
TRIAGE_KEYWORDS = [
    "sakit", "pusing", "nyeri", "gejala", "demam", "batuk",
    "gatel", "gatal", "mual", "muntah", "sesak", "lemas",
    "pilek", "flu", "diare", "panas", "bengkak", "luka",
]

# Darurat/Emergency — langsung handoff ke admin
EMERGENCY_KEYWORDS = [
    "tidak sadarkan diri", "pingsan", "kejang", "sesak napas berat",
    "serangan jantung", "stroke", "pendarahan hebat", "kecelakaan",
    "overdosis", "bunuh diri", "darurat",
]

#  Handoff 
HANDOFF_KEYWORDS = {
    "admin", "cs", "manusia", "operator", "helpdesk",
    "bicara dengan admin", "mau ketemu admin", "hubungi admin",
    "tolong admin", "butuh bantuan manusia",
}
MAX_FALLBACK_BEFORE_HANDOFF = 3
HANDOFF_TIMEOUT_MINUTES = int(os.getenv("HANDOFF_TIMEOUT_MINUTES", "15"))

#  Storage Dirs 
HISTORY_DIR = "chat_history"
STATE_DIR = "chat_state"

for _dir in (HISTORY_DIR, STATE_DIR):
    if not os.path.exists(_dir):
        os.makedirs(_dir)
