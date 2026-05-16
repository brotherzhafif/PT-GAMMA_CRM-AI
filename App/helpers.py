# ======================================================
# SmartClinic CRM AI — helpers.py
# Fungsi-fungsi pembantu yang dipakai lintas router
#
# Last Change   :   16 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

import json
import os
import requests
from datetime import datetime
from typing import Optional
from fastapi import HTTPException

from App.config import (
    supabase,
    HISTORY_DIR,
    STATE_DIR,
    RASA_URL,
    RASA_CONFIDENCE_THRESHOLD,
    HANDOFF_KEYWORDS,
)


# Supabase 

def _require_supabase():
    """Guard: raise 500 jika Supabase belum dikonfigurasi."""
    if supabase is None:
        raise HTTPException(
            status_code=500,
            detail="Supabase belum dikonfigurasi. Cek SUPABASE_URL dan SUPABASE_ANON_KEY di .env",
        )


def save_to_supabase(no_hp: str, message: str, direction: str, source: str = "system"):
    """Insert satu baris pesan ke tabel messages di Supabase."""
    if supabase is None:
        print("[Supabase] Skip save — belum dikonfigurasi.")
        return None
    return supabase.table("messages").insert({
        "sender_number": no_hp,
        "message_text": message,
        "direction": direction,
        "source": source,
    }).execute()


def upsert_patient(no_hp: str, name: Optional[str] = None):
    """Simpan atau update pasien di Supabase. Jika Supabase tidak ada, skip."""
    if supabase is None:
        print(f"[Patient] Skip upsert {no_hp} — Supabase belum dikonfigurasi.")
        return
    supabase.table("patients").upsert(
        {"phone_number": no_hp, "name": name},
        on_conflict="phone_number",
    ).execute()
    label = f"nama: {name}" if name else "tanpa nama"
    print(f"[Patient] Upsert {no_hp} ({label})")


def is_patient_registered(no_hp: str) -> bool:
    """Cek apakah nomor sudah ada di tabel patients."""
    if supabase is None:
        return False
    result = supabase.table("patients").select("id").eq("phone_number", no_hp).execute()
    return len(result.data) > 0


# Chat History (JSON lokal) 

def get_chat_history_json(no_hp: str, limit: int = 5) -> list:
    """Ambil riwayat chat lokal dari file JSON (dipakai sebagai memori Groq)."""
    file_path = os.path.join(HISTORY_DIR, f"{no_hp}.json")
    if not os.path.exists(file_path):
        return []
    try:
        with open(file_path, "r") as f:
            return json.load(f)[-limit:]
    except Exception as e:
        print(f"[History] Error baca {no_hp}: {e}")
        return []


def save_chat_to_json(no_hp: str, pesan_user: str, pesan_bot: str, source: str = "groq"):
    """Simpan satu sesi chat ke file JSON lokal."""
    file_path = os.path.join(HISTORY_DIR, f"{no_hp}.json")
    entry = {
        "waktu": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user": pesan_user,
        "bot": pesan_bot,
        "source": source,
    }
    current = []
    if os.path.exists(file_path):
        try:
            with open(file_path, "r") as f:
                current = json.load(f)
        except Exception:
            current = []
    current.append(entry)
    with open(file_path, "w") as f:
        json.dump(current, f, indent=4)


# Session State (onboarding) 

def get_session_state(no_hp: str) -> Optional[str]:
    """Ambil state sesi saat ini untuk nomor tertentu. Return None jika tidak ada."""
    file_path = os.path.join(STATE_DIR, f"{no_hp}.json")
    if not os.path.exists(file_path):
        return None
    try:
        with open(file_path, "r") as f:
            return json.load(f).get("state")
    except Exception:
        return None


def set_session_state(no_hp: str, state: Optional[str]):
    """Set atau hapus state sesi. Kirim state=None untuk clear."""
    file_path = os.path.join(STATE_DIR, f"{no_hp}.json")
    if state is None:
        if os.path.exists(file_path):
            os.remove(file_path)
        return
    with open(file_path, "w") as f:
        json.dump({"state": state}, f)


# Rasa 

def query_rasa(message: str, sender: str) -> Optional[dict]:
    """
    Kirim pesan ke Rasa dan parse hasilnya.
    Return dict {reply, confidence, intent} atau None jika Rasa error.
    """
    try:
        resp = requests.post(
            f"{RASA_URL}/webhooks/rest/webhook",
            json={"sender": sender, "message": message},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        if not data:
            return None

        bot_reply = "\n\n".join(item.get("text", "") for item in data if "text" in item)

        parse_resp = requests.post(
            f"{RASA_URL}/model/parse",
            json={"text": message},
            timeout=10,
        )
        parse_resp.raise_for_status()
        parse_data = parse_resp.json()

        return {
            "reply": bot_reply,
            "confidence": parse_data.get("intent", {}).get("confidence", 0.0),
            "intent": parse_data.get("intent", {}).get("name", ""),
        }
    except Exception as e:
        print(f"[Rasa Error] {e}")
        return None


# Handoff helpers 

def is_handoff_keyword(pesan: str) -> bool:
    """Cek apakah pesan mengandung keyword trigger handoff."""
    pesan_lower = pesan.lower().strip()
    return any(keyword in pesan_lower for keyword in HANDOFF_KEYWORDS)


# Fallback counter per nomor (in-memory, reset saat restart)
_fallback_counter: dict = {}


def increment_fallback(no_hp: str) -> int:
    """Tambah counter fallback Groq, return jumlah sekarang."""
    _fallback_counter[no_hp] = _fallback_counter.get(no_hp, 0) + 1
    return _fallback_counter[no_hp]


def reset_fallback(no_hp: str):
    """Reset counter fallback untuk nomor tertentu."""
    _fallback_counter.pop(no_hp, None)
