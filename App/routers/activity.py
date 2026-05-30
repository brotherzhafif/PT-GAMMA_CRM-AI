from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Path, Query, status

from App.auth.dependencies import require_admin_or_above, require_manager_or_above
from App.config import supabase


router = APIRouter(prefix="/api/activity", tags=["Activity"])


NOTIFICATION_CATEGORIES = ["patient", "appointment", "handoff", "campaign"]
AUDIT_CATEGORIES = ["user_mgmt", "settings"]


def _activity_columns() -> str:
    return "id, category, action, from_actor, message, ip_address, device, location, metadata, is_read, created_at"


def _require_supabase() -> None:
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase belum dikonfigurasi",
        )


def _query_activity_logs(
    *,
    category: str | None = None,
    action: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    query = supabase.table("activity_logs").select(_activity_columns())

    if category:
        query = query.eq("category", category)
    if action:
        query = query.eq("action", action)
    if from_date:
        query = query.gte("created_at", from_date)
    if to_date:
        query = query.lte("created_at", to_date)

    response = query.order("created_at", desc=True).limit(limit).execute()
    return response.data or []


def _query_activity_by_categories(
    categories: list[str],
    *,
    unread_only: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    query = supabase.table("activity_logs").select(_activity_columns()).in_("category", categories)
    if unread_only:
        query = query.eq("is_read", False)

    response = query.order("created_at", desc=True).limit(limit).execute()
    return response.data or []


@router.get("")
async def get_activity_logs(
    category: str | None = Query(None),
    action: str | None = Query(None),
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    current_user: dict = require_manager_or_above,
):
    _require_supabase()
    _ = current_user

    return await asyncio.to_thread(
        _query_activity_logs,
        category=category,
        action=action,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
    )


@router.get("/notifications")
async def get_notifications(
    unread_only: bool = Query(False),
    current_user: dict = require_admin_or_above,
):
    _require_supabase()
    _ = current_user

    return await asyncio.to_thread(
        _query_activity_by_categories,
        NOTIFICATION_CATEGORIES,
        unread_only=unread_only,
        limit=100,
    )


@router.get("/audit")
async def get_audit_logs(current_user: dict = require_manager_or_above):
    _require_supabase()
    _ = current_user

    return await asyncio.to_thread(
        _query_activity_by_categories,
        AUDIT_CATEGORIES,
        unread_only=False,
        limit=100,
    )


@router.get("/logins")
async def get_login_logs(current_user: dict = require_manager_or_above):
    _require_supabase()
    _ = current_user

    return await asyncio.to_thread(
        _query_activity_logs,
        category="auth",
        limit=50,
    )


@router.put("/{id}/read")
async def mark_activity_read(
    id: str = Path(..., description="ID activity log"),
    current_user: dict = require_admin_or_above,
):
    _require_supabase()
    _ = current_user

    response = await asyncio.to_thread(
        lambda: supabase.table("activity_logs")
        .update({"is_read": True})
        .eq("id", id)
        .select("id")
        .limit(1)
        .execute()
    )

    if not (response.data or []):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity tidak ditemukan")

    return {"message": "ok"}


@router.put("/read-all")
async def mark_all_notifications_read(current_user: dict = require_admin_or_above):
    _require_supabase()
    _ = current_user

    await asyncio.to_thread(
        lambda: supabase.table("activity_logs")
        .update({"is_read": True})
        .in_("category", NOTIFICATION_CATEGORIES)
        .execute()
    )

    return {"message": "ok"}
