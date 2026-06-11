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
    _send_pending_reminders,
    _process_reminders,
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
                        "total": 5,
                        "reminders": [
                            {
                                "id": "550e8400-e29b-41d4-a716-446655440000",
                                "phone_number": "6281234567890",
                                "appointment_date": "2026-06-15",
                                "reminder_type": "H-1",
                                "reminder_message": "...",
                                "status": "pending",
                                "created_at": "2026-06-14T10:00:00Z",
                                "sent_at": None,
                                "updated_at": "2026-06-14T10:00:00Z",
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
    reminder_type: Optional[str] = Query(None, description="Filter: H-1 atau H-0"),
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
    "/send-pending",
    summary="Kirim semua reminders yang masih pending (H-0)",
    description="Trigger manual untuk mengirim reminder hari ini (H-0). Biasanya dijalankan otomatis scheduler.",
    responses={
        200: {
            "description": "Reminders berhasil dikirim",
            "content": {"application/json": {"example": {"status": "ok", "message": "Reminders sent successfully"}}},
        },
        500: {
            "description": "Gagal mengirim reminders",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
async def send_pending_reminders(request: Request):
    try:
        _require_supabase()
        _send_pending_reminders()
        
        await log_activity(
            category="reminders",
            action="SEND_PENDING_REMINDERS",
            from_actor=request.client.host if request.client else "system",
            message="Manual trigger kirim pending reminders",
        )
        
        return {"status": "ok", "message": "Pending reminders sent successfully"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


def log_activity(*args, **kwargs):
    """Async wrapper untuk log_activity (dijalankan secara sync)."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            return asyncio.create_task(log_activity(*args, **kwargs))
        else:
            return loop.run_until_complete(log_activity(*args, **kwargs))
    except RuntimeError:
        return None


@router.post(
    "/process",
    summary="Trigger manual process reminders",
    description="Trigger manual untuk proses dan cek reminders H-1 (besok) dan H-0 (hari ini). Biasanya dijalankan otomatis scheduler.",
    responses={
        200: {
            "description": "Process berhasil dijalankan",
            "content": {"application/json": {"example": {"status": "ok", "message": "Reminder process completed"}}},
        },
        500: {
            "description": "Gagal jalankan process",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
def process_reminders(request: Request):
    try:
        _require_supabase()
        _process_reminders()
        
        # Try to log activity (safe if fails)
        try:
            import asyncio
            asyncio.create_task(
                log_activity(
                    category="reminders",
                    action="PROCESS_REMINDERS",
                    from_actor=request.client.host if request.client else "system",
                    message="Manual trigger process reminders",
                )
            )
        except:
            pass
        
        return {"status": "ok", "message": "Reminder process completed"}
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
def delete_reminders(
    request: Request,
    phone_number: str = Query(..., description="Nomor WhatsApp pasien"),
    appointment_date: str = Query(..., description="Tanggal appointment (YYYY-MM-DD)"),
):
    try:
        _require_supabase()
        
        supabase.table("appointment_reminders").delete().eq("phone_number", phone_number).eq("appointment_date", appointment_date).execute()
        
        # Try to log activity (safe if fails)
        try:
            import asyncio
            asyncio.create_task(
                log_activity(
                    category="reminders",
                    action="DELETE_REMINDERS",
                    from_actor=request.client.host if request.client else "system",
                    message=f"Reminder dihapus untuk {phone_number} on {appointment_date}",
                    metadata={"phone_number": phone_number, "appointment_date": appointment_date},
                )
            )
        except:
            pass
        
        return {"status": "ok", "message": "Reminders deleted successfully"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
