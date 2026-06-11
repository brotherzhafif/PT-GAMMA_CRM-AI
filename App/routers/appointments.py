# ======================================================
# SmartClinic CRM AI — routers/appointments.py
# Endpoint: /api/appointment
#
# Last Change   :   11 Jun 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

import asyncio
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field

from App.activity_logger import log_activity
from App.config import SMARTCLINIC_BASE_URL
from App.helpers import get_rme_patient_id_by_phone, proxy_smartclinic


router = APIRouter(prefix="/api/appointment", tags=["Appointments"])

SMARTCLINIC_APPOINTMENTS_PATH = "/queues/appointments"
SMARTCLINIC_QUEUES_BY_USER_PATH = "/queues/user"


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
    summary="Ambil antrean berdasarkan nomor telepon",
    description="Menerima nomor telepon pasien, mencari rme_patient_id di Supabase, lalu memanggil endpoint RME /api/v1/queues/user/{userId}.",
    responses={
        200: {
            "description": "Daftar antrean berhasil diambil",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "data": [],
                        "timestamp": "2026-05-31T14:53:56.476Z",
                    }
                }
            },
        },
        404: {
            "description": "Pasien tidak ditemukan",
            "content": {"application/json": {"example": {"detail": "Pasien tidak ditemukan"}}},
        },
        500: {
            "description": "Gagal mengambil antrean",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
async def get_appointments_by_phone(phone_number: str = Query(..., description="Nomor telepon pasien")):
    rme_patient_id = get_rme_patient_id_by_phone(phone_number)
    return await proxy_smartclinic(
        "GET",
        SMARTCLINIC_BASE_URL,
        f"{SMARTCLINIC_QUEUES_BY_USER_PATH}/{rme_patient_id}",
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
    return await proxy_smartclinic("DELETE", SMARTCLINIC_BASE_URL, f"/queues/appointments/{id}/cancel")


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
    request: Request,
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
    try:
        rme_patient_id = get_rme_patient_id_by_phone(payload.phone_number)

        query_params = [("pasienId", rme_patient_id)]
        body = {
            "jadwalId": payload.jadwalId,
            "tanggalKunjungan": payload.tanggalKunjungan,
            "catatan": payload.catatan,
            "jenisKunjunganBpjs": payload.jenisKunjunganBpjs,
            "noRujukanFktp": payload.noRujukanFktp,
        }

        result = await proxy_smartclinic(
            "POST",
            SMARTCLINIC_BASE_URL,
            SMARTCLINIC_APPOINTMENTS_PATH,
            params=query_params,
            json=body,
        )
        
        await log_activity(
            category="appointments",
            action="CREATE_APPOINTMENT",
            from_actor=request.client.host if request.client else "system",
            message=f"Janji temu dibuat untuk {payload.phone_number} pada {payload.tanggalKunjungan}",
            metadata={
                "phone_number": payload.phone_number,
                "tanggal": payload.tanggalKunjungan,
                "jadwal_id": payload.jadwalId,
            },
        )
        
        return result
    except Exception as exc:
        await log_activity(
            category="appointments",
            action="CREATE_APPOINTMENT_FAILED",
            from_actor=request.client.host if request.client else "system",
            message=f"Gagal buat janji temu untuk {payload.phone_number}",
            metadata={"error": str(exc)},
        )
        raise exc