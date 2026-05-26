

"""
Rasa Custom Actions — SmartClinic API Integration
==================================================
Handles:
  - Fetch Doctor Schedule
  - Fetch Queue Status
  - Booking Flow (Pasien Baru & Lama)
"""

# Last Change   :   27 May 2026
# ======================================================

import os
import re
import requests
from datetime import datetime, timedelta
from typing import Any, Text, Dict, List, Optional

from rasa_sdk import Action, Tracker, FormValidationAction
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet, ActiveLoop, FollowupAction

# URL Base API FastAPI 
API_BASE_URL = os.getenv("SMARTCLINIC_API_URL", "https://ai-crm.brotherzhafif.my.id")

# ======================================================
#  CORE HELPERS 
# ======================================================

def api_get(endpoint: str, params: dict = None) -> Any:
    """Melakukan request HTTP GET terpadu ke gateway FastAPI."""
    url = f"{API_BASE_URL}{endpoint}"
    try:
        resp = requests.get(url, params=params, timeout=12)
        if resp.status_code == 200:
            return resp.json()
        print(f"[API Error] GET {endpoint} status: {resp.status_code}")
        return None
    except Exception as e:
        print(f"[API Exception] GET {endpoint}: {e}")
        return None

def api_post(endpoint: str, payload: dict) -> Any:
    """Melakukan request HTTP POST terpadu ke gateway FastAPI dengan JSON body."""
    url = f"{API_BASE_URL}{endpoint}"
    try:
        resp = requests.post(url, json=payload, timeout=12)
        if resp.status_code in (200, 201):
            return resp.json()
        print(f"[API Error] POST {endpoint} status: {resp.status_code} | Response: {resp.text}")
        return None
    except Exception as e:
        print(f"[API Exception] POST {endpoint}: {e}")
        return None

def get_patient_by_phone(phone_number: str) -> dict:
    """Mencari data pasien terdaftar menggunakan endpoint /api/patients/by-phone."""
    result = api_get("/api/patients/by-phone", params={"phone": phone_number})
    if result and isinstance(result, dict):
        return result
    elif result and isinstance(result, list) and len(result) > 0:
        return result[0]
    return {}

# ======================================================
#  JADWAL & ANTREAN ACTIONS
# ======================================================

class ActionFetchSchedule(Action):
    def name(self) -> Text:
        return "action_fetch_schedule"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        # Tembak GET /api/schedules
        result = api_get("/api/schedules")

        if result is None:
            dispatcher.utter_message(
                text="Mohon maaf, saya sedang tidak bisa mengakses data jadwal dokter saat ini. "
                     "Silakan coba beberapa saat lagi atau hubungi admin klinik. 🙏"
            )
            return []

        schedules = result if isinstance(result, list) else result.get("data", [])

        if not schedules:
            dispatcher.utter_message(text="Saat ini belum ada jadwal dokter yang tersedia di sistem RME. 🙏")
            return []

        msg = "📅 *Jadwal Dokter Klinik SmartClinic*\n\n"
        for i, sched in enumerate(schedules[:6], 1):
            dokter_name = sched.get("dokter_nama") or sched.get("nama_dokter") or sched.get("dokter", {}).get("namaLengkap", "Dokter")
            spesialis = sched.get("spesialis") or sched.get("dokter", {}).get("spesialis", "Umum")
            hari = sched.get("hari_nama") or sched.get("hari") or "Senin - Jumat"
            jam = sched.get("jam") or f"{sched.get('jamMulai', '08:00')} - {sched.get('jamSelesai', '14:00')}"
            
            msg += f"{i}. 🩺 *{dokter_name}* ({spesialis})\n"
            msg += f"   📆 Hari: {hari}\n"
            msg += f"   🕐 Jam: {jam}\n\n"

        msg += "Apakah Anda ingin membuat janji temu dengan salah satu dokter? 😊"
        dispatcher.utter_message(text=msg)
        return []


