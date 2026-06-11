# ======================================================
# SmartClinic CRM AI — appointment_reminder_scheduler.py
# Background worker untuk mengelola reminder appointment H-1 dan H-0.
#
# Last Change   :   11 Jun 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

import json
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException

from App.config import supabase, SMARTCLINIC_BASE_URL
from App.helpers import _require_supabase
from App.wa_gateway import send_text_best_effort

_scheduler_started = False
_scheduler_lock = asyncio.Lock()

REMINDER_TYPE_H_MINUS_1 = "H-1"
REMINDER_TYPE_H_MINUS_0 = "H-0"

REMINDER_STATUS_PENDING = "pending"
REMINDER_STATUS_SENT = "sent"
REMINDER_STATUS_FAILED = "failed"


def _get_today_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _get_tomorrow_date() -> str:
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    return tomorrow.strftime("%Y-%m-%d")


async def _fetch_appointments(date: str) -> list[dict]:
    """Fetch appointments dari endpoint lokal untuk tanggal tertentu.
    
    Args:
        date: Tanggal dalam format YYYY-MM-DD
    
    Returns:
        List appointment data asli dari nested response data.data
    """
    try:
        from App.helpers import proxy_smartclinic
        response = await proxy_smartclinic("GET", SMARTCLINIC_BASE_URL, "/queues", params=[("tanggal", date)])
        
        # Decode bytes ke json dict
        res_json = json.loads(response.body.decode("utf-8"))

        # Mengikuti struktur: res_json -> "data" (dict) -> "data" (list of appointments)
        if isinstance(res_json, dict) and "data" in res_json:
            inner_data = res_json.get("data")
            if isinstance(inner_data, dict) and "data" in inner_data:
                return inner_data.get("data", [])
            elif isinstance(inner_data, list):
                return inner_data
                
        if isinstance(res_json, list):
            return res_json
            
        return []
    except HTTPException as exc:
        print(f"[AppointmentReminder] HTTP error fetching appointments for {date}: {exc.status_code} - {exc.detail}")
        return []
    except Exception as exc:
        print(f"[AppointmentReminder] Gagal mengambil daftar appointment untuk {date}: {exc}")
        return []

async def _fetch_patient_by_rme_id(rme_patient_id: str) -> Optional[dict]:
    """Ambil data patient menggunakan asyncio.to_thread agar tidak memblokir event loop."""
    def _sync_fetch():
        response = supabase.table("patients").select("phone_number, name").eq("rme_patient_id", rme_patient_id).execute()
        return response.data

    try:
        patients = await asyncio.to_thread(_sync_fetch)
        if patients and len(patients) > 0:
            return patients[0]
        return None
    except Exception as exc:
        print(f"[AppointmentReminder] Gagal fetch patient {rme_patient_id}: {exc}")
        return None


async def _reminder_already_exists(phone_number: str, appointment_date: str, reminder_type: str) -> bool:
    """Check apakah reminder sudah ada untuk appointment ini (Non-blocking)."""
    def _sync_check():
        response = (
            supabase.table("appointment_reminders")
            .select("id")
            .eq("phone_number", phone_number)
            .eq("appointment_date", appointment_date)
            .eq("reminder_type", reminder_type)
            .eq("status", REMINDER_STATUS_PENDING)
            .execute()
        )
        return response.data

    try:
        data = await asyncio.to_thread(_sync_check)
        return len(data or []) > 0
    except Exception as exc:
        print(f"[AppointmentReminder] Gagal check existing reminder: {exc}")
        return False


async def _create_reminder(
    phone_number: str,
    appointment_date: str,
    reminder_type: str,
    patient_name: Optional[str] = None,
    appointment_time: Optional[str] = None,
) -> bool:
    """Buat reminder baru di Supabase (Non-blocking)."""
    try:
        time_str = f" jam {appointment_time}" if appointment_time else ""

        if reminder_type == REMINDER_TYPE_H_MINUS_1:
            message = f"Halo {patient_name or 'pasien'}! Ingatkan: Anda memiliki janji temu besok ({appointment_date}{time_str}). Pastikan tiba 15 menit lebih awal. Sampai jumpa!"
        else:
            message = f"Halo {patient_name or 'pasien'}! Ingatkan: Anda memiliki janji temu HARI INI ({appointment_date}{time_str}). Harap datang tepat waktu. Terima kasih!"
        
        def _sync_insert():
            supabase.table("appointment_reminders").insert({
                "phone_number": phone_number,
                "appointment_date": appointment_date,
                "reminder_type": reminder_type,
                "reminder_message": message,
                "status": REMINDER_STATUS_PENDING,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }).execute()

        await asyncio.to_thread(_sync_insert)
        print(f"[AppointmentReminder] Reminder {reminder_type} created untuk {phone_number} on {appointment_date}")
        return True
    except Exception as exc:
        print(f"[AppointmentReminder] Gagal buat reminder: {exc}")
        return False


