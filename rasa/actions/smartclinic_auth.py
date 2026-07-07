import json
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
import requests

SMARTCLINIC_BASE_URL = os.getenv(
    "SMARTCLINIC_BASE_URL",
    "https://smartclinic-rekam-medis-production.up.railway.app/api/v1",
)
SMARTCLINIC_EMAIL = os.getenv("SMARTCLINIC_EMAIL")
SMARTCLINIC_PASSWORD = os.getenv("SMARTCLINIC_PASSWORD")

# Simpan token cache ke direktori lokal di dalam container
STATE_DIR = "chat_state"
if not os.path.exists(STATE_DIR):
    os.makedirs(STATE_DIR)

SMARTCLINIC_TOKEN_CACHE_FILE = os.path.join(STATE_DIR, "smartclinic_token.json")
SMARTCLINIC_TOKEN_TTL_SECONDS = 600


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
