# ======================================================
# SmartClinic CRM AI — routers/wa.py
# Endpoint: /api/wa
#
# Last Change   :   18 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

import os
import requests
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/wa", tags=["WA Service"])

WA_SERVICE_URL = os.getenv("WA_SERVICE_URL", "http://wa-service:3000")


@router.get(
    "/status",
    summary="Cek status koneksi WhatsApp",
)
def wa_status():
    try:
        response = requests.get(f"{WA_SERVICE_URL}/status", timeout=5)
        return response.json()
    except Exception:
        return {"status": "unreachable", "ready": False, "has_qr": False}


@router.get(
    "/qr",
    summary="Ambil QR code untuk login WhatsApp",
    description="Return QR code dalam format base64 PNG. Tampilkan di dashboard untuk di-scan.",
)
def wa_qr():
    try:
        response = requests.get(f"{WA_SERVICE_URL}/qr", timeout=5)
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))