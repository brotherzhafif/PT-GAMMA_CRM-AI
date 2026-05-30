from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from dotenv import load_dotenv
from supabase import create_client


BOOTSTRAP_USERS: list[dict[str, str]] = [
    {
        "role": "super_admin",
        "name": "Super Admin",
        "email": "superadmin@smartclinic.local",
        "password": "Admin@12345!",
    },
    {
        "role": "admin",
        "name": "Admin",
        "email": "admin@smartclinic.local",
        "password": "Admin@12345!",
    },
    {
        "role": "manager",
        "name": "Manager",
        "email": "manager@smartclinic.local",
        "password": "Admin@12345!",
    },
    {
        "role": "mkt_staff",
        "name": "Marketing Staff",
        "email": "marketing@smartclinic.local",
        "password": "Admin@12345!",
    },
]


def _require_value(value: str | None, label: str) -> str:
    if not value:
        raise SystemExit(f"Missing required value: {label}")
    return value


def _unwrap_response_data(response: Any) -> Any:
    if response is None:
        return None
    if isinstance(response, dict):
        return response
    return getattr(response, "__dict__", response)


def _extract_admin_users_list(response: Any) -> list[dict[str, Any]]:
    if response is None:
        return []
    if isinstance(response, dict):
        data = response.get("users") or response.get("data") or []
        return list(data)
    data = getattr(response, "users", None)
    if data is None:
        data = getattr(response, "data", None)
    return list(data or [])


def _extract_user_id(user: Any) -> str | None:
    if user is None:
        return None
    if isinstance(user, dict):
        return user.get("id")
    return getattr(user, "id", None)


def _extract_user_email(user: Any) -> str | None:
    if user is None:
        return None
    if isinstance(user, dict):
        return user.get("email")
    return getattr(user, "email", None)


def _extract_table_rows(response: Any) -> list[dict[str, Any]]:
    if response is None:
        return []
    if isinstance(response, dict):
        return list(response.get("data") or [])
    return list(getattr(response, "data", None) or [])


def _find_auth_user_by_email(admin_client: Any, email: str) -> dict[str, Any] | None:
    list_response = admin_client.list_users()
    for user in _extract_admin_users_list(_unwrap_response_data(list_response)):
        if (_extract_user_email(user) or "").lower() == email.lower():
            return user
    return None


def _ensure_auth_user(client: Any, seed: dict[str, str]) -> str:
    auth_user = _find_auth_user_by_email(client.auth.admin, seed["email"])
    auth_user_id = _extract_user_id(auth_user)

    if auth_user_id is None:
        create_response = client.auth.admin.create_user(
            {
                "email": seed["email"],
                "password": seed["password"],
                "email_confirm": True,
                "app_metadata": {"role": seed["role"]},
            }
        )
        create_data = _unwrap_response_data(create_response)
        auth_user = create_data.get("user") if isinstance(create_data, dict) else getattr(create_data, "user", None)
        auth_user_id = _extract_user_id(auth_user)
        if auth_user_id is None:
            raise RuntimeError(f"Gagal membuat user auth untuk {seed['email']}")
        print(f"[Seeder] Auth user created: {seed['email']}")
    else:
        print(f"[Seeder] Auth user already exists: {seed['email']}")

    return auth_user_id


def _upsert_user_row(client: Any, auth_user_id: str, seed: dict[str, str]) -> dict[str, Any]:
    existing_rows = _extract_table_rows(
        client.table("users").select("id, auth_id, name, email, role, is_active").eq("auth_id", auth_user_id).limit(1).execute()
    )

    payload = {
        "auth_id": auth_user_id,
        "name": seed["name"],
        "email": seed["email"],
        "role": seed["role"],
        "is_active": True,
    }

    if existing_rows:
        result = client.table("users").update(payload).eq("auth_id", auth_user_id).select("id, auth_id, name, email, role, is_active").limit(1).execute()
        rows = _extract_table_rows(result)
        if not rows:
            raise RuntimeError(f"Gagal update row users untuk {seed['email']}")
        print(f"[Seeder] users row updated for: {seed['email']}")
        return rows[0]

    result = client.table("users").insert(payload).select("id, auth_id, name, email, role, is_active").execute()
    rows = _extract_table_rows(result)
    if not rows:
        raise RuntimeError(f"Gagal insert row users untuk {seed['email']}")
    print(f"[Seeder] users row inserted for: {seed['email']}")
    return rows[0]


def _normalize_seed_item(item: dict[str, Any]) -> dict[str, str]:
    role = str(item.get("role") or "").strip()
    name = str(item.get("name") or "").strip()
    email = str(item.get("email") or "").strip()
    password = str(item.get("password") or "").strip()

    if not role or not name or not email or not password:
        raise SystemExit("Each bootstrap user must have role, name, email, and password")

    return {
        "role": role,
        "name": name,
        "email": email,
        "password": password,
    }


def seed_bootstrap_users() -> int:
    load_dotenv()

    supabase_url = _require_value(os.getenv("SUPABASE_URL"), "SUPABASE_URL")
    service_role_key = _require_value(
        os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE"),
        "SUPABASE_SERVICE_ROLE_KEY",
    )
    seeds = [_normalize_seed_item(item) for item in BOOTSTRAP_USERS]

    client = create_client(supabase_url, service_role_key)

    for seed in seeds:
        auth_user_id = _ensure_auth_user(client, seed)
        _upsert_user_row(client, auth_user_id, seed)

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed initial users into Supabase.")
    parser.parse_args()

    try:
        seed_bootstrap_users()
    except Exception as exc:
        print(f"[Seeder] Failed: {exc}")
        return 1

    print("[Seeder] Done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
