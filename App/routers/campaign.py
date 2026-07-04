# ======================================================
# SmartClinic CRM AI — routers/campaign.py
# Endpoint: /api/marketing/campaigns
#
# Last Change   :   11 Jun 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

import asyncio
from datetime import datetime, timedelta, timezone
import os
import re
import shutil
from uuid import uuid4

from fastapi import APIRouter, Body, File, Form, HTTPException, Path, UploadFile, Request

from App.activity_logger import log_activity
from App.config import supabase
from App.helpers import _require_supabase, save_image_from_bytes, save_image_from_url
from App.models import CampaignRecord, SaveCampaignPayload, UpdateCampaignPayload

router = APIRouter(prefix="/api/marketing/campaigns", tags=["Marketing Campaigns"])

CAMPAIGN_UPLOAD_DIR = os.path.join("chat_state", "campaign_uploads")
os.makedirs(CAMPAIGN_UPLOAD_DIR, exist_ok=True)


CAMPAIGN_EXAMPLE = {
    "id": "7f5f4ce1-7d7a-4f6d-9c01-2db0b1f5a111",
    "campaign_name": "Promo Cek Gigi Mei",
    "schedule_date": "2026-05-25T09:00:00Z",
    "campaign_message": "Halo pasien SmartClinic, promo cek gigi bulan ini tersedia sampai akhir Mei.",
    "attachment_url": "https://example.com/promo-cekgigi.jpg",
    "filename": "promo-cekgigi.jpg",
    "status": "scheduled",
    "created_at": "2026-05-22T10:00:00Z",
    "updated_at": "2026-05-22T10:00:00Z",
}

CAMPAIGN_LIST_EXAMPLE = [
    CAMPAIGN_EXAMPLE,
    {
        **CAMPAIGN_EXAMPLE,
        "id": "8c6f4ce1-7d7a-4f6d-9c01-2db0b1f5a222",
        "campaign_name": "Promo Scaling Gigi Juni",
        "schedule_date": "2026-06-02T09:00:00Z",
        "campaign_message": "Promo scaling gigi bulan ini tersedia dengan kuota terbatas.",
        "attachment_url": "file://chat_state/campaign_uploads/demo-scaling-gigi.pdf",
        "filename": "demo-scaling-gigi.pdf",
        "status": "sent",
    },
]

SUCCESS_MESSAGE_EXAMPLE = {
    "status": "ok",
    "message": "Campaign berhasil diproses",
}

ERROR_EXAMPLE = {
    "detail": "Campaign 'Promo Cek Gigi Mei' tidak ditemukan",
}


def _campaign_select_columns() -> str:
    return "id, campaign_name, schedule_date, campaign_message, attachment_url, filename, status, campaign_type, recurrence, last_run_date, image_url, created_at, updated_at"


def _campaign_row(record: dict) -> dict:
    return {
        "id": record.get("id"),
        "campaign_name": record.get("campaign_name"),
        "schedule_date": record.get("schedule_date"),
        "campaign_message": record.get("campaign_message"),
        "attachment_url": record.get("attachment_url"),
        "filename": record.get("filename"),
        "status": record.get("status"),
        "campaign_type": record.get("campaign_type", "standard"),
        "recurrence": record.get("recurrence", "once"),
        "last_run_date": record.get("last_run_date"),
        "image_url": record.get("image_url"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }


def _parse_schedule_date(schedule_date: datetime | str) -> datetime:
    if isinstance(schedule_date, datetime):
        return schedule_date.astimezone(timezone.utc) if schedule_date.tzinfo else schedule_date.replace(tzinfo=timezone.utc)

    normalized = schedule_date.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="schedule_date harus format ISO 8601 yang valid") from exc


def _validate_schedule_date(schedule_date: datetime | str):
    campaign_time = _parse_schedule_date(schedule_date)
    now = datetime.now(timezone.utc) if campaign_time.tzinfo else datetime.now()
    if campaign_time < now + timedelta(minutes=10):
        raise HTTPException(status_code=400, detail="schedule_date minimal 10 menit dari sekarang")


def _serialize_schedule_date(schedule_date: datetime | str | None) -> str | None:
    if schedule_date is None:
        return None
    campaign_time = _parse_schedule_date(schedule_date)
    return campaign_time.isoformat()


def _sanitize_filename(filename: str | None) -> str:
    base_name = os.path.basename(filename or "upload")
    safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", base_name).strip("._")
    return safe_name or "upload"


