# Log last change: 20 May 2026

"""
Rasa Custom Actions — SmartClinic API Integration
==================================================
Handles:
  - Fetch Doctor Schedule
  - Fetch Queue Status
  - Booking Flow (Pasien Baru & Lama)
"""

import os
import re
import requests
from datetime import datetime, timedelta
from typing import Any, Text, Dict, List, Optional

from rasa_sdk import Action, Tracker, FormValidationAction
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet, ActiveLoop, FollowupAction

# ── SmartClinic API Configuration ─────────────────────────────────────────────
SMARTCLINIC_BASE_URL = os.getenv("SMARTCLINIC_BASE_URL", "https://smartclinic-rekam-medis.onrender.com/api/v1")
SMARTCLINIC_EMAIL    = os.getenv("SMARTCLINIC_EMAIL", "")
SMARTCLINIC_PASSWORD = os.getenv("SMARTCLINIC_PASSWORD", "")

# Token cache (untuk future auto-refresh)
_token_cache = {
    "access_token": None,
    "expires_at": None,
}


# ==============================================
# RASA ACTIONS 
# ==============================================

# Action: Get Access to RME API and Token
def get_access_token() -> str | None:
    env_token = os.getenv("SMARTCLINIC_ACCESS_TOKEN", "").strip()
    if env_token:
        return env_token

    if _token_cache["access_token"] and _token_cache["expires_at"]:
        if datetime.now() < _token_cache["expires_at"]:
            return _token_cache["access_token"]

    try:
        resp = requests.post(
            f"{SMARTCLINIC_BASE_URL}/auth/login",
            json={"email": SMARTCLINIC_EMAIL, "password": SMARTCLINIC_PASSWORD},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        token = data.get("data", {}).get("accessToken") or data.get("accessToken")
        if token:
            _token_cache["access_token"] = token
            _token_cache["expires_at"] = datetime.now() + timedelta(minutes=15)
            return token
    except Exception as e:
        print(f"[SmartClinic] ERROR saat login: {e}")
    return None

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
        print(f"[SmartClinic API Error] GET {endpoint}: {e}")
        return None


def api_post(endpoint: str, payload: dict) -> dict | None:
    """Make authenticated POST request to SmartClinic API."""
    token = get_access_token()
    if not token:
        return None
    try:
        resp = requests.post(
            f"{SMARTCLINIC_BASE_URL}{endpoint}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[SmartClinic API Error] POST {endpoint}: {e}")
        return None


def get_patient_from_supabase(sender_id: str) -> dict:
    SUPABASE_URL = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
    if not SUPABASE_URL or not SUPABASE_KEY:
        # Mock data untuk keperluan testing (sebelum BE update kolom)
        return {
            "nama": "Budi Santoso",
            "nik": "1234567890123456",
            "date_of_birth": "15/08/1995"
        }
        
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    url = f"{SUPABASE_URL}/rest/v1/patients?sender_id=eq.{sender_id}&select=nama,nik,date_of_birth"
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data and isinstance(data, list):
                return data[0]
    except Exception as e:
        print(f"Supabase error: {e}")
    return {}



# Action: Fetch Doctor Schedule (RME)
class ActionFetchSchedule(Action):
    def name(self) -> Text:
        return "action_fetch_schedule"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:

        result = api_get("/schedules")

        if result is None:
            dispatcher.utter_message(
                text="Mohon maaf, saya sedang tidak bisa mengakses data jadwal dokter saat ini. "
                     "Silakan coba beberapa saat lagi atau hubungi admin klinik. 🙏"
            )
            return []

        schedules = result.get("data", result)

        if isinstance(schedules, dict) and "data" in schedules:
            schedules = schedules["data"]

        if not schedules or (isinstance(schedules, list) and len(schedules) == 0):
            dispatcher.utter_message(
                text="Saat ini belum ada jadwal dokter yang tersedia. "
                     "Silakan hubungi admin klinik untuk informasi lebih lanjut. 🙏"
            )
            return []

        msg = "📅 *Jadwal Dokter Klinik SmartClinic*\n\n"

        if isinstance(schedules, list):
            nama_hari = {
                1: "Senin", 2: "Selasa", 3: "Rabu",
                4: "Kamis", 5: "Jumat", 6: "Sabtu", 7: "Minggu",
                0: "Minggu"
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


#  Action: Fetch Queue Status (RME)
class ActionFetchQueue(Action):
    def name(self) -> Text:
        return "action_fetch_queue"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:

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

        msg = f"🔢 *Status Antrian Hari Ini ({today})*\n\n"

        if isinstance(queues, list):
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

            dipanggil = [q for q in queues if q.get("status") == "DIPANGGIL"]
            if dipanggil:
                msg += "\n📢 *Sedang dipanggil:*\n"
                for q in dipanggil:
                    no_antrian = q.get("nomorAntrian", q.get("queueNumber", "?"))
                    msg += f"   Nomor *{no_antrian}*\n"

            menunggu = [q for q in queues if q.get("status") == "MENUNGGU"]
            if menunggu:
                msg += f"\n⏳ Masih menunggu: *{len(menunggu)}* pasien"
        else:
            msg += str(queues)

        msg += "\n\nApakah ada hal lain yang bisa saya bantu? 😊"
        dispatcher.utter_message(text=msg)
        return []


#==========================================================
# BOOKING ACTIONS 
#==========================================================


def parse_tanggal_kunjungan(teks: str) -> Optional[str]:
    """
    Konversi input teks bebas ke format YYYY-MM-DD.
    Mendukung: DD/MM/YYYY, DD-MM-YYYY, 'besok', 'lusa', nama hari.
    """
    teks = teks.strip().lower()
    today = datetime.now()

    if teks in ("hari ini", "sekarang"):
        return today.strftime("%Y-%m-%d")
    if teks in ("besok", "bsk"):
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    if teks == "lusa":
        return (today + timedelta(days=2)).strftime("%Y-%m-%d")

    nama_hari_map = {
        "senin": 0, "selasa": 1, "rabu": 2, "kamis": 3,
        "jumat": 4, "sabtu": 5, "minggu": 6,
    }
    for nama, target_weekday in nama_hari_map.items():
        if nama in teks:
            days_ahead = (target_weekday - today.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            return (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    match = re.search(r"(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})", teks)
    if match:
        day, month, year = match.groups()
        try:
            dt = datetime(int(year), int(month), int(day))
            if dt.date() < today.date():
                return None
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            return None

    return None


def parse_tanggal_lahir(teks: str) -> Optional[str]:
    """Konversi DD/MM/YYYY ke YYYY-MM-DD."""
    match = re.search(r"(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})", teks)
    if match:
        day, month, year = match.groups()
        try:
            return datetime(int(year), int(month), int(day)).strftime("%Y-%m-%d")
        except ValueError:
            return None
    return None


def format_tgl_indonesia(tgl_str: str) -> str:
    """Format YYYY-MM-DD ke 'Senin, 19 Mei 2026'."""
    hari_map = {
        "Monday": "Senin", "Tuesday": "Selasa", "Wednesday": "Rabu",
        "Thursday": "Kamis", "Friday": "Jumat",
        "Saturday": "Sabtu", "Sunday": "Minggu",
    }
    bulan_map = {
        "January": "Januari", "February": "Februari", "March": "Maret",
        "April": "April", "May": "Mei", "June": "Juni",
        "July": "Juli", "August": "Agustus", "September": "September",
        "October": "Oktober", "November": "November", "December": "Desember",
    }
    try:
        dt = datetime.strptime(tgl_str, "%Y-%m-%d")
        hasil = dt.strftime("%A, %d %B %Y")
        for en, id_ in {**hari_map, **bulan_map}.items():
            hasil = hasil.replace(en, id_)
        return hasil
    except Exception:
        return tgl_str


# Action: Mulai Booking 
class ActionStartBooking(Action):
    """Dipanggil saat intent_ingin_booking. Tampilkan sapaan & tanya tipe pasien."""

    def name(self) -> Text:
        return "action_start_booking"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:

        sender_id = tracker.sender_id
        patient_data = get_patient_from_supabase(sender_id)
        
        nik = patient_data.get("nik")
        dob = patient_data.get("date_of_birth")
        
        if nik and dob:
            dispatcher.utter_message(response="utter_ask_booking_untuk_siapa", nik=nik)
            return [
                SlotSet("booking_tipe_pasien", None),
                SlotSet("booking_nik", None),
                SlotSet("booking_nama", None),
                SlotSet("booking_tgl_lahir", None),
                SlotSet("booking_keluhan", None),
                SlotSet("booking_tgl_kunjungan", None),
                SlotSet("booking_step", "tanya_untuk_siapa"),
                SlotSet("booking_untuk_siapa", None)
            ]
        else:
            dispatcher.utter_message(response="utter_booking_tanya_tipe")
            return [
                SlotSet("booking_tipe_pasien", None),
                SlotSet("booking_nik", None),
                SlotSet("booking_nama", None),
                SlotSet("booking_tgl_lahir", None),
                SlotSet("booking_keluhan", None),
                SlotSet("booking_tgl_kunjungan", None),
                SlotSet("booking_step", "tanya_tipe"),
            ]


class ActionHandleUntukSiapa(Action):
    def name(self) -> Text:
        return "action_handle_untuk_siapa"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:

        intent = tracker.latest_message.get("intent", {}).get("name")
        
        if intent == "intent_diri_sendiri":
            sender_id = tracker.sender_id
            patient_data = get_patient_from_supabase(sender_id)
            nama = patient_data.get("nama", "")
            nik = patient_data.get("nik", "")
            dob = patient_data.get("date_of_birth", "")
            
            # Langsung trigger pertanyaan keluhan dengan bypass form
            dispatcher.utter_message(response="utter_booking_intro_baru")
            
            return [
                SlotSet("booking_nama", nama),
                SlotSet("booking_nik", nik),
                SlotSet("booking_tgl_lahir", dob),
                SlotSet("booking_tipe_pasien", "baru"),
                SlotSet("booking_step", "form_baru"),
                ActiveLoop("booking_form_baru"),
                FollowupAction("booking_form_baru")
            ]
        else:
            # Orang Lain
            dispatcher.utter_message(response="utter_booking_intro_baru")
            return [
                SlotSet("booking_tipe_pasien", "baru"),
                SlotSet("booking_step", "form_baru"),
                ActiveLoop("booking_form_baru"),
                FollowupAction("booking_form_baru")
            ]


#  Validasi Form Pasien Baru
class ValidateBookingFormBaru(FormValidationAction):
    """Validasi slot form pasien baru satu per satu."""

    def name(self) -> Text:
        return "validate_booking_form_baru"

    def validate_booking_nama(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        nama = str(slot_value).strip()
        if len(nama) < 2:
            dispatcher.utter_message(
                text="⚠️ Nama terlalu pendek. Mohon ketik nama lengkap Anda sesuai KTP."
            )
            return {"booking_nama": None}
        return {"booking_nama": nama.title()}

    def validate_booking_nik(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        nik = re.sub(r"\D", "", str(slot_value))
        if len(nik) != 16:
            dispatcher.utter_message(response="utter_booking_nik_invalid")
            return {"booking_nik": None}
        return {"booking_nik": nik}

    def validate_booking_tgl_lahir(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        parsed = parse_tanggal_lahir(str(slot_value))
        if not parsed:
            dispatcher.utter_message(response="utter_booking_tgl_invalid")
            return {"booking_tgl_lahir": None}
        return {"booking_tgl_lahir": parsed}

    def validate_booking_keluhan(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        keluhan = str(slot_value).strip()
        if len(keluhan) < 3:
            dispatcher.utter_message(
                text="⚠️ Keluhan terlalu singkat. Mohon ceritakan sedikit lebih detail."
            )
            return {"booking_keluhan": None}
        return {"booking_keluhan": keluhan}

    def validate_booking_tgl_kunjungan(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        parsed = parse_tanggal_kunjungan(str(slot_value))
        if not parsed:
            dispatcher.utter_message(response="utter_booking_tgl_kunjungan_invalid")
            return {"booking_tgl_kunjungan": None}
        return {"booking_tgl_kunjungan": parsed}


#  Validasi Form Pasien Lama
class ValidateBookingFormLama(FormValidationAction):
    """Validasi slot form pasien lama."""

    def name(self) -> Text:
        return "validate_booking_form_lama"

    def validate_booking_nik(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        nilai = str(slot_value).strip()
        digit_only = re.sub(r"\D", "", nilai)

        if len(digit_only) == 16:
            return {"booking_nik": digit_only}
        if not nilai.isdigit() and len(nilai) >= 2:
            return {"booking_nik": nilai}  # Nama sebagai identifier

        dispatcher.utter_message(response="utter_booking_nik_invalid")
        return {"booking_nik": None}

    def validate_booking_keluhan(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        keluhan = str(slot_value).strip()
        if len(keluhan) < 3:
            dispatcher.utter_message(
                text="⚠️ Keluhan terlalu singkat. Mohon ceritakan sedikit lebih detail."
            )
            return {"booking_keluhan": None}
        return {"booking_keluhan": keluhan}

    def validate_booking_tgl_kunjungan(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> Dict[Text, Any]:
        parsed = parse_tanggal_kunjungan(str(slot_value))
        if not parsed:
            dispatcher.utter_message(response="utter_booking_tgl_kunjungan_invalid")
            return {"booking_tgl_kunjungan": None}
        return {"booking_tgl_kunjungan": parsed}


#  Submit Form Pasien Baru 
class ActionBookingFormBaruSubmit(Action):
    """Dipanggil setelah semua slot form baru terisi."""

    def name(self) -> Text:
        return "action_booking_form_baru_submit"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        return [SlotSet("booking_step", "review")]


# Submit Form Pasien Lama
class ActionBookingFormLamaSubmit(Action):
    """Lookup pasien lama di API. Jika ketemu, isi nama & tgl_lahir otomatis."""

    def name(self) -> Text:
        return "action_booking_form_lama_submit"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:

        identifier = tracker.get_slot("booking_nik") or ""
        events = [SlotSet("booking_step", "review")]

        digit_only = re.sub(r"\D", "", identifier)
        if len(digit_only) == 16:
            result = api_get("/patients", params={"nik": digit_only})
        else:
            result = api_get("/patients", params={"nama": identifier})

        if result:
            data = result.get("data", {})
            if isinstance(data, list) and len(data) > 0:
                data = data[0]
            nama = data.get("namaLengkap") or data.get("nama") or ""
            tgl_lahir = data.get("tanggalLahir") or data.get("tgl_lahir") or ""
            nik = data.get("nik") or digit_only
            if nama:
                dispatcher.utter_message(
                    text=f"✅ Data Anda ditemukan. Halo kembali, *{nama}*! 😊"
                )
                events += [
                    SlotSet("booking_nama", nama),
                    SlotSet("booking_nik", nik),
                    SlotSet("booking_tgl_lahir", tgl_lahir),
                ]
            else:
                dispatcher.utter_message(
                    text="⚠️ Data Anda belum ditemukan. Kami daftarkan sebagai pasien baru ya."
                )
        else:
            dispatcher.utter_message(
                text="⚠️ Tidak dapat mengakses data pasien saat ini. Kami lanjutkan pendaftaran Anda."
            )

        return events


#  Review Data Booking
class ActionBookingReview(Action):
    """Tampilkan ringkasan data untuk dikonfirmasi pasien."""

    def name(self) -> Text:
        return "action_booking_review"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:

        nama = tracker.get_slot("booking_nama") or "-"
        nik = tracker.get_slot("booking_nik") or "-"
        tgl_lahir = tracker.get_slot("booking_tgl_lahir") or "-"
        keluhan = tracker.get_slot("booking_keluhan") or "-"
        tgl_kunjungan = tracker.get_slot("booking_tgl_kunjungan") or "-"
        tipe = tracker.get_slot("booking_tipe_pasien") or "baru"

        tgl_display = format_tgl_indonesia(tgl_kunjungan)

        # Masking NIK — tampilkan 4 digit terakhir saja
        nik_display = f"****-****-****-{nik[-4:]}" if len(nik) == 16 else nik

        if tipe == "baru":
            msg = (
                "📋 *Ringkasan Data Pendaftaran*\n\n"
                f"👤 Nama        : *{nama}*\n"
                f"🪪  NIK         : `{nik_display}`\n"
                f"🎂 Tgl Lahir  : {tgl_lahir}\n"
                f"🩺 Keluhan    : {keluhan}\n"
                f"📅 Kunjungan : {tgl_display}\n\n"
                "Apakah data di atas sudah benar?\n"
                "Balas *ya* untuk lanjutkan\n"
                "Balas *ubah* untuk perbaiki data"
            )
        else:
            msg = (
                "📋 *Ringkasan Data Pendaftaran*\n\n"
                f"🪪  NIK/Nama   : *{nik_display}*\n"
                f"🩺 Keluhan    : {keluhan}\n"
                f"📅 Kunjungan : {tgl_display}\n\n"
                "Apakah data di atas sudah benar?\n"
                "Balas *ya* untuk lanjutkan\n"
                "Balas *ubah* untuk perbaiki data"
            )

        dispatcher.utter_message(text=msg)
        return [SlotSet("booking_step", "review")]


#  Konfirmasi dan kirim ke API
class ActionBookingConfirm(Action):
    """
    Pasien konfirmasi → POST ke API → generate tiket.
    Jika API belum tersedia, kirim tiket MOCK untuk keperluan testing.
    """

    def name(self) -> Text:
        return "action_booking_confirm"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:

        nama = tracker.get_slot("booking_nama") or "Pasien"
        nik = tracker.get_slot("booking_nik") or ""
        tgl_lahir = tracker.get_slot("booking_tgl_lahir") or ""
        keluhan = tracker.get_slot("booking_keluhan") or ""
        tgl_kunjungan = tracker.get_slot("booking_tgl_kunjungan") or ""
        tipe = tracker.get_slot("booking_tipe_pasien") or "baru"

        dispatcher.utter_message(
            text="⏳ Sedang memproses pendaftaran Anda, mohon tunggu sebentar..."
        )

        # Kirim ke API
        payload = {
            "namaLengkap": nama,
            "nik": nik,
            "tanggalLahir": tgl_lahir,
            "keluhan": keluhan,
            "tanggalKunjungan": tgl_kunjungan,
            "statusPasien": tipe,
            "sumber": "whatsapp",
        }

        # result = api_post("/appointments", payload)
        result = None # Dimatikan sementara karena API masih dalam pengerjaan

        if result:
            # ── Response dari API ──
            data = result.get("data", {})
            nomor_antrian = data.get("nomorAntrian") or data.get("queueNumber") or "?"
            nama_dokter = data.get("dokter", {}).get("namaLengkap") or "Akan ditentukan"
            nama_poli = data.get("poli") or "Poli Umum"
            jam_kunjungan = data.get("jamMulai") or "08.00 – 17.00"
            booking_id = str(data.get("id") or data.get("appointmentId") or "-")
        else:
            # ── MOCK untuk testing (API belum tersedia) ──
            print(f"[Booking] API tidak tersedia → pakai mock data")
            import random
            nomor_antrian = random.randint(1, 50)
            nama_dokter = "Akan ditentukan oleh admin"
            nama_poli = "Poli Umum"
            jam_kunjungan = "08.00 – 17.00"
            booking_id = f"MOCK-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        tgl_display = format_tgl_indonesia(tgl_kunjungan)

        tiket = (
            "✅ *Pendaftaran Berhasil!* 🎉\n\n"
            "🎫 *Konfirmasi Kunjungan*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 Nama Pasien  : *{nama}*\n"
            f"🏥 Dokter/Poli   : {nama_dokter} / {nama_poli}\n"
            f"📅 Waktu           : {tgl_display}\n"
            f"🕐 Jam               : {jam_kunjungan}\n"
            f"🔢 No. Antrian   : *{nomor_antrian}*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "📍 Jl. Magelang No. 88, Sinduadi, Sleman\n"
            "🗺️ https://maps.google.com/?q=-7.7218,110.3568\n\n"
            "⚠️ Mohon datang *15 menit lebih awal*.\n"
            "Sampai jumpa di klinik! 🙏\n\n"
            "_Ketik *reschedule* untuk ganti jadwal_\n"
            "_Ketik *batalkan* untuk membatalkan_"
        )

        dispatcher.utter_message(text=tiket)
        return [
            SlotSet("booking_step", "selesai"),
            SlotSet("booking_id_konfirmasi", booking_id),
        ]


#  Batalkan Booking
class ActionBookingCancel(Action):
    """Reset semua slot dan konfirmasi pembatalan."""

    def name(self) -> Text:
        return "action_booking_cancel"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:

        dispatcher.utter_message(response="utter_booking_batalkan")

        return [
            SlotSet("booking_tipe_pasien", None),
            SlotSet("booking_nik", None),
            SlotSet("booking_nama", None),
            SlotSet("booking_tgl_lahir", None),
            SlotSet("booking_keluhan", None),
            SlotSet("booking_tgl_kunjungan", None),
            SlotSet("booking_step", None),
            ActiveLoop(None),
        ]


#  Reset Slot Booking
class ActionSlotResetBooking(Action):
    """Reset slot agar pasien bisa isi ulang dari awal."""

    def name(self) -> Text:
        return "action_slot_reset_booking"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:

        dispatcher.utter_message(
            text="Baik, mari kita mulai ulang. Silakan isi data Anda kembali. 😊"
        )

        return [
            SlotSet("booking_tipe_pasien", None),
            SlotSet("booking_nik", None),
            SlotSet("booking_nama", None),
            SlotSet("booking_tgl_lahir", None),
            SlotSet("booking_keluhan", None),
            SlotSet("booking_tgl_kunjungan", None),
            SlotSet("booking_step", "tanya_tipe"),
            ActiveLoop(None),
        ]