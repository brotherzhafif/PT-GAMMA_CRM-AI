# ======================================================
# SmartClinic CRM AI — appointment_reminder_scheduler.py
# Background worker untuk mengelola reminder appointment H-1 dan H-0.
#
# Last Change   :   11 Jun 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, Request

from App.config import supabase, SMARTCLINIC_BASE_URL
from App.helpers import _require_supabase, proxy_smartclinic
from App.wa_gateway import send_text_best_effort

_scheduler_started = False
_scheduler_lock = threading.Lock()

# Tipe reminder: H-1 (H minus 1, besok ada appointment), H-0 (hari ini ada appointment)
REMINDER_TYPE_H_MINUS_1 = "H-1"
REMINDER_TYPE_H_MINUS_0 = "H-0"

# Status reminder
REMINDER_STATUS_PENDING = "pending"
REMINDER_STATUS_SENT = "sent"
REMINDER_STATUS_FAILED = "failed"


def _get_today_date() -> str:
    """Get today's date in YYYY-MM-DD format (UTC)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _get_tomorrow_date() -> str:
    """Get tomorrow's date in YYYY-MM-DD format (UTC)."""
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    return tomorrow.strftime("%Y-%m-%d")


async def _fetch_appointments(date: str) -> list[dict]:
    """Fetch appointments dari endpoint lokal untuk tanggal tertentu.
    
    Args:
        date: Tanggal dalam format YYYY-MM-DD
    
    Returns:
        List appointment data dari endpoint lokal
    """
    try:
        # Gunakan proxy_smartclinic untuk memanggil endpoint lokal
        response = await proxy_smartclinic("GET", SMARTCLINIC_BASE_URL, "/queues", params=[("tanggal", date)])
        
        # FastAPI response object, bukan httpx.Response, jadi perlu di-parse
        # response.body adalah bytes, perlu decode lalu json.loads
        data = json.loads(response.body.decode("utf-8"))

        if isinstance(data, dict) and "data" in data:
            return data.get("data", [])
        elif isinstance(data, list):
            return data
        return []
    except HTTPException as exc:
        print(f"[AppointmentReminder] HTTP error fetching appointments for {date}: {exc.status_code} - {exc.detail}")
        return []
    except Exception as exc:
        print(f"[AppointmentReminder] Gagal mengambil daftar appointment untuk {date}: {exc}")
        return []


def _fetch_patient_by_rme_id(rme_patient_id: str) -> Optional[dict]:
    """Ambil data patient dari Supabase berdasarkan rme_patient_id."""
    try:
        response = supabase.table("patients").select("phone_number, name").eq("rme_patient_id", rme_patient_id).execute()
        patients = response.data
        if patients and len(patients) > 0:
            return patients[0]
        return None
    except Exception as exc:
        print(f"[AppointmentReminder] Gagal fetch patient {rme_patient_id}: {exc}")
        return None


def _reminder_already_exists(phone_number: str, appointment_date: str, reminder_type: str) -> bool:
    """Check apakah reminder sudah ada untuk appointment ini."""
    try:
        response = (
            supabase.table("appointment_reminders")
            .select("id")
            .eq("phone_number", phone_number)
            .eq("appointment_date", appointment_date)
            .eq("reminder_type", reminder_type)
            .eq("status", REMINDER_STATUS_PENDING)
            .execute()
        )
        return len(response.data or []) > 0
    except Exception as exc:
        print(f"[AppointmentReminder] Gagal check existing reminder: {exc}")
        return False


def _create_reminder(
    phone_number: str,
    appointment_date: str,
    reminder_type: str,
    patient_name: Optional[str] = None,
    appointment_time: Optional[str] = None,
) -> bool:
    """Buat reminder baru di Supabase."""
    try:
        if appointment_time:
            time_str = f" jam {appointment_time}"
        else:
            time_str = ""

        if reminder_type == REMINDER_TYPE_H_MINUS_1:
            message = f"Halo {patient_name or 'pasien'}! Ingatkan: Anda memiliki janji temu besok ({appointment_date}{time_str}). Pastikan tiba 15 menit lebih awal. Sampai jumpa!"
        else:  # H-0
            message = f"Halo {patient_name or 'pasien'}! Ingatkan: Anda memiliki janji temu HARI INI ({appointment_date}{time_str}). Harap datang tepat waktu. Terima kasih!"
        
        supabase.table("appointment_reminders").insert({
            "phone_number": phone_number,
            "appointment_date": appointment_date,
            "reminder_type": reminder_type,
            "reminder_message": message,
            "status": REMINDER_STATUS_PENDING,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        
        print(f"[AppointmentReminder] Reminder {reminder_type} created untuk {phone_number} on {appointment_date}")
        return True
    except Exception as exc:
        print(f"[AppointmentReminder] Gagal buat reminder: {exc}")
        return False


def _mark_reminder_as_sent(reminder_id: str):
    """Mark reminder as sent."""
    try:
        supabase.table("appointment_reminders").update({
            "status": REMINDER_STATUS_SENT,
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", reminder_id).execute()
    except Exception as exc:
        print(f"[AppointmentReminder] Gagal update reminder {reminder_id}: {exc}")


def _mark_reminder_as_failed(reminder_id: str):
    """Mark reminder as failed."""
    try:
        supabase.table("appointment_reminders").update({
            "status": REMINDER_STATUS_FAILED,
        }).eq("id", reminder_id).execute()
    except Exception as exc:
        print(f"[AppointmentReminder] Gagal update reminder {reminder_id}: {exc}")


def _send_pending_reminders():
    """Send all pending reminders (scheduled untuk H-0 hari ini)."""
    try:
        _require_supabase()
        
        # Query pending reminders dengan reminder_type H-0 (hari ini)
        response = (
            supabase.table("appointment_reminders")
            .select("id, phone_number, reminder_message")
            .eq("status", REMINDER_STATUS_PENDING)
            .eq("reminder_type", REMINDER_TYPE_H_MINUS_0)
            .execute()
        )
        
        reminders = response.data or []
        for reminder in reminders:
            reminder_id = reminder.get("id")
            phone_number = reminder.get("phone_number")
            message = reminder.get("reminder_message")
            
            try:
                result = send_text_best_effort(phone_number, message)
                if result and result.get("status") in ["ok", "success"]:
                    _mark_reminder_as_sent(reminder_id)
                    print(f"[AppointmentReminder] Reminder sent ke {phone_number}")
                else:
                    _mark_reminder_as_failed(reminder_id)
                    print(f"[AppointmentReminder] Gagal send reminder ke {phone_number}")
            except Exception as exc:
                _mark_reminder_as_failed(reminder_id)
                print(f"[AppointmentReminder] Error send reminder {reminder_id}: {exc}")
    except HTTPException:
        pass
    except Exception as exc:
        print(f"[AppointmentReminder] Error sending reminders: {exc}")


async def _process_reminders():
    """Process reminders untuk H-1 (besok) dan H-0 (hari ini)."""
    try:
        _require_supabase()
        
        today_date = _get_today_date()
        tomorrow_date = _get_tomorrow_date()
        
        # Fetch appointments untuk besok (H-1)
        tomorrow_appointments = _fetch_appointments(tomorrow_date)
        for apt in tomorrow_appointments:
            patient_id = apt.get("pasienId") or apt.get("patient_id")
            if not patient_id:
                continue
            
            patient = _fetch_patient_by_rme_id(patient_id)
            if not patient:
                continue
            
            phone_number = patient.get("phone_number")
            patient_name = patient.get("name")
            appointment_time = apt.get("jadwal", {}).get("jamMulai")

            # Check dan buat reminder H-1
            if not _reminder_already_exists(phone_number, tomorrow_date, REMINDER_TYPE_H_MINUS_1):
                _create_reminder(phone_number, tomorrow_date, REMINDER_TYPE_H_MINUS_1, patient_name, appointment_time)
        
        # Fetch appointments untuk hari ini (H-0)
        today_appointments = _fetch_appointments(today_date)
        for apt in today_appointments:
            patient_id = apt.get("pasienId") or apt.get("patient_id")
            if not patient_id:
                continue
            
            patient = _fetch_patient_by_rme_id(patient_id)
            if not patient:
                continue
            
            phone_number = patient.get("phone_number")
            patient_name = patient.get("name")
            appointment_time = apt.get("jadwal", {}).get("jamMulai")

            # Check dan buat reminder H-0
            if not _reminder_already_exists(phone_number, today_date, REMINDER_TYPE_H_MINUS_0):
                _create_reminder(phone_number, today_date, REMINDER_TYPE_H_MINUS_0, patient_name, appointment_time)
        
        # Send semua pending H-0 reminders (appointment hari ini)
        _send_pending_reminders()
        
        print(f"[AppointmentReminder] Process completed for {today_date}")
    except HTTPException:
        pass
    except Exception as exc:
        print(f"[AppointmentReminder] Process error: {exc}")


async def _worker_loop():
    """Worker loop yang berjalan setiap N detik."""
    while True:
        try:
            await _process_reminders()
        except Exception as exc:
            print(f"[AppointmentReminder] Worker loop error: {exc}")
        
        # Check every 30 minutes (1800 detik)
        time.sleep(1800)


def start_appointment_reminder_scheduler():
    """Start appointment reminder scheduler worker thread."""
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_started = True
    
    thread = threading.Thread(target=_worker_loop, name="AppointmentReminderScheduler", daemon=True)
    thread.start()
    print(f"[AppointmentReminder] Worker thread '{thread.name}' started")
