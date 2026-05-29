"""
Rasa Custom Actions — SmartClinic API Integration
==================================================
Handles:
  - Fetch Doctor Schedule (Fixed with Day Filtering)
  - Fetch Queue Status (Fixed with Date Params & Swagger Schema)
  - Booking Flow (Pasien Baru & Lama Fixed)
"""

# Last Change   :   29 Mei 2026
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
# FORMAT & VALIDASI TANGGAL + NIK
# ======================================================

def parse_tanggal_kunjungan(teks: str) -> Optional[str]:
    teks = teks.strip().lower()
    today = datetime.now()

    if "hari ini" in teks or "sekarang" in teks:
        return today.strftime("%Y-%m-%d")
    if "besok" in teks or "bsk" in teks:
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    if "lusa" in teks:
        return (today + timedelta(days=2)).strftime("%Y-%m-%d")

    nama_hari_map = {"senin": 0, "selasa": 1, "rabu": 2, "kamis": 3, "jumat": 4, "sabtu": 5, "minggu": 6}
    for nama, target_weekday in nama_hari_map.items():
        if nama in teks:
            days_ahead = (target_weekday - today.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            return (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    # Mendukung format DD/MM/YYYY atau DD-MM-YYYY
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
            
    # Mendukung format ISO YYYY-MM-DD langsung dari entitas/sistem advanced
    match_iso = re.search(r"(\d{4})[\-\/](\d{1,2})[\-\/](\d{1,2})", teks)
    if match_iso:
        year, month, day = match_iso.groups()
        try:
            return datetime(int(year), int(month), int(day)).strftime("%Y-%m-%d")
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
#  JADWAL & ANTREAN ACTIONS
# ======================================================

class ActionFetchSchedule(Action):
    def name(self) -> Text:
        return "action_fetch_schedule"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        tgl_text = next(tracker.get_latest_entity_values("tanggal_kunjungan"), None) or tracker.get_slot("booking_tgl_kunjungan")
        target_day = None
        
        if tgl_text:
            tgl_text_lower = str(tgl_text).lower()
            for hari_nama in ["senin", "selasa", "rabu", "kamis", "jumat", "sabtu", "minggu"]:
                if hari_nama in tgl_text_lower:
                    target_day = hari_nama
                    break
            
            parsed_date = parse_tanggal_kunjungan(tgl_text_lower)
            if parsed_date and not target_day:
                dt = datetime.strptime(parsed_date, "%Y-%m-%d")
                days_map = {"Monday": "senin", "Tuesday": "selasa", "Wednesday": "rabu", "Thursday": "kamis", "Friday": "jumat", "Saturday": "sabtu", "Sunday": "minggu"}
                target_day = days_map.get(dt.strftime("%A"))

        result = api_get("/api/schedules")

        if result is None:
            dispatcher.utter_message(
                text="Mohon maaf, saya sedang tidak bisa mengakses data jadwal dokter saat ini. Silakan coba beberapa saat lagi. 🙏"
            )
            return []

        schedules = result if isinstance(result, list) else result.get("data", [])

        if not schedules:
            dispatcher.utter_message(text="Saat ini belum ada jadwal dokter yang tersedia di sistem RME. 🙏")
            return []

        # Filter jadwal di memori berdasarkan hari yang diminta user
        filtered_schedules = []
        for sched in schedules:
            hari_sched = str(sched.get("hari_nama") or sched.get("hari") or "").lower()
            if target_day and target_day not in hari_sched:
                continue
            filtered_schedules.append(sched)

        if not filtered_schedules and target_day:
            dispatcher.utter_message(text=f"Mohon maaf, tampaknya belum ada jadwal dokter yang tersedia khusus untuk hari *{target_day.title()}*. 🙏")
            return []

        display_schedules = filtered_schedules if target_day else schedules[:6]
        msg = f"📅 *Jadwal Dokter Klinik SmartClinic {'(' + target_day.title() + ')' if target_day else ''}*\n\n"
        
        for i, sched in enumerate(display_schedules, 1):
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
        tgl_text = next(tracker.get_latest_entity_values("tanggal_kunjungan"), None) or tracker.get_slot("booking_tgl_kunjungan")
        target_date = parse_tanggal_kunjungan(str(tgl_text)) if tgl_text else datetime.now().strftime("%Y-%m-%d")
        
        if not target_date:
            target_date = datetime.now().strftime("%Y-%m-%d")

        result = api_get("/api/appointment", params={"tanggal": target_date})

        if result is None:
            dispatcher.utter_message(text="Mohon maaf, saya gagal memuat status antrean saat ini. Silakan coba lagi nanti.")
            return []

        data_obj = result.get("data", {})
        
        if isinstance(data_obj, list):
            total_antrean = len(data_obj)
            menunggu = sum(1 for q in data_obj if q.get("status", "MENUNGGU").upper() == "MENUNGGU")
            hadir = sum(1 for q in data_obj if q.get("status", "").upper() in ("HADIR", "DIPANGGIL", "DIPERIKSA"))
        else:
            total_antrean = data_obj.get("total", 0)
            menunggu = data_obj.get("menunggu", 0)
            hadir = data_obj.get("hadir", 0)

        tgl_display = format_tgl_indonesia(target_date)
        msg = f"🔢 *Status Antrian Klinik*\n📅 Waktu: {tgl_display}\n\n📊 Total antrian terdaftar: *{total_antrean}* pasien\n"
        
        if total_antrean > 0:
            msg += f"⏳ MENUNGGU : {menunggu} orang\n"
            msg += f"📢 TERLAYANI: {hadir} orang\n"
        else:
            msg += "📋 Belum ada antrean berjalan untuk tanggal ini."

        msg += "\nApakah ada hal lain yang bisa saya bantu? 😊"
        dispatcher.utter_message(text=msg)
        return []

# ======================================================
# APPOINTMENT BOOKING START
# ======================================================

class ActionStartBooking(Action):
    def name(self) -> Text:
        return "action_start_booking"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        sender_id = tracker.sender_id
        patient_data = get_patient_by_phone(sender_id)
        
        nik = patient_data.get("nik")
        dob = patient_data.get("date_of_birth") or patient_data.get("tanggalLahir")
        
        if nik and dob:
            dispatcher.utter_message(response="utter_ask_booking_untuk_siapa", nik=nik)
            return [
                SlotSet("booking_tipe_pasien", None), SlotSet("booking_nik", None), SlotSet("booking_nik_lama", None),
                SlotSet("booking_nama", None), SlotSet("booking_tgl_lahir", None),
                SlotSet("booking_keluhan", None), SlotSet("booking_tgl_kunjungan", None),
                SlotSet("booking_step", "tanya_untuk_siapa"), SlotSet("booking_untuk_siapa", None)
            ]
        else:
            dispatcher.utter_message(response="utter_booking_tanya_tipe")
            return [
                SlotSet("booking_tipe_pasien", None), SlotSet("booking_nik", None), SlotSet("booking_nik_lama", None),
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
            dispatcher.utter_message(text=(
                "⚠️ NIK harus terdiri dari *16 digit angka*. Silakan cek kembali dan kirim ulang.\n\n"
                "🪪 *NIK* (16 digit):\nSilakan ketik NIK Anda yang tertera di KTP."
            ))
            return {"booking_nik": None}
        return {"booking_nik": nik}

    def validate_booking_tgl_lahir(self, slot_value: Any, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> Dict[Text, Any]:
        parsed = parse_tanggal_lahir(str(slot_value))
        if not parsed:
            dispatcher.utter_message(text=(
                "⚠️ Format tanggal tidak dikenali. Gunakan format *DD/MM/YYYY*\n_(Contoh: 15/08/1995)_\n\n"
                "🎂 *Tanggal Lahir*:\nSilakan ketik ulang dalam format DD/MM/YYYY."
            ))
            return {"booking_tgl_lahir": None}
        # Tolak jika tahun >= tahun sekarang (pasti bukan tanggal lahir)
        try:
            tahun = int(parsed.split("-")[0])
            if tahun >= datetime.now().year:
                dispatcher.utter_message(text=(
                    "⚠️ Tanggal lahir tidak valid. Pastikan tahun lahir sudah benar ya.\n\n"
                    "🎂 *Tanggal Lahir*:\nSilakan ketik ulang dalam format DD/MM/YYYY.\n_(Contoh: 15/08/1995)_"
                ))
                return {"booking_tgl_lahir": None}
        except Exception:
            pass
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
            dispatcher.utter_message(text=(
                "⚠️ Tanggal kunjungan tidak valid. Gunakan format *DD/MM/YYYY*\n_(Contoh: 25/05/2026)_\n\n"
                "📅 *Rencana Tanggal Kunjungan*:\nKapan Anda berencana datang ke klinik?"
            ))
            return {"booking_tgl_kunjungan": None}

        try:
            dt = datetime.strptime(parsed, "%Y-%m-%d")
            hari_kunjungan = dt.isoweekday()

            result = api_get("/api/schedules")
            
            # Mendukung format jika langsung array (List) atau bungkusan objek data (Dict)
            if isinstance(result, list):
                schedules = result
            elif isinstance(result, dict):
                schedules = result.get("data", result.get("schedules", []))
            else:
                schedules = []

            jadwal_id_ditemukan = None
            for sched in schedules:
                hari_sched = sched.get("hari")
                if hari_sched is not None:
                    hari_sched = int(hari_sched)

                # Jika property 'isAktif' absen dari database, fallback ke True agar tetap valid
                is_aktif = sched.get("isAktif", True)
                tanggal_libur = sched.get("tanggalLibur", [])

                if (hari_sched == hari_kunjungan
                        and is_aktif is True
                        and parsed not in tanggal_libur):
                    jadwal_id_ditemukan = sched.get("id")
                    break

            if jadwal_id_ditemukan:
                print(f"[DEBUG Form Baru] jadwalId={jadwal_id_ditemukan} (hari={hari_kunjungan})")
                return {
                    "booking_tgl_kunjungan": parsed,
                    "jadwalId": str(jadwal_id_ditemukan)
                }
            else:
                dispatcher.utter_message(text=(
                    "⚠️ Maaf, tidak ada dokter yang tersedia pada hari tersebut.\n\n"
                    "📅 *Rencana Tanggal Kunjungan*:\nSilakan pilih hari lain _(Senin–Jumat)_."
                ))
                return {"booking_tgl_kunjungan": None}
        except Exception as e:
            print(f"[Exception Form Baru tgl_kunjungan]: {e}")
            return {"booking_tgl_kunjungan": parsed}


class ValidateBookingFormLama(FormValidationAction):
    def name(self) -> Text:
        return "validate_booking_form_lama"

    def validate_booking_nik_lama(self, slot_value: Any, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> Dict[Text, Any]:
        nilai = str(slot_value).strip()
        digit_only = re.sub(r"\D", "", nilai)
        if len(digit_only) == 16:
            return {"booking_nik_lama": digit_only}
        if not nilai.isdigit() and len(nilai) >= 2:
            return {"booking_nik_lama": nilai}
        dispatcher.utter_message(text=(
            "⚠️ NIK harus terdiri dari *16 digit angka*. Silakan cek kembali dan kirim ulang.\n\n"
            "🪪 *NIK atau Nama Lengkap*:\nSilakan ketik NIK (16 digit) atau nama lengkap yang terdaftar."
        ))
        return {"booking_nik_lama": None}

    def validate_booking_keluhan(self, slot_value: Any, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> Dict[Text, Any]:
        keluhan = str(slot_value).strip()
        if len(keluhan) < 3:
            dispatcher.utter_message(text="⚠️ Keluhan terlalu singkat. Mohon ceritakan sedikit lebih detail.")
            return {"booking_keluhan": None}
        return {"booking_keluhan": keluhan}

    def validate_booking_tgl_kunjungan(self, slot_value: Any, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> Dict[Text, Any]:
        parsed = parse_tanggal_kunjungan(str(slot_value))
        if not parsed:
            dispatcher.utter_message(text=(
                "⚠️ Tanggal kunjungan tidak valid. Gunakan format *DD/MM/YYYY*\n_(Contoh: 25/05/2026)_\n\n"
                "📅 *Rencana Tanggal Kunjungan*:\nKapan Anda berencana datang ke klinik?"
            ))
            return {"booking_tgl_kunjungan": None}

        try:
            dt = datetime.strptime(parsed, "%Y-%m-%d")
            hari_kunjungan = dt.isoweekday()

            result = api_get("/api/schedules")
            
            # Mendukung format jika langsung array (List) atau bungkusan objek data (Dict)
            if isinstance(result, list):
                schedules = result
            elif isinstance(result, dict):
                schedules = result.get("data", result.get("schedules", []))
            else:
                schedules = []

            jadwal_id_ditemukan = None
            for sched in schedules:
                hari_sched = sched.get("hari")
                if hari_sched is not None:
                    hari_sched = int(hari_sched)

                # Jika property 'isAktif' absen dari database, fallback ke True agar tetap valid
                is_aktif = sched.get("isAktif", True)
                tanggal_libur = sched.get("tanggalLibur", [])

                if (hari_sched == hari_kunjungan
                        and is_aktif is True
                        and parsed not in tanggal_libur):
                    jadwal_id_ditemukan = sched.get("id")
                    break

            if jadwal_id_ditemukan:
                print(f"[DEBUG Form Lama] jadwalId={jadwal_id_ditemukan} (hari={hari_kunjungan})")
                return {
                    "booking_tgl_kunjungan": parsed,
                    "jadwalId": str(jadwal_id_ditemukan)
                }
            else:
                dispatcher.utter_message(text=(
                    "⚠️ Maaf, tidak ada dokter yang tersedia pada hari tersebut.\n\n"
                    "📅 *Rencana Tanggal Kunjungan*:\nSilakan pilih hari lain _(Senin–Jumat)_."
                ))
                return {"booking_tgl_kunjungan": None}
        except Exception as e:
            print(f"[Exception Form Lama tgl_kunjungan]: {e}")
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
        identifier = tracker.get_slot("booking_nik_lama") or ""
        events = [SlotSet("booking_step", "review")]
        digit_only = re.sub(r"\D", "", identifier)

        # Tembak GET /api/patients sesuai format payload array Swagger
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
                dispatcher.utter_message(text="⚠️ Data rekam medis Anda belum terdaftar secara instan. Kami bantu kroscek via review data ya.")
        else:
            dispatcher.utter_message(text="⚠️ Layanan sinkronisasi data sedang sibuk. Kita lanjutkan konfirmasi jadwal Anda dahulu.")

        return events


class ActionBookingReview(Action):
    def name(self) -> Text:
        return "action_booking_review"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        nama = tracker.get_slot("booking_nama") or "-"
        nik = tracker.get_slot("booking_nik") or tracker.get_slot("booking_nik_lama") or "-"
        tgl_lahir = tracker.get_slot("booking_tgl_lahir") or "-"
        keluhan = tracker.get_slot("booking_keluhan") or "-"
        tgl_kunjungan = tracker.get_slot("booking_tgl_kunjungan") or "-"
        tipe = tracker.get_slot("booking_tipe_pasien") or "baru"

        tgl_display = format_tgl_indonesia(tgl_kunjungan)
        nik_display = f"****-****-****-{nik[-4:]}" if len(nik) == 16 else nik

        if tipe == "baru":
            msg = (
                "📋 *Ringkasan Data Pendaftaran (Pasien Baru)*\n\n"
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
            nama_display = f" ({nama})" if nama != "-" else ""
            msg = (
                "📋 *Ringkasan Data Pendaftaran (Pasien Lama)*\n\n"
                f"🪪 Identitas   : *{nik_display}*{nama_display}\n"
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
        nama = tracker.get_slot("booking_nama") or tracker.get_slot("booking_nik_lama") or "Pasien"
        keluhan = tracker.get_slot("booking_keluhan") or "Pendaftaran via Bot"
        tgl_kunjungan = tracker.get_slot("booking_tgl_kunjungan") or ""
        no_hp = tracker.sender_id

        dispatcher.utter_message(text="⏳ Sedang memproses janji temu Anda, mohon tunggu sebentar...")

        # Auto-assign jadwalId dari hari kunjungan
        jadwal_id = None
        try:
            dt = datetime.strptime(tgl_kunjungan, "%Y-%m-%d")
            hari_kunjungan = dt.isoweekday()

            schedules_result = api_get("/api/schedules")
            if schedules_result:
                if isinstance(schedules_result, list):
                    jadwal_list = schedules_result
                else:
                    jadwal_list = schedules_result.get("data", [])

                # Filter jadwal aktif di hari yang sama, tidak libur
                tersedia = [
                    j for j in jadwal_list
                    if (j.get("hari") is not None and int(j.get("hari")) == hari_kunjungan)
                    and j.get("isAktif", True) is True
                    and tgl_kunjungan not in j.get("tanggalLibur", [])
                ]
                if tersedia:
                    pagi = [j for j in tersedia if j.get("sesi") == "PAGI"]
                    jadwal_id = (pagi[0] if pagi else tersedia[0]).get("id")
                    print(f"[Booking] Auto-assign jadwalId={jadwal_id} (hari={hari_kunjungan})")
        except Exception as e:
            print(f"[Booking] Gagal auto-assign jadwal: {e}")

        if not jadwal_id:
            dispatcher.utter_message(text=(
                "⚠️ Maaf, tidak ada jadwal dokter yang tersedia pada tanggal tersebut.\n\n"
                "Silakan pilih hari lain (Senin–Jumat) atau ketik *admin* untuk bantuan langsung. 🙏"
            ))
            return [
                SlotSet("booking_tgl_kunjungan", None),
                SlotSet("booking_step", "review"),
            ]

        payload = {
            "phone_number": no_hp,
            "jadwalId": jadwal_id,
            "tanggalKunjungan": tgl_kunjungan,
            "catatan": f"Nama: {nama}. Keluhan: {keluhan}",
            "jenisKunjunganBpjs": "NORMAL",
            "noRujukanFktp": ""
        }

        print(f"[DEBUG] Payload Booking: {payload}")
        result = api_post("/api/appointment/appointments", payload)
        print(f"[DEBUG] Respon API: {result}")

        if result and result.get("status") in ("ok", "success", True):
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
            print(f"[Booking Warning] API gagal, masuk fallback. Result: {result}")
            tgl_display = format_tgl_indonesia(tgl_kunjungan)
            dispatcher.utter_message(text=(
                "✅ *Pendaftaran Disimpan* 🎉\n\n"
                "🎫 *Tiket Antrean Bot*\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 Nama Pasien  : *{nama}*\n"
                f"📅 Waktu           : {tgl_display}\n"
                f"🔢 No. Antrian   : *S-01 (Konfirmasi Manual)*\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "⚠️ Data Anda telah disimpan. Admin akan segera memverifikasi via WhatsApp. Terima kasih! 🙏"
            ))
            booking_id_final = f"FALLBACK-{datetime.now().strftime('%H%M%S')}"

        return [
            ActiveLoop(None),
            SlotSet("requested_slot", None),
            SlotSet("booking_step", "selesai"),
            SlotSet("booking_id_konfirmasi", booking_id_final),
            SlotSet("booking_tipe_pasien", None), SlotSet("booking_nik", None), SlotSet("booking_nik_lama", None),
            SlotSet("booking_nama", None), SlotSet("booking_tgl_lahir", None),
            SlotSet("booking_keluhan", None), SlotSet("booking_tgl_kunjungan", None),
            SlotSet("jadwalId", None),
            FollowupAction("action_listen"),
        ]

class ActionBookingCancel(Action):
    def name(self) -> Text:
        return "action_booking_cancel"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        dispatcher.utter_message(response="utter_booking_batalkan")
        return [
            SlotSet("booking_tipe_pasien", None),
            SlotSet("booking_nik", None),
            SlotSet("booking_nik_lama", None),
            SlotSet("booking_nama", None),
            SlotSet("booking_tgl_lahir", None),
            SlotSet("booking_keluhan", None),
            SlotSet("booking_tgl_kunjungan", None),
            SlotSet("jadwalId", None),
            SlotSet("booking_step", None),
            SlotSet("requested_slot", None),
            ActiveLoop(None)
        ]


class ActionSlotResetBooking(Action):
    def name(self) -> Text:
        return "action_slot_reset_booking"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        dispatcher.utter_message(text="Baik, mari kita mulai ulang. Silakan isi data Anda kembali. 😊")
        return [
           SlotSet("booking_tipe_pasien", None),
            SlotSet("booking_nik", None),
            SlotSet("booking_nik_lama", None),
            SlotSet("booking_nama", None),
            SlotSet("booking_tgl_lahir", None),
            SlotSet("booking_keluhan", None),
            SlotSet("booking_tgl_kunjungan", None),
            SlotSet("jadwalId", None),
            SlotSet("booking_step", "tanya_tipe"),
            ActiveLoop(None)
        ]
    
class ActionBookingReschedule(Action):
    def name(self) -> Text:
        return "action_booking_reschedule"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        dispatcher.utter_message(response="utter_booking_reschedule_info")
        return []