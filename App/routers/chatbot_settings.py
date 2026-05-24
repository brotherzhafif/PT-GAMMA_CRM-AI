from datetime import datetime, timezone

from fastapi import APIRouter, Body, HTTPException

from App.config import supabase
from App.helpers import _require_supabase
from App.models import ChatbotSettingsRecord, UpdateChatbotSettingsPayload

router = APIRouter(prefix="/api/chatbot-settings", tags=["System"])


CHATBOT_SETTINGS_EXAMPLE = {
    "id": "2f4d52c2-1111-4b5f-9b5d-1b2c3d4e5f67",
    "ai_name": "SmartClinic AI",
    "primary_language": "id",
    "conversation_tone": "friendly",
    "handoff_threshold": 70,
    "handoff_message": "Mohon tunggu sebentar, admin kami akan segera membantu.",
    "ai_badge_enabled": True,
    "created_at": "2026-05-25T10:00:00Z",
    "updated_at": "2026-05-25T10:00:00Z",
}


def _chatbot_settings_columns() -> str:
    return "id, ai_name, primary_language, conversation_tone, handoff_threshold, handoff_message, ai_badge_enabled, created_at, updated_at"


def _chatbot_settings_row(record: dict) -> dict:
    return {
        "id": record.get("id"),
        "ai_name": record.get("ai_name"),
        "primary_language": record.get("primary_language"),
        "conversation_tone": record.get("conversation_tone"),
        "handoff_threshold": record.get("handoff_threshold"),
        "handoff_message": record.get("handoff_message"),
        "ai_badge_enabled": record.get("ai_badge_enabled"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }


def _get_single_settings_row() -> dict:
    _require_supabase()
    response = supabase.table("chatbot_settings").select(_chatbot_settings_columns()).order("created_at", desc=False).limit(1).execute()
    if not response.data:
        raise HTTPException(status_code=404, detail="Chatbot settings belum ditemukan")
    return response.data[0]


@router.get(
    "",
    response_model=ChatbotSettingsRecord,
    summary="Ambil chatbot settings",
    description="Mengembalikan satu baris settings chatbot dari Supabase.",
    responses={
        200: {
            "description": "Settings berhasil diambil",
            "content": {"application/json": {"example": CHATBOT_SETTINGS_EXAMPLE}},
        },
        404: {
            "description": "Settings tidak ditemukan",
            "content": {"application/json": {"example": {"detail": "Chatbot settings belum ditemukan"}}},
        },
        500: {
            "description": "Gagal mengambil settings",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
def get_chatbot_settings():
    try:
        row = _get_single_settings_row()
        return _chatbot_settings_row(row)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put(
    "",
    response_model=ChatbotSettingsRecord,
    summary="Update chatbot settings",
    description="Memperbarui satu baris settings chatbot dan menyimpan updated_at saat ini.",
    responses={
        200: {
            "description": "Settings berhasil diperbarui",
            "content": {"application/json": {"example": CHATBOT_SETTINGS_EXAMPLE}},
        },
        404: {
            "description": "Settings tidak ditemukan",
            "content": {"application/json": {"example": {"detail": "Chatbot settings belum ditemukan"}}},
        },
        500: {
            "description": "Gagal memperbarui settings",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
def update_chatbot_settings(
    payload: UpdateChatbotSettingsPayload = Body(
        ...,
        examples={
            "updateChatbotSettingsExample": {
                "summary": "Contoh request update settings",
                "value": {
                    "ai_name": "SmartClinic AI",
                    "primary_language": "id",
                    "conversation_tone": "friendly",
                    "handoff_threshold": 70,
                    "handoff_message": "Mohon tunggu sebentar, admin kami akan segera membantu.",
                    "ai_badge_enabled": True,
                },
            }
        },
    )
):
    try:
        current_row = _get_single_settings_row()
        update_data = payload.model_dump(exclude_none=True)
        if not update_data:
            return _chatbot_settings_row(current_row)

        update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        response = (
            supabase.table("chatbot_settings")
            .update(update_data)
            .eq("id", current_row["id"])
            .select(_chatbot_settings_columns())
            .execute()
        )

        if not response.data:
            raise HTTPException(status_code=404, detail="Chatbot settings belum ditemukan")

        return _chatbot_settings_row(response.data[0])
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc