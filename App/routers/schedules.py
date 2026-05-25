# ======================================================
# SmartClinic CRM AI — routers/schedules.py
# Endpoint: /api/schedules
#
# Last Change   :   25 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from App.config import SMARTCLINIC_BASE_URL
from App.helpers import proxy_smartclinic


router = APIRouter(prefix="/api/schedules", tags=["Schedules"])

SMARTCLINIC_SCHEDULES_PATH = "/schedules"

SCHEDULE_EXAMPLE = {
    "id": "sch_123",
    "dokterId": "dok_123",
    "hari": 1,
    "jamMulai": "09:00",
    "jamSelesai": "12:00",
    "kapasitasMaks": 20,
}


@router.get(
    "",
    summary="Ambil semua jadwal dokter",
    description="Meneruskan seluruh query params ke SmartClinic tanpa perubahan.",
    responses={
        200: {
            "description": "Daftar jadwal berhasil diambil",
            "content": {"application/json": {"example": [SCHEDULE_EXAMPLE]}},
        },
        500: {
            "description": "Gagal mengambil jadwal",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
async def get_all_schedules(dokterId: Optional[str] = None, request: Request = None):
    query_params = list(request.query_params.multi_items())
    return await proxy_smartclinic("GET", SMARTCLINIC_BASE_URL, SMARTCLINIC_SCHEDULES_PATH, params=query_params)


@router.get(
    "/weekly",
    summary="Ambil jadwal mingguan",
    description="Meneruskan query params startDate, endDate, dan dokterId ke SmartClinic tanpa perubahan.",
    responses={
        200: {
            "description": "Jadwal mingguan berhasil diambil",
            "content": {"application/json": {"example": [SCHEDULE_EXAMPLE]}},
        },
        500: {
            "description": "Gagal mengambil jadwal mingguan",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
async def get_weekly_schedules(
    startDate: str,
    endDate: Optional[str] = None,
    dokterId: Optional[str] = None,
    request: Request = None,
):
    query_params = list(request.query_params.multi_items())
    return await proxy_smartclinic("GET", SMARTCLINIC_BASE_URL, f"{SMARTCLINIC_SCHEDULES_PATH}/weekly", params=query_params)


@router.get(
    "/slots",
    summary="Ambil slot jadwal tersedia",
    description="Meneruskan query params tanggal dan dokterId ke SmartClinic tanpa perubahan.",
    responses={
        200: {
            "description": "Slot jadwal berhasil diambil",
            "content": {"application/json": {"example": [SCHEDULE_EXAMPLE]}},
        },
        500: {
            "description": "Gagal mengambil slot jadwal",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
async def get_schedule_slots(tanggal: str, dokterId: Optional[str] = None, request: Request = None):
    query_params = list(request.query_params.multi_items())
    return await proxy_smartclinic("GET", SMARTCLINIC_BASE_URL, f"{SMARTCLINIC_SCHEDULES_PATH}/slots", params=query_params)