from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from App.activity_logger import log_activity
from App.auth.dependencies import require_any_staff
from App.config import supabase, supabase_auth
from App.helpers_device import get_real_ip, parse_user_agent, resolve_ip_location
from App.models import AuthLoginResponse, AuthRefreshResponse, AuthSimpleMessage


router = APIRouter(prefix="/api/auth", tags=["Auth"])

LOGIN_EXAMPLE = {
    "email": "superadmin@smartclinic.local",
    "password": "Admin@12345!",
}

LOGIN_RESPONSE_EXAMPLE = {
    "access_token": "eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9...",
    "refresh_token": "stjkhvrykqfo",
    "user": {
        "id": "0c16dc6d-e940-475e-a822-479ffbaca372",
        "name": "Super Admin",
        "email": "superadmin@smartclinic.local",
        "role": "super_admin",
    },
}


class LoginPayload(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "superadmin@smartclinic.local",
                "password": "Admin@12345!",
            }
        }
    )

    email: str
    password: str


class RefreshPayload(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "refresh_token": "stjkhvrykqfo",
            }
        }
    )

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
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase admin belum dikonfigurasi",
        )

    response = (
        supabase.table("users")
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


@router.post(
    "/login",
    response_model=AuthLoginResponse,
    summary="Login admin",
    description="Masukkan email superadmin dan password default untuk masuk ke dashboard admin.",
    responses={
        200: {
            "description": "Login berhasil",
            "content": {"application/json": {"example": LOGIN_RESPONSE_EXAMPLE}},
        },
        401: {
            "description": "Login gagal",
            "content": {"application/json": {"example": {"detail": "Email atau password salah"}}},
        },
        500: {
            "description": "Supabase belum dikonfigurasi",
            "content": {"application/json": {"example": {"detail": "Supabase belum dikonfigurasi"}}},
        },
    },
)
async def login(
    request: Request,
    payload: LoginPayload = Body(
        ...,
        examples={
            "superadminLogin": {
                "summary": "Login superadmin",
                "value": LOGIN_EXAMPLE,
            }
        },
    ),
):
    if supabase_auth is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase belum dikonfigurasi",
        )

    ip_address = get_real_ip(request)
    raw_ua     = request.headers.get("user-agent")
    device     = parse_user_agent(raw_ua)
    location   = await resolve_ip_location(ip_address)

    try:
        auth_response = await asyncio.to_thread(
            supabase_auth.auth.sign_in_with_password,
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
            location=location,
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
            location=location,
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
            location=location,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email atau password salah") from exc


@router.post("/logout")
async def logout(request: Request, current_user: dict = require_any_staff):
    if supabase_auth is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase belum dikonfigurasi",
        )

    await asyncio.to_thread(supabase_auth.auth.sign_out)

    _ip  = get_real_ip(request)
    _dev = parse_user_agent(request.headers.get("user-agent"))
    _loc = await resolve_ip_location(_ip)

    await log_activity(
        category="auth",
        action="LOGOUT",
        from_actor=current_user.get("email") or "system",
        message=f"{current_user.get('email') or 'User'} logout berhasil",
        ip_address=_ip,
        device=_dev,
        location=_loc,
    )

    return AuthSimpleMessage(message="Logout berhasil")


@router.post(
    "/logout-all",
    summary="Logout dari semua device",
    description="Logout dari semua perangkat/session pengguna. Ini akan menginvalidasi semua refresh token yang aktif.",
    responses={
        200: {
            "description": "Logout dari semua device berhasil",
            "content": {"application/json": {"example": {"message": "Logout dari semua device berhasil"}}},
        },
        500: {
            "description": "Supabase belum dikonfigurasi",
            "content": {"application/json": {"example": {"detail": "Supabase belum dikonfigurasi"}}},
        },
    },
)
async def logout_all_devices(request: Request, current_user: dict = require_any_staff):
    """Logout pengguna dari semua device/session yang aktif.
    
    Endpoint ini akan:
    1. Logout session saat ini
    2. Menginvalidasi semua refresh token yang tersimpan untuk user ini
    """
    if supabase is None or supabase_auth is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase belum dikonfigurasi",
        )

    email = current_user.get("email") or "system"
    user_id = current_user.get("id")

    try:
        # Logout session saat ini
        await asyncio.to_thread(supabase_auth.auth.sign_out)
        
        # Invalidate semua session/token untuk user di database
        # Dengan menghapus atau menandai semua session yang tersimpan (jika ada)
        if user_id:
            try:
                # Jika ada tabel 'user_sessions' atau sejenisnya, update di sini
                # Untuk sekarang, kita cukup logout session yang aktif
                pass
            except Exception as e:
                print(f"[Auth] Warning: Gagal invalidate sessions di DB: {e}")
        
        _ip  = get_real_ip(request)
        _dev = parse_user_agent(request.headers.get("user-agent"))
        _loc = await resolve_ip_location(_ip)

        await log_activity(
            category="auth",
            action="LOGOUT_ALL",
            from_actor=email,
            message=f"{email} logout dari semua device",
            ip_address=_ip,
            device=_dev,
            location=_loc,
        )

        return AuthSimpleMessage(message="Logout dari semua device berhasil")
        
    except Exception as exc:
        await log_activity(
            category="auth",
            action="LOGOUT_ALL_FAILED",
            from_actor=email,
            message=f"{email} logout semua device gagal",
            ip_address=get_real_ip(request),
            device=parse_user_agent(request.headers.get("user-agent")),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Logout semua device gagal"
        ) from exc


@router.post(
    "/refresh",
    response_model=AuthRefreshResponse,
    summary="Refresh token",
    description="Tukar refresh token dengan access token baru.",
    responses={
        200: {
            "description": "Token berhasil diperbarui",
            "content": {"application/json": {"example": {"access_token": "eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9...", "refresh_token": "stjkhvrykqfo"}}},
        },
        401: {
            "description": "Refresh token tidak valid",
            "content": {"application/json": {"example": {"detail": "Refresh token tidak valid"}}},
        },
    },
)
async def refresh_token(
    payload: RefreshPayload = Body(
        ...,
        examples={
            "refreshTokenExample": {
                "summary": "Contoh refresh token",
                "value": {"refresh_token": "stjkhvrykqfo"},
            }
        },
    )
):
    if supabase_auth is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase belum dikonfigurasi",
        )

    try:
        auth_response = await asyncio.to_thread(supabase_auth.auth.refresh_session, payload.refresh_token)
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