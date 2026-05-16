# ======================================================
# SmartClinic CRM AI — routers/handoff.py
# Endpoint: /api/handoff
#
# Last Change   :   16 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

from typing import List
from fastapi import APIRouter, HTTPException

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

router = APIRouter(prefix="/api/handoff", tags=["Handoff"])


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
)
def start_handoff_manual(phone_number: str):
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
)
def end_handoff_endpoint(phone_number: str):
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
)
def admin_reply(phone_number: str, payload: AdminReplyPayload):
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