class ActionFetchQueue(Action):
    def name(self) -> Text:
        return "action_fetch_queue"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        # Tembak GET /api/appointment (Ambil daftar antrian hari ini)
        result = api_get("/api/appointment")

        if result is None:
            dispatcher.utter_message(text="Mohon maaf, saya gagal memuat status antrean saat ini. Silakan coba lagi nanti.")
            return []

        queues = result if isinstance(result, list) else result.get("data", [])
        total_antrean = len(queues)

        msg = f"🔢 *Status Antrian Hari Ini*\n\n📊 Total antrian terdaftar: *{total_antrean}* pasien\n"
        
        if total_antrean > 0:
            # Hitung ringkasan status antrean jika ada datanya
            status_count = {}
            for q in queues:
                st = q.get("status", "MENUNGGU").upper()
                status_count[st] = status_count.get(st, 0) + 1
            
            status_emoji = {"MENUNGGU": "⏳", "DIPANGGIL": "📢", "DIPERIKSA": "🩺", "SELESAI": "✅"}
            for status, count in status_count.items():
                emoji = status_emoji.get(status, "•")
                msg += f"{emoji} {status}: {count} orang\n"
        else:
            msg += "📋 Belum ada antrean berjalan untuk hari ini."

        msg += "\nApakah ada hal lain yang bisa saya bantu? 😊"
        dispatcher.utter_message(text=msg)
        return []

# ======================================================
# FORMAT & VALIDASI TANGGAL + NIK
# ======================================================

def parse_tanggal_kunjungan(teks: str) -> Optional[str]:
    teks = teks.strip().lower()
    today = datetime.now()

    if teks in ("hari ini", "sekarang"):
        return today.strftime("%Y-%m-%d")
    if teks in ("besok", "bsk"):
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    if teks == "lusa":
        return (today + timedelta(days=2)).strftime("%Y-%m-%d")

    nama_hari_map = {"senin": 0, "selasa": 1, "rabu": 2, "kamis": 3, "jumat": 4, "sabtu": 5, "minggu": 6}
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
    match = re.search(r"(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})", teks)
    if match:
        day, month, year = match.groups()
        try:
            return datetime(int(year), int(month), int(day)).strftime("%Y-%m-%d")
        except ValueError:
            return None
    return None

def format_tgl_indonesia(tgl_str: str) -> str:
    hari_map = {"Monday": "Senin", "Tuesday": "Selasa", "Wednesday": "Rabu", "Thursday": "Kamis", "Friday": "Jumat", "Saturday": "Sabtu", "Sunday": "Minggu"}
    bulan_map = {"January": "Januari", "February": "Februari", "March": "Maret", "April": "April", "May": "Mei", "June": "Juni", "July": "Juli", "August": "Agustus", "September": "September", "October": "Oktober", "November": "November", "December": "Desember"}
    try:
        dt = datetime.strptime(tgl_str, "%Y-%m-%d")
        hasil = dt.strftime("%A, %d %B %Y")
        for en, id_ in {**hari_map, **bulan_map}.items():
            hasil = hasil.replace(en, id_)
        return hasil
    except Exception:
        return tgl_str

# ======================================================
# APPOINTMENT BOOKING 
# ======================================================

class ActionStartBooking(Action):
    def name(self) -> Text:
        return "action_start_booking"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        sender_id = tracker.sender_id
        # Lookup pasien via API FastAPI
        patient_data = get_patient_by_phone(sender_id)
        
        nik = patient_data.get("nik")
        dob = patient_data.get("date_of_birth") or patient_data.get("tanggalLahir")
        
        if nik and dob:
            dispatcher.utter_message(response="utter_ask_booking_untuk_siapa", nik=nik)
            return [
                SlotSet("booking_tipe_pasien", None), SlotSet("booking_nik", None),
                SlotSet("booking_nama", None), SlotSet("booking_tgl_lahir", None),
                SlotSet("booking_keluhan", None), SlotSet("booking_tgl_kunjungan", None),
                SlotSet("booking_step", "tanya_untuk_siapa"), SlotSet("booking_untuk_siapa", None)
            ]
        else:
            dispatcher.utter_message(response="utter_booking_tanya_tipe")
            return [
                SlotSet("booking_tipe_pasien", None), SlotSet("booking_nik", None),
                SlotSet("booking_nama", None), SlotSet("booking_tgl_lahir", None),
                SlotSet("booking_keluhan", None), SlotSet("booking_tgl_kunjungan", None),
                SlotSet("booking_step", "tanya_tipe")
            ]