def _store_campaign_attachment(file: UploadFile) -> tuple[str, str]:
    safe_name = _sanitize_filename(file.filename)
    stored_name = f"{uuid4()}-{safe_name}"
    stored_path = os.path.join(CAMPAIGN_UPLOAD_DIR, stored_name)

    file.file.seek(0)
    with open(stored_path, "wb") as output_handle:
        shutil.copyfileobj(file.file, output_handle)

    relative_path = os.path.relpath(stored_path).replace(os.sep, "/")
    return f"file://{relative_path}", safe_name


@router.get(
    "",
    response_model=list[CampaignRecord],
    summary="Ambil semua campaign",
    description="Mengembalikan semua campaign yang tersimpan, tanpa limit default, kecuali yang canceled jika include_canceled=false.",
    responses={
        200: {
            "description": "Campaign berhasil diambil",
            "content": {"application/json": {"example": CAMPAIGN_LIST_EXAMPLE}},
        },
        500: {
            "description": "Gagal mengambil campaign",
            "content": {"application/json": {"example": ERROR_EXAMPLE}},
        },
    },
)
def get_all_campaigns(include_canceled: bool = False):
    _require_supabase()
    try:
        response = (
            supabase.table("campaigns")
            .select(_campaign_select_columns())
            .execute()
        )
        campaigns = response.data or []
        if not include_canceled:
            campaigns = [row for row in campaigns if row.get("status") != "canceled"]
        
        # Urutkan: tipe birthday di atas, sisanya diurutkan berdasarkan campaign_name secara alfabetis
        campaigns.sort(key=lambda x: (x.get("campaign_type") != "birthday", x.get("campaign_name", "")))
        return [_campaign_row(row) for row in campaigns]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/by-name/{campaign_name}",
    response_model=CampaignRecord,
    summary="Ambil campaign berdasarkan nama",
    responses={
        200: {
            "description": "Campaign ditemukan",
            "content": {"application/json": {"example": CAMPAIGN_EXAMPLE}},
        },
        404: {
            "description": "Campaign tidak ditemukan",
            "content": {"application/json": {"example": ERROR_EXAMPLE}},
        },
        500: {
            "description": "Gagal mengambil campaign",
            "content": {"application/json": {"example": ERROR_EXAMPLE}},
        },
    },
)
def get_campaign_by_name(campaign_name: str = Path(..., description="Nama campaign yang dicari", examples=["Promo Cek Gigi Mei"])):
    _require_supabase()
    try:
        response = (
            supabase.table("campaigns")
            .select(_campaign_select_columns())
            .eq("campaign_name", campaign_name)
            .limit(1)
            .execute()
        )
        if not response.data:
            raise HTTPException(status_code=404, detail=f"Campaign '{campaign_name}' tidak ditemukan")
        return _campaign_row(response.data[0])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# @router.get(
