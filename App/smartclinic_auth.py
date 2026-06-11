# ======================================================
# SmartClinic CRM AI — smartclinic_auth.py
# Shared SmartClinic login/token cache for the whole project
#
# Last Change   :   11 Jun 2026
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
SMARTCLINIC_TOKEN_TTL_SECONDS = 3000  # Fallback jika SmartClinic tidak return expiry
SMARTCLINIC_BUFFER_SECONDS = 60  # 1 menit buffer sebelum token dianggap expired
_SMARTCLINIC_TOKEN_LOCK = asyncio.Lock()


def _load_token_cache() -> dict:
    if not os.path.exists(SMARTCLINIC_TOKEN_CACHE_FILE):
        return {}

    try:
        with open(SMARTCLINIC_TOKEN_CACHE_FILE, "r") as file_handle:
            return json.load(file_handle)
    except Exception:
        return {}


def _save_token_cache(access_token: str, refresh_token: Optional[str] = None, expires_in: Optional[int] = None) -> None:
    """Simpan token cache dengan expiry time yang akurat dari SmartClinic response."""
    # Gunakan expires_in dari response jika tersedia, otherwise fallback ke TTL default
    ttl_seconds = expires_in if expires_in else SMARTCLINIC_TOKEN_TTL_SECONDS
    
    payload = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat(),
        "expires_in": ttl_seconds,  # Store untuk reference
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
    
    # Gunakan buffer 1 menit sebelum expiry untuk trigger refresh lebih awal
    # Ini menghindari race condition di mana SmartClinic sudah reject token
    # sebelum sistem aware token sudah expired
    BUFFER = timedelta(seconds=SMARTCLINIC_BUFFER_SECONDS)
    now = datetime.now(timezone.utc)
    is_valid = now < (expires_at_dt - BUFFER)
    
    # Debug logging
    if not is_valid and access_token:
        print(f"[SmartClinic] Token akan segera expired. Expiry: {expires_at}, Current: {now.isoformat()}")
    
    return is_valid

def get_smartclinic_token_status() -> dict:
    """Baca status token cache dan refresh otomatis jika token sudah kedaluwarsa."""
    cache = _load_token_cache()
    access_token = cache.get("access_token")
    expires_at = cache.get("expires_at")
    cached_at = cache.get("cached_at")
    expires_in = cache.get("expires_in")

    valid = _is_token_valid(cache)
    if not valid and SMARTCLINIC_EMAIL and SMARTCLINIC_PASSWORD:
        try:
            get_smartclinic_token_sync()
            cache = _load_token_cache()
            access_token = cache.get("access_token")
            expires_at = cache.get("expires_at")
            cached_at = cache.get("cached_at")
            expires_in = cache.get("expires_in")
            valid = _is_token_valid(cache)
        except Exception as e:
            print(f"[SmartClinic] Token refresh error: {e}")
            # Biarkan status turun ke expired/missing jika login ulang gagal.
            pass

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
        "expires_in_seconds": expires_in,
        "buffer_seconds": SMARTCLINIC_BUFFER_SECONDS,
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
    expires_in = payload.get("data", {}).get("expiresIn")  # Deteksi token expiry dari response
    
    if not access_token:
        raise RuntimeError("SmartClinic tidak mengembalikan accessToken")

    _save_token_cache(access_token, refresh_token, expires_in)
    return access_token


def _refresh_token_sync() -> Optional[str]:
    """Coba refresh token menggunakan refresh_token yang tersimpan. Return None jika refresh gagal."""
    cache = _load_token_cache()
    refresh_token = cache.get("refresh_token")
    
    if not refresh_token:
        return None  # Tidak ada refresh token, harus login ulang
    
    refresh_url = f"{SMARTCLINIC_BASE_URL.rstrip('/')}/auth/refresh"
    try:
        response = requests.post(
            refresh_url,
            json={"refreshToken": refresh_token},
            timeout=30,
        )
        
        if response.status_code >= 400:
            print(f"[SmartClinic] Refresh token gagal (status {response.status_code}), akan login ulang")
            return None  # Refresh gagal, fallback ke login
        
        payload = response.json()
        access_token = payload.get("data", {}).get("accessToken")
        new_refresh_token = payload.get("data", {}).get("refreshToken", refresh_token)
        expires_in = payload.get("data", {}).get("expiresIn")
        
        if not access_token:
            return None
        
        _save_token_cache(access_token, new_refresh_token, expires_in)
        print("[SmartClinic] Token berhasil di-refresh")
        return access_token
    except Exception as e:
        print(f"[SmartClinic] Refresh token error: {e}")
        return None  # Error saat refresh, fallback ke login


def get_smartclinic_token_sync() -> str:
    cache = _load_token_cache()
    if _is_token_valid(cache):
        return cache["access_token"]

    # Token tidak valid, coba refresh terlebih dahulu
    print("[SmartClinic] Token tidak valid, mencoba refresh...")
    refreshed_token = _refresh_token_sync()
    if refreshed_token:
        return refreshed_token
    
    # Refresh gagal, lakukan login ulang
    print("[SmartClinic] Refresh gagal, lakukan login ulang...")
    return _login_sync()


async def get_smartclinic_token() -> str:
    async with _SMARTCLINIC_TOKEN_LOCK:
        return await asyncio.to_thread(get_smartclinic_token_sync)