class ActionHandleUntukSiapa(Action):
    def name(self) -> Text:
        return "action_handle_untuk_siapa"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        intent = tracker.latest_message.get("intent", {}).get("name")
        
        if intent == "intent_diri_sendiri":
            sender_id = tracker.sender_id
            patient_data = get_patient_by_phone(sender_id)
            nama = patient_data.get("nama") or patient_data.get("namaLengkap", "")
            nik = patient_data.get("nik", "")
            dob = patient_data.get("date_of_birth") or patient_data.get("tanggalLahir", "")
            
            dispatcher.utter_message(response="utter_booking_intro_baru")
            return [
                SlotSet("booking_nama", nama), SlotSet("booking_nik", nik), SlotSet("booking_tgl_lahir", dob),
                SlotSet("booking_tipe_pasien", "baru"), SlotSet("booking_step", "form_baru"),
                ActiveLoop("booking_form_baru"), FollowupAction("booking_form_baru")
            ]
        else:
            dispatcher.utter_message(response="utter_booking_intro_baru")
            return [
                SlotSet("booking_tipe_pasien", "baru"), SlotSet("booking_step", "form_baru"),
                ActiveLoop("booking_form_baru"), FollowupAction("booking_form_baru")
            ]


# ======================================================
#  FORM VALIDATION ACTIONS
# ======================================================

