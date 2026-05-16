# ======================================================
# SmartClinic CRM AI — routers/send.py
# Endpoint: /api/send
#
# Last Change   :   16 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

from fastapi import APIRouter, HTTPException

from App.config import supabase
from App.models import SendMessagePayload, BroadcastPayload, BroadcastResult
from App.helpers import save_to_supabase, _require_supabase
from App.queue_manager import fonnte_queue

router = APIRouter(prefix="/api/send", tags=["Send"])


# ======================================================
#
#               SEND MESSAGE ENDPOINTS
#
# ======================================================

@router.post(
    "",
    summary="Kirim pesan ke satu nomor",
    description="Kirim pesan manual ke satu nomor WhatsApp melalui antrian Fonnte. Tercatat di Supabase sebagai outbound/manual.",
)
def send_message(payload: SendMessagePayload):
    try:
        fonnte_queue.add_to_queue(payload.target, payload.message)
        save_to_supabase(payload.target, payload.message, direction="outbound", source="manual")
        print(f"[SEND] Manual → {payload.target}: {payload.message[:60]}...")
        return {"status": "ok", "message": f"Pesan untuk {payload.target} masuk antrian"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/broadcast",
    response_model=BroadcastResult,
    summary="Broadcast pesan ke semua nomor pasien",
    description=(
        "Kirim satu pesan ke seluruh nomor di tabel patients. "
        "Setiap pesan dimasukkan ke antrian Fonnte dengan delay acak (anti-blokir WA). "
        "Semua pengiriman dicatat di Supabase sebagai outbound/broadcast."
    ),
)
def broadcast_message(payload: BroadcastPayload):
    _require_supabase()
    try:
        response = supabase.table("patients").select("phone_number").execute()
        patients = response.data

        if not patients:
            raise HTTPException(
                status_code=404,
                detail="Tidak ada nomor pasien tersimpan. Tambahkan dulu via POST /api/patients",
            )

        recipients = []
        for patient in patients:
            number = patient.get("phone_number")
            if not number:
                continue
            fonnte_queue.add_to_queue(number, payload.message)
            save_to_supabase(number, payload.message, direction="outbound", source="broadcast")
            recipients.append(number)

        print(f"[BROADCAST] {len(recipients)} pesan masuk antrian")
        return BroadcastResult(status="ok", total_sent=len(recipients), recipients=recipients)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
