# ======================================================
# SmartClinic CRM AI — routers/patients.py
# Endpoint: /api/patients
#
# Last Change   :   25 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

import json
from typing import Literal, Optional

import httpx
from fastapi import APIRouter, Body, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, Field

from App.config import supabase
from App.helpers import normalize_phone_number
from App.smartclinic_auth import get_smartclinic_token


router = APIRouter(prefix="/api/patients", tags=["Patients"])

SMARTCLINIC_BASE_URL = "https://smartclinic-rekam-medis.onrender.com"
SMARTCLINIC_PATIENTS_PATH = "/api/v1/patients"

class PatientPayload(BaseModel):
    nik: str = Field(..., description="NIK pasien")
    namaLengkap: str = Field(..., description="Nama lengkap pasien")
    tanggalLahir: str = Field(..., description="Tanggal lahir pasien")
    jenisKelamin: Literal["LAKI_LAKI", "PEREMPUAN"] = Field(..., description="Jenis kelamin pasien")
    telepon: str = Field(..., description="Nomor telepon")


PATIENT_EXAMPLE = {
    "id": "rme_patient_uuid_from_smartclinic",
    "nik": "3174xxxxxxxxxxxx",
    "namaLengkap": "Budi Santoso",
    "tanggalLahir": "1990-01-15",
    "jenisKelamin": "LAKI_LAKI",
    "telepon": "6281234567890",
}

PATIENT_ERROR_EXAMPLE = {"detail": "Pasien tidak ditemukan"}


async def _smartclinic_request(
    method: str,
    path: str,
    *,
    params: Optional[list[tuple[str, str]]] = None,
    json_body: Optional[dict] = None,
) -> Response:
    token = await get_smartclinic_token()
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(base_url=SMARTCLINIC_BASE_URL, timeout=30.0) as client:
        try:
            upstream = await client.request(method, path, params=params, json=json_body, headers=headers)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="Gagal menghubungi SmartClinic") from exc

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
    )


def _upsert_patient_to_supabase(rme_patient_id: str, payload: PatientPayload) -> None:
    if supabase is None:
        raise HTTPException(status_code=500, detail="Supabase belum dikonfigurasi")

    supabase.table("patients").upsert(
        {
            "rme_patient_id": rme_patient_id,
            "phone_number": payload.telepon,
            "name": payload.namaLengkap,
        },
        on_conflict="rme_patient_id",
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
    return await _smartclinic_request("GET", SMARTCLINIC_PATIENTS_PATH, params=query_params)


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
    response = await _smartclinic_request(
        "POST",
        SMARTCLINIC_PATIENTS_PATH,
        json_body=payload.model_dump(exclude_none=True),
    )
    if response.status_code < 400:
        try:
            upstream_payload = json.loads(response.body.decode("utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=502, detail="Respons SmartClinic tidak valid") from exc

        rme_patient_id = (upstream_payload.get("data") or {}).get("id") if isinstance(upstream_payload, dict) else None
        if not rme_patient_id:
            raise HTTPException(status_code=502, detail="SmartClinic tidak mengembalikan data.id")

        try:
            _upsert_patient_to_supabase(rme_patient_id, payload)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Gagal menyimpan mapping pasien ke Supabase: {exc}") from exc
    return response


@router.get(
    "/by-phone",
    summary="Cari pasien berdasarkan nomor telepon",
    responses={
        200: {
            "description": "Pasien ditemukan",
            "content": {
                "application/json": {
                    "example": {
                        "id": "8de0f7b2-4b90-4c4b-8c59-12b7b7f8a111",
                        "rme_patient_id": "f1a2b3c4-d5e6-7f80-1234-56789abcdef0",
                        "phone_number": "6281234567890",
                        "name": "Budi Santoso",
                    }
                }
            },
        },
        404: {
            "description": "Pasien tidak ditemukan",
            "content": {"application/json": {"example": {"detail": "Pasien dengan nomor 6281234567890 tidak ditemukan"}}},
        },
        500: {
            "description": "Gagal membaca data pasien",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
async def get_patient_by_phone(phone: str = Query(..., description="Nomor telepon pasien")):
    if supabase is None:
        raise HTTPException(status_code=500, detail="Supabase belum dikonfigurasi")

    normalized_phone = normalize_phone_number(phone)
    response = (
        supabase.table("patients")
        .select("rme_patient_id")
        .eq("phone_number", normalized_phone)
        .limit(1)
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=404, detail=f"Pasien dengan nomor {normalized_phone} tidak ditemukan")

    rme_patient_id = response.data[0].get("rme_patient_id")
    if not rme_patient_id:
        raise HTTPException(status_code=404, detail=f"Pasien dengan nomor {normalized_phone} tidak ditemukan")

    return await _smartclinic_request("GET", f"{SMARTCLINIC_PATIENTS_PATH}/{rme_patient_id}")


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
    return await _smartclinic_request("GET", f"{SMARTCLINIC_PATIENTS_PATH}/rm/{noRm}")


@router.get(
    "/{rme_patient_id}",
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
async def get_patient_by_id(rme_patient_id: str = Path(..., description="rme_patient_id pasien")):
    return await _smartclinic_request("GET", f"{SMARTCLINIC_PATIENTS_PATH}/{rme_patient_id}")


@router.put(
    "/{rme_patient_id}",
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
    rme_patient_id: str = Path(..., description="rme_patient_id pasien"),
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
    response = await _smartclinic_request(
        "PUT",
        f"{SMARTCLINIC_PATIENTS_PATH}/{rme_patient_id}",
        json_body=payload.model_dump(exclude_none=True),
    )
    if response.status_code < 400:
        try:
            _upsert_patient_to_supabase(rme_patient_id, payload)
        except HTTPException:
            raise
        except Exception:
            raise
    return response


@router.delete(
    "/{rme_patient_id}",
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
async def delete_patient(rme_patient_id: str = Path(..., description="rme_patient_id pasien")):
    response = await _smartclinic_request("DELETE", f"{SMARTCLINIC_PATIENTS_PATH}/{rme_patient_id}")
    if response.status_code < 400 and supabase is not None:
        supabase.table("patients").delete().eq("rme_patient_id", rme_patient_id).execute()
    return response