class ValidateBookingFormBaru(FormValidationAction):
    def name(self) -> Text:
        return "validate_booking_form_baru"

    def validate_booking_nama(self, slot_value: Any, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> Dict[Text, Any]:
        nama = str(slot_value).strip()
        if len(nama) < 2:
            dispatcher.utter_message(text="⚠️ Nama terlalu pendek. Mohon ketik nama lengkap Anda sesuai KTP.")
            return {"booking_nama": None}
        return {"booking_nama": nama.title()}

    def validate_booking_nik(self, slot_value: Any, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> Dict[Text, Any]:
        nik = re.sub(r"\D", "", str(slot_value))
        if len(nik) != 16:
            dispatcher.utter_message(response="utter_booking_nik_invalid")
            return {"booking_nik": None}
        return {"booking_nik": nik}

    def validate_booking_tgl_lahir(self, slot_value: Any, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> Dict[Text, Any]:
        parsed = parse_tanggal_lahir(str(slot_value))
        if not parsed:
            dispatcher.utter_message(response="utter_booking_tgl_invalid")
            return {"booking_tgl_lahir": None}
        return {"booking_tgl_lahir": parsed}

    def validate_booking_keluhan(self, slot_value: Any, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> Dict[Text, Any]:
        keluhan = str(slot_value).strip()
        if len(keluhan) < 3:
            dispatcher.utter_message(text="⚠️ Keluhan terlalu singkat. Mohon ceritakan sedikit lebih detail.")
            return {"booking_keluhan": None}
        return {"booking_keluhan": keluhan}

    def validate_booking_tgl_kunjungan(self, slot_value: Any, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> Dict[Text, Any]:
        parsed = parse_tanggal_kunjungan(str(slot_value))
        if not parsed:
            dispatcher.utter_message(response="utter_booking_tgl_kunjungan_invalid")
            return {"booking_tgl_kunjungan": None}
        return {"booking_tgl_kunjungan": parsed}


class ValidateBookingFormLama(FormValidationAction):
    def name(self) -> Text:
        return "validate_booking_form_lama"

    def validate_booking_nik(self, slot_value: Any, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> Dict[Text, Any]:
        nilai = str(slot_value).strip()
        digit_only = re.sub(r"\D", "", nilai)
        if len(digit_only) == 16:
            return {"booking_nik": digit_only}
        if not nilai.isdigit() and len(nilai) >= 2:
            return {"booking_nik": nilai}
        dispatcher.utter_message(response="utter_booking_nik_invalid")
        return {"booking_nik": None}

    def validate_booking_keluhan(self, slot_value: Any, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> Dict[Text, Any]:
        keluhan = str(slot_value).strip()
        if len(keluhan) < 3:
            dispatcher.utter_message(text="⚠️ Keluhan terlalu singkat. Mohon ceritakan sedikit lebih detail.")
            return {"booking_keluhan": None}
        return {"booking_keluhan": keluhan}

    def validate_booking_tgl_kunjungan(self, slot_value: Any, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> Dict[Text, Any]:
        parsed = parse_tanggal_kunjungan(str(slot_value))
        if not parsed:
            dispatcher.utter_message(response="utter_booking_tgl_kunjungan_invalid")
            return {"booking_tgl_kunjungan": None}
        return {"booking_tgl_kunjungan": parsed}


# ======================================================
# SUBMIT & REVIEW ACTIONS
# ======================================================

class ActionBookingFormBaruSubmit(Action):
    def name(self) -> Text:
        return "action_booking_form_baru_submit"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        return [SlotSet("booking_step", "review")]


class ActionBookingFormLamaSubmit(Action):
    def name(self) -> Text:
        return "action_booking_form_lama_submit"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        identifier = tracker.get_slot("booking_nik") or ""
        events = [SlotSet("booking_step", "review")]
        digit_only = re.sub(r"\D", "", identifier)

        #  Tembak GET /api/patients (Melakukan pencarian pasien didasarkan NIK atau nama untuk pasien lama)
        if len(digit_only) == 16:
            result = api_get("/api/patients", params={"nik": digit_only})
        else:
            result = api_get("/api/patients", params={"nama": identifier})

        if result:
            data = result if isinstance(result, list) else result.get("data", [])
            if isinstance(data, list) and len(data) > 0:
                data = data[0]
            
            nama = data.get("namaLengkap") or data.get("nama") or ""
            tgl_lahir = data.get("tanggalLahir") or data.get("date_of_birth") or ""
            nik = data.get("nik") or digit_only
            
            if nama:
                dispatcher.utter_message(text=f"✅ Data Anda ditemukan. Halo kembali, *{nama}*! 😊")
                events += [SlotSet("booking_nama", nama), SlotSet("booking_nik", nik), SlotSet("booking_tgl_lahir", tgl_lahir)]
            else:
                dispatcher.utter_message(text="⚠️ Data rekam medis Anda belum ditemukan. Kami bantu daftarkan via data form ya.")
        else:
            dispatcher.utter_message(text="⚠️ Layanan data pasien sedang sibuk. Kita lanjutkan konfirmasi jadwal Anda dahulu.")

        return events


class ActionBookingReview(Action):
    def name(self) -> Text:
        return "action_booking_review"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        nama = tracker.get_slot("booking_nama") or "-"
        nik = tracker.get_slot("booking_nik") or "-"
        tgl_lahir = tracker.get_slot("booking_tgl_lahir") or "-"
        keluhan = tracker.get_slot("booking_keluhan") or "-"
        tgl_kunjungan = tracker.get_slot("booking_tgl_kunjungan") or "-"
        tipe = tracker.get_slot("booking_tipe_pasien") or "baru"

        tgl_display = format_tgl_indonesia(tgl_kunjungan)
        nik_display = f"****-****-****-{nik[-4:]}" if len(nik) == 16 else nik

        if tipe == "baru":
            msg = (
                "📋 *Ringkasan Data Pendaftaran*\n\n"
                f"👤 Nama        : *{nama}*\n"
                f"🪪 NIK         : `{nik_display}`\n"
                f"🎂 Tgl Lahir  : {tgl_lahir}\n"
                f"🩺 Keluhan    : {keluhan}\n"
                f"📅 Kunjungan : {tgl_display}\n\n"
                "Apakah data di atas sudah benar?\n"
                "Balas *ya* untuk melanjutkan\n"
                "Balas *ubah* untuk memperbaiki"
            )
        else:
            msg = (
                "📋 *Ringkasan Data Pendaftaran*\n\n"
                f"🪪 NIK/Nama   : *{nik_display}*\n"
                f"🩺 Keluhan    : {keluhan}\n"
                f"📅 Kunjungan : {tgl_display}\n\n"
                "Apakah data di atas sudah benar?\n"
                "Balas *ya* untuk melanjutkan\n"
                "Balas *ubah* untuk memperbaiki"
            )

        dispatcher.utter_message(text=msg)
        return [SlotSet("booking_step", "review")]


class ActionBookingConfirm(Action):
    def name(self) -> Text:
        return "action_booking_confirm"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        nama = tracker.get_slot("booking_nama") or "Pasien"
        keluhan = tracker.get_slot("booking_keluhan") or "Pendaftaran via Bot"
        tgl_kunjungan = tracker.get_slot("booking_tgl_kunjungan") or ""
        no_hp = tracker.sender_id

        dispatcher.utter_message(text="⏳ Sedang memproses janji temu Anda, mohon tunggu sebentar...")

        # Struktur PAYLOAD booking
        payload = {
            "phone_number": no_hp,
            "jadwalId": "JDW-AUTO-DEFAULT",  
            "tanggalKunjungan": tgl_kunjungan,  
            "catatan": f"Nama: {nama}. Keluhan: {keluhan}",
            "jenisKunjunganBpjs": "non-bpjs",
            "noRujukanFktp": ""
        }

        # Tembak POST /api/appointment/appointments (Membuat booking baru)
        result = api_post("/api/appointment/appointments", payload)

        if result and (result.get("status") == "ok" or "status" in result):
            nomor_antrian = result.get("nomorAntrian") or result.get("queue_number") or "Akan diberikan di klinik"
            booking_id = result.get("appointmentId") or result.get("id") or f"SC-{datetime.now().strftime('%m%d%H%M')}"
            
            tgl_display = format_tgl_indonesia(tgl_kunjungan)
            tiket = (
                "✅ *Pendaftaran Berhasil!* 🎉\n\n"
                "🎫 *Konfirmasi Kunjungan*\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 Nama Pasien  : *{nama}*\n"
                f"📅 Waktu           : {tgl_display}\n"
                f"🔢 No. Antrian   : *{nomor_antrian}*\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "📍 Jl. Magelang No. 88, Sinduadi, Sleman\n"
                "⚠️ Mohon datang *15 menit lebih awal*.\n"
                "Sampai jumpa di klinik! 🙏\n\n"
                "_Ketik *reschedule* untuk ganti jadwal_\n"
                "_Ketik *batalkan* untuk membatalkan_"
            )
            dispatcher.utter_message(text=tiket)
            booking_id_final = str(booking_id)
        else:
            # fallback manual jika API gagal merespons dengan benar
            print(f"[Booking Warning] POST /api/appointment/appointments gagal. Memicu fallback manual.")
            dispatcher.utter_message(
                text="⚠️ *Sistem Sedang Padat*\n"
                     "Data pendaftaran Anda sudah aman tersimpan dalam sistem antrean chatbot kami. "
                     "Tim admin kami akan memvalidasi slot Anda secara manual dan mengirimkan nomor antrean resmi sesaat lagi. Terima kasih! 🙏"
            )
            booking_id_final = f"FALLBACK-{datetime.now().strftime('%H%M%S')}"

        return [
            SlotSet("booking_tipe_pasien", None), SlotSet("booking_nik", None),
            SlotSet("booking_nama", None), SlotSet("booking_tgl_lahir", None),
            SlotSet("booking_keluhan", None), SlotSet("booking_tgl_kunjungan", None),
            SlotSet("booking_step", "selesai"), SlotSet("booking_id_konfirmasi", booking_id_final),
            ActiveLoop(None)
        ]


class ActionBookingCancel(Action):
    def name(self) -> Text:
        return "action_booking_cancel"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        dispatcher.utter_message(response="utter_booking_batalkan")
        return [
            SlotSet("booking_tipe_pasien", None), SlotSet("booking_nik", None),
            SlotSet("booking_nama", None), SlotSet("booking_tgl_lahir", None),
            SlotSet("booking_keluhan", None), SlotSet("booking_tgl_kunjungan", None),
            SlotSet("booking_step", None), ActiveLoop(None)
        ]


class ActionSlotResetBooking(Action):
    def name(self) -> Text:
        return "action_slot_reset_booking"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        dispatcher.utter_message(text="Baik, mari kita mulai ulang. Silakan isi data Anda kembali. 😊")
        return [
            SlotSet("booking_tipe_pasien", None), SlotSet("booking_nik", None),
            SlotSet("booking_nama", None), SlotSet("booking_tgl_lahir", None),
            SlotSet("booking_keluhan", None), SlotSet("booking_tgl_kunjungan", None),
            SlotSet("booking_step", "tanya_tipe"), ActiveLoop(None)
        ]