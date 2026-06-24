# ======================================================
# SmartClinic CRM AI — routers/reminder.py
# Endpoint: /api/reminder
# Manajemen reminder appointment H-1 dan H-0
#
# Last Change   :   11 Jun 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Request

from App.activity_logger import log_activity
from App.config import supabase
from App.helpers import _require_supabase
from App.models import GetAppointmentRemindersResponse, AppointmentReminderStatistics, AppointmentReminderRecord
from App.appointment_reminder_scheduler import (
    _process_reminders,
    REMINDER_TYPE_T_3H,
    REMINDER_TYPE_T_1H,
    REMINDER_STATUS_PENDING,
    REMINDER_STATUS_SENT,
    REMINDER_STATUS_FAILED,
)

router = APIRouter(prefix="/api/reminder", tags=["Reminders"])


@router.get(
    "",
    summary="Ambil daftar reminders",
    description="Ambil semua reminder dengan filter opsional (status, reminder_type, phone_number).",
    responses={
        200: {
            "description": "Daftar reminders berhasil diambil",
            "content": {
                "application/json": {
                    "example": {
                        "status": "ok",
                        "total": 2,
                        "reminders": [
                            {
                                "id": "550e8400-e29b-41d4-a716-446655440000",
                                "phone_number": "6281234567890",
                                "appointment_date": "2026-06-15",
                                "reminder_type": "T-3h",
                                "scheduled_send_at": "2026-06-15T11:00:00+07:00",
                                "reminder_message": "Halo Budi! Pengingat: janji temu hari ini pukul 14:00 (3 jam lagi).",
                                "status": "sent",
                                "created_at": "2026-06-15T08:00:00Z",
                                "sent_at": "2026-06-15T11:00:05Z",
                                "updated_at": "2026-06-15T11:00:05Z",
                            }
                        ],
                    }
                }
            },
        },
        500: {
            "description": "Gagal mengambil reminders",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
def get_reminders(
    status: Optional[str] = Query(None, description="Filter: pending, sent, atau failed"),
    reminder_type: Optional[str] = Query(None, description="Filter: T-3h (3 jam sebelum) atau T-1h (1 jam sebelum)"),
    phone_number: Optional[str] = Query(None, description="Filter: nomor telepon pasien"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    try:
        _require_supabase()
        
        query = supabase.table("appointment_reminders").select("*")
        
        if status:
            query = query.eq("status", status)
        if reminder_type:
            query = query.eq("reminder_type", reminder_type)
        if phone_number:
            query = query.eq("phone_number", phone_number)
        
        response = query.order("created_at", desc=True).limit(limit).offset(offset).execute()
        reminders = response.data or []
        
        return GetAppointmentRemindersResponse(
            status="ok",
            total=len(reminders),
            reminders=[AppointmentReminderRecord(**r) for r in reminders],
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get(
    "/statistics",
    summary="Ambil statistik reminders",
    description="Ambil total reminder berdasarkan status (pending, sent, failed).",
    responses={
        200: {
            "description": "Statistik reminder berhasil diambil",
            "content": {
                "application/json": {
                    "example": {
                        "total_pending": 15,
                        "total_sent": 120,
                        "total_failed": 5,
                        "total_all": 140,
                    }
                }
            },
        },
        500: {
            "description": "Gagal mengambil statistik",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
def get_reminder_statistics():
    try:
        _require_supabase()
        
        pending_response = supabase.table("appointment_reminders").select("id").eq("status", REMINDER_STATUS_PENDING).execute()
        sent_response = supabase.table("appointment_reminders").select("id").eq("status", REMINDER_STATUS_SENT).execute()
        failed_response = supabase.table("appointment_reminders").select("id").eq("status", REMINDER_STATUS_FAILED).execute()
        
        total_pending = len(pending_response.data or [])
        total_sent = len(sent_response.data or [])
        total_failed = len(failed_response.data or [])
        total_all = total_pending + total_sent + total_failed
        
        return AppointmentReminderStatistics(
            total_pending=total_pending,
            total_sent=total_sent,
            total_failed=total_failed,
            total_all=total_all,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@router.post(
    "/trigger",
    summary="Trigger manual proses reminder hari ini (T-3h & T-1h)",
    description="Jalankan manual proses reminder: cek appointment hari ini dan kirim reminder yang sudah waktunya (T-3h dan T-1h).",
    responses={200: {"description": "Proses reminder berhasil dijalankan"}},
)
async def trigger_reminder_process(request: Request):
    try:
        _require_supabase()
        await _process_reminders()

        await log_activity(
            category="reminders",
            action="TRIGGER_REMINDER_PROCESS",
            from_actor=request.client.host if request.client else "system",
            message="Manual trigger proses reminder T-3h & T-1h",
        )
        return {"status": "ok", "message": "Reminder process completed (T-3h & T-1h)"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))



@router.delete(
    "",
    summary="Hapus reminder berdasarkan phone_number dan appointment_date",
    description="Hapus reminder untuk appointment tertentu pasien.",
    responses={
        200: {
            "description": "Reminder berhasil dihapus",
            "content": {"application/json": {"example": {"status": "ok", "message": "Reminder deleted successfully"}}},
        },
        400: {
            "description": "Parameter tidak lengkap",
            "content": {"application/json": {"example": {"detail": "phone_number dan appointment_date harus diisi"}}},
        },
        500: {
            "description": "Gagal menghapus reminder",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
async def delete_reminders(
    request: Request,
    phone_number: str = Query(..., description="Nomor WhatsApp pasien"),
    appointment_date: str = Query(..., description="Tanggal appointment (YYYY-MM-DD)"),
):
    try:
        _require_supabase()
        supabase.table("appointment_reminders").delete()\
            .eq("phone_number", phone_number)\
            .eq("appointment_date", appointment_date)\
            .execute()

        await log_activity(
            category="reminders",
            action="DELETE_REMINDERS",
            from_actor=request.client.host if request.client else "system",
            message=f"Reminder dihapus untuk {phone_number} on {appointment_date}",
            metadata={"phone_number": phone_number, "appointment_date": appointment_date},
        )

        return {"status": "ok", "message": "Reminders deleted successfully"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
