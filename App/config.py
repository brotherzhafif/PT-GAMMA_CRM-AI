# ======================================================
# SmartClinic CRM AI — config.py
# Semua konfigurasi, konstanta, dan inisialisasi client
#
# Last Change   :   11 Jun 2026
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
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")

# Client utama — service role key, tidak pernah expired, untuk semua DB queries
supabase: Optional[Client] = (
    create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY
    else None
)

# Alias untuk backward compatibility (tidak perlu ganti semua file lama)
supabase_admin = supabase

# Client khusus auth operations (sign_in, sign_out, refresh) — butuh anon key
supabase_auth: Optional[Client] = (
    create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    if SUPABASE_URL and SUPABASE_ANON_KEY
    else None
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
    "intent_berikan_rating", "intent_diri_sendiri", "intent_orang_lain",
    "booking_konfirmasi", "booking_ubah_data",
    "booking_batalkan", "booking_reschedule",
    "booking_pengguna_bpjs", "booking_pengguna_umum",
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

#  Onboarding Timeout
ONBOARDING_TIMEOUT_MINUTES = int(os.getenv("ONBOARDING_TIMEOUT_MINUTES", "30"))

#  Storage Dirs
HISTORY_DIR = "chat_history"
STATE_DIR = "chat_state"

for _dir in (HISTORY_DIR, STATE_DIR):
    if not os.path.exists(_dir):
        os.makedirs(_dir)