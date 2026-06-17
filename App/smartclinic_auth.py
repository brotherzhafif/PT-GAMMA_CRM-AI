# ======================================================
# SmartClinic CRM AI — smartclinic_auth.py
# Shared SmartClinic login/token cache untuk seluruh project
#
# Last Change   :   18 Jun 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================
#
# Token lifecycle:
#   - Buffer 300 s  → proactive refresh 5 menit sebelum expired
#   - On-demand     → setiap request yang butuh token memanggil
#                     get_smartclinic_token[_sync](); kalau cache masih
#                     valid langsung return, kalau sudah mepet TTL → refresh
#   - 401 handler   → proxy/request yang dapat 401 memanggil
#                     force_refresh_smartclinic_token(); dijamin hanya
#                     satu goroutine yang refresh sekaligus (async lock)
#   - Background    → start_token_refresher() dijalankan di app lifespan;
#                     cek token tiap 4 menit, refresh proaktif sebelum
#                     expired sehingga 401 praktis tidak pernah terjadi
# ======================================================

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from App.config import SMARTCLINIC_BASE_URL, SMARTCLINIC_EMAIL, SMARTCLINIC_PASSWORD, STATE_DIR


SMARTCLINIC_TOKEN_CACHE_FILE = os.path.join(STATE_DIR, "smartclinic_token.json")
SMARTCLINIC_TOKEN_TTL_SECONDS = 3000   # Fallback TTL jika RME tidak return expiresIn
SMARTCLINIC_BUFFER_SECONDS    = 300    # 5 menit buffer — refresh jauh sebelum RME reject
TOKEN_REFRESH_CHECK_INTERVAL  = 240    # Proactive refresher cek tiap 4 menit

# Satu lock global untuk semua operasi tulis token (async-safe)
_SMARTCLINIC_TOKEN_LOCK = asyncio.Lock()


# ──────────────────────────────────────────────────────────
# Cache helpers (sync, I/O ringan)
# ──────────────────────────────────────────────────────────

def _load_token_cache() -> dict:
    if not os.path.exists(SMARTCLINIC_TOKEN_CACHE_FILE):
        return {}
    try:
        with open(SMARTCLINIC_TOKEN_CACHE_FILE, "r") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _save_token_cache(
    access_token: str,
    refresh_token: Optional[str] = None,
    expires_in: Optional[int] = None,
) -> None:
    """Simpan token ke cache dengan expires_at yang akurat dari RME response."""
    ttl = expires_in if expires_in else SMARTCLINIC_TOKEN_TTL_SECONDS
    payload = {
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "cached_at":     datetime.now(timezone.utc).isoformat(),
        "expires_at":    (datetime.now(timezone.utc) + timedelta(seconds=ttl)).isoformat(),
        "expires_in":    ttl,
    }
    with open(SMARTCLINIC_TOKEN_CACHE_FILE, "w") as fh:
        json.dump(payload, fh, indent=2)


def _is_token_valid(cache: dict) -> bool:
    """Return True jika token masih valid dengan mempertimbangkan buffer 5 menit."""
    access_token = cache.get("access_token")
    expires_at   = cache.get("expires_at")
    if not access_token or not expires_at:
        return False
    try:
        expires_at_dt = datetime.fromisoformat(expires_at)
    except Exception:
        return False

    buffer = timedelta(seconds=SMARTCLINIC_BUFFER_SECONDS)
    now    = datetime.now(timezone.utc)
    valid  = now < (expires_at_dt - buffer)

    if not valid and access_token:
        remaining = (expires_at_dt - now).total_seconds()
        print(
            f"[SmartClinic] Token mendekati expiry — "
            f"sisa {remaining:.0f}s (buffer {SMARTCLINIC_BUFFER_SECONDS}s). "
            f"Expiry: {expires_at}"
        )
    return valid


# ──────────────────────────────────────────────────────────
# Network calls (blocking, jalan di thread pool)
# ──────────────────────────────────────────────────────────

