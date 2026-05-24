# ======================================================
# SmartClinic CRM AI — routers/patients.py
# Endpoint: /api/v1/patients
#
# Last Change   :   25 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

from typing import Any, Literal, Optional

import httpx
from fastapi import APIRouter, Body, HTTPException, Path, Request, Response
from pydantic import BaseModel, Field

try:
    from App.config import SMARTCLINIC_BASE_URL, supabase
    from App.helpers import get_smartclinic_token
except ImportError:  # pragma: no cover - fallback only if helper is unavailable
    from App.config import SMARTCLINIC_BASE_URL, supabase

    async def get_smartclinic_token() -> str:
        raise RuntimeError("get_smartclinic_token() is not available")


router = APIRouter(prefix="/api/v1/patients", tags=["Patients"])

SMARTCLINIC_PATIENTS_PATH = "/patients"

class PatientPayload(BaseModel):
    nik: str = Field(..., description="NIK pasien")
    namaLengkap: str = Field(..., description="Nama lengkap pasien")
    tanggalLahir: str = Field(..., description="Tanggal lahir pasien")
    jenisKelamin: Literal["LAKI_LAKI", "PEREMPUAN"] = Field(..., description="Jenis kelamin pasien")
    telepon: str = Field(..., description="Nomor telepon")


PATIENT_EXAMPLE = {
    "id": "8de0f7b2-4b90-4c4b-8c59-12b7b7f8a111",
    "nik": "3174xxxxxxxxxxxx",
    "namaLengkap": "Budi Santoso",
    "tanggalLahir": "1990-01-15",
    "jenisKelamin": "LAKI_LAKI",
    "telepon": "6281234567890",
}

PATIENT_ERROR_EXAMPLE = {"detail": "Pasien tidak ditemukan"}


async def _proxy_smartclinic(
    method: str,
    path: str,
    *,
    params: Optional[list[tuple[str, str]]] = None,
    json: Optional[dict[str, Any]] = None,
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


def _sync_patient_to_supabase(payload: PatientPayload) -> None:
    if supabase is None:
        return

    supabase.table("patients").upsert(
        {
            "phone_number": payload.telepon,
            "name": payload.namaLengkap,
        },
        on_conflict="phone_number",
    ).execute()


@router.get(
    "",
    summary="Ambil semua data pasien",
    description="Meneruskan seluruh query params ke SmartClinic tanpa perubahan.",
    responses={
        200: {
            "description": "Daftar pasien berhasil diambil",
            "content": {"application/json": {"example": [PATIENT_EXAMPLE]}},
        },
        500: {
            "description": "Gagal mengambil daftar pasien",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
async def get_all_patients(request: Request):
    query_params = list(request.query_params.multi_items())
    if not query_params:
        query_params = [("page", "1"), ("limit", "100")]
    return await _proxy_smartclinic("GET", SMARTCLINIC_PATIENTS_PATH, params=query_params)


@router.post(
    "",
    summary="Buat data pasien baru",
    responses={
        200: {
            "description": "Pasien berhasil disimpan",
            "content": {"application/json": {"example": PATIENT_EXAMPLE}},
        },
        500: {
            "description": "Pasien gagal disimpan",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
async def create_patient(
    payload: PatientPayload = Body(
        ...,
        examples={
            "createPatientExample": {
                "summary": "Contoh request create patient",
                "value": {
                    "nik": "3174xxxxxxxxxxxx",
                    "namaLengkap": "Budi Santoso",
                    "tanggalLahir": "1990-01-15",
                    "jenisKelamin": "LAKI_LAKI",
                    "telepon": "6281234567890",
                },
            }
        },
    )
):
    response = await _proxy_smartclinic("POST", SMARTCLINIC_PATIENTS_PATH, json=payload.model_dump(exclude_none=True))
    if response.status_code < 400:
        try:
            _sync_patient_to_supabase(payload)
        except Exception:
            pass
    return response


@router.get(
    "/rm/{noRm}",
    summary="Ambil data pasien berdasarkan nomor RM",
    responses={
        200: {
            "description": "Pasien berhasil diambil",
            "content": {"application/json": {"example": PATIENT_EXAMPLE}},
        },
        404: {
            "description": "Pasien tidak ditemukan",
            "content": {"application/json": {"example": PATIENT_ERROR_EXAMPLE}},
        },
        500: {
            "description": "Gagal mengambil pasien",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
async def get_patient_by_rm(noRm: str = Path(..., description="Nomor RM pasien")):
    return await _proxy_smartclinic("GET", f"{SMARTCLINIC_PATIENTS_PATH}/rm/{noRm}")


@router.get(
    "/{id}",
    summary="Ambil data pasien berdasarkan ID",
    responses={
        200: {
            "description": "Pasien berhasil diambil",
            "content": {"application/json": {"example": PATIENT_EXAMPLE}},
        },
        404: {
            "description": "Pasien tidak ditemukan",
            "content": {"application/json": {"example": PATIENT_ERROR_EXAMPLE}},
        },
        500: {
            "description": "Gagal mengambil pasien",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
async def get_patient_by_id(id: str = Path(..., description="ID pasien")):
    return await _proxy_smartclinic("GET", f"{SMARTCLINIC_PATIENTS_PATH}/{id}")


@router.put(
    "/{id}",
    summary="Perbarui data pasien",
    responses={
        200: {
            "description": "Pasien berhasil diupdate",
            "content": {"application/json": {"example": PATIENT_EXAMPLE}},
        },
        404: {
            "description": "Pasien tidak ditemukan",
            "content": {"application/json": {"example": PATIENT_ERROR_EXAMPLE}},
        },
        500: {
            "description": "Pasien gagal diupdate",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
async def update_patient(
    id: str = Path(..., description="ID pasien"),
    payload: PatientPayload = Body(
        ...,
        examples={
            "updatePatientExample": {
                "summary": "Contoh request update patient",
                "value": {
                    "nik": "3174xxxxxxxxxxxx",
                    "namaLengkap": "Budi Santoso",
                    "tanggalLahir": "1990-01-15",
                    "jenisKelamin": "LAKI_LAKI",
                    "telepon": "6281234567890",
                },
            }
        },
    ),
):
    response = await _proxy_smartclinic("PUT", f"{SMARTCLINIC_PATIENTS_PATH}/{id}", json=payload.model_dump(exclude_none=True))
    if response.status_code < 400:
        try:
            _sync_patient_to_supabase(payload)
        except Exception:
            pass
    return response


@router.delete(
    "/{id}",
    summary="Hapus data pasien",
    responses={
        200: {
            "description": "Pasien berhasil dihapus",
            "content": {"application/json": {"example": {"status": "ok", "message": "Pasien berhasil dihapus"}}},
        },
        404: {
            "description": "Pasien tidak ditemukan",
            "content": {"application/json": {"example": PATIENT_ERROR_EXAMPLE}},
        },
        500: {
            "description": "Pasien gagal dihapus",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
async def delete_patient(id: str = Path(..., description="ID pasien")):
    return await _proxy_smartclinic("DELETE", f"{SMARTCLINIC_PATIENTS_PATH}/{id}")
