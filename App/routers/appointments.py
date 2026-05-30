# ======================================================
# SmartClinic CRM AI — routers/appointments.py
# Endpoint: /api/appointments
#
# Last Change   :   25 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field

from App.config import SMARTCLINIC_BASE_URL, supabase
from App.helpers import normalize_phone_number, proxy_smartclinic


router = APIRouter(prefix="/api/appointment", tags=["Appointments"])

SMARTCLINIC_APPOINTMENTS_PATH = "/queues/appointments"


class CreateAppointmentPayload(BaseModel):
    phone_number: str = Field(..., description="Nomor telepon pasien")
    jadwalId: str = Field(..., description="ID jadwal")
    tanggalKunjungan: str = Field(..., description="Tanggal kunjungan YYYY-MM-DD")
    catatan: Optional[str] = Field(default=None, description="Catatan kunjungan")
    jenisKunjunganBpjs: Optional[str] = Field(default=None, description="Jenis kunjungan BPJS")
    noRujukanFktp: Optional[str] = Field(default=None, description="Nomor rujukan FKTP")


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
async def get_queues(
    tanggal: str,
    dokterId: Optional[str] = None,
    status: Optional[str] = None,
    request: Request = None,
):
    if not tanggal:
        raise HTTPException(status_code=422, detail="tanggal wajib diisi")

    query_params = list(request.query_params.multi_items())
    return await proxy_smartclinic("GET", SMARTCLINIC_BASE_URL, "/queues", params=query_params)


@router.get(
    "/appointments/by-phone",
    summary="Ambil janji temu berdasarkan nomor telepon",
    responses={
        200: {
            "description": "Daftar janji temu berhasil diambil",
            "content": {"application/json": {"example": {"data": []}}},
        },
        404: {
            "description": "Pasien tidak ditemukan",
            "content": {"application/json": {"example": {"detail": "Pasien tidak ditemukan"}}},
        },
        500: {
            "description": "Gagal mengambil janji temu",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
async def get_appointments_by_phone(phone_number: str = Query(..., description="Nomor telepon pasien")):
    rme_patient_id = _lookup_rme_patient_id(phone_number)
    return await proxy_smartclinic(
        "GET",
        SMARTCLINIC_BASE_URL,
        f"{SMARTCLINIC_APPOINTMENTS_PATH}/{rme_patient_id}",
    )


@router.delete(
    "/appointments/{id}",
    summary="Batalkan janji temu pasien",
    description="Meneruskan permintaan pembatalan janji temu ke SmartClinic.",
    responses={
        200: {
            "description": "Janji temu berhasil dibatalkan",
            "content": {"application/json": {"example": {"status": "ok"}}},
        },
        400: {
            "description": "Janji temu tidak bisa dibatalkan",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
        404: {
            "description": "Janji temu tidak ditemukan",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
        500: {
            "description": "Gagal membatalkan janji temu",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
async def cancel_appointment(id: str = Path(..., description="ID janji temu")):
    return await proxy_smartclinic("DELETE", SMARTCLINIC_BASE_URL, f"{SMARTCLINIC_APPOINTMENTS_PATH}/{id}/cancel")


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

    return await proxy_smartclinic(
        "POST",
        SMARTCLINIC_BASE_URL,
        SMARTCLINIC_APPOINTMENTS_PATH,
        params=query_params,
        json=body,
    )