# ======================================================
# SmartClinic CRM AI — routers/patients.py
# Endpoint: /api/patients
#
# Last Change   :   18 Jun 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Path, Query, Request, Response

from App.activity_logger import log_activity
from App.config import SMARTCLINIC_BASE_URL, supabase
from App.helpers import get_rme_patient_id_by_phone, normalize_phone_number, proxy_smartclinic
from App.models import PatientPayload


router = APIRouter(prefix="/api/patients", tags=["Patients"])

SMARTCLINIC_PATIENTS_PATH = "/patients"

PATIENT_EXAMPLE = {
    "id": "rme_patient_uuid_from_smartclinic",
    "nik": "3174xxxxxxxxxxxx",
    "namaLengkap": "Budi Santoso",
    "tanggalLahir": "1990-01-15",
    "jenisKelamin": "LAKI_LAKI",
    "telepon": "6281234567890",
}

PATIENT_ERROR_EXAMPLE = {"detail": "Pasien tidak ditemukan"}


def _build_patient_supabase_row(rme_patient_id: str, payload: PatientPayload) -> dict:
    tgl_lahir = payload.tanggalLahir
    if tgl_lahir:
        tgl_lahir = tgl_lahir.split("T")[0]
    return {
        "rme_patient_id": rme_patient_id,
        "phone_number": normalize_phone_number(payload.telepon),
        "name": payload.namaLengkap,
        "birthdate": tgl_lahir,
    }


def _upsert_patient_to_supabase(rme_patient_id: str, payload: PatientPayload) -> None:
    if supabase is None:
        raise HTTPException(status_code=500, detail="Supabase belum dikonfigurasi")

    supabase.table("patients").upsert(
        _build_patient_supabase_row(rme_patient_id, payload),
        on_conflict="phone_number",
    ).execute()


async def _delete_patient_in_smartclinic(rme_patient_id: str) -> None:
    await proxy_smartclinic("DELETE", SMARTCLINIC_BASE_URL, f"{SMARTCLINIC_PATIENTS_PATH}/{rme_patient_id}")


# ──────────────────────────────────────────────────────────────────────────────
# Background sync helpers
# ──────────────────────────────────────────────────────────────────────────────

async def _sync_single_patient(rme_patient_id: str, response_body: bytes) -> None:
    """Sinkronisasi satu pasien ke Supabase secara background.

    - Jika RME balik 404 → hapus record di Supabase (cleanup stale data).
    - Jika RME balik 200 → upsert name + phone_number ke Supabase.
    Semua error ditangkap agar tidak mengganggu response utama.
    """
    if supabase is None:
        return
    try:
        data = json.loads(response_body.decode("utf-8"))
    except Exception:
        return

    # Jika 404 dari RME → hapus dari Supabase
    # (response_body berupa {"message": "..."} atau {"detail": "..."} saat 404)
    # Tapi kita tidak punya status code di sini — kita periksa strukturnya.
    # Status code diteruskan lewat parameter terpisah via _sync_single_patient_with_status.
    # Fungsi ini dipanggil hanya saat status 200, jadi langsung upsert.

    # Ambil data pasien dari respons RME (bisa nested di "data")
    patient_data = data
    if isinstance(data, dict) and "data" in data:
        patient_data = data["data"]

    if not isinstance(patient_data, dict):
        return

    rme_id = patient_data.get("id") or rme_patient_id
    telepon = patient_data.get("telepon") or patient_data.get("noHp")
    nama = patient_data.get("namaLengkap") or patient_data.get("nama")
    tgl_lahir = patient_data.get("tanggalLahir") or patient_data.get("tanggal_lahir")
    if tgl_lahir:
        tgl_lahir = tgl_lahir.split("T")[0]

    if not telepon:
        return

    phone_normalized = normalize_phone_number(telepon)
    if not phone_normalized:
        return

    def _do_upsert():
        supabase.table("patients").upsert(
            {
                "rme_patient_id": rme_id,
                "phone_number": phone_normalized,
                "name": nama,
                "birthdate": tgl_lahir,
            },
            on_conflict="phone_number",
        ).execute()

    try:
        await asyncio.to_thread(_do_upsert)
        print(f"[PatientSync] Upsert sukses: {rme_id} ({phone_normalized})")
    except Exception as exc:
        print(f"[PatientSync] Gagal upsert {rme_id}: {exc}")


