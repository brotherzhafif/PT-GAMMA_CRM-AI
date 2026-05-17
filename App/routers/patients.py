# ======================================================
# SmartClinic CRM AI — routers/patients.py
# Endpoint: /api/patients
#
# Last Change   :   16 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

from typing import List
from fastapi import APIRouter, HTTPException

from App.config import supabase
from App.models import PatientRecord, SavePatientPayload, UpdatePatientPayload
from App.helpers import _require_supabase

router = APIRouter(prefix="/api/patients", tags=["Patients"])


# ======================================================
#
#               PATIENTS ENDPOINTS
#
# ======================================================

@router.get(
    "",
    response_model=List[PatientRecord],
    summary="Ambil semua nomor pasien tersimpan",
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
)
def save_patient(payload: SavePatientPayload):
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
)
def update_patient(phone_number: str, payload: UpdatePatientPayload):
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
)
def delete_patient(phone_number: str):
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
