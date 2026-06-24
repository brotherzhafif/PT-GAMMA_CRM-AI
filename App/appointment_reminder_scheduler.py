# ======================================================
# SmartClinic CRM AI — appointment_reminder_scheduler.py
# Background worker untuk mengelola reminder appointment.
# Mengirim 2x reminder: 3 jam (T-3h) dan 1 jam (T-1h) sebelum jadwal.
#
# Last Change   :   25 Jun 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

import json
import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Optional

from fastapi import HTTPException

from App.config import supabase, SMARTCLINIC_BASE_URL
from App.helpers import _require_supabase
from App.wa_gateway import send_text_best_effort

_scheduler_started = False
_scheduler_lock = asyncio.Lock()

# Tipe reminder berbasis jam
REMINDER_TYPE_T_3H = "T-3h"   # 3 jam sebelum appointment
REMINDER_TYPE_T_1H = "T-1h"   # 1 jam sebelum appointment

REMINDER_STATUS_PENDING = "pending"
REMINDER_STATUS_SENT = "sent"
REMINDER_STATUS_FAILED = "failed"

LOCAL_TZ = ZoneInfo("Asia/Jakarta")


def _get_today_date() -> str:
    """Get today's date in YYYY-MM-DD format berdasarkan timezone lokal klinik (WIB)."""
    return datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")


def _parse_appointment_datetime(date_str: str, jam_mulai: str) -> Optional[datetime]:
    """Parse tanggal + jamMulai menjadi datetime aware WIB.

    Args:
        date_str: Tanggal dalam format YYYY-MM-DD
        jam_mulai: Jam mulai dalam format HH:MM atau HH:MM:SS

    Returns:
        datetime aware WIB, atau None jika parse gagal
    """
    if not jam_mulai:
        return None
    try:
        # Normalisasi: ambil hanya HH:MM
        time_part = jam_mulai.strip()[:5]  # "14:30"
        dt_str = f"{date_str} {time_part}"
        naive_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
        return naive_dt.replace(tzinfo=LOCAL_TZ)
    except (ValueError, TypeError):
        return None


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
    """Check apakah reminder sudah ada untuk appointment ini (Non-blocking).

    Cek semua status (pending/sent/failed) — bukan hanya pending.
    Ini mencegah duplikasi row tiap 30 menit saat pengiriman gagal (failed).
    """
    def _sync_check():
        response = (
            supabase.table("appointment_reminders")
            .select("id")
            .eq("phone_number", phone_number)
            .eq("appointment_date", appointment_date)
            .eq("reminder_type", reminder_type)
            # Tidak filter status — cek ANY reminder yang sudah ada
            .execute()
        )
        return response.data

    try:
        data = await asyncio.to_thread(_sync_check)
        return len(data or []) > 0
    except Exception as exc:
        print(f"[AppointmentReminder] Gagal check existing reminder: {exc}")
        return False


async def _create_and_send_reminder(
    phone_number: str,
    appointment_date: str,
    reminder_type: str,
    scheduled_send_at: datetime,
    patient_name: Optional[str] = None,
    appointment_time: Optional[str] = None,
) -> bool:
    """Buat reminder baru di Supabase dan langsung kirim via WhatsApp.

    Args:
        phone_number: Nomor WA pasien
        appointment_date: Tanggal appointment (YYYY-MM-DD)
        reminder_type: REMINDER_TYPE_T_3H atau REMINDER_TYPE_T_1H
        scheduled_send_at: Waktu eksak kapan reminder seharusnya dikirim
        patient_name: Nama pasien (opsional, untuk isi pesan)
        appointment_time: Jam appointment dalam format HH:MM (opsional, untuk isi pesan)
    """
    try:
        name = patient_name or "pasien"
        time_label = f"pukul {appointment_time}" if appointment_time else "sebentar lagi"

        if reminder_type == REMINDER_TYPE_T_3H:
            message = (
                f"Halo {name}! 🔔 Pengingat: Anda memiliki janji temu HARI INI {time_label} "
                f"(sekitar 3 jam lagi). Pastikan tiba 15 menit lebih awal. Sampai jumpa!"
            )
        else:  # T-1h
            message = (
                f"Halo {name}! ⏰ Pengingat: Janji temu Anda HARI INI {time_label} "
                f"sudah semakin dekat (sekitar 1 jam lagi). Harap datang tepat waktu. Terima kasih!"
            )

        scheduled_send_at_iso = scheduled_send_at.isoformat()
        now_iso = datetime.now(timezone.utc).isoformat()

        # Buat row reminder di DB
        reminder_id = None

        def _sync_insert():
            return supabase.table("appointment_reminders").insert({
                "phone_number": phone_number,
                "appointment_date": appointment_date,
                "reminder_type": reminder_type,
                "scheduled_send_at": scheduled_send_at_iso,
                "reminder_message": message,
                "status": REMINDER_STATUS_PENDING,
                "created_at": now_iso,
            }).select("id").execute()

        insert_resp = await asyncio.to_thread(_sync_insert)
        if insert_resp.data:
            reminder_id = insert_resp.data[0].get("id")

        print(f"[AppointmentReminder] Reminder {reminder_type} created untuk {phone_number} ({appointment_date})")

        # Langsung kirim
        result = await asyncio.to_thread(send_text_best_effort, phone_number, message)

        if result and (result.get("queued") is True or result.get("status") in ["ok", "success"]):
            status = REMINDER_STATUS_SENT
            print(f"[AppointmentReminder] Reminder {reminder_type} sukses terkirim ke {phone_number}")
        else:
            status = REMINDER_STATUS_FAILED
            print(f"[AppointmentReminder] Gagal kirim reminder {reminder_type} ke {phone_number}. Response: {result}")

        # Update status di DB
        if reminder_id:
            payload = {"status": status}
            if status == REMINDER_STATUS_SENT:
                payload["sent_at"] = datetime.now(timezone.utc).isoformat()

            def _sync_update():
                supabase.table("appointment_reminders").update(payload).eq("id", reminder_id).execute()
            await asyncio.to_thread(_sync_update)

        return status == REMINDER_STATUS_SENT

    except Exception as exc:
        print(f"[AppointmentReminder] Gagal buat/kirim reminder {reminder_type} ke {phone_number}: {exc}")
        return False


async def _retry_failed_reminders():
    """Coba kirim ulang reminder yang statusnya failed (belum lebih dari 2 jam sejak dibuat)."""
    try:
        _require_supabase()

        def _sync_get_failed():
            return (
                supabase.table("appointment_reminders")
                .select("id, phone_number, reminder_message, created_at")
                .eq("status", REMINDER_STATUS_FAILED)
                .execute()
                .data
            )

        reminders = await asyncio.to_thread(_sync_get_failed) or []
        now = datetime.now(timezone.utc)

        for reminder in reminders:
            # Hanya retry dalam 2 jam sejak gagal pertama
            created_at_str = reminder.get("created_at")
            if created_at_str:
                try:
                    created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                    if (now - created_at).total_seconds() > 7200:  # > 2 jam, skip
                        continue
                except Exception:
                    pass

            reminder_id = reminder.get("id")
            phone_number = reminder.get("phone_number")
            message = reminder.get("reminder_message")

            try:
                result = await asyncio.to_thread(send_text_best_effort, phone_number, message)
                if result and (result.get("queued") is True or result.get("status") in ["ok", "success"]):
                    payload = {"status": REMINDER_STATUS_SENT, "sent_at": now.isoformat()}
                    def _sync_update(rid=reminder_id, p=payload):
                        supabase.table("appointment_reminders").update(p).eq("id", rid).execute()
                    await asyncio.to_thread(_sync_update)
                    print(f"[AppointmentReminder] Retry sukses ke {phone_number}")
            except Exception as exc:
                print(f"[AppointmentReminder] Retry gagal untuk {reminder_id}: {exc}")
    except Exception as exc:
        print(f"[AppointmentReminder] Error retry failed reminders: {exc}")


async def _process_reminders():
    """Process reminder untuk hari ini dengan logika berbasis jam.

    Untuk setiap appointment hari ini yang memiliki jamMulai:
    - Hitung send_at_3h = appointment_time - 3 jam
    - Hitung send_at_1h = appointment_time - 1 jam
    - Jika sekarang >= send_at_Xh dan reminder belum ada → buat & kirim
    """
    try:
        _require_supabase()

        today_date = _get_today_date()
        now = datetime.now(LOCAL_TZ)

        print(f"[AppointmentReminder] Processing reminders untuk {today_date}, jam sekarang: {now.strftime('%H:%M')} WIB")

        appointments = await _fetch_appointments(today_date)

        if not appointments:
            print(f"[AppointmentReminder] Tidak ada appointment untuk {today_date}")
        
        for apt in appointments:
            patient_id = apt.get("pasienId") or apt.get("patient_id")
            if not patient_id:
                continue

            jam_mulai = apt.get("jadwal", {}).get("jamMulai") if isinstance(apt.get("jadwal"), dict) else apt.get("jamMulai")
            if not jam_mulai:
                print(f"[AppointmentReminder] Appointment {patient_id} tidak punya jamMulai, dilewati.")
                continue

            appointment_dt = _parse_appointment_datetime(today_date, jam_mulai)
            if not appointment_dt:
                print(f"[AppointmentReminder] Gagal parse jam '{jam_mulai}' untuk appointment {patient_id}, dilewati.")
                continue

            patient = await _fetch_patient_by_rme_id(patient_id)
            if not patient:
                continue

            phone_number = patient.get("phone_number")
            patient_name = patient.get("name")

            # Window T-3h: kirim saat now >= (appointment - 3 jam)
            send_at_3h = appointment_dt - timedelta(hours=3)
            if now >= send_at_3h and now < appointment_dt:
                if not await _reminder_already_exists(phone_number, today_date, REMINDER_TYPE_T_3H):
                    print(f"[AppointmentReminder] Kirim T-3h ke {phone_number} (apt jam {jam_mulai})")
                    await _create_and_send_reminder(
                        phone_number, today_date, REMINDER_TYPE_T_3H,
                        send_at_3h, patient_name, jam_mulai[:5]
                    )

            # Window T-1h: kirim saat now >= (appointment - 1 jam)
            send_at_1h = appointment_dt - timedelta(hours=1)
            if now >= send_at_1h and now < appointment_dt:
                if not await _reminder_already_exists(phone_number, today_date, REMINDER_TYPE_T_1H):
                    print(f"[AppointmentReminder] Kirim T-1h ke {phone_number} (apt jam {jam_mulai})")
                    await _create_and_send_reminder(
                        phone_number, today_date, REMINDER_TYPE_T_1H,
                        send_at_1h, patient_name, jam_mulai[:5]
                    )

        # Coba kirim ulang yang failed
        await _retry_failed_reminders()

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
    print("[AppointmentReminder] Scheduler task started (T-3h & T-1h mode)")