async def _sync_single_patient_with_status(rme_patient_id: str, response: Response) -> None:
    """Wrapper: cek status code dulu, baru sync atau hapus."""
    if supabase is None:
        return

    try:
        if response.status_code == 404:
            # Pasien sudah tidak ada di RME → hapus dari Supabase
            def _do_delete():
                supabase.table("patients").delete().eq("rme_patient_id", rme_patient_id).execute()
            await asyncio.to_thread(_do_delete)
            print(f"[PatientSync] Pasien {rme_patient_id} tidak ada di RME → dihapus dari Supabase")
        elif response.status_code < 400:
            await _sync_single_patient(rme_patient_id, response.body)
    except Exception as exc:
        print(f"[PatientSync] Error sync {rme_patient_id}: {exc}")


async def _sync_patients_list(response_body: bytes) -> None:
    """Sinkronisasi daftar pasien dari respons GET all ke Supabase secara background."""
    if supabase is None:
        return
    try:
        data = json.loads(response_body.decode("utf-8"))
    except Exception:
        return

    # Normalkan ke list — RME bisa nested di data.data atau langsung list
    patients: list = []
    if isinstance(data, list):
        patients = data
    elif isinstance(data, dict):
        inner = data.get("data", data)
        if isinstance(inner, list):
            patients = inner
        elif isinstance(inner, dict):
            patients = inner.get("data", [])

    if not patients:
        return

    def _do_upsert_batch(rows: list):
        supabase.table("patients").upsert(rows, on_conflict="phone_number").execute()

    rows = []
    for p in patients:
        if not isinstance(p, dict):
            continue
        rme_id = p.get("id")
        telepon = p.get("telepon") or p.get("noHp")
        nama = p.get("namaLengkap") or p.get("nama")
        tgl_lahir = p.get("tanggalLahir") or p.get("tanggal_lahir")
        if tgl_lahir:
            tgl_lahir = tgl_lahir.split("T")[0]

        if not rme_id or not telepon:
            continue

        phone_normalized = normalize_phone_number(telepon)
        if not phone_normalized:
            continue

        rows.append({
            "rme_patient_id": rme_id,
            "phone_number": phone_normalized,
            "name": nama,
            "birthdate": tgl_lahir,
        })

    if not rows:
        return

    try:
        await asyncio.to_thread(_do_upsert_batch, rows)
        print(f"[PatientSync] Batch upsert {len(rows)} pasien selesai")
    except Exception as exc:
        print(f"[PatientSync] Gagal batch upsert: {exc}")


async def _sync_all_patients_on_startup() -> None:
    """Sinkronisasi semua pasien dari RME ke Supabase saat server startup.

    Fetch halaman demi halaman (limit 100) sampai habis, lalu batch upsert ke Supabase.
    Semua error ditangkap agar tidak mengganggu startup.
    """
    if supabase is None:
        return

    print("[PatientSync] Startup sync dimulai — mengambil semua pasien dari RME...")
    page = 1
    total_synced = 0

    while True:
        try:
            response = await proxy_smartclinic(
                "GET",
                SMARTCLINIC_BASE_URL,
                SMARTCLINIC_PATIENTS_PATH,
                params=[("page", str(page)), ("limit", "100")],
            )

            if response.status_code >= 400:
                print(f"[PatientSync] Startup sync: RME balik {response.status_code} pada page {page}, berhenti.")
                break

            await _sync_patients_list(response.body)

            # Cek apakah masih ada halaman berikutnya
            try:
                data = json.loads(response.body.decode("utf-8"))
                # Ambil list pasien dari nested response
                patients_list: list = []
                if isinstance(data, list):
                    patients_list = data
                elif isinstance(data, dict):
                    inner = data.get("data", data)
                    if isinstance(inner, list):
                        patients_list = inner
                    elif isinstance(inner, dict):
                        patients_list = inner.get("data", [])

                total_synced += len(patients_list)

                # Kalau hasil kurang dari 100, berarti sudah halaman terakhir
                if len(patients_list) < 100:
                    break
            except Exception:
                break

            page += 1

        except Exception as exc:
            print(f"[PatientSync] Startup sync error pada page {page}: {exc}")
            break

    print(f"[PatientSync] Startup sync selesai — total {total_synced} pasien diproses dari {page} halaman.")


# ──────────────────────────────────────────────────────────────────────────────
# GET endpoints
# ──────────────────────────────────────────────────────────────────────────────