async def _mark_reminder_status(reminder_id: str, status: str, send_time: bool = False):
    """Helper async untuk mengupdate status reminder."""
    payload = {"status": status}
    if send_time:
        payload["sent_at"] = datetime.now(timezone.utc).isoformat()

    def _sync_update():
        supabase.table("appointment_reminders").update(payload).eq("id", reminder_id).execute()

    try:
        await asyncio.to_thread(_sync_update)
    except Exception as exc:
        print(f"[AppointmentReminder] Gagal update status reminder {reminder_id} ke {status}: {exc}")


async def _send_pending_reminders():
    """Send all pending reminders (scheduled untuk H-0 hari ini) secara Async."""
    try:
        _require_supabase()
        
        def _sync_get_pending():
            return supabase.table("appointment_reminders").select("id, phone_number, reminder_message").eq("status", REMINDER_STATUS_PENDING).eq("reminder_type", REMINDER_TYPE_H_MINUS_0).execute().data

        reminders = await asyncio.to_thread(_sync_get_pending) or []
        
        for reminder in reminders:
            reminder_id = reminder.get("id")
            phone_number = reminder.get("phone_number")
            message = reminder.get("reminder_message")
            
            try:
                # Bungkus pemanggilan WA gateway jika ia sinkronus
                result = await asyncio.to_thread(send_text_best_effort, phone_number, message)
                if result and result.get("status") in ["ok", "success"]:
                    await _mark_reminder_status(reminder_id, REMINDER_STATUS_SENT, send_time=True)
                    print(f"[AppointmentReminder] Reminder sent ke {phone_number}")
                else:
                    await _mark_reminder_status(reminder_id, REMINDER_STATUS_FAILED)
                    print(f"[AppointmentReminder] Gagal send reminder ke {phone_number}")
            except Exception as exc:
                await _mark_reminder_status(reminder_id, REMINDER_STATUS_FAILED)
                print(f"[AppointmentReminder] Error send reminder {reminder_id}: {exc}")
    except Exception as exc:
        print(f"[AppointmentReminder] Error sending reminders: {exc}")


async def _process_reminders():
    """Process reminders untuk H-1 (besok) dan H-0 (hari ini)."""
    try:
        _require_supabase()
        
        today_date = _get_today_date()
        tomorrow_date = _get_tomorrow_date()
        
        # 1. Fetch & Process H-1
        tomorrow_appointments = await _fetch_appointments(tomorrow_date)
        for apt in tomorrow_appointments:
            patient_id = apt.get("pasienId") or apt.get("patient_id")
            if not patient_id:
                continue
            
            patient = await _fetch_patient_by_rme_id(patient_id)
            if not patient:
                continue
            
            phone_number = patient.get("phone_number")
            patient_name = patient.get("name")
            appointment_time = apt.get("jadwal", {}).get("jamMulai")

            if not await _reminder_already_exists(phone_number, tomorrow_date, REMINDER_TYPE_H_MINUS_1):
                await _create_reminder(phone_number, tomorrow_date, REMINDER_TYPE_H_MINUS_1, patient_name, appointment_time)
        
        # 2. Fetch & Process H-0
        today_appointments = await _fetch_appointments(today_date)
        for apt in today_appointments:
            patient_id = apt.get("pasienId") or apt.get("patient_id")
            if not patient_id:
                continue
            
            patient = await _fetch_patient_by_rme_id(patient_id)
            if not patient:
                continue
            
            phone_number = patient.get("phone_number")
            patient_name = patient.get("name")
            appointment_time = apt.get("jadwal", {}).get("jamMulai")

            if not await _reminder_already_exists(phone_number, today_date, REMINDER_TYPE_H_MINUS_0):
                await _create_reminder(phone_number, today_date, REMINDER_TYPE_H_MINUS_0, patient_name, appointment_time)
        
        # 3. Eksekusi pengiriman pesan pending
        await _send_pending_reminders()
        
        print(f"[AppointmentReminder] Process completed for {today_date}")
    except Exception as exc:
        print(f"[AppointmentReminder] Process error: {exc}")


async def _worker_loop():
    """Worker loop yang berjalan setiap 30 menit dengan aman."""
    while True:
        try:
            async with _scheduler_lock:
                await _process_reminders()
        except Exception as exc:
            print(f"[AppointmentReminder] Worker loop error: {exc}")

        await asyncio.sleep(1800) 


def start_appointment_reminder_scheduler():
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True

    asyncio.create_task(_worker_loop())
    print("[AppointmentReminder] Scheduler task started")   