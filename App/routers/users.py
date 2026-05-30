from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel

from App.activity_logger import log_activity
from App.auth.dependencies import require_super_admin
from App.config import supabase


router = APIRouter(prefix="/api/users", tags=["Users"])


class CreateUserPayload(BaseModel):
    name: str
    email: str
    password: str
    role: str


class UpdateUserPayload(BaseModel):
    name: str | None = None
    role: str | None = None
    is_active: bool | None = None


def _users_columns() -> str:
    return "id, auth_id, name, email, role, is_active, created_at, updated_at"


def _extract_auth_user_id(create_user_response: Any) -> str | None:
    if create_user_response is None:
        return None

    if isinstance(create_user_response, dict):
        auth_user = create_user_response.get("user")
    else:
        auth_user = getattr(create_user_response, "user", None)

    if isinstance(auth_user, dict):
        return auth_user.get("id")

    return getattr(auth_user, "id", None)


def _fetch_user_by_id(user_id: str) -> dict[str, Any] | None:
    response = (
        supabase.table("users")
        .select(_users_columns())
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


def _require_supabase() -> None:
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase belum dikonfigurasi",
        )


@router.get("")
async def get_users(current_user: dict = require_super_admin):
    _require_supabase()
    _ = current_user

    response = (
        await asyncio.to_thread(
            lambda: supabase.table("users")
            .select(_users_columns())
            .order("created_at", desc=True)
            .execute()
        )
    )
    return response.data or []


@router.post("")
async def create_user(payload: CreateUserPayload, current_user: dict = require_super_admin):
    _require_supabase()

    try:
        create_auth_response = await asyncio.to_thread(
            supabase.auth.admin.create_user,
            {
                "email": payload.email,
                "password": payload.password,
                "email_confirm": True,
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    auth_user_id = _extract_auth_user_id(create_auth_response)
    if not auth_user_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Gagal membuat user auth",
        )

    try:
        insert_response = await asyncio.to_thread(
            lambda: supabase.table("users")
            .insert(
                {
                    "auth_id": auth_user_id,
                    "name": payload.name,
                    "email": payload.email,
                    "role": payload.role,
                    "is_active": True,
                }
            )
            .select(_users_columns())
            .execute()
        )
    except Exception as exc:
        # Rollback auth user jika insert profile gagal.
        try:
            await asyncio.to_thread(supabase.auth.admin.delete_user, auth_user_id)
        except Exception:
            pass
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    rows = insert_response.data or []
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Gagal menyimpan user",
        )

    created = rows[0]
    await log_activity(
        category="user_mgmt",
        action="CREATE_USER",
        from_actor=current_user.get("email", "system"),
        message=f"User baru ditambahkan: {payload.name} ({payload.role})",
    )

    return created


@router.get("/{id}")
async def get_user_by_id(
    id: str = Path(..., description="ID user"),
    current_user: dict = require_super_admin,
):
    _require_supabase()
    _ = current_user

    user = await asyncio.to_thread(_fetch_user_by_id, id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User tidak ditemukan")
    return user


@router.put("/{id}")
async def update_user(
    payload: UpdateUserPayload,
    id: str = Path(..., description="ID user"),
    current_user: dict = require_super_admin,
):
    _require_supabase()

    existing = await asyncio.to_thread(_fetch_user_by_id, id)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User tidak ditemukan")

    updates: dict[str, Any] = {k: v for k, v in payload.model_dump().items() if v is not None}
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()

    response = await asyncio.to_thread(
        lambda: supabase.table("users")
        .update(updates)
        .eq("id", id)
        .select(_users_columns())
        .limit(1)
        .execute()
    )

    rows = response.data or []
    if not rows:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Gagal update user")

    updated = rows[0]
    updated_name = updated.get("name") or existing.get("name") or "unknown"
    await log_activity(
        category="user_mgmt",
        action="UPDATE_USER",
        from_actor=current_user.get("email", "system"),
        message=f"User diupdate: {updated_name}",
    )

    return updated


@router.delete("/{id}")
async def deactivate_user(
    id: str = Path(..., description="ID user"),
    current_user: dict = require_super_admin,
):
    _require_supabase()

    existing = await asyncio.to_thread(_fetch_user_by_id, id)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User tidak ditemukan")

    name = existing.get("name") or "unknown"
    await asyncio.to_thread(
        lambda: supabase.table("users")
        .update(
            {
                "is_active": False,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .eq("id", id)
        .execute()
    )

    await log_activity(
        category="user_mgmt",
        action="DELETE_USER",
        from_actor=current_user.get("email", "system"),
        message=f"User dinonaktifkan: {name}",
    )

    return {"message": "User berhasil dinonaktifkan"}