@router.get(
    "",
    summary="Ambil semua data pasien",
    description="Meneruskan seluruh query params ke SmartClinic tanpa perubahan. Sinkronisasi data ke Supabase berjalan di background.",
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

    response = await proxy_smartclinic("GET", SMARTCLINIC_BASE_URL, SMARTCLINIC_PATIENTS_PATH, params=query_params)

    # Sinkronisasi asinkronus di latar belakang — tidak memblokir response
    if response.status_code < 400:
        asyncio.create_task(_sync_patients_list(response.body))

    return response


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
    request: Request,
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
    try:
        response = await proxy_smartclinic(
            "POST",
            SMARTCLINIC_BASE_URL,
            SMARTCLINIC_PATIENTS_PATH,
            json=payload.model_dump(exclude_none=True),
        )
        if response.status_code >= 400:
            return response

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
            rollback_error = None
            try:
                await _delete_patient_in_smartclinic(rme_patient_id)
            except Exception as rollback_exc:
                rollback_error = rollback_exc

            if rollback_error is not None:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Gagal menyimpan mapping pasien ke Supabase dan gagal rollback data RME: "
                        f"{exc}; rollback: {rollback_error}"
                    ),
                ) from exc

            raise HTTPException(
                status_code=500,
                detail=f"Gagal menyimpan mapping pasien ke Supabase, data RME sudah dihapus lagi: {exc}",
            ) from exc

        await log_activity(
            category="patients",
            action="CREATE_PATIENT",
            from_actor=request.client.host if request.client else "system",
            message=f"Pasien baru terdaftar: {payload.namaLengkap}",
            metadata={
                "phone": normalize_phone_number(payload.telepon),
                "name": payload.namaLengkap,
                "nik": payload.nik,
            },
        )

        return response
    except Exception as exc:
        await log_activity(
            category="patients",
            action="CREATE_PATIENT_FAILED",
            from_actor=request.client.host if request.client else "system",
            message=f"Gagal terdaftar pasien: {payload.namaLengkap}",
            metadata={"error": str(exc)},
        )
        raise exc


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
    normalized_phone = normalize_phone_number(phone)
    rme_patient_id = get_rme_patient_id_by_phone(
        normalized_phone,
        not_found_detail=f"Pasien dengan nomor {normalized_phone} tidak ditemukan",
    )

    response = await proxy_smartclinic("GET", SMARTCLINIC_BASE_URL, f"{SMARTCLINIC_PATIENTS_PATH}/{rme_patient_id}")

    # Sinkronisasi asinkronus di latar belakang
    asyncio.create_task(_sync_single_patient_with_status(rme_patient_id, response))

    return response


# @router.get(
#     "/rm/{noRm}",
#     summary="Ambil data pasien berdasarkan nomor RM",
#     responses={
#         200: {
#             "description": "Pasien berhasil diambil",
#             "content": {"application/json": {"example": PATIENT_EXAMPLE}},
#         },
#         404: {
#             "description": "Pasien tidak ditemukan",
#             "content": {"application/json": {"example": PATIENT_ERROR_EXAMPLE}},
#         },
#         500: {
#             "description": "Gagal mengambil pasien",
#             "content": {"application/json": {"example": {"detail": "..."}}},
#         },
#     },
# )
# async def get_patient_by_rm(noRm: str = Path(..., description="Nomor RM pasien")):
#     return await proxy_smartclinic("GET", SMARTCLINIC_BASE_URL, f"{SMARTCLINIC_PATIENTS_PATH}/rm/{noRm}")


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
    response = await proxy_smartclinic("GET", SMARTCLINIC_BASE_URL, f"{SMARTCLINIC_PATIENTS_PATH}/{rme_patient_id}")

    # Sinkronisasi asinkronus di latar belakang
    # Jika 404 → otomatis cleanup record stale di Supabase
    asyncio.create_task(_sync_single_patient_with_status(rme_patient_id, response))

    return response


# ──────────────────────────────────────────────────────────────────────────────
# PUT / DELETE
# ──────────────────────────────────────────────────────────────────────────────

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
    response = await proxy_smartclinic(
        "PUT",
        SMARTCLINIC_BASE_URL,
        f"{SMARTCLINIC_PATIENTS_PATH}/{rme_patient_id}",
        json=payload.model_dump(exclude_none=True),
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
    response = await proxy_smartclinic("DELETE", SMARTCLINIC_BASE_URL, f"{SMARTCLINIC_PATIENTS_PATH}/{rme_patient_id}")
    if response.status_code < 400 and supabase is not None:
        supabase.table("patients").delete().eq("rme_patient_id", rme_patient_id).execute()
    return response
