import asyncio
import os
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from App.config import SUPABASE_JWT_SECRET, supabase


http_bearer = HTTPBearer()


def _verify_supabase_jwt(token: str) -> dict[str, Any]:
    secret = SUPABASE_JWT_SECRET or os.getenv("SUPABASE_JWT_SECRET")
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SUPABASE_JWT_SECRET belum dikonfigurasi",
        )

    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token tidak valid",
        ) from exc


def _fetch_active_user_by_auth_id(auth_id: str) -> dict[str, Any] | None:
    if supabase is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase belum dikonfigurasi",
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
        "auth_id": user.get("auth_id"),
        "name": user.get("name"),
        "email": user.get("email"),
        "role": user.get("role"),
    }


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(http_bearer),
) -> dict:
    payload = _verify_supabase_jwt(credentials.credentials)
    user_id = payload.get("sub")

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token tidak memiliki user id",
        )

    try:
        user = await asyncio.to_thread(_fetch_active_user_by_auth_id, user_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Gagal memvalidasi user",
        ) from exc

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User tidak ditemukan atau tidak aktif",
        )

    return user


def require_roles(allowed_roles: list[str]):
    async def role_checker(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user.get("role") not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Akses ditolak",
            )
        return current_user

    return Depends(role_checker)


require_super_admin = require_roles(["super_admin"])
require_admin_or_above = require_roles(["super_admin", "admin"])
require_manager_or_above = require_roles(["super_admin", "manager"])
require_any_staff = require_roles(["super_admin", "manager", "admin", "mkt_staff"])