def _login_sync() -> str:
    """Login penuh ke RME dan simpan token baru ke cache."""
    if not SMARTCLINIC_EMAIL or not SMARTCLINIC_PASSWORD:
        raise RuntimeError("SMARTCLINIC_EMAIL dan SMARTCLINIC_PASSWORD harus diisi di .env")

    login_url = f"{SMARTCLINIC_BASE_URL.rstrip('/')}/auth/login"
    response  = requests.post(
        login_url,
        json={"identifier": SMARTCLINIC_EMAIL, "password": SMARTCLINIC_PASSWORD},
        timeout=30,
    )

    if response.status_code >= 400:
        try:
            detail = response.json()
        except Exception:
            detail = response.text
        raise RuntimeError(f"SmartClinic login gagal: {detail}")

    payload       = response.json()
    access_token  = payload.get("data", {}).get("accessToken")
    refresh_token = payload.get("data", {}).get("refreshToken")
    expires_in    = payload.get("data", {}).get("expiresIn")

    if not access_token:
        raise RuntimeError("SmartClinic tidak mengembalikan accessToken")

    _save_token_cache(access_token, refresh_token, expires_in)
    print("[SmartClinic] Login berhasil, token baru tersimpan.")
    return access_token


def _refresh_token_sync() -> Optional[str]:
    """Coba refresh menggunakan refreshToken yang tersimpan.

    Return access_token baru, atau None jika refresh gagal (perlu login ulang).
    """
    cache         = _load_token_cache()
    refresh_token = cache.get("refresh_token")

    if not refresh_token:
        print("[SmartClinic] Tidak ada refresh_token tersimpan, perlu login ulang.")
        return None

    refresh_url = f"{SMARTCLINIC_BASE_URL.rstrip('/')}/auth/refresh"
    try:
        response = requests.post(
            refresh_url,
            json={"refreshToken": refresh_token},
            timeout=30,
        )

        if response.status_code >= 400:
            print(
                f"[SmartClinic] Refresh token gagal (status {response.status_code}), "
                "akan login ulang."
            )
            return None

        payload           = response.json()
        access_token      = payload.get("data", {}).get("accessToken")
        new_refresh_token = payload.get("data", {}).get("refreshToken", refresh_token)
        expires_in        = payload.get("data", {}).get("expiresIn")

        if not access_token:
            print("[SmartClinic] Refresh response tidak mengandung accessToken.")
            return None

        _save_token_cache(access_token, new_refresh_token, expires_in)
        print("[SmartClinic] Token berhasil di-refresh via refreshToken.")
        return access_token

    except Exception as exc:
        print(f"[SmartClinic] Error saat refresh token: {exc}")
        return None


# ──────────────────────────────────────────────────────────
# Public sync API (dipakai oleh helper/sync context)
# ──────────────────────────────────────────────────────────

def get_smartclinic_token_sync() -> str:
    """Return access_token yang valid (cache → refresh → login).

    Dipanggil dari konteks sinkron (thread pool). TIDAK membawa async lock;
    caller yang async harus memanggil get_smartclinic_token() atau
    force_refresh_smartclinic_token() yang sudah dilengkapi lock.
    """
    cache = _load_token_cache()
    if _is_token_valid(cache):
        return cache["access_token"]

    print("[SmartClinic] Token tidak valid, mencoba refresh via refreshToken...")
    refreshed = _refresh_token_sync()
    if refreshed:
        return refreshed

    print("[SmartClinic] Refresh gagal, fallback ke login ulang...")
    return _login_sync()


# ──────────────────────────────────────────────────────────
# Public async API (dipakai oleh FastAPI endpoints)
# ──────────────────────────────────────────────────────────

async def get_smartclinic_token() -> str:
    """Async-safe: return token valid; refresh/login hanya satu goroutine sekaligus."""
    async with _SMARTCLINIC_TOKEN_LOCK:
        return await asyncio.to_thread(get_smartclinic_token_sync)


