# ======================================================
# SmartClinic CRM AI — smartclinic_auth.py
# Shared SmartClinic login/token cache for the whole project
#
# Last Change   :   25 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from App.config import SMARTCLINIC_BASE_URL, SMARTCLINIC_EMAIL, SMARTCLINIC_PASSWORD, STATE_DIR


SMARTCLINIC_TOKEN_CACHE_FILE = os.path.join(STATE_DIR, "smartclinic_token.json")
SMARTCLINIC_TOKEN_TTL_SECONDS = 600
_SMARTCLINIC_TOKEN_LOCK = asyncio.Lock()


def _load_token_cache() -> dict:
    if not os.path.exists(SMARTCLINIC_TOKEN_CACHE_FILE):
        return {}

    try:
        with open(SMARTCLINIC_TOKEN_CACHE_FILE, "r") as file_handle:
            return json.load(file_handle)
    except Exception:
        return {}


def _save_token_cache(access_token: str, refresh_token: Optional[str] = None) -> None:
    payload = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=SMARTCLINIC_TOKEN_TTL_SECONDS)).isoformat(),
    }

    with open(SMARTCLINIC_TOKEN_CACHE_FILE, "w") as file_handle:
        json.dump(payload, file_handle, indent=2)


def _is_token_valid(cache: dict) -> bool:
    access_token = cache.get("access_token")
    expires_at = cache.get("expires_at")
    if not access_token or not expires_at:
        return False

    try:
        expires_at_dt = datetime.fromisoformat(expires_at)
    except Exception:
        return False

    return datetime.now(timezone.utc) < expires_at_dt


def get_smartclinic_token_status() -> dict:
    """Baca status token cache tanpa memicu login ulang."""
    cache = _load_token_cache()
    access_token = cache.get("access_token")
    expires_at = cache.get("expires_at")
    cached_at = cache.get("cached_at")

    valid = _is_token_valid(cache)
    status = "valid" if valid else ("expired" if access_token else "missing")

    token_preview = None
    if access_token:
        if len(access_token) > 16:
            token_preview = f"{access_token[:8]}...{access_token[-8:]}"
        else:
            token_preview = access_token

    return {
        "status": status,
        "valid": valid,
        "token_preview": token_preview,
        "cached_at": cached_at,
        "last_change_at": cached_at,
        "expires_at": expires_at,
        "base_url": SMARTCLINIC_BASE_URL,
    }


def _login_sync() -> str:
    if not SMARTCLINIC_EMAIL or not SMARTCLINIC_PASSWORD:
        raise RuntimeError("SMARTCLINIC_EMAIL dan SMARTCLINIC_PASSWORD harus diisi di .env")

    login_url = f"{SMARTCLINIC_BASE_URL.rstrip('/')}/auth/login"
    response = requests.post(
        login_url,
        json={
            "identifier": SMARTCLINIC_EMAIL,
            "password": SMARTCLINIC_PASSWORD,
        },
        timeout=30,
    )

    if response.status_code >= 400:
        try:
            detail = response.json()
        except Exception:
            detail = response.text
        raise RuntimeError(f"SmartClinic login gagal: {detail}")

    payload = response.json()
    access_token = payload.get("data", {}).get("accessToken")
    refresh_token = payload.get("data", {}).get("refreshToken")
    if not access_token:
        raise RuntimeError("SmartClinic tidak mengembalikan accessToken")

    _save_token_cache(access_token, refresh_token)
    return access_token


def get_smartclinic_token_sync() -> str:
    cache = _load_token_cache()
    if _is_token_valid(cache):
        return cache["access_token"]

    return _login_sync()


async def get_smartclinic_token() -> str:
    async with _SMARTCLINIC_TOKEN_LOCK:
        return await asyncio.to_thread(get_smartclinic_token_sync)
