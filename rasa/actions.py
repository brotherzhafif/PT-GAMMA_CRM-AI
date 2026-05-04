"""
Rasa Custom Actions — SmartClinic API Integration
Handles: Fetch Doctor Schedule, Fetch Queue Status
Auto-login to get fresh token on every API call.
"""

import requests
from datetime import datetime, timedelta
from typing import Any, Text, Dict, List
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher

# ── SmartClinic API Configuration ─────────────────────────────────────────────
SMARTCLINIC_BASE_URL = "https://smartclinic-rekam-medis.onrender.com/api/v1"
SMARTCLINIC_EMAIL = "admin@smartclinic.id"
SMARTCLINIC_PASSWORD = "Admin@1234"

# Token cache to avoid login on every single request
_token_cache = {
    "access_token": None,
    "expires_at": None,
}


def get_access_token() -> str | None:
    """Return hardcoded token for testing."""
    return "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI5MDAyOGEyMS1mOGNhLTRjZWYtOGY0OS0wOTIzNDJmMGFjZmUiLCJlbWFpbCI6ImFkbWluQHNtYXJ0Y2xpbmljLmlkIiwicm9sZSI6IkFETUlOIiwiaWF0IjoxNzc3Nzk4MzA2LCJleHAiOjE3Nzc3OTkyMDZ9.kHiTC0V36lp-x4yM3SgCMNgQNpKInyD0uvYcHjUVQPc"


def api_get(endpoint: str, params: dict = None) -> dict | None:
    """Make authenticated GET request to SmartClinic API."""
    token = get_access_token()
    if not token:
        return None

    try:
        resp = requests.get(
            f"{SMARTCLINIC_BASE_URL}{endpoint}",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[SmartClinic API Error] {endpoint}: {e}")
        return None


# ── Action: Fetch Doctor Schedule ─────────────────────────────────────────────
class ActionFetchSchedule(Action):
    def name(self) -> Text:
        return "action_fetch_schedule"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:

        # Try fetching all active schedules
        result = api_get("/schedules")

        if result is None:
            dispatcher.utter_message(
                text="Mohon maaf, saya sedang tidak bisa mengakses data jadwal dokter saat ini. "
                     "Silakan coba beberapa saat lagi atau hubungi admin klinik. 🙏"
            )
            return []

        schedules = result.get("data", result)

        # Handle if data is wrapped differently
        if isinstance(schedules, dict) and "data" in schedules:
            schedules = schedules["data"]

        if not schedules or (isinstance(schedules, list) and len(schedules) == 0):
            dispatcher.utter_message(
                text="Saat ini belum ada jadwal dokter yang tersedia. "
                     "Silakan hubungi admin klinik untuk informasi lebih lanjut. 🙏"
            )
            return []

        # Format schedule for WhatsApp
        msg = "📅 *Jadwal Dokter Klinik SmartClinic*\n\n"

        if isinstance(schedules, list):
            # Mapping hari angka ke nama hari
            nama_hari = {
                1: "Senin", 2: "Selasa", 3: "Rabu", 
                4: "Kamis", 5: "Jumat", 6: "Sabtu", 7: "Minggu",
                0: "Minggu" # Jaga-jaga jika 0 itu Minggu
            }
            
            for i, sched in enumerate(schedules, 1):
                dokter = sched.get("dokter", {})
                dokter_name = dokter.get("namaLengkap", "Dokter") if isinstance(dokter, dict) else "Dokter"
                spesialis = dokter.get("spesialis", "") if isinstance(dokter, dict) else ""
                
                hari_angka = sched.get("hari")
                hari = nama_hari.get(hari_angka, str(hari_angka))
                
                jam_mulai = sched.get("jamMulai", "-")
                jam_selesai = sched.get("jamSelesai", "-")
                kuota = sched.get("kapasitasMaks", "-")

                if spesialis:
                    msg += f"{i}. 🩺 *{dokter_name}* ({spesialis})\n"
                else:
                    msg += f"{i}. 🩺 *{dokter_name}*\n"
                    
                msg += f"   📆 Hari: {hari}\n"
                msg += f"   🕐 Jam: {jam_mulai} - {jam_selesai}\n"
                if kuota and kuota != "-":
                    msg += f"   👥 Kuota: {kuota} pasien\n"
                msg += "\n"
        else:
            msg += str(schedules)

        msg += "Apakah Anda ingin membuat janji temu dengan salah satu dokter? 😊"
        dispatcher.utter_message(text=msg)
        return []


# ── Action: Fetch Queue Status ────────────────────────────────────────────────
class ActionFetchQueue(Action):
    def name(self) -> Text:
        return "action_fetch_queue"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:

        # Get today's date
        today = datetime.now().strftime("%Y-%m-%d")

        result = api_get("/queues", params={"tanggal": today})

        if result is None:
            dispatcher.utter_message(
                text="Mohon maaf, saya sedang tidak bisa mengakses data antrian saat ini. "
                     "Silakan coba beberapa saat lagi atau hubungi admin klinik. 🙏"
            )
            return []

        queues = result.get("data", result)

        if isinstance(queues, dict) and "data" in queues:
            queues = queues["data"]

        if not queues or (isinstance(queues, list) and len(queues) == 0):
            dispatcher.utter_message(
                text=f"📋 Belum ada antrian untuk hari ini ({today}). "
                     "Klinik mungkin belum mulai beroperasi atau belum ada pasien yang mendaftar."
            )
            return []

        # Format queue for WhatsApp
        msg = f"🔢 *Status Antrian Hari Ini ({today})*\n\n"

        if isinstance(queues, list):
            # Count by status
            status_count = {}
            for q in queues:
                status = q.get("status", "UNKNOWN")
                status_count[status] = status_count.get(status, 0) + 1

            msg += f"📊 Total antrian: *{len(queues)}* pasien\n\n"

            status_emoji = {
                "MENUNGGU": "⏳",
                "DIPANGGIL": "📢",
                "DIPERIKSA": "🩺",
                "SELESAI": "✅",
                "BATAL": "❌",
            }

            for status, count in status_count.items():
                emoji = status_emoji.get(status, "•")
                msg += f"{emoji} {status}: {count} orang\n"

            # Show current being called
            dipanggil = [q for q in queues if q.get("status") == "DIPANGGIL"]
            if dipanggil:
                msg += "\n📢 *Sedang dipanggil:*\n"
                for q in dipanggil:
                    no_antrian = q.get("nomorAntrian", q.get("queueNumber", "?"))
                    pasien = q.get("pasien", {})
                    nama = (
                        pasien.get("nama", "Pasien")
                        if isinstance(pasien, dict)
                        else "Pasien"
                    )
                    msg += f"   Nomor *{no_antrian}*\n"

            menunggu = [q for q in queues if q.get("status") == "MENUNGGU"]
            if menunggu:
                msg += f"\n⏳ Masih menunggu: *{len(menunggu)}* pasien"
        else:
            msg += str(queues)

        msg += "\n\nApakah ada hal lain yang bisa saya bantu? 😊"
        dispatcher.utter_message(text=msg)
        return []