async def force_refresh_smartclinic_token() -> str:
    """Paksa refresh token sekarang (dipanggil saat dapat 401).

    Dijamin hanya satu goroutine yang refresh sekaligus berkat async lock.
    Flow: refreshToken → login ulang (jika refresh gagal).
    """
    async with _SMARTCLINIC_TOKEN_LOCK:
        print("[SmartClinic] Force refresh dipanggil (kemungkinan karena 401)...")
        refreshed = await asyncio.to_thread(_refresh_token_sync)
        if refreshed:
            return refreshed
        print("[SmartClinic] RefreshToken gagal saat force refresh, login ulang...")
        return await asyncio.to_thread(_login_sync)


# ──────────────────────────────────────────────────────────
# Proactive background token refresher
# ──────────────────────────────────────────────────────────

async def _token_refresher_loop() -> None:
    """Background loop yang proaktif refresh token sebelum expired.

    Cek tiap TOKEN_REFRESH_CHECK_INTERVAL detik (default 4 menit).
    Dengan buffer 5 menit, token pasti di-refresh sebelum RME reject.
    """
    print(
        f"[SmartClinic] Proactive token refresher aktif "
        f"(cek tiap {TOKEN_REFRESH_CHECK_INTERVAL}s, buffer {SMARTCLINIC_BUFFER_SECONDS}s)."
    )
    while True:
        await asyncio.sleep(TOKEN_REFRESH_CHECK_INTERVAL)
        try:
            cache = _load_token_cache()
            if not _is_token_valid(cache):
                print("[SmartClinic] Proactive refresher: token mepet/expired, refresh sekarang...")
                # Gunakan lock agar tidak bentrok dengan request yang juga sedang refresh
                async with _SMARTCLINIC_TOKEN_LOCK:
                    # Double-check setelah dapat lock (mungkin sudah di-refresh oleh request lain)
                    cache = _load_token_cache()
                    if not _is_token_valid(cache):
                        refreshed = await asyncio.to_thread(_refresh_token_sync)
                        if not refreshed:
                            await asyncio.to_thread(_login_sync)
                        print("[SmartClinic] Proactive refresh selesai.")
            else:
                expires_at = cache.get("expires_at", "?")
                print(f"[SmartClinic] Proactive refresher: token masih valid (expires: {expires_at}).")
        except Exception as exc:
            print(f"[SmartClinic] Proactive refresher error (non-fatal): {exc}")


def start_token_refresher() -> asyncio.Task:
    """Jalankan proactive token refresher sebagai background asyncio Task.

    Panggil ini dari lifespan startup di app.py.
    """
    task = asyncio.create_task(_token_refresher_loop(), name="smartclinic_token_refresher")
    return task


# ──────────────────────────────────────────────────────────
# Status endpoint helper
# ──────────────────────────────────────────────────────────

def get_smartclinic_token_status() -> dict:
    """Baca status token cache dan refresh otomatis jika token sudah kedaluwarsa."""
    cache         = _load_token_cache()
    access_token  = cache.get("access_token")
    expires_at    = cache.get("expires_at")
    cached_at     = cache.get("cached_at")
    expires_in    = cache.get("expires_in")

    valid = _is_token_valid(cache)
    if not valid and SMARTCLINIC_EMAIL and SMARTCLINIC_PASSWORD:
        try:
            get_smartclinic_token_sync()
            cache        = _load_token_cache()
            access_token = cache.get("access_token")
            expires_at   = cache.get("expires_at")
            cached_at    = cache.get("cached_at")
            expires_in   = cache.get("expires_in")
            valid        = _is_token_valid(cache)
        except Exception as exc:
            print(f"[SmartClinic] Token refresh on status-check error: {exc}")

    status = "valid" if valid else ("expired" if access_token else "missing")

    token_preview = None
    if access_token:
        token_preview = (
            f"{access_token[:8]}...{access_token[-8:]}"
            if len(access_token) > 16
            else access_token
        )

    return {
        "status":            status,
        "valid":             valid,
        "token_preview":     token_preview,
        "cached_at":         cached_at,
        "last_change_at":    cached_at,
        "expires_at":        expires_at,
        "expires_in_seconds": expires_in,
        "buffer_seconds":    SMARTCLINIC_BUFFER_SECONDS,
        "base_url":          SMARTCLINIC_BASE_URL,
    }
