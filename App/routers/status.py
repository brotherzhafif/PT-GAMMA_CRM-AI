# ======================================================
# SmartClinic CRM AI — routers/status.py
# Endpoint: /api/status
#
# Last Change   :   25 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

import json
import asyncio
from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from App.smartclinic_auth import get_smartclinic_token_status
from App.wa_service_client import wa_service_request

router = APIRouter(prefix="/api/status", tags=["System"])

WA_STATUS_EXAMPLE = {"status": "connected", "ready": True, "has_qr": False}
WA_QR_STREAM_CONNECTED_EXAMPLE = "event: status\ndata: connected"
WA_QR_STREAM_UPDATE_EXAMPLE = "event: qr_update\ndata: data:image/png;base64,..."
WA_CONNECTION_STATUS_EXAMPLE = "event: status\ndata: {\"status\":\"connected\"}"
SMARTCLINIC_TOKEN_STATUS_EXAMPLE = {
    "status": "valid",
    "valid": True,
    "token_preview": "eyJhbGci...cMpsc",
    "cached_at": "2026-05-25T20:33:53.458Z",
    "last_change_at": "2026-05-25T20:33:53.458Z",
    "expires_at": "2026-05-25T20:43:53.458Z",
}


@router.get(
    "/whatsapp-connection",
    summary="Stream koneksi WhatsApp (SSE)",
    description="Membuka satu stream SSE untuk status koneksi WhatsApp dan QR code login secara realtime.",
    responses={
        200: {
            "description": "Stream SSE aktif",
            "content": {
                "text/event-stream": {
                    "examples": {
                        "status": {"summary": "Status koneksi", "value": WA_CONNECTION_STATUS_EXAMPLE},
                        "qrUpdate": {"summary": "QR code baru", "value": WA_QR_STREAM_UPDATE_EXAMPLE},
                        "connected": {"summary": "Sudah terhubung", "value": WA_QR_STREAM_CONNECTED_EXAMPLE},
                    }
                }
            },
        },
        500: {
            "description": "Gagal membuka stream QR",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
async def whatsapp_connection_stream(request: Request):
    async def event_generator():
        last_status = None

        while True:
            # Jika user menutup tab browser atau pindah halaman, hentikan loop
            if await request.is_disconnected():
                break

            try:
                # Ambil data dari Node.js wa-service (yang me-return status + base64)
                status_response = wa_service_request("GET", "/status", timeout=3)
                if status_response.status_code == 200:
                    status_data = status_response.json()
                    if status_data != last_status:
                        last_status = status_data
                        yield {
                            "event": "status",
                            "data": json.dumps(status_data),
                        }
                else:
                    yield {
                        "event": "status",
                        "data": json.dumps({"status": "unreachable", "ready": False, "has_qr": False}),
                    }

                response = wa_service_request("GET", "/qr", timeout=3)

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

            # Polling setiap 2 atau 3 detik sekali untuk cek apakah status/QR diperbarui oleh Puppeteer
            await asyncio.sleep(3)

    return EventSourceResponse(event_generator())


@router.get(
    "/rme-connection",
    summary="Stream koneksi RME SmartClinic (SSE)",
    description="Mengirim status token SmartClinic, preview token, dan waktu perubahan terakhir secara realtime.",
    responses={
        200: {
            "description": "Stream SSE aktif",
            "content": {
                "text/event-stream": {
                    "examples": {
                        "tokenStatus": {"summary": "Status token", "value": "event: status\ndata: {\"status\":\"valid\"}"},
                    }
                }
            },
        },
        500: {
            "description": "Gagal membuka stream status token",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
async def smartclinic_token_status_stream(request: Request):
    async def event_generator():
        last_payload = None

        while True:
            if await request.is_disconnected():
                break

            payload = get_smartclinic_token_status()
            if payload != last_payload:
                last_payload = payload
                yield {
                    "event": "status",
                    "data": json.dumps(payload),
                }

            await asyncio.sleep(5)

    return EventSourceResponse(event_generator())