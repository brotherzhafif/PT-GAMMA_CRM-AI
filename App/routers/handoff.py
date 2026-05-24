# ======================================================
# SmartClinic CRM AI — routers/handoff.py
# Endpoint: /api/handoff
#
# Last Change   :   16 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

from typing import List
from fastapi import APIRouter, Body, HTTPException, Path

from App.models import AdminReplyPayload, HandoffSession
from App.helpers import save_to_supabase
from App.handoff_manager import (
    is_in_handoff,
    start_handoff,
    end_handoff,
    update_admin_reply_time,
    get_all_handoff_sessions,
)
from App.queue_manager import fonnte_queue

router = APIRouter(prefix="/api/handoff", tags=["Unified Chat"])


HANDOFF_SESSION_EXAMPLE = {
    "phone_number": "6281234567890",
    "started_at": "2026-05-22T10:00:00Z",
    "last_admin_reply_at": "2026-05-22T10:05:00Z",
    "timeout_at": "2026-05-22T10:15:00Z",
}

HANDOFF_MESSAGE_EXAMPLE = {
    "status": "ok",
    "message": "Handoff untuk 6281234567890 dimulai",
}

HANDOFF_ERROR_EXAMPLE = {"detail": "6281234567890 tidak dalam mode handoff"}


# ======================================================
#
#               HANDOFF ENDPOINTS
#
# ======================================================

@router.get(
    "",
    response_model=List[HandoffSession],
    summary="Ambil semua sesi handoff aktif",
    description="Dipakai dashboard untuk tampilkan daftar pasien yang sedang menunggu admin. Sesi yang sudah timeout otomatis tidak muncul.",
    responses={
        200: {
            "description": "Daftar handoff aktif berhasil diambil",
            "content": {"application/json": {"example": [HANDOFF_SESSION_EXAMPLE]}},
        },
        500: {
            "description": "Gagal mengambil sesi handoff",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
def get_handoff_sessions():
    try:
        return get_all_handoff_sessions()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/{phone_number}",
    summary="Mulai handoff manual oleh admin",
    description="Admin bisa paksa override nomor tertentu ke mode handoff langsung dari dashboard.",
    responses={
        200: {
            "description": "Handoff berhasil dimulai",
            "content": {"application/json": {"example": HANDOFF_MESSAGE_EXAMPLE}},
        },
        500: {
            "description": "Gagal memulai handoff",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
def start_handoff_manual(phone_number: str = Path(..., description="Nomor HP yang akan di-handoff", examples=["6281234567890"])):
    try:
        if is_in_handoff(phone_number):
            return {"status": "ok", "message": f"{phone_number} sudah dalam mode handoff"}
        start_handoff(phone_number)
        notif = (
            "Halo! Admin kami akan segera membalas pesanmu. "
            "Mohon tunggu sebentar ya 🙏\n\n"
            "_Bot sementara tidak aktif._"
        )
        fonnte_queue.add_to_queue(phone_number, notif)
        save_to_supabase(phone_number, notif, direction="outbound", source="system")
        return {"status": "ok", "message": f"Handoff untuk {phone_number} dimulai"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/{phone_number}",
    summary="Akhiri handoff, kembalikan ke bot",
    description="Admin klik tombol 'Serahkan ke Bot' di dashboard. Bot aktif kembali untuk nomor ini.",
    responses={
        200: {
            "description": "Handoff berhasil diakhiri",
            "content": {"application/json": {"example": {"status": "ok", "message": "Handoff untuk 6281234567890 diakhiri, bot aktif kembali"}}},
        },
        404: {
            "description": "Nomor tidak sedang dalam handoff",
            "content": {"application/json": {"example": HANDOFF_ERROR_EXAMPLE}},
        },
        500: {
            "description": "Gagal mengakhiri handoff",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
def end_handoff_endpoint(phone_number: str = Path(..., description="Nomor HP yang akan dikembalikan ke bot", examples=["6281234567890"])):
    try:
        if not is_in_handoff(phone_number):
            raise HTTPException(status_code=404, detail=f"{phone_number} tidak dalam mode handoff")
        end_handoff(phone_number)
        notif = (
            "Terima kasih sudah menunggu! 😊 "
            "Bot kami sudah aktif kembali dan siap membantu kamu."
        )
        fonnte_queue.add_to_queue(phone_number, notif)
        save_to_supabase(phone_number, notif, direction="outbound", source="system")
        return {"status": "ok", "message": f"Handoff untuk {phone_number} diakhiri, bot aktif kembali"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/{phone_number}/reply",
    summary="Admin balas pesan ke pasien",
    description=(
        "Admin mengirim balasan ke pasien dari dashboard. "
        "Pesan dikirim via Fonnte dan dicatat di Supabase sebagai outbound/admin. "
        "Timeout handoff direset setiap kali admin membalas."
    ),
    responses={
        200: {
            "description": "Balasan admin berhasil dikirim",
            "content": {"application/json": {"example": {"status": "ok", "message": "Pesan admin terkirim ke pasien"}}},
        },
        400: {
            "description": "Nomor belum dalam handoff",
            "content": {"application/json": {"example": {"detail": "6281234567890 tidak dalam mode handoff. Mulai handoff dulu via POST /api/handoff/6281234567890"}}},
        },
        500: {
            "description": "Gagal mengirim balasan admin",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
def admin_reply(
    phone_number: str = Path(..., description="Nomor HP yang akan dibalas", examples=["6281234567890"]),
    payload: AdminReplyPayload = Body(
        ...,
        examples={
            "adminReplyExample": {
                "summary": "Contoh request balasan admin",
                "value": {"message": "Halo, kami sedang cek data Anda ya."},
            }
        },
    ),
):
    try:
        if not is_in_handoff(phone_number):
            raise HTTPException(
                status_code=400,
                detail=f"{phone_number} tidak dalam mode handoff. Mulai handoff dulu via POST /api/handoff/{phone_number}",
            )
        fonnte_queue.add_to_queue(phone_number, payload.message)
        save_to_supabase(phone_number, payload.message, direction="outbound", source="admin")
        update_admin_reply_time(phone_number)
        print(f"[Handoff] Admin → {phone_number}: {payload.message[:60]}...")
        return {"status": "ok", "message": "Pesan admin terkirim ke pasien"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
