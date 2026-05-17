# ======================================================
# SmartClinic CRM AI — routers/messages.py
# Endpoint: /api/messages
#
# Last Change   :   16 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

from typing import List
from fastapi import APIRouter, HTTPException

from App.config import supabase
from App.models import ChatRecord
from App.helpers import _require_supabase

router = APIRouter(prefix="/api/messages", tags=["Messages"])


# ======================================================
#
#                  MESSAGES ENDPOINTS
#
# ======================================================

@router.get(
    "",
    response_model=List[ChatRecord],
    summary="Ambil semua pesan",
    description="Seluruh pesan dari semua nomor, diurutkan dari terlama. Gunakan query param `?limit=N` untuk batasi jumlah (default: 100).",
)
def get_all_messages(limit: int = 100):
    _require_supabase()
    try:
        response = (
            supabase.table("messages")
            .select("*")
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
        )
        return response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get(
    "/latest",
    response_model=List[dict],
    summary="Ambil chat terbaru semua customer",
    description="Mengambil 1 pesan terbaru per nomor beserta nama pasien. Untuk sidebar CRM.",
)
def get_latest_messages():
    _require_supabase()
    try:
        response = supabase.rpc("get_latest_messages").execute()
        return response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get(
    "/{phone_number}",
    response_model=List[ChatRecord],
    summary="Ambil pesan berdasarkan nomor",
    description="Seluruh riwayat inbound dan outbound milik satu nomor WhatsApp.",
)
def get_messages_by_number(phone_number: str):
    _require_supabase()
    try:
        response = (
            supabase.table("messages")
            .select("*")
            .eq("sender_number", phone_number)
            .order("created_at", desc=False)
            .execute()
        )
        if not response.data:
            raise HTTPException(status_code=404, detail=f"Tidak ada pesan untuk nomor {phone_number}")
        return response.data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
