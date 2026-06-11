from __future__ import annotations

import asyncio
import os
from typing import Optional
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Body, HTTPException, Request

from App.activity_logger import log_activity
from App.config import supabase
from App.helpers import _require_supabase
from App.models import ChatbotSettingsRecord, UpdateChatbotSettingsPayload
from LLM.groq_service import groq_service

router = APIRouter(prefix="/api/chatbot-settings", tags=["System"])

DEFAULT_HANDOFF_TIMEOUT_MINUTES = 15
DEFAULT_MAX_FALLBACK_BEFORE_HANDOFF = 3


CHATBOT_SETTINGS_EXAMPLE = {
    "id": "2f4d52c2-1111-4b5f-9b5d-1b2c3d4e5f67",
    "ai_name": "SmartClinic AI",
    "primary_language": "id",
    "conversation_tone": "friendly",
    "handoff_threshold": 70,
    "handoff_message": "Mohon tunggu sebentar, admin kami akan segera membantu.",
    "ai_badge_enabled": True,
    "api_key": "gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "quota_used_tokens": 12500,
    "quota_limit_tokens": 50000,
    "quota": "12500/50000",
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


def _groq_quota_state() -> dict[str, int | str]:
    used_tokens = int(groq_service.last_usage.get("total_tokens") or 0)
    limit_value = groq_service.last_rate_limits.get("tokens", {}).get("limit")
    try:
        limit_tokens = int(limit_value) if limit_value is not None else 0
    except (TypeError, ValueError):
        limit_tokens = 0
    return {
        "quota_used_tokens": used_tokens,
        "quota_limit_tokens": limit_tokens,
        "quota": f"{used_tokens}/{limit_tokens}",
    }


def _groq_api_key() -> Optional[str]:
    return groq_service.api_key


def _chatbot_settings_columns() -> str:
    return "id, ai_name, primary_language, conversation_tone, handoff_threshold, handoff_message, ai_badge_enabled, created_at, updated_at"


def _chatbot_settings_row(record: dict) -> dict:
    quota_state = _groq_quota_state()
    return {
        "id": record.get("id"),
        "ai_name": record.get("ai_name"),
        "primary_language": record.get("primary_language"),
        "conversation_tone": record.get("conversation_tone"),
        "handoff_threshold": record.get("handoff_threshold"),
        "handoff_message": record.get("handoff_message"),
        "ai_badge_enabled": record.get("ai_badge_enabled"),
        "api_key": _groq_api_key(),
        "quota_used_tokens": quota_state["quota_used_tokens"],
        "quota_limit_tokens": quota_state["quota_limit_tokens"],
        "quota": quota_state["quota"],
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
    description=(
        "Mengembalikan satu baris settings chatbot dari Supabase beserta api_key runtime aktif dan ringkasan kuota Groq "
        "dalam format used/limit dari request terakhir."
    ),
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
    description=(
        "Memperbarui satu baris settings chatbot. Field api_key akan dipakai oleh runtime Groq saat ini, sementara quota "
        "di response menampilkan used/limit dari metadata respons Groq terakhir."
    ),
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
async def update_chatbot_settings(
    request: Request,
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
                    "api_key": "gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                },
            }
        },
    )
):
    try:
        update_data = payload.model_dump(exclude_none=True)
        api_key = update_data.pop("api_key", None)
        if api_key:
            os.environ["GROQ_API_KEY"] = api_key
            groq_service.api_key = api_key

        current_row = _get_single_settings_row()
        if current_row is None:
            return _chatbot_settings_row(_create_chatbot_settings_row(update_data))

        if not update_data:
            return _chatbot_settings_row(current_row)

        update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        response = await asyncio.to_thread(
            lambda: supabase.table("chatbot_settings")
            .update(update_data)
            .eq("id", current_row["id"])
            .select(_chatbot_settings_columns())
            .execute()
        )

        if not response.data:
            raise HTTPException(status_code=500, detail="Gagal memperbarui chatbot settings")

        await log_activity(
            category="system_config",
            action="UPDATE_CHATBOT_SETTINGS",
            from_actor=request.client.host if request.client else "system",
            message="Chatbot settings diperbarui",
            metadata={
                "updated_fields": list(update_data.keys()),
                "ai_name": update_data.get("ai_name"),
                "handoff_threshold": update_data.get("handoff_threshold"),
            },
        )

        return _chatbot_settings_row(response.data[0])
    except HTTPException:
        raise
    except Exception as exc:
        await log_activity(
            category="system_config",
            action="UPDATE_CHATBOT_SETTINGS_FAILED",
            from_actor=request.client.host if request.client else "system",
            message=f"Gagal update chatbot settings: {str(exc)}",
            metadata={"error": str(exc)},
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc