from __future__ import annotations

from typing import Optional
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Body, HTTPException

from App.config import supabase
from App.helpers import _require_supabase
from App.models import ChatbotSettingsRecord, UpdateChatbotSettingsPayload

router = APIRouter(prefix="/api/chatbot-settings", tags=["System"])

DEFAULT_HANDOFF_TIMEOUT_MINUTES = 15
DEFAULT_MAX_FALLBACK_BEFORE_HANDOFF = 3


CHATBOT_SETTINGS_EXAMPLE = {
    "id": "2f4d52c2-1111-4b5f-9b5d-1b2c3d4e5f67",
    "ai_name": "SmartClinic AI",
    "primary_language": "id",
    "conversation_tone": "friendly",
    "handoff_threshold": 70,
    "handoff_timeout_minutes": 15,
    "handoff_message": "Mohon tunggu sebentar, admin kami akan segera membantu.",
    "ai_badge_enabled": True,
    "created_at": "2026-05-25T10:00:00Z",
    "updated_at": "2026-05-25T10:00:00Z",
}


def _default_chatbot_settings_row() -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": str(uuid4()),
        "ai_name": "SmartClinic AI",
        "primary_language": "id",
        "conversation_tone": "friendly",
        "handoff_threshold": 70,
        "handoff_message": "Mohon tunggu sebentar, admin kami akan segera membantu.",
        "ai_badge_enabled": True,
        "created_at": now,
        "updated_at": now,
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


def _get_single_settings_row() -> Optional[dict] | None:
    _require_supabase()
    response = supabase.table("chatbot_settings").select(_chatbot_settings_columns()).order("created_at", desc=False).limit(1).execute()
    if not response.data:
        return None
    return response.data[0]


def _create_chatbot_settings_row(initial_values: dict | None = None, allow_fallback: bool = False) -> dict:
    payload = _default_chatbot_settings_row()
    if initial_values:
        payload.update(initial_values)
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        response = supabase.table("chatbot_settings").insert(payload).select(_chatbot_settings_columns()).execute()
        if response.data:
            return response.data[0]
    except Exception:
        if not allow_fallback:
            raise

    if allow_fallback:
        return payload

    raise HTTPException(status_code=500, detail="Gagal membuat chatbot settings default")


def _get_or_create_single_settings_row(initial_values: dict | None = None, allow_fallback: bool = False) -> dict:
    row = _get_single_settings_row()
    if row is not None:
        return row
    return _create_chatbot_settings_row(initial_values, allow_fallback=allow_fallback)


def get_handoff_timeout_minutes(default: int = DEFAULT_HANDOFF_TIMEOUT_MINUTES) -> int:
    return default


def get_max_fallback_before_handoff(default: int = DEFAULT_MAX_FALLBACK_BEFORE_HANDOFF) -> int:
    return default


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
        500: {
            "description": "Gagal mengambil settings",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
def get_chatbot_settings():
    try:
        row = _get_or_create_single_settings_row(allow_fallback=True)
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
        update_data = payload.model_dump(exclude_none=True)
        current_row = _get_single_settings_row()
        if current_row is None:
            return _chatbot_settings_row(_create_chatbot_settings_row(update_data))

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
            raise HTTPException(status_code=500, detail="Gagal memperbarui chatbot settings")

        return _chatbot_settings_row(response.data[0])
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc