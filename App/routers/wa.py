# ======================================================
# SmartClinic CRM AI — routers/wa.py
# Endpoint: /api/wa
#
# Last Change   :   18 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

import os
import requests
import asyncio
from fastapi.responses import JSONResponse
from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

router = APIRouter(prefix="/api/wa", tags=["WA Service"])

WA_SERVICE_URL = os.getenv("WA_SERVICE_URL", "http://wa-service:3000")

WA_STATUS_EXAMPLE = {"status": "connected", "ready": True, "has_qr": False}


@router.get(
    "/status",
    summary="Cek status koneksi WhatsApp",
    responses={
        200: {
            "description": "Status koneksi berhasil dibaca",
            "content": {"application/json": {"example": WA_STATUS_EXAMPLE}},
        },
    },
)
def wa_status():
    try:
        response = requests.get(f"{WA_SERVICE_URL}/status", timeout=5)
        return response.json()
    except Exception:
        return {"status": "unreachable", "ready": False, "has_qr": False}


@router.get(
    "/qr-stream",
    summary="Stream QR code untuk login WhatsApp (SSE)",
    description="Membuka koneksi streaming SSE yang mengirimkan data QR code (Base64 PNG) secara realtime.",
    responses={
        200: {
            "description": "Stream SSE aktif",
        },
        500: {
            "description": "Gagal membuka stream QR",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
async def wa_qr_stream(request: Request):
    async def event_generator():
        while True:
            # Jika user menutup tab browser atau pindah halaman, hentikan loop
            if await request.is_disconnected():
                break

            try:
                # Ambil data dari Node.js wa-service (yang me-return base64)
                response = requests.get(f"{WA_SERVICE_URL}/qr", timeout=3)
                
                if response.status_code == 200:
                    data = response.json()
                    status = data.get("status")
                    qr_base64 = data.get("qr")  # Ini isinya 'data:image/png;base64,...'

                    if status == "qr_ready" and qr_base64:
                        # Kirim gambar QR ke frontend
                        yield {
                            "event": "qr_update",
                            "data": qr_base64
                        }
                    elif status == "already_connected":
                        yield {
                            "event": "status",
                            "data": "connected"
                        }
                        break  # Stop stream kalau sudah sukses terhubung
                    else:
                        yield {
                            "event": "status",
                            "data": status
                        }
                else:
                    yield {
                        "event": "error",
                        "data": f"wa-service return status {response.status_code}"
                    }

            except Exception as e:
                yield {
                    "event": "error",
                    "data": f"Gagal fetch ke wa-service: {str(e)}"
                }

            # Polling setiap 2 atau 3 detik sekali untuk cek apakah QR diperbarui oleh Puppeteer
            await asyncio.sleep(3)

    return EventSourceResponse(event_generator())