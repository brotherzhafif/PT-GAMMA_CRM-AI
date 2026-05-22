# ======================================================
# SmartClinic CRM AI — routers/campaign.py
# Endpoint: /api/marketing/campaigns
#
# Last Change   :   22 May 2026
# Developer     :   GitHub Copilot
# ======================================================

from fastapi import APIRouter, Body, HTTPException, Path

from App.config import supabase
from App.helpers import _require_supabase
from App.models import CampaignRecord, SaveCampaignPayload, UpdateCampaignPayload

router = APIRouter(prefix="/api/marketing/campaigns", tags=["Marketing Campaigns"])


CAMPAIGN_EXAMPLE = {
    "id": "7f5f4ce1-7d7a-4f6d-9c01-2db0b1f5a111",
    "campaign_name": "Promo Cek Gigi Mei",
    "schedule_date": "2026-05-25T09:00:00Z",
    "campaign_message": "Halo pasien SmartClinic, promo cek gigi bulan ini tersedia sampai akhir Mei.",
    "status": "draft",
    "created_at": "2026-05-22T10:00:00Z",
    "updated_at": "2026-05-22T10:00:00Z",
}

SUCCESS_MESSAGE_EXAMPLE = {
    "status": "ok",
    "message": "Campaign berhasil diproses",
}

ERROR_EXAMPLE = {
    "detail": "Campaign 'Promo Cek Gigi Mei' tidak ditemukan",
}


def _campaign_select_columns() -> str:
    return "id, campaign_name, schedule_date, campaign_message, status, created_at, updated_at"


def _campaign_row(record: dict) -> dict:
    return {
        "id": record.get("id"),
        "campaign_name": record.get("campaign_name"),
        "schedule_date": record.get("schedule_date"),
        "campaign_message": record.get("campaign_message"),
        "status": record.get("status"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }


@router.get(
    "",
    response_model=list[CampaignRecord],
    summary="Ambil semua campaign",
    description="Mengembalikan campaign name, schedule date, campaign message, dan metadata status.",
    responses={
        200: {
            "description": "Campaign berhasil diambil",
            "content": {"application/json": {"example": [CAMPAIGN_EXAMPLE]}},
        },
        500: {
            "description": "Gagal mengambil campaign",
            "content": {"application/json": {"example": ERROR_EXAMPLE}},
        },
    },
)
def get_all_campaigns(limit: int = 100, include_canceled: bool = False):
    _require_supabase()
    try:
        response = (
            supabase.table("campaigns")
            .select(_campaign_select_columns())
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        campaigns = response.data or []
        if not include_canceled:
            campaigns = [row for row in campaigns if row.get("status") != "canceled"]
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


@router.get(
    "/template/latest",
    response_model=CampaignRecord,
    summary="Ambil template campaign dari campaign terakhir",
    description="Dipakai frontend untuk prefill campaign baru dari campaign sebelumnya.",
    responses={
        200: {
            "description": "Template campaign berhasil diambil",
            "content": {"application/json": {"example": CAMPAIGN_EXAMPLE}},
        },
        404: {
            "description": "Belum ada campaign",
            "content": {"application/json": {"example": {"detail": "Belum ada campaign untuk dijadikan template"}}},
        },
        500: {
            "description": "Gagal mengambil template",
            "content": {"application/json": {"example": ERROR_EXAMPLE}},
        },
    },
)
def get_latest_campaign_template():
    _require_supabase()
    try:
        response = (
            supabase.table("campaigns")
            .select(_campaign_select_columns())
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not response.data:
            raise HTTPException(status_code=404, detail="Belum ada campaign untuk dijadikan template")
        return _campaign_row(response.data[0])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
def create_campaign(
    payload: SaveCampaignPayload = Body(
        ...,
        examples={
            "campaignExample": {
                "summary": "Contoh request create campaign",
                "value": {
                    "campaign_name": "Promo Cek Gigi Mei",
                    "schedule_date": "2026-05-25T09:00:00Z",
                    "campaign_message": "Halo pasien SmartClinic, promo cek gigi bulan ini tersedia sampai akhir Mei.",
                    "status": "draft",
                },
            }
        },
    )
):
    _require_supabase()
    try:
        insert_data = {
            "campaign_name": payload.campaign_name,
            "schedule_date": payload.schedule_date,
            "campaign_message": payload.campaign_message,
            "status": payload.status or "draft",
        }
        response = supabase.table("campaigns").insert(insert_data).execute()
        if not response.data:
            raise HTTPException(status_code=500, detail="Campaign gagal disimpan")
        return _campaign_row(response.data[0])
    except HTTPException:
        raise
    except Exception as e:
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
def update_campaign(
    campaign_name: str = Path(..., description="Nama campaign yang akan diedit", examples=["Promo Cek Gigi Mei"]),
    payload: UpdateCampaignPayload = Body(
        ...,
        examples={
            "campaignUpdateExample": {
                "summary": "Contoh request edit campaign",
                "value": {
                    "schedule_date": "2026-05-26T09:00:00Z",
                    "campaign_message": "Promo cek gigi diperpanjang sampai akhir Mei.",
                    "status": "scheduled",
                },
            }
        },
    ),
):
    _require_supabase()
    try:
        update_data = {key: value for key, value in payload.model_dump().items() if value is not None}
        if not update_data:
            raise HTTPException(status_code=400, detail="Tidak ada field yang diupdate")

        response = (
            supabase.table("campaigns")
            .update(update_data)
            .eq("campaign_name", campaign_name)
            .execute()
        )
        if not response.data:
            raise HTTPException(status_code=404, detail=f"Campaign '{campaign_name}' tidak ditemukan")
        return _campaign_row(response.data[0])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/by-name/{campaign_name}",
    response_model=CampaignRecord,
    summary="Cancel campaign berdasarkan nama",
    description="Menandai campaign sebagai canceled tanpa menghapus datanya.",
    responses={
        200: {
            "description": "Campaign berhasil dibatalkan",
            "content": {"application/json": {"example": {**CAMPAIGN_EXAMPLE, "status": "canceled"}}},
        },
        404: {
            "description": "Campaign tidak ditemukan",
            "content": {"application/json": {"example": ERROR_EXAMPLE}},
        },
        500: {
            "description": "Campaign gagal dibatalkan",
            "content": {"application/json": {"example": ERROR_EXAMPLE}},
        },
    },
)
def cancel_campaign(campaign_name: str = Path(..., description="Nama campaign yang akan dibatalkan", examples=["Promo Cek Gigi Mei"])):
    _require_supabase()
    try:
        response = (
            supabase.table("campaigns")
            .update({"status": "canceled"})
            .eq("campaign_name", campaign_name)
            .execute()
        )
        if not response.data:
            raise HTTPException(status_code=404, detail=f"Campaign '{campaign_name}' tidak ditemukan")
        return _campaign_row(response.data[0])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))