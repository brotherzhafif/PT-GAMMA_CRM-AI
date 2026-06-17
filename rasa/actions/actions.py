"""
Rasa Custom Actions — SmartClinic API Integration
==================================================
Handles:
  - Fetch Doctor Schedule (Fixed with Day Filtering)
  - Fetch Queue Status (Fixed with Date Params & Swagger Schema)
  - Booking Flow (Pasien Baru & Lama Fixed)
"""

# Last Change   :   07 Juni 2026
# ======================================================

import os
import re
import requests
from datetime import datetime, timedelta
from typing import Any, Text, Dict, List, Optional

from rasa_sdk import Action, Tracker, FormValidationAction
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet, ActiveLoop, FollowupAction, ConversationPaused


# URL Base API FastAPI 
API_BASE_URL = os.getenv("SMARTCLINIC_API_URL", "https://ai-crm.brotherzhafif.my.id")

# ------------------------------------------------------
#  CORE HELPERS 
# ------------------------------------------------------

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
        print(f"[API Error] POST {endpoint} status: {resp.status_code}")
        print(f"[API Error] Response body: {resp.text}")
        return None
    except Exception as e:
        print(f"[API Exception] POST {endpoint}: {e}")
        return None

def api_delete(endpoint: str) -> bool:
    """Melakukan request HTTP DELETE. Returns True on success."""
    url = f"{API_BASE_URL}{endpoint}"
    try:
        resp = requests.delete(url, timeout=12)
        if resp.status_code in (200, 204):
            return True
        print(f"[API Error] DELETE {endpoint} status: {resp.status_code}")
        return False
    except Exception as e:
        print(f"[API Exception] DELETE {endpoint}: {e}")
        return False

def get_patient_by_phone(phone_number: str) -> dict:
    """Mencari data pasien terdaftar menggunakan endpoint /api/patients/by-phone."""
    result = api_get("/api/patients/by-phone", params={"phone": phone_number})
    if not result:
        return {}
    
    # If the top level is a list (fallback)
    if isinstance(result, list):
        return result[0] if len(result) > 0 else {}
        
    if isinstance(result, dict):
        # standard API success check
        if result.get("success") is False:
            return {}
            
        # extract 'data'
        inner = result.get("data")
        if inner is None:
            # Maybe the top-level dict is already the patient data
            if "nik" in result or "namaLengkap" in result:
                return result
            return {}
            
        if isinstance(inner, dict):
            # double nesting check: {"success": true, "data": {"data": [...]}} or {"success": true, "data": {"data": {...}}}
            if "data" in inner:
                deep_inner = inner["data"]
                if isinstance(deep_inner, list):
                    return deep_inner[0] if len(deep_inner) > 0 else {}
                elif isinstance(deep_inner, dict):
                    return deep_inner
            # single nesting: {"success": true, "data": {...}}
            return inner
        elif isinstance(inner, list):
            # list nesting: {"success": true, "data": [...]}
            return inner[0] if len(inner) > 0 else {}
            
    return {}

# ------------------------------------------------------
# FORMAT dan VALIDASI TANGGAL 
#------------------------------------------------------

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

    # format DD/MM/YYYY atau DD-MM-YYYY
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
            
    # format ISO YYYY-MM-DD 
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

# ------------------------------------------------------
# JADWAL dan ANTREAN actions
# ------------------------------------------------------

#Action untuk mengambil jadwal dokter 
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

        # Mapping integer hari ke nama hari (1=Senin ... 7=Minggu)
        HARI_MAP = {1: "Senin", 2: "Selasa", 3: "Rabu", 4: "Kamis", 5: "Jumat", 6: "Sabtu", 7: "Minggu"}
        HARI_STR_TO_INT = {v.lower(): k for k, v in HARI_MAP.items()}

        # Parse data response API 
        schedules = result.get("data", []) if isinstance(result, dict) else result

        if not schedules:
            dispatcher.utter_message(text="Saat ini belum ada jadwal dokter yang tersedia di sistem RME. 🙏")
            return []

        # Convert target_day (string) ke integer lalu bandingkan dengan field "hari"
        if target_day:
            target_day_int = HARI_STR_TO_INT.get(target_day)
            filtered_schedules = [
                s for s in schedules
                if target_day_int is not None and int(s.get("hari", 0)) == target_day_int
            ]
        else:
            filtered_schedules = list(schedules)

        if not filtered_schedules and target_day:
            dispatcher.utter_message(text=f"Mohon maaf, tampaknya belum ada jadwal dokter yang tersedia khusus untuk hari *{target_day.title()}*. 🙏")
            return []

        # Sort ascending berdasarkan integer hari (Senin → Minggu)
        filtered_schedules.sort(key=lambda s: int(s.get("hari", 9)))

        # Batasi 6 entri jika tidak ada filter hari (sebelum grouping)
        source = filtered_schedules if target_day else filtered_schedules[:10]

        # Grouping dokter + spesialis + hari yang sama → gabungkan jam ke dalam satu entri
        grouped = {}
        for sched in source:
            dokter_name = sched.get("dokter_nama") or sched.get("nama_dokter") or sched.get("dokter", {}).get("namaLengkap", "Dokter")
            spesialis   = sched.get("spesialis") or sched.get("dokter", {}).get("spesialis", "Umum")
            hari_int    = int(sched.get("hari", 0))
            jam         = sched.get("jam") or f"{sched.get('jamMulai', '??')} - {sched.get('jamSelesai', '??')}"
            key = (hari_int, dokter_name, spesialis)
            if key not in grouped:
                grouped[key] = {
                    "dokter":    dokter_name,
                    "spesialis": spesialis,
                    "hari":      HARI_MAP.get(hari_int, str(hari_int)),
                    "jam":       [jam],
                }
            else:
                if jam not in grouped[key]["jam"]:
                    grouped[key]["jam"].append(jam)

        msg = f"📅 *Jadwal Dokter Klinik SmartClinic {'(' + target_day.title() + ')' if target_day else ''}*\n\n"

        for i, entry in enumerate(grouped.values(), 1):
            jam_display = "\n            ".join(entry["jam"])
            msg += f"{i}. 🩺 *{entry['dokter']}*\n"
            msg += f"   📆 Hari      : {entry['hari']}\n"
            msg += f"   🚑 Poliklinik: {entry['spesialis']}\n"
            msg += f"   🕐 Jam       : {jam_display}\n\n"

        msg += "Apakah Anda ingin membuat janji temu dengan salah satu dokter? 😊"
        dispatcher.utter_message(text=msg)
        return []

