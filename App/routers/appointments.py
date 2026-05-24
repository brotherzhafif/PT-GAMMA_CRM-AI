# ======================================================
# SmartClinic CRM AI — routers/appointments.py
# Endpoint: /api/appointments
#
# Last Change   :   25 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

from typing import Optional

import httpx
from fastapi import APIRouter, Body, HTTPException, Request, Response
from pydantic import BaseModel, Field

from App.config import SMARTCLINIC_BASE_URL, supabase
from App.helpers import get_smartclinic_token, normalize_phone_number


router = APIRouter(prefix="/api/appointment", tags=["Appointments"])

SMARTCLINIC_APPOINTMENTS_PATH = "/queues/appointments"


class CreateAppointmentPayload(BaseModel):
    phone_number: str = Field(..., description="Nomor telepon pasien")
    jadwalId: str = Field(..., description="ID jadwal")
    tanggalKunjungan: str = Field(..., description="Tanggal kunjungan YYYY-MM-DD")
    catatan: Optional[str] = Field(default=None, description="Catatan kunjungan")
    jenisKunjunganBpjs: Optional[str] = Field(default=None, description="Jenis kunjungan BPJS")
    noRujukanFktp: Optional[str] = Field(default=None, description="Nomor rujukan FKTP")


async def _proxy_smartclinic(
    method: str,
    path: str,
    *,
    params: Optional[list[tuple[str, str]]] = None,
    json: Optional[dict] = None,
) -> Response:
    token = await get_smartclinic_token()
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(base_url=SMARTCLINIC_BASE_URL, timeout=30.0) as client:
        try:
            upstream = await client.request(method, path, params=params, json=json, headers=headers)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="Gagal menghubungi SmartClinic") from exc

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
    )


@router.get(
    "",
    summary="Ambil daftar queues",
    description="Meneruskan query params tanggal, dokterId, dan status ke SmartClinic tanpa perubahan.",
    responses={
        200: {
            "description": "Daftar queues berhasil diambil",
            "content": {"application/json": {"example": {"data": []}}},
        },
        400: {
            "description": "Request tidak valid",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
        500: {
            "description": "Gagal mengambil queues",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
async def get_queues(request: Request):
    tanggal = request.query_params.get("tanggal")
    if not tanggal:
        raise HTTPException(status_code=422, detail="tanggal wajib diisi")

    query_params = list(request.query_params.multi_items())
    return await _proxy_smartclinic("GET", "/queues", params=query_params)


def _lookup_rme_patient_id(phone_number: str) -> str:
    if supabase is None:
        raise HTTPException(status_code=500, detail="Supabase belum dikonfigurasi")

    normalized_phone = normalize_phone_number(phone_number)
    response = (
        supabase.table("patients")
        .select("rme_patient_id")
        .eq("phone_number", normalized_phone)
        .limit(1)
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=404, detail="Pasien tidak ditemukan")

    rme_patient_id = response.data[0].get("rme_patient_id")
    if not rme_patient_id:
        raise HTTPException(status_code=404, detail="Pasien tidak ditemukan")

    return rme_patient_id


@router.post(
    "/appointments",
    summary="Buat janji temu",
    responses={
        200: {
            "description": "Janji temu berhasil dibuat",
            "content": {"application/json": {"example": {"status": "ok"}}},
        },
        404: {
            "description": "Pasien tidak ditemukan",
            "content": {"application/json": {"example": {"detail": "Pasien tidak ditemukan"}}},
        },
        500: {
            "description": "Gagal membuat janji temu",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
async def create_appointment(
    payload: CreateAppointmentPayload = Body(
        ...,
        examples={
            "createAppointmentExample": {
                "summary": "Contoh request janji temu",
                "value": {
                    "phone_number": "6281234567890",
                    "jadwalId": "jad_123",
                    "tanggalKunjungan": "2026-05-25",
                    "catatan": "Kontrol gigi",
                    "jenisKunjunganBpjs": "REGULER",
                    "noRujukanFktp": "RUJ-123456",
                },
            }
        },
    )
):
    rme_patient_id = _lookup_rme_patient_id(payload.phone_number)

    query_params = [("pasienId", rme_patient_id)]
    body = {
        "jadwalId": payload.jadwalId,
        "tanggalKunjungan": payload.tanggalKunjungan,
        "catatan": payload.catatan,
        "jenisKunjunganBpjs": payload.jenisKunjunganBpjs,
        "noRujukanFktp": payload.noRujukanFktp,
    }

    return await _proxy_smartclinic(
        "POST",
        SMARTCLINIC_APPOINTMENTS_PATH,
        params=query_params,
        json=body,
    )