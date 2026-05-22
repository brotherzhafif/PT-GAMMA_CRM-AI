# ======================================================
# SmartClinic CRM AI — routers/patients.py
# Endpoint: /api/patients
#
# Last Change   :   16 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

from typing import List
from fastapi import APIRouter, Body, HTTPException, Path

from App.config import supabase
from App.models import PatientRecord, SavePatientPayload, UpdatePatientPayload
from App.helpers import _require_supabase

router = APIRouter(prefix="/api/patients", tags=["Patients"])


PATIENT_EXAMPLE = {
    "id": "8de0f7b2-4b90-4c4b-8c59-12b7b7f8a111",
    "phone_number": "6281234567890",
    "name": "Budi Santoso",
    "created_at": "2026-05-22T10:00:00Z",
}

PATIENT_ERROR_EXAMPLE = {"detail": "Nomor 6281234567890 tidak ditemukan"}


# ======================================================
#
#               PATIENTS ENDPOINTS
#
# ======================================================

@router.get(
    "",
    response_model=List[PatientRecord],
    summary="Ambil semua nomor pasien tersimpan",
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
def get_all_patients():
    _require_supabase()
    try:
        response = supabase.table("patients").select("*").order("created_at", desc=False).execute()
        return response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "",
    response_model=PatientRecord,
    summary="Simpan nomor pasien baru",
    description="Jika nomor sudah ada, data diupdate (upsert). Tidak akan duplikat.",
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
def save_patient(
    payload: SavePatientPayload = Body(
        ...,
        examples={
            "savePatientExample": {
                "summary": "Contoh request simpan pasien",
                "value": {
                    "phone_number": "6281234567890",
                    "name": "Budi Santoso",
                },
            }
        },
    )
):
    _require_supabase()
    try:
        response = (
            supabase.table("patients")
            .upsert(
                {"phone_number": payload.phone_number, "name": payload.name},
                on_conflict="phone_number",
            )
            .execute()
        )
        return response.data[0]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch(
    "/{phone_number}",
    response_model=PatientRecord,
    summary="Update data pasien",
    description="Update nama atau nomor HP pasien. Hanya field yang diisi yang akan diupdate.",
    responses={
        200: {
            "description": "Pasien berhasil diupdate",
            "content": {"application/json": {"example": PATIENT_EXAMPLE}},
        },
        400: {
            "description": "Tidak ada field yang diupdate",
            "content": {"application/json": {"example": {"detail": "Tidak ada field yang diupdate"}}},
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
def update_patient(
    phone_number: str = Path(..., description="Nomor HP pasien yang akan diupdate", examples=["6281234567890"]),
    payload: UpdatePatientPayload = Body(
        ...,
        examples={
            "updatePatientExample": {
                "summary": "Contoh request update pasien",
                "value": {"name": "Budi Santoso Baru"},
            }
        },
    ),
):
    _require_supabase()
    try:
        # Bangun dict update — hanya field yang tidak None
        update_data = {k: v for k, v in payload.model_dump().items() if v is not None}

        if not update_data:
            raise HTTPException(status_code=400, detail="Tidak ada field yang diupdate")

        response = (
            supabase.table("patients")
            .update(update_data)
            .eq("phone_number", phone_number)
            .execute()
        )

        if not response.data:
            raise HTTPException(status_code=404, detail=f"Nomor {phone_number} tidak ditemukan")

        return response.data[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/{phone_number}",
    summary="Hapus nomor pasien",
    responses={
        200: {
            "description": "Pasien berhasil dihapus",
            "content": {"application/json": {"example": {"status": "ok", "message": "Nomor 6281234567890 berhasil dihapus"}}},
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
def delete_patient(phone_number: str = Path(..., description="Nomor HP pasien yang akan dihapus", examples=["6281234567890"])):
    _require_supabase()
    try:
        response = (
            supabase.table("patients")
            .delete()
            .eq("phone_number", phone_number)
            .execute()
        )
        if not response.data:
            raise HTTPException(status_code=404, detail=f"Nomor {phone_number} tidak ditemukan")
        return {"status": "ok", "message": f"Nomor {phone_number} berhasil dihapus"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
