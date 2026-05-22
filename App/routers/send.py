# ======================================================
# SmartClinic CRM AI — routers/send.py
# Endpoint: /api/send
#
# Last Change   :   16 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

import os
import requests

from fastapi import APIRouter, Body, HTTPException

from App.config import supabase
from App.models import SendMessagePayload, BroadcastPayload, BroadcastResult
from App.helpers import save_to_supabase, _require_supabase
from App.queue_manager import fonnte_queue

router = APIRouter(prefix="/api/send", tags=["Send"])


SEND_EXAMPLE = {
    "status": "ok",
    "message": "Pesan untuk 6281234567890 masuk antrian",
}

SEND_ATTACHMENT_EXAMPLE = {
    "status": "ok",
    "message": "Pesan untuk 6281234567890 masuk antrian",
}

SEND_ERROR_EXAMPLE = {"detail": "..."}

BROADCAST_EXAMPLE = {
    "status": "ok",
    "total_sent": 2,
    "recipients": ["6281234567890", "6289876543210"],
}


# ======================================================
#
#               SEND MESSAGE ENDPOINTS
#
# ======================================================

@router.post(
    "",
    summary="Kirim pesan ke satu nomor",
    description=(
        "Kirim pesan teks ke satu nomor via Fonnte, atau kirim attachment via wa-service "
        "jika attachment_url diisi. Pesan tetap dicatat ke Supabase sebagai outbound."
    ),
    summary="Kirim pesan ke satu nomor",
    responses={
        200: {
            "description": "Pesan berhasil dimasukkan antrian",
            "content": {
                "application/json": {
                    "examples": {
                        "textMessage": {"summary": "Pesan teks", "value": SEND_EXAMPLE},
                        "attachmentMessage": {"summary": "Pesan dengan attachment", "value": SEND_ATTACHMENT_EXAMPLE},
                    }
                }
            },
        },
        500: {
            "description": "Gagal mengirim pesan",
            "content": {"application/json": {"example": SEND_ERROR_EXAMPLE}},
        },
    },
)
def send_message(
    payload: SendMessagePayload = Body(
        ...,
        examples={
            "sendMessageExample": {
                "summary": "Contoh request kirim pesan",
                "value": {
                    "target": "6281234567890",
                    "message": "Halo, ini pesan dari admin SmartClinic.",
                    "attachment_url": None,
                    "filename": None,
                },
            }
        },
    )
):
    try:
        if payload.attachment_url:
            # Kirim via whatsapp-web.js (attachment) 
            WA_SERVICE_URL = os.getenv("WA_SERVICE_URL", "http://wa-service:3000")
            response = requests.post(
                f"{WA_SERVICE_URL}/send-attachment",
                json={
                    "target": payload.target,
                    "message": payload.message,
                    "attachment_url": payload.attachment_url,
                    "filename": payload.filename,
                },
                timeout=30,
            )
            response.raise_for_status()
            source = "wa-service"
        else:
            # Kirim via Fonnte (teks biasa) 
            fonnte_queue.add_to_queue(payload.target, payload.message)
            source = "manual"

        save_to_supabase(payload.target, payload.message, direction="outbound", source=source)
        print(f"[SEND] {source} → {payload.target}: {payload.message[:60]}...")
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
    responses={
        200: {
            "description": "Broadcast berhasil dikirim",
            "content": {"application/json": {"example": BROADCAST_EXAMPLE}},
        },
        404: {
            "description": "Tidak ada nomor pasien",
            "content": {"application/json": {"example": {"detail": "Tidak ada nomor pasien tersimpan."}}},
        },
        500: {
            "description": "Broadcast gagal",
            "content": {"application/json": {"example": SEND_ERROR_EXAMPLE}},
        },
    },
)
def broadcast_message(
    payload: BroadcastPayload = Body(
        ...,
        examples={
            "broadcastExample": {
                "summary": "Contoh request broadcast",
                "value": {
                    "message": "Promo pemeriksaan gigi hari ini tersedia untuk pasien kami.",
                    "attachment_url": None,
                    "filename": None,
                },
            }
        },
    )
):
    _require_supabase()
    try:
        response = supabase.table("patients").select("phone_number").execute()
        patients = response.data

        if not patients:
            raise HTTPException(
                status_code=404,
                detail="Tidak ada nomor pasien tersimpan.",
            )

        WA_SERVICE_URL = os.getenv("WA_SERVICE_URL", "http://wa-service:3000")
        recipients = []

        for patient in patients:
            number = patient.get("phone_number")
            if not number:
                continue

            if payload.attachment_url:
                # Kirim via whatsapp-web.js 
                requests.post(
                    f"{WA_SERVICE_URL}/send-attachment",
                    json={
                        "target": number,
                        "message": payload.message,
                        "attachment_url": payload.attachment_url,
                        "filename": payload.filename,
                    },
                    timeout=30,
                )
                source = "wa-service"
            else:
                # Kirim via Fonnte 
                fonnte_queue.add_to_queue(number, payload.message)
                source = "broadcast"

            save_to_supabase(number, payload.message, direction="outbound", source=source)
            recipients.append(number)

        print(f"[BROADCAST] {len(recipients)} pesan masuk antrian")
        return BroadcastResult(status="ok", total_sent=len(recipients), recipients=recipients)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
