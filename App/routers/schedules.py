# ======================================================
# SmartClinic CRM AI — routers/schedules.py
# Endpoint: /api/v1/schedules
#
# Last Change   :   25 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request, Response

from App.config import SMARTCLINIC_BASE_URL
from App.smartclinic_auth import get_smartclinic_token


router = APIRouter(prefix="/api/v1/schedules", tags=["Schedules"])

SMARTCLINIC_SCHEDULES_PATH = "/schedules"

SCHEDULE_EXAMPLE = {
    "id": "sch_123",
    "dokterId": "dok_123",
    "hari": 1,
    "jamMulai": "09:00",
    "jamSelesai": "12:00",
    "kapasitasMaks": 20,
}


async def _proxy_smartclinic(
    method: str,
    path: str,
    *,
    params: Optional[list[tuple[str, str]]] = None,
) -> Response:
    token = await get_smartclinic_token()
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(base_url=SMARTCLINIC_BASE_URL, timeout=30.0) as client:
        try:
            upstream = await client.request(method, path, params=params, headers=headers)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="Gagal menghubungi SmartClinic") from exc

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
    )


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
async def get_all_schedules(request: Request):
    query_params = list(request.query_params.multi_items())
    return await _proxy_smartclinic("GET", SMARTCLINIC_SCHEDULES_PATH, params=query_params)


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
async def get_weekly_schedules(request: Request):
    query_params = list(request.query_params.multi_items())
    return await _proxy_smartclinic("GET", f"{SMARTCLINIC_SCHEDULES_PATH}/weekly", params=query_params)


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
async def get_schedule_slots(request: Request):
    query_params = list(request.query_params.multi_items())
    return await _proxy_smartclinic("GET", f"{SMARTCLINIC_SCHEDULES_PATH}/slots", params=query_params)