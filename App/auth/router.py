from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request, status
from pydantic import BaseModel

from App.activity_logger import log_activity
from App.auth.dependencies import require_any_staff
from App.config import supabase, supabase_admin


router = APIRouter(prefix="/api/auth", tags=["Auth"])


class LoginPayload(BaseModel):
    email: str
    password: str


class RefreshPayload(BaseModel):
    refresh_token: str


def _extract_session(auth_response: Any) -> Any | None:
    if auth_response is None:
        return None
    if isinstance(auth_response, dict):
        return auth_response.get("session")
    return getattr(auth_response, "session", None)


def _extract_user(auth_response: Any) -> Any | None:
    if auth_response is None:
        return None
    if isinstance(auth_response, dict):
        return auth_response.get("user")
    return getattr(auth_response, "user", None)


def _session_tokens(session: Any) -> tuple[str | None, str | None]:
    if session is None:
        return None, None
    if isinstance(session, dict):
        return session.get("access_token"), session.get("refresh_token")
    return getattr(session, "access_token", None), getattr(session, "refresh_token", None)


def _user_id_from_auth_user(auth_user: Any) -> str | None:
    if auth_user is None:
        return None
    if isinstance(auth_user, dict):
        return auth_user.get("id")
    return getattr(auth_user, "id", None)


def _get_user_profile_by_auth_id(auth_id: str) -> dict[str, Any] | None:
    if supabase_admin is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase admin belum dikonfigurasi",
        )

    response = (
        supabase_admin.table("users")
        .select("id, auth_id, name, email, role, is_active")
        .eq("auth_id", auth_id)
        .limit(1)
        .execute()
    )

    rows = response.data or []
    if not rows:
        return None

    user = rows[0]
    if not user.get("is_active", False):
        return None

    return {
        "id": user.get("id"),
        "name": user.get("name"),
        "email": user.get("email"),
        "role": user.get("role"),
    }


@router.post("/login")
async def login(payload: LoginPayload, request: Request):
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase belum dikonfigurasi",
        )

    ip_address = request.client.host if request.client else None
    device = request.headers.get("user-agent")

    try:
        auth_response = await asyncio.to_thread(
            supabase.auth.sign_in_with_password,
            {"email": payload.email, "password": payload.password},
        )
        session = _extract_session(auth_response)
        auth_user = _extract_user(auth_response)
        access_token, refresh_token = _session_tokens(session)
        auth_user_id = _user_id_from_auth_user(auth_user)

        if not access_token or not refresh_token or not auth_user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email atau password salah")

        user_profile = await asyncio.to_thread(_get_user_profile_by_auth_id, auth_user_id)
        if user_profile is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User tidak ditemukan atau tidak aktif")

        await log_activity(
            category="auth",
            action="LOGIN",
            from_actor=str(payload.email),
            message=f"{payload.email} login berhasil",
            ip_address=ip_address,
            device=device,
        )

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": user_profile,
        }
    except HTTPException as exc:
        await log_activity(
            category="auth",
            action="LOGIN_FAILED",
            from_actor=str(payload.email),
            message=f"{payload.email} login gagal",
            ip_address=ip_address,
            device=device,
        )
        raise exc
    except Exception as exc:
        await log_activity(
            category="auth",
            action="LOGIN_FAILED",
            from_actor=str(payload.email),
            message=f"{payload.email} login gagal",
            ip_address=ip_address,
            device=device,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email atau password salah") from exc


@router.post("/logout")
async def logout(request: Request, current_user: dict = require_any_staff):
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase belum dikonfigurasi",
        )

    await asyncio.to_thread(supabase.auth.sign_out)

    await log_activity(
        category="auth",
        action="LOGOUT",
        from_actor=current_user.get("email") or "system",
        message=f"{current_user.get('email') or 'User'} logout berhasil",
        ip_address=request.client.host if request.client else None,
        device=request.headers.get("user-agent"),
    )

    return {"message": "Logout berhasil"}


@router.post("/refresh")
async def refresh_token(payload: RefreshPayload = Body(...)):
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase belum dikonfigurasi",
        )

    try:
        auth_response = await asyncio.to_thread(supabase.auth.refresh_session, payload.refresh_token)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token tidak valid") from exc

    session = _extract_session(auth_response)
    access_token, refresh_token = _session_tokens(session)
    if not access_token or not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token tidak valid")

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
    }