# Action untuk ambil data antrian hari ini, dengan filter tanggal & grouping per dokter
class ActionFetchQueue(Action):
    def name(self) -> Text:
        return "action_fetch_queue"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        today = datetime.now().strftime("%Y-%m-%d")
        result = api_get("/api/appointment", params={"tanggal": today})

        if result is None or not result.get("success"):
            dispatcher.utter_message(
                text="Mohon maaf, saya tidak bisa mengakses data antrian saat ini. Silakan coba beberapa saat lagi. 🙏"
            )
            return []

        data = result.get("data", {})
        queue_list = data.get("data", [])
        total = data.get("total", 0)
        menunggu = data.get("menunggu", 0)
        hadir = data.get("hadir", 0)

        if not queue_list:
            dispatcher.utter_message(
                text=f"📋 Tidak ada antrian untuk hari ini ({format_tgl_indonesia(today)}). 🙏"
            )
            return []

        msg = (
            f"🔢 *Status Antrian Hari Ini*\n"
            f"_{format_tgl_indonesia(today)}_\n\n"
            f"📊 Total: *{total}* | ⏳ Menunggu: *{menunggu}* | ✅ Hadir: *{hadir}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        )

        # Kelompokkan antrian per dokter
        grouped_queue = {}
        for q in queue_list:
            jadwal = q.get("jadwal", {})
            dokter = jadwal.get("dokter", {})
            nama_dokter = dokter.get("namaLengkap", "Dokter")
            spesialis   = dokter.get("spesialis", "Umum")
            jam_mulai   = jadwal.get("jamMulai", "")
            jam_selesai = jadwal.get("jamSelesai", "")
            key = (nama_dokter, spesialis, jam_mulai, jam_selesai)
            if key not in grouped_queue:
                grouped_queue[key] = {
                    "dokter":      nama_dokter,
                    "spesialis":   spesialis,
                    "jam_mulai":   jam_mulai,
                    "jam_selesai": jam_selesai,
                    "total":       0,
                    "menunggu":    0,
                    "hadir":       0,
                }
            grouped_queue[key]["total"] += 1
            status = q.get("status", "MENUNGGU")
            if status == "MENUNGGU":
                grouped_queue[key]["menunggu"] += 1
            elif status in ("HADIR", "DIPANGGIL", "DIPERIKSA"):
                grouped_queue[key]["hadir"] += 1

        for grp in grouped_queue.values():
            msg += (
                f"🩺 *{grp['dokter']}* ({grp['spesialis']})\n"
                f"🕐 {grp['jam_mulai']} – {grp['jam_selesai']}\n"
                f"📊 Total: *{grp['total']}* | ⏳ Menunggu: *{grp['menunggu']}* | ✅ Hadir: *{grp['hadir']}*\n\n"
            )

        msg += "Apakah ada yang bisa saya bantu lagi? 😊"
        dispatcher.utter_message(text=msg)
        return []

# ------------------------------------------------------
# Alur Booking dan Actionnya
# ------------------------------------------------------

class ActionStartBooking(Action):
    def name(self) -> Text:
        return "action_start_booking"

    def run(self, dispatcher, tracker, domain):
        sender_id = tracker.sender_id
        patient_data = get_patient_by_phone(sender_id)
        nik = patient_data.get("nik")
        masked_nik = "Tidak Terdeteksi"
        if nik:
            nik_str = str(nik).strip()
            if len(nik_str) >= 12:
                masked_nik = f"{nik_str[:4]}********{nik_str[-4:]}"
            elif len(nik_str) > 4:
                masked_nik = f"{'*' * (len(nik_str) - 4)}{nik_str[-4:]}"
            else:
                masked_nik = nik_str

        dispatcher.utter_message(response="utter_tanya_bpjs")
        return [
            SlotSet("booking_nama", None), SlotSet("booking_nik", None),
            SlotSet("booking_tgl_lahir", None), SlotSet("booking_keluhan", None),
            SlotSet("booking_poli", None), SlotSet("booking_tgl_kunjungan", None),
            SlotSet("booking_jam_praktik", None), SlotSet("booking_is_bpjs", None),
            SlotSet("booking_step", "tanya_bpjs"), SlotSet("booking_untuk_siapa", None)
        ]

class ActionHandleBpjs(Action):
    def name(self) -> Text:
        return "action_handle_bpjs"

    def run(self, dispatcher, tracker, domain):
        intent = tracker.latest_message.get("intent", {}).get("name")

        if intent == "booking_pengguna_bpjs":
            dispatcher.utter_message(response="utter_bpjs_redirect_jkn")
            return [
                SlotSet("booking_is_bpjs", "true"),
                SlotSet("booking_step", None),
            ]

        # Non-BPJS → tanya untuk siapa
        sender_id = tracker.sender_id
        patient_data = get_patient_by_phone(sender_id)
        nik = patient_data.get("nik", "")
        nik_str = str(nik).strip() if nik else ""
        if len(nik_str) >= 12:
            masked_nik = f"{nik_str[:4]}********{nik_str[-4:]}"
        elif len(nik_str) > 4:
            masked_nik = f"{'*' * (len(nik_str) - 4)}{nik_str[-4:]}"
        else:
            masked_nik = nik_str or "Tidak Terdeteksi"

        dispatcher.utter_message(response="utter_ask_booking_untuk_siapa", nik=masked_nik)
        return [
            SlotSet("booking_is_bpjs", "false"),
            SlotSet("booking_step", "tanya_untuk_siapa"),
        ]

class ActionHandleUntukSiapa(Action):
    def name(self) -> Text:
        return "action_handle_untuk_siapa"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        intent = tracker.latest_message.get("intent", {}).get("name")
        
        # Untuk diri sendiri
        if intent == "intent_diri_sendiri":
            sender_id = tracker.sender_id
            patient_data = get_patient_by_phone(sender_id)
            nama = patient_data.get("nama") or patient_data.get("namaLengkap", "")
            nik = patient_data.get("nik", "")
            dob = patient_data.get("date_of_birth") or patient_data.get("tanggalLahir", "")
            if isinstance(dob, str) and "T" in dob:
                dob = dob.split("T")[0]
            
            dispatcher.utter_message(response="utter_booking_intro_baru")
            return [
                SlotSet("booking_nama", nama if nama else None),
                SlotSet("booking_nik", nik if nik else None),
                SlotSet("booking_tgl_lahir", dob if dob else None),
                SlotSet("booking_step", "form_baru"),
                ActiveLoop("booking_form_baru"), 
                FollowupAction("booking_form_baru")
            ]
        
        # Untuk orang lain (Handoff ke Admin)
        else:
            sender_id = tracker.sender_id
            dispatcher.utter_message(text=(
                "Halo Bapak/Ibu 😊\n\n"
                "Mohon lengkapi data berikut untuk pendaftaran pasien:\n\n"
                "Nama Lengkap:\n"
                "NIK:\n"
                "Tanggal Lahir (DD/MM/YYYY):\n"
                "Keluhan:\n"
                "Poliklinik:\n"
                "Tanggal Kunjungan:\n\n"
                "Terima kasih 🙏"
            ))
            
            
            api_post(f"/api/handoff/{sender_id}", {})
            
            # Return list dengan ConversationPaused dan reset full state pendaftaran
            return [
                ActiveLoop(None),
                ConversationPaused(),             
                SlotSet("booking_step", "selesai"), 
                SlotSet("konteks_percakapan", None),
                SlotSet("booking_nik", None),
                SlotSet("booking_nama", None),
                SlotSet("booking_tgl_lahir", None),
                SlotSet("booking_keluhan", None),
                SlotSet("booking_tgl_kunjungan", None),
                SlotSet("jadwalId", None)
            ]

# ------------------------------------------------------
#  Fungsi Validator Booking
# ------------------------------------------------------

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
    
    def validate_booking_keluhan(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> Dict[Text, Any]:
        
        keluhan = str(slot_value).strip()
        if len(keluhan) < 3:
            dispatcher.utter_message(text="⚠️ Keluhan terlalu singkat. Mohon ceritakan sedikit lebih detail.")
            return {"booking_keluhan": None}
        
        # Fetch poli dari API dan tampilkan daftar
        result = api_get("/api/schedules")
        if isinstance(result, list):
            schedules = result
        elif isinstance(result, dict):
            schedules = result.get("data", [])
        else:
            schedules = []

        # Extract poli unik
        poli_list = []
        seen = set()
        for s in schedules:
            poli = s.get("spesialis") or s.get("dokter", {}).get("spesialis", "")
            if poli and poli not in seen and s.get("isAktif", True) is True:
                seen.add(poli)
                poli_list.append(poli)

        if not poli_list:
            dispatcher.utter_message(text=(
                "⚠️ Maaf, saat ini tidak ada poliklinik yang tersedia. "
                "Silakan ketik *admin* untuk bantuan langsung. 🙏"
            ))
            return {"booking_keluhan": keluhan, "booking_poli": None}

        daftar = "\n".join([f"{i+1}️⃣ {p}" for i, p in enumerate(poli_list)])
        dispatcher.utter_message(text=(
            f"🏥 *Pilih Poliklinik*\n\n"
            f"Berikut poliklinik yang tersedia:\n{daftar}\n\n"
            f"Balas dengan nomor atau nama poliklinik yang Anda tuju."
        ))
        return {"booking_keluhan": keluhan}

    def validate_booking_poli(
        self,
        slot_value: Any,
        dispatcher: CollectingDispatcher,
        tracker: Tracker,
        domain: Dict[Text, Any]
    ) -> Dict[Text, Any]:
        
        input_user = str(slot_value).strip()

        # Fetch schedules
        result = api_get("/api/schedules")
        if isinstance(result, list):
            schedules = result
        elif isinstance(result, dict):
            schedules = result.get("data", [])
        else:
            schedules = []

        # Extract poli unik dan jadwal per poli
        poli_list = []
        seen = set()
        for s in schedules:
            poli = s.get("spesialis") or s.get("dokter", {}).get("spesialis", "")
            if poli and poli not in seen and s.get("isAktif", True) is True:
                seen.add(poli)
                poli_list.append(poli)

        if not poli_list:
            dispatcher.utter_message(text="⚠️ Maaf, tidak ada poliklinik tersedia saat ini. Ketik *admin* untuk bantuan. 🙏")
            return {"booking_poli": None}

        # Cocokkan nomor wa atau nama
        poli_dipilih = None
        if input_user.isdigit():
            idx = int(input_user) - 1
            if 0 <= idx < len(poli_list):
                poli_dipilih = poli_list[idx]
        else:
            for p in poli_list:
                if input_user.lower() in p.lower() or p.lower() in input_user.lower():
                    poli_dipilih = p
                    break

        if not poli_dipilih:
            daftar = "\n".join([f"{i+1}️⃣ {p}" for i, p in enumerate(poli_list)])
            dispatcher.utter_message(text=(
                f"⚠️ Poliklinik tidak dikenali. Silakan pilih dari daftar berikut:\n\n"
                f"{daftar}\n\n"
                f"Balas dengan nomor atau nama poliklinik yang Anda tuju."
            ))
            return {"booking_poli": None}

        # Ambil jadwal hari untuk poli yang dipilih
        HARI_MAP = {1: "Senin", 2: "Selasa", 3: "Rabu", 4: "Kamis", 5: "Jumat", 6: "Sabtu", 7: "Minggu"}
        jadwal_poli = {}
        for s in schedules:
            poli = s.get("spesialis") or s.get("dokter", {}).get("spesialis", "")
            if poli != poli_dipilih or s.get("isAktif", True) is not True:
                continue
            hari_int = int(s.get("hari", 0))
            hari_nama = HARI_MAP.get(hari_int, str(hari_int))
            jam_mulai = s.get("jamMulai", "??")
            jam_selesai = s.get("jamSelesai", "??")
            jam = f"{jam_mulai} - {jam_selesai}"
            if hari_nama not in jadwal_poli:
                jadwal_poli[hari_nama] = jam

        if not jadwal_poli:
            dispatcher.utter_message(text=(
                f"⚠️ Maaf, saat ini belum ada jadwal aktif untuk poliklinik *{poli_dipilih}*.\n"
                f"Silakan pilih poliklinik lain atau ketik *admin* untuk bantuan langsung. 🙏"
            ))
            return {"booking_poli": None}

        jadwal_display = "\n".join([f"📆 {hari} ({jam})" for hari, jam in jadwal_poli.items()])
        dispatcher.utter_message(text=(
            f"✅ Poliklinik dipilih: *{poli_dipilih}*\n\n"
            f"📅 Dokter {poli_dipilih} praktek setiap:\n"
            f"{jadwal_display}\n\n"
            
        ))
        return {"booking_poli": poli_dipilih}


    def validate_booking_tgl_kunjungan(self, slot_value: Any, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> Dict[Text, Any]:
        parsed = parse_tanggal_kunjungan(str(slot_value))
        if not parsed:
            dispatcher.utter_message(text=(
                "⚠️ Tanggal kunjungan tidak valid. Gunakan format *DD/MM/YYYY*\n_(Contoh: 25/05/2026)_\n\n"
                "📅 *Rencana Tanggal Kunjungan*:\nKapan Anda berencana datang ke klinik?"
            ))
            return {"booking_tgl_kunjungan": None}

        booking_poli = tracker.get_slot("booking_poli") or ""

        try:
            dt = datetime.strptime(parsed, "%Y-%m-%d")
            hari_kunjungan = dt.isoweekday()
            tgl_display = format_tgl_indonesia(parsed)

            result = api_get("/api/schedules")
            if isinstance(result, list):
                schedules = result
            elif isinstance(result, dict):
                schedules = result.get("data", result.get("schedules", []))
            else:
                schedules = []

            jadwal_cocok = None
            for sched in schedules:
                poli_sched = sched.get("spesialis") or sched.get("dokter", {}).get("spesialis", "")
                hari_sched = sched.get("hari")
                if hari_sched is not None:
                    hari_sched = int(hari_sched)
                is_aktif = sched.get("isAktif", True)
                tanggal_libur = sched.get("tanggalLibur", [])
                if (poli_sched == booking_poli
                        and hari_sched == hari_kunjungan
                        and is_aktif is True
                        and parsed not in tanggal_libur):
                    jadwal_cocok = sched
                    break

            jam_sudah_lewat = False
            jam_praktik_lewat_display = ""
            if jadwal_cocok:
                jadwal_id = str(jadwal_cocok.get("id"))
                jam_mulai = jadwal_cocok.get("jamMulai", "")
                jam_selesai = jadwal_cocok.get("jamSelesai", "")
                jam_praktik = f"{jam_mulai} - {jam_selesai}" if jam_mulai and jam_selesai else "-"

                # Jika tanggal kunjungan adalah hari ini, cek apakah jam praktik sudah lewat
                today_str = datetime.now().strftime("%Y-%m-%d")
                if parsed == today_str and jam_selesai:
                    try:
                        jam_selesai_dt = datetime.strptime(jam_selesai, "%H:%M").time()
                        now_time = datetime.now().time()
                        if now_time > jam_selesai_dt:
                            jadwal_cocok = None
                            jam_sudah_lewat = True
                            jam_praktik_lewat_display = jam_praktik
                    except Exception:
                        pass

            if jadwal_cocok:
                print(f"[DEBUG Form] jadwalId={jadwal_id}, poli={booking_poli}, hari={hari_kunjungan}")
                return {
                    "booking_tgl_kunjungan": parsed,
                    "jadwalId": jadwal_id,
                    "booking_jam_praktik": jam_praktik
                }

            HARI_MAP = {1: "Senin", 2: "Selasa", 3: "Rabu", 4: "Kamis", 5: "Jumat", 6: "Sabtu", 7: "Minggu"}
            hari_tersedia = {}
            for sched in schedules:
                poli_sched = sched.get("spesialis") or sched.get("dokter", {}).get("spesialis", "")
                if poli_sched != booking_poli or sched.get("isAktif", True) is not True:
                    continue
                hari_int = int(sched.get("hari", 0))
                jam_mulai = sched.get("jamMulai", "")
                jam_selesai = sched.get("jamSelesai", "")
                if hari_int not in hari_tersedia:
                    hari_tersedia[hari_int] = f"{jam_mulai} - {jam_selesai}"

            if not hari_tersedia:
                dispatcher.utter_message(text=(
                    f"⚠️ Maaf, tidak ada jadwal aktif untuk poliklinik *{booking_poli}*.\n"
                    f"Silakan ketik *admin* untuk bantuan langsung. 🙏"
                ))
                return {"booking_tgl_kunjungan": None}

            rekomendasi = []
            for hari_int, jam in sorted(hari_tersedia.items()):
                days_ahead = (hari_int - dt.isoweekday()) % 7
                if days_ahead == 0:
                    days_ahead = 7
                tgl_rekomendasi = (dt + timedelta(days=days_ahead)).strftime("%d/%m/%Y")
                hari_nama = HARI_MAP.get(hari_int, str(hari_int))
                rekomendasi.append(f"📆 {hari_nama} — terdekat: *{tgl_rekomendasi}*")

            hari_kunjungan_nama = HARI_MAP.get(hari_kunjungan, str(hari_kunjungan))
            rekomendasi_display = "\n".join(rekomendasi)

            if jam_sudah_lewat:
                dispatcher.utter_message(text=(
                    f"⚠️ Maaf, jam praktik dokter *{booking_poli}* hari ini "
                    f"({jam_praktik_lewat_display}) sudah berakhir.\n\n"
                    f"Silakan pilih dari jadwal yang tersedia:\n{rekomendasi_display}"
                ))
            else:
                dispatcher.utter_message(text=(
                    f"⚠️ Maaf, tidak ada dokter *{booking_poli}* yang praktek "
                    f"pada tanggal {tgl_display}.\n\n"
                    f"Silakan pilih dari jadwal yang tersedia:\n{rekomendasi_display}"
                ))
            return {"booking_tgl_kunjungan": None}

        except Exception as e:
            print(f"[Exception validate_tgl_kunjungan]: {e}")
            return {"booking_tgl_kunjungan": parsed}

# ------------------------------------------------------
#  Action Review & Confirm Booking
# ------------------------------------------------------
class ActionBookingFormBaruSubmit(Action):
    def name(self) -> Text:
        return "action_booking_form_baru_submit"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        # Form selesai diisi → arahkan ke review
        return [
            SlotSet("booking_step", "review"),
            FollowupAction("action_booking_review")
        ]


class ActionBookingReview(Action):
    def name(self) -> Text:
        return "action_booking_review"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        nama = tracker.get_slot("booking_nama") or "-"
        nik = tracker.get_slot("booking_nik") or "-"
        tgl_lahir = tracker.get_slot("booking_tgl_lahir") or "-"
        if isinstance(tgl_lahir, str) and "T" in tgl_lahir:
            tgl_lahir = tgl_lahir.split("T")[0]
        keluhan = tracker.get_slot("booking_keluhan") or "-"
        poli = tracker.get_slot("booking_poli") or "-"
        tgl_kunjungan = tracker.get_slot("booking_tgl_kunjungan") or "-"
        jam_praktik = tracker.get_slot("booking_jam_praktik") or "-"

        tgl_display = format_tgl_indonesia(tgl_kunjungan)
        nik_display = f"****-****-****-{nik[-4:]}" if len(nik) == 16 else nik

        msg = (
            "📋 *Ringkasan Data Pendaftaran*\n\n"
            f"👤 Nama          : *{nama}*\n"
            f"🪪 NIK            : `{nik_display}`\n"
            f"🎂 Tgl Lahir    : {tgl_lahir}\n"
            f"🩺 Keluhan      : {keluhan}\n"
            f"🏥 Poliklinik   : *{poli}*\n"
            f"📅 Kunjungan  : {tgl_display}\n"
            f"🕐 Jam Praktik : {jam_praktik}\n\n"
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
        poli = tracker.get_slot("booking_poli") or ""
        jam_praktik_slot = tracker.get_slot("booking_jam_praktik") or "-"
        no_hp = tracker.sender_id
        reschedule_id = tracker.get_slot("reschedule_booking_id")

        if reschedule_id:
            dispatcher.utter_message(text="⏳ Sedang memproses reschedule janji temu Anda, mohon tunggu sebentar...")
        else:
            dispatcher.utter_message(text="⏳ Sedang memproses janji temu Anda, mohon tunggu sebentar...")

        # --- Reschedule: Delete old booking first ---
        if reschedule_id:
            delete_ok = api_delete(f"/api/appointment/appointments/{reschedule_id}")
            if not delete_ok:
                dispatcher.utter_message(text=(
                    "⚠️ Maaf, gagal membatalkan janji temu lama Anda. "
                    "Jadwal lama tetap aktif.\n\n"
                    "Silakan ketik *admin* untuk bantuan langsung. 🙏"
                ))
                return [
                    SlotSet("reschedule_booking_id", None),
                    SlotSet("booking_step", "selesai"),
                ]
            print(f"[Reschedule] Old booking {reschedule_id} deleted successfully")

        # Gunakan jadwalId dari slot (sudah di-set saat validasi tgl_kunjungan)
        jadwal_id = tracker.get_slot("jadwalId")

        # Fallback: auto-assign jadwalId filter by poli + hari jika slot kosong
        if not jadwal_id:
            try:
                dt = datetime.strptime(tgl_kunjungan, "%Y-%m-%d")
                hari_kunjungan = dt.isoweekday()

                schedules_result = api_get("/api/schedules")
                if schedules_result:
                    if isinstance(schedules_result, list):
                        jadwal_list = schedules_result
                    else:
                        jadwal_list = schedules_result.get("data", [])

                    tersedia = [
                        j for j in jadwal_list
                        if (j.get("hari") is not None and int(j.get("hari")) == hari_kunjungan)
                        and (j.get("spesialis") or j.get("dokter", {}).get("spesialis", "")) == poli
                        and j.get("isAktif", True) is True
                        and tgl_kunjungan not in j.get("tanggalLibur", [])
                    ]
                    if tersedia:
                        pagi = [j for j in tersedia if j.get("sesi") == "PAGI"]
                        jadwal = pagi[0] if pagi else tersedia[0]
                        jadwal_id = jadwal.get("id")
                        jam_m = jadwal.get("jamMulai", "")
                        jam_s = jadwal.get("jamSelesai", "")
                        if jam_m and jam_s:
                            jam_praktik_slot = f"{jam_m} - {jam_s}"
                        print(f"[Booking] Fallback jadwalId={jadwal_id} (poli={poli}, hari={hari_kunjungan})")
            except Exception as e:
                print(f"[Booking] Gagal fallback jadwal: {e}")

        if not jadwal_id:
            # ponytail: if reschedule already deleted old booking but no jadwal found, trigger handoff
            if reschedule_id:
                dispatcher.utter_message(text=(
                    "⚠️ Janji temu lama sudah dibatalkan, tapi gagal membuat yang baru.\n"
                    "Admin akan segera menghubungi Anda untuk membantu. 🙏"
                ))
                api_post(f"/api/handoff/{no_hp}", {})
                return [
                    SlotSet("reschedule_booking_id", None),
                    SlotSet("booking_step", "selesai"),
                ]
            dispatcher.utter_message(text=(
                "⚠️ Maaf, tidak ada jadwal dokter yang tersedia pada tanggal tersebut.\n\n"
                "Silakan pilih hari lain atau ketik *admin* untuk bantuan langsung. 🙏"
            ))
            return [
                SlotSet("booking_tgl_kunjungan", None),
                SlotSet("booking_step", "review"),
            ]

        payload = {
            "phone_number": str(no_hp),
            "jadwalId": str(jadwal_id),
            "tanggalKunjungan": str(tgl_kunjungan),
            "catatan": str(keluhan),
            "jenisKunjunganBpjs": "NORMAL",
            "noRujukanFktp": ""
        }

        print(f"[DEBUG] Payload Booking: {payload}")
        result = api_post("/api/appointment/appointments", payload)
        print(f"[DEBUG] Respon API: {result}")

        if result is not None:
            nomor_antrian = "Akan diberikan di klinik"
            jam_praktik = jam_praktik_slot
            booking_id = f"SC-{datetime.now().strftime('%m%d%H%M')}"
            try:
                antrian_result = api_get(
                    "/api/appointment/appointments/by-phone",
                    params={"phone_number": no_hp}
                )
                if antrian_result and antrian_result.get("success"):
                    antrian_list = antrian_result.get("data", [])
                    milik_pasien = [
                        a for a in antrian_list
                        if a.get("tanggalKunjungan", "").startswith(tgl_kunjungan)
                    ]
                    if milik_pasien:
                        terbaru = max(milik_pasien, key=lambda x: x.get("createdAt", ""))
                        nomor_antrian = terbaru.get("noAntrian", nomor_antrian)
                        booking_id = terbaru.get("id", booking_id)
                        jadwal_info = terbaru.get("jadwal", {})
                        jam_mulai = jadwal_info.get("jamMulai", "")
                        jam_selesai = jadwal_info.get("jamSelesai", "")
                        if jam_mulai and jam_selesai:
                            jam_praktik = f"{jam_mulai} - {jam_selesai}"
            except Exception as e:
                print(f"[Booking] Gagal ambil noAntrian: {e}")

            tgl_display = format_tgl_indonesia(tgl_kunjungan)
            label = "Reschedule Berhasil!" if reschedule_id else "Pendaftaran Berhasil!"
            tiket = (
                f"✅ *{label}* 🎉\n\n"
                "🎫 *Konfirmasi Kunjungan*\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 Nama Pasien            : *{nama}*\n"
                f"🏥 Poliklinik                  : *{poli}*\n"
                f"📅 Waktu                        : {tgl_display}\n"
                f"🔢 No. Antrian             : *{nomor_antrian}*\n"
                f"🕐 Jam Praktik Dokter : {jam_praktik}\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "📍 Jl. Magelang No. 88, Sinduadi, Sleman\n"
                "⚠️ Admin akan memanggil anda *15 menit Sebelum Waktu Pemeriksaan*.\n"
                "Sampai jumpa di klinik! 🙏\n\n"
                "_Ketik *reschedule* untuk ganti jadwal_\n"
            )
            dispatcher.utter_message(text=tiket)
            booking_id_final = str(booking_id)
        else:
            # POST failed
            if reschedule_id:
                # ponytail: critical path — old booking already deleted, new one failed → handoff
                print(f"[Reschedule CRITICAL] POST failed after DELETE of {reschedule_id}")
                dispatcher.utter_message(text=(
                    "⚠️ *Perhatian:* Janji temu lama sudah dibatalkan, "
                    "tetapi gagal membuat jadwal baru.\n\n"
                    "Admin klinik akan segera menghubungi Anda untuk "
                    "membantu menjadwalkan ulang. Mohon tunggu sebentar. 🙏"
                ))
                api_post(f"/api/handoff/{no_hp}", {})
                return [
                    ActiveLoop(None),
                    SlotSet("requested_slot", None),
                    SlotSet("reschedule_booking_id", None),
                    SlotSet("booking_step", "selesai"),
                    SlotSet("booking_nik", None),
                    SlotSet("booking_nama", None),
                    SlotSet("booking_tgl_lahir", None),
                    SlotSet("booking_keluhan", None),
                    SlotSet("booking_poli", None),
                    SlotSet("booking_tgl_kunjungan", None),
                    SlotSet("booking_jam_praktik", None),
                    SlotSet("jadwalId", None),
                    FollowupAction("action_listen"),
                ]

            print(f"[Booking Warning] API gagal, masuk fallback. Result: {result}")
            tgl_display = format_tgl_indonesia(tgl_kunjungan)
            dispatcher.utter_message(text=(
                "⚠️ Maaf, terjadi kendala saat memproses pendaftaran Anda.\n\n"
                "🎫 *Tiket Antrean Bot*\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 Nama Pasien  : *{nama}*\n"
                f"🏥 Poliklinik     : *{poli}*\n"
                f"📅 Waktu           : {tgl_display}\n"
                f"🕐 Jam Praktik  : {jam_praktik_slot}\n"
                f"🔢 No. Antrian   : *S-01 (Konfirmasi Manual)*\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "⚠️ Data Anda sudah tercatat. Admin klinik akan segera menghubungi Anda via WhatsApp untuk konfirmasi. 🙏"
            ))
            api_post(f"/api/handoff/{no_hp}", {})
            booking_id_final = f"FALLBACK-{datetime.now().strftime('%H%M%S')}"

        return [
            ActiveLoop(None),
            SlotSet("requested_slot", None),
            SlotSet("booking_step", "selesai"),
            SlotSet("booking_id_konfirmasi", booking_id_final),
            SlotSet("reschedule_booking_id", None),
            SlotSet("booking_nik", None),
            SlotSet("booking_nama", None),
            SlotSet("booking_tgl_lahir", None),
            SlotSet("booking_keluhan", None),
            SlotSet("booking_poli", None),
            SlotSet("booking_tgl_kunjungan", None),
            SlotSet("booking_jam_praktik", None),
            SlotSet("jadwalId", None),
            FollowupAction("action_listen"),
        ]
 
class ActionBookingCancel(Action):
    def name(self) -> Text:
        return "action_booking_cancel"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        dispatcher.utter_message(response="utter_booking_batalkan")
        return [
            SlotSet("booking_is_bpjs", None),
            SlotSet("booking_nik", None),
            SlotSet("booking_nama", None),
            SlotSet("booking_tgl_lahir", None),
            SlotSet("booking_keluhan", None),
            SlotSet("booking_poli", None),
            SlotSet("booking_tgl_kunjungan", None),
            SlotSet("booking_jam_praktik", None),
            SlotSet("jadwalId", None),
            SlotSet("booking_step", None),
            SlotSet("requested_slot", None),
            ActiveLoop(None)
        ]


class ActionSlotResetBooking(Action):
    def name(self) -> Text:
        return "action_slot_reset_booking"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        dispatcher.utter_message(text="Baik, mari kita mulai ulang. Silakan periksa data Anda kembali. 😊")
        return [
            SlotSet("booking_is_bpjs", None),
            SlotSet("booking_nik", None),
            SlotSet("booking_nama", None),
            SlotSet("booking_tgl_lahir", None),
            SlotSet("booking_keluhan", None),
            SlotSet("booking_poli", None),
            SlotSet("booking_tgl_kunjungan", None),
            SlotSet("booking_jam_praktik", None),
            SlotSet("jadwalId", None),
            SlotSet("booking_step", "tanya_untuk_siapa"),
            ActiveLoop(None),
            FollowupAction("action_start_booking")
        ]
    
class ActionBookingReschedule(Action):
    """Fetch active bookings, pre-fill patient slots, launch booking_form_baru for new date only."""

    def name(self) -> Text:
        return "action_booking_reschedule"

    def run(self, dispatcher: CollectingDispatcher, tracker: Tracker, domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
        no_hp = tracker.sender_id
        today_str = datetime.now().strftime("%Y-%m-%d")

        # Fetch active bookings
        result = api_get("/api/appointment/appointments/by-phone", params={"phone_number": no_hp})
        bookings = []
        if result:
            raw = result.get("data", result) if isinstance(result, dict) else result
            if isinstance(raw, list):
                bookings = [
                    b for b in raw
                    if b.get("tanggalKunjungan", "")[:10] >= today_str
                ]

        # Case 0: no active bookings
        if not bookings:
            dispatcher.utter_message(text=(
                "📋 Tidak ada janji temu aktif yang bisa di-reschedule.\n\n"
                "Ketik *booking* untuk membuat janji temu baru. 😊"
            ))
            return []

        # Case 1: exactly one booking → auto-select
        if len(bookings) == 1:
            return self._prefill_and_start(dispatcher, tracker, bookings[0])

        # Case N: multiple bookings → show list, save to slot for selection
        # ponytail: store list in reschedule_booking_id as JSON for simple selection
        import json
        msg = "📋 *Anda memiliki beberapa janji temu aktif:*\n\n"
        options = []
        for i, b in enumerate(bookings, 1):
            jadwal = b.get("jadwal", {})
            dokter = jadwal.get("dokter", {})
            poli = dokter.get("spesialis", "")
            tgl = format_tgl_indonesia(b.get("tanggalKunjungan", "")[:10])
            msg += f"{i}. 🏥 {poli} — {tgl}\n"
            options.append({"id": b.get("id"), "idx": i})

        msg += "\nBalas dengan *nomor* janji temu yang ingin di-reschedule."
        dispatcher.utter_message(text=msg)

        # ponytail: save options + full bookings as JSON in reschedule_booking_id
        # booking_step=reschedule_select signals webhook to route next message back here
        return [
            SlotSet("reschedule_booking_id", json.dumps({"options": options, "bookings": bookings})),
            SlotSet("booking_step", "reschedule_select"),
        ]

    def _prefill_and_start(self, dispatcher, tracker, booking):
        """Pre-fill patient slots from existing booking, clear date, launch form."""
        booking_id = booking.get("id")
        jadwal = booking.get("jadwal", {})
        dokter = jadwal.get("dokter", {})
        poli = dokter.get("spesialis", "")
        catatan = booking.get("catatan", "")

        # Get patient profile for name/nik/dob
        no_hp = tracker.sender_id
        patient = get_patient_by_phone(no_hp)
        nama = patient.get("nama") or patient.get("namaLengkap", "")
        nik = patient.get("nik", "")
        dob = patient.get("date_of_birth") or patient.get("tanggalLahir", "")
        if isinstance(dob, str) and "T" in dob:
            dob = dob.split("T")[0]

        old_tgl = format_tgl_indonesia(booking.get("tanggalKunjungan", "")[:10])
        dispatcher.utter_message(text=(
            f"🔄 *Reschedule Janji Temu*\n\n"
            f"Jadwal lama: {old_tgl} — {poli}\n\n"
            f"Silakan masukkan *tanggal baru* untuk kunjungan Anda."
        ))

        return [
            SlotSet("reschedule_booking_id", str(booking_id)),
            SlotSet("booking_nama", nama if nama else None),
            SlotSet("booking_nik", nik if nik else None),
            SlotSet("booking_tgl_lahir", dob if dob else None),
            SlotSet("booking_keluhan", catatan if catatan else None),
            SlotSet("booking_poli", poli if poli else None),
            SlotSet("booking_tgl_kunjungan", None),  # force form to ask
            SlotSet("jadwalId", None),  # force form to ask
            SlotSet("booking_jam_praktik", None),
            SlotSet("booking_is_bpjs", "false"),
            SlotSet("booking_step", "form_baru"),
            ActiveLoop("booking_form_baru"),
            FollowupAction("booking_form_baru"),
        ]