#     "/template/latest",
#     response_model=CampaignRecord,
#     summary="Ambil template campaign dari campaign terakhir",
#     description="Dipakai frontend untuk prefill campaign baru dari campaign sebelumnya.",
#     responses={
#         200: {
#             "description": "Template campaign berhasil diambil",
#             "content": {"application/json": {"example": CAMPAIGN_EXAMPLE}},
#         },
#         404: {
#             "description": "Belum ada campaign",
#             "content": {"application/json": {"example": {"detail": "Belum ada campaign untuk dijadikan template"}}},
#         },
#         500: {
#             "description": "Gagal mengambil template",
#             "content": {"application/json": {"example": ERROR_EXAMPLE}},
#         },
#     },
# )
# def get_latest_campaign_template():
#     _require_supabase()
#     try:
#         response = (
#             supabase.table("campaigns")
#             .select(_campaign_select_columns())
#             .order("created_at", desc=True)
#             .limit(1)
#             .execute()
#         )
#         if not response.data:
#             raise HTTPException(status_code=404, detail="Belum ada campaign untuk dijadikan template")
#         return _campaign_row(response.data[0])
#     except HTTPException:
#         raise
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "",
    response_model=CampaignRecord,
    summary="Buat campaign baru",
    description="Endpoint opsional untuk menyimpan campaign marketing baru ke Supabase.",
    responses={
        200: {
            "description": "Campaign berhasil dibuat",
            "content": {"application/json": {"example": CAMPAIGN_EXAMPLE}},
        },
        500: {
            "description": "Campaign gagal disimpan",
            "content": {"application/json": {"example": {"detail": "Campaign gagal disimpan"}}},
        },
    },
)
async def create_campaign(
    request: Request,
    payload: SaveCampaignPayload = Body(
        ...,
        examples={
            "campaignExample": {
                "summary": "Contoh request create campaign",
                "value": {
                    "campaign_name": "Promo Cek Gigi Mei",
                    "schedule_date": "2026-05-25T09:00:00Z",
                    "campaign_message": "Halo pasien SmartClinic, promo cek gigi bulan ini tersedia sampai akhir Mei.",
                    "attachment_url": "https://example.com/promo-cekgigi.jpg",
                    "filename": "promo-cekgigi.jpg",
                    "status": "scheduled",
                },
            }
        },
    )
):
    _require_supabase()
    try:
        if payload.schedule_date:
            _validate_schedule_date(payload.schedule_date)

        # Resolve image_url jika bertipe gambar
        image_url = payload.image_url
        if not image_url and payload.attachment_url:
            image_url = save_image_from_url(payload.attachment_url, payload.filename)

        insert_data = {
            "campaign_name": payload.campaign_name,
            "schedule_date": _serialize_schedule_date(payload.schedule_date) if payload.schedule_date else None,
            "campaign_message": payload.campaign_message,
            "attachment_url": payload.attachment_url,
            "filename": payload.filename,
            "status": payload.status or "scheduled",
            "campaign_type": payload.campaign_type or "standard",
            "recurrence": payload.recurrence or "once",
            "image_url": image_url,
        }
        response = await asyncio.to_thread(
            lambda: supabase.table("campaigns").insert(insert_data).execute()
        )
        if not response.data:
            raise HTTPException(status_code=500, detail="Campaign gagal disimpan")
        
        await log_activity(
            category="marketing",
            action="CREATE_CAMPAIGN",
            from_actor=request.client.host if request.client else "system",
            message=f"Campaign baru dibuat: {payload.campaign_name}",
            metadata={
                "campaign_name": payload.campaign_name,
                "status": payload.status or "scheduled",
                "schedule_date": payload.schedule_date.isoformat() if payload.schedule_date else None,
            },
        )
        
        return _campaign_row(response.data[0])
    except HTTPException:
        raise
    except Exception as e:
        await log_activity(
            category="marketing",
            action="CREATE_CAMPAIGN_FAILED",
            from_actor=request.client.host if request.client else "system",
            message=f"Gagal buat campaign: {payload.campaign_name}",
            metadata={"error": str(e)},
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.patch(
    "/by-name/{campaign_name}",
    response_model=CampaignRecord,
    summary="Edit campaign berdasarkan nama",
    responses={
        200: {
            "description": "Campaign berhasil diupdate",
            "content": {"application/json": {"example": CAMPAIGN_EXAMPLE}},
        },
        400: {
            "description": "Tidak ada field yang diupdate",
            "content": {"application/json": {"example": {"detail": "Tidak ada field yang diupdate"}}},
        },
        404: {
            "description": "Campaign tidak ditemukan",
            "content": {"application/json": {"example": ERROR_EXAMPLE}},
        },
        500: {
            "description": "Campaign gagal diupdate",
            "content": {"application/json": {"example": ERROR_EXAMPLE}},
        },
    },
)
async def update_campaign(
    request: Request,
    campaign_name: str = Path(..., description="Nama campaign yang akan diedit", examples=["Promo Cek Gigi Mei"]),
    payload: UpdateCampaignPayload = Body(
        ...,
        examples={
            "campaignUpdateExample": {
                "summary": "Contoh request edit campaign",
                "value": {
                    "schedule_date": "2026-05-26T09:00:00Z",
                    "campaign_message": "Promo cek gigi diperpanjang sampai akhir Mei.",
                    "attachment_url": "https://example.com/promo-cekgigi.jpg",
                    "filename": "promo-cekgigi.jpg",
                    "status": "scheduled",
                },
            }
        },
    ),
):
    _require_supabase()
    try:
        if payload.schedule_date:
            _validate_schedule_date(payload.schedule_date)

        # Dapatkan campaign yang ada untuk memeriksa tipe
        check_resp = await asyncio.to_thread(
            lambda: supabase.table("campaigns").select("campaign_type").eq("campaign_name", campaign_name).limit(1).execute()
        )
        is_birthday = False
        if check_resp.data and check_resp.data[0].get("campaign_type") == "birthday":
            is_birthday = True

        update_data = {key: value for key, value in payload.model_dump().items() if value is not None}
        
        if is_birthday:
            if "status" in update_data and update_data["status"] not in ("active", "disabled"):
                raise HTTPException(status_code=400, detail="Status untuk campaign ulang tahun hanya boleh 'active' atau 'disabled'")
            if "schedule_date" in update_data:
                raise HTTPException(status_code=400, detail="Campaign ulang tahun tidak menggunakan schedule_date")

        # Resolve image_url if attachment_url is being updated and no custom image_url was sent
        if "attachment_url" in update_data and "image_url" not in update_data:
            resolved_img = save_image_from_url(update_data["attachment_url"], update_data.get("filename"))
            if resolved_img:
                update_data["image_url"] = resolved_img

        if "schedule_date" in update_data and update_data["schedule_date"]:
            update_data["schedule_date"] = _serialize_schedule_date(update_data["schedule_date"])
        if not update_data:
            raise HTTPException(status_code=400, detail="Tidak ada field yang diupdate")

        response = await asyncio.to_thread(
            lambda: supabase.table("campaigns")
            .update(update_data)
            .eq("campaign_name", campaign_name)
            .execute()
        )
        if not response.data:
            raise HTTPException(status_code=404, detail=f"Campaign '{campaign_name}' tidak ditemukan")
        
        await log_activity(
            category="marketing",
            action="UPDATE_CAMPAIGN",
            from_actor=request.client.host if request.client else "system",
            message=f"Campaign diperbarui: {campaign_name}",
            metadata={
                "campaign_name": campaign_name,
                "updated_fields": list(update_data.keys()),
            },
        )
        
        return _campaign_row(response.data[0])
    except HTTPException:
        raise
    except Exception as e:
        await log_activity(
            category="marketing",
            action="UPDATE_CAMPAIGN_FAILED",
            from_actor=request.client.host if request.client else "system",
            message=f"Gagal update campaign: {campaign_name}",
            metadata={"error": str(e)},
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/upload",
    response_model=CampaignRecord,
    summary="Buat campaign baru dengan file upload",
    description=(
        "Buat campaign marketing lewat multipart/form-data. Endpoint ini menerima jam campaign sebagai ISO 8601, "
        "dan attachment bisa di-upload langsung tanpa perlu URL eksternal."
    ),
    responses={
        200: {
            "description": "Campaign berhasil dibuat",
            "content": {"application/json": {"example": CAMPAIGN_EXAMPLE}},
        },
        500: {
            "description": "Campaign gagal disimpan",
            "content": {"application/json": {"example": {"detail": "Campaign gagal disimpan"}}},
        },
    },
)
async def create_campaign_with_upload(
    request: Request,
    campaign_name: str = Form(..., description="Nama campaign", examples=["Promo Cek Gigi Mei"]),
    schedule_date: datetime = Form(..., description="Waktu campaign (ISO 8601)", examples=["2026-05-25T09:00:00Z"]),
    campaign_message: str = Form(..., description="Isi pesan campaign", examples=["Halo pasien SmartClinic, promo cek gigi bulan ini tersedia sampai akhir Mei."]),
    status: str = Form(default="scheduled", description="Status campaign", examples=["scheduled"]),
    file: UploadFile | None = File(default=None, description="Attachment file campaign (opsional)"),
    attachment_url: str | None = Form(default=None, description="URL attachment eksternal jika tidak upload file", examples=["https://example.com/promo-cekgigi.jpg"]),
):
    _require_supabase()
    try:
        _validate_schedule_date(schedule_date)

        resolved_attachment_url = attachment_url
        resolved_filename = None
        image_url = None
        if file is not None:
            file.file.seek(0)
            file_bytes = file.file.read()
            resolved_attachment_url, resolved_filename = _store_campaign_attachment(file)
            image_url = save_image_from_bytes(file_bytes, file.filename or "upload")
        elif attachment_url:
            resolved_filename = _sanitize_filename(attachment_url.rsplit("/", 1)[-1])
            image_url = save_image_from_url(attachment_url, resolved_filename)

        insert_data = {
            "campaign_name": campaign_name,
            "schedule_date": schedule_date.astimezone(timezone.utc).isoformat() if schedule_date.tzinfo else schedule_date.replace(tzinfo=timezone.utc).isoformat(),
            "campaign_message": campaign_message,
            "attachment_url": resolved_attachment_url,
            "filename": resolved_filename,
            "status": status or "scheduled",
            "image_url": image_url,
        }
        response = await asyncio.to_thread(
            lambda: supabase.table("campaigns").insert(insert_data).execute()
        )
        if not response.data:
            raise HTTPException(status_code=500, detail="Campaign gagal disimpan")
        
        await log_activity(
            category="marketing",
            action="CREATE_CAMPAIGN_WITH_UPLOAD",
            from_actor=request.client.host if request.client else "system",
            message=f"Campaign dengan file upload dibuat: {campaign_name}",
            metadata={
                "campaign_name": campaign_name,
                "filename": resolved_filename,
                "status": status or "scheduled",
                "schedule_date": schedule_date.isoformat(),
            },
        )
        
        return _campaign_row(response.data[0])
    except HTTPException:
        raise
    except Exception as e:
        await log_activity(
            category="marketing",
            action="CREATE_CAMPAIGN_WITH_UPLOAD_FAILED",
            from_actor=request.client.host if request.client else "system",
            message=f"Gagal buat campaign dengan upload: {campaign_name}",
            metadata={"error": str(e)},
        )
        raise HTTPException(status_code=500, detail=str(e))


# @router.patch(
#     "/by-name/{campaign_name}/cancel",
#     response_model=CampaignRecord,
#     summary="Cancel campaign berdasarkan nama",
#     description="Menandai campaign sebagai canceled tanpa menghapus datanya.",
#     responses={
#         200: {
#             "description": "Campaign berhasil dibatalkan",
#             "content": {"application/json": {"example": {**CAMPAIGN_EXAMPLE, "status": "canceled"}}},
#         },
#         404: {
#             "description": "Campaign tidak ditemukan",
#             "content": {"application/json": {"example": ERROR_EXAMPLE}},
#         },
#         500: {
#             "description": "Campaign gagal dibatalkan",
#             "content": {"application/json": {"example": ERROR_EXAMPLE}},
#         },
#     },
# )
# def cancel_campaign(campaign_name: str = Path(..., description="Nama campaign yang akan dibatalkan", examples=["Promo Cek Gigi Mei"])):
#     _require_supabase()
#     try:
#         response = (
#             supabase.table("campaigns")
#             .update({"status": "canceled"})
#             .eq("campaign_name", campaign_name)
#             .execute()
#         )
#         if not response.data:
#             raise HTTPException(status_code=404, detail=f"Campaign '{campaign_name}' tidak ditemukan")
#         return _campaign_row(response.data[0])
#     except HTTPException:
#         raise
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/by-name/{campaign_name}",
    summary="Hapus campaign berdasarkan nama",
    responses={
        200: {
            "description": "Campaign berhasil dihapus",
            "content": {"application/json": {"example": {"status": "ok", "message": "Campaign '...' berhasil dihapus"}}},
        },
        400: {
            "description": "Campaign ulang tahun tidak bisa dihapus",
            "content": {"application/json": {"example": {"detail": "Campaign ulang tahun tidak dapat dihapus, hanya bisa dinonaktifkan"}}},
        },
        404: {
            "description": "Campaign tidak ditemukan",
            "content": {"application/json": {"example": ERROR_EXAMPLE}},
        },
        500: {
            "description": "Gagal menghapus campaign",
            "content": {"application/json": {"example": ERROR_EXAMPLE}},
        },
    },
)
async def delete_campaign(
    request: Request,
    campaign_name: str = Path(..., description="Nama campaign yang akan dihapus", examples=["Promo Cek Gigi Mei"]),
):
    _require_supabase()
    try:
        check_resp = await asyncio.to_thread(
            lambda: supabase.table("campaigns").select("campaign_type").eq("campaign_name", campaign_name).limit(1).execute()
        )
        if not check_resp.data:
            raise HTTPException(status_code=404, detail=f"Campaign '{campaign_name}' tidak ditemukan")
        
        if check_resp.data[0].get("campaign_type") == "birthday":
            raise HTTPException(status_code=400, detail="Campaign ulang tahun tidak dapat dihapus, hanya bisa dinonaktifkan")
            
        response = await asyncio.to_thread(
            lambda: supabase.table("campaigns").delete().eq("campaign_name", campaign_name).execute()
        )
        if not response.data:
             raise HTTPException(status_code=404, detail=f"Campaign '{campaign_name}' tidak ditemukan")
             
        await log_activity(
            category="marketing",
            action="DELETE_CAMPAIGN",
            from_actor=request.client.host if request.client else "system",
            message=f"Campaign dihapus: {campaign_name}",
            metadata={"campaign_name": campaign_name}
        )
        return {"status": "ok", "message": f"Campaign '{campaign_name}' berhasil dihapus"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
