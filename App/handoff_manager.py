# App/handoff_manager.py
#
# Mengelola state handoff per nomor HP.
# State disimpan di folder handoff_state/ sebagai JSON per nomor.
#
# State yang mungkin:
#   None           → bot aktif normal
#   "handoff"      → admin sedang handle, bot diam
#
# Auto timeout: jika admin tidak balas dalam HANDOFF_TIMEOUT_MINUTES,
# state otomatis dikembalikan ke bot.

import json
import os
from datetime import datetime, timedelta
from App.config import supabase
from App.helpers import normalize_phone_number

HANDOFF_DIR = "handoff_state"
HANDOFF_TIMEOUT_MINUTES = int(os.getenv("HANDOFF_TIMEOUT_MINUTES", "15"))

if not os.path.exists(HANDOFF_DIR):
    os.makedirs(HANDOFF_DIR)


def _file(no_hp: str) -> str:
    return os.path.join(HANDOFF_DIR, f"{normalize_phone_number(no_hp)}.json")


def _read(no_hp: str) -> dict:
    path = _file(no_hp)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _write(no_hp: str, data: dict):
    with open(_file(no_hp), "w") as f:
        json.dump(data, f, indent=2)


def _delete(no_hp: str):
    path = _file(no_hp)
    if os.path.exists(path):
        os.remove(path)


# Public API 

def is_in_handoff(no_hp: str) -> bool:
    """
    Cek apakah nomor sedang dalam mode handoff.
    Otomatis clear state jika sudah timeout.
    """
    normalized_phone = normalize_phone_number(no_hp)
    data = _read(normalized_phone)
    if not data or data.get("state") != "handoff":
        return False

    # Cek timeout
    started_at = datetime.fromisoformat(data["started_at"])
    if datetime.now() - started_at > timedelta(minutes=HANDOFF_TIMEOUT_MINUTES):
        print(f"[Handoff] Timeout untuk {normalized_phone} — balik ke bot otomatis")
        end_handoff(normalized_phone)
        return False

    return True


def start_handoff(no_hp: str):
    """Mulai mode handoff untuk nomor ini."""
    normalized_phone = normalize_phone_number(no_hp)
    _write(no_hp, {
        "state": "handoff",
        "started_at": datetime.now().isoformat(),
        "last_admin_reply_at": None,
    })
    if supabase:
        supabase.table("patients").update({"is_handoff": True}).eq("telepon", normalized_phone).execute()
    print(f"[Handoff] {normalized_phone} masuk mode handoff")


def end_handoff(no_hp: str):
    """Akhiri handoff, kembalikan ke bot."""
    normalized_phone = normalize_phone_number(no_hp)
    _delete(normalized_phone)
    if supabase:
        supabase.table("patients").update({"is_handoff": False}).eq("telepon", normalized_phone).execute()
    print(f"[Handoff] {normalized_phone} keluar dari handoff — bot aktif kembali")


def update_admin_reply_time(no_hp: str):
    """Catat waktu terakhir admin balas — untuk reset timeout."""
    normalized_phone = normalize_phone_number(no_hp)
    data = _read(normalized_phone)
    if data:
        data["last_admin_reply_at"] = datetime.now().isoformat()
        _write(normalized_phone, data)


def get_all_handoff_sessions() -> list:
    """
    Ambil semua sesi handoff yang sedang aktif.
    Dipakai oleh dashboard untuk tampilkan inbox.
    Auto-filter yang sudah timeout.
    """
    sessions = []
    if not os.path.exists(HANDOFF_DIR):
        return sessions

    for filename in os.listdir(HANDOFF_DIR):
        if not filename.endswith(".json"):
            continue
        no_hp = filename.replace(".json", "")
        if is_in_handoff(no_hp):  # ini sekaligus filter timeout
            data = _read(normalize_phone_number(no_hp))
            sessions.append({
                "phone_number": no_hp,
                "started_at": data.get("started_at"),
                "last_admin_reply_at": data.get("last_admin_reply_at"),
                "timeout_at": (
                    datetime.fromisoformat(data["started_at"])
                    + timedelta(minutes=HANDOFF_TIMEOUT_MINUTES)
                ).isoformat(),
            })

    return sorted(sessions, key=lambda x: x["started_at"], reverse=True)
