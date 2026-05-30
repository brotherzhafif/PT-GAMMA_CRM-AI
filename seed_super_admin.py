from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from dotenv import load_dotenv
from supabase import create_client


DEFAULT_ROLE = "super_admin"


def _get_env_value(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


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


def _seed_super_admin(client: Any, name: str, email: str, password: str, role: str) -> dict[str, Any]:
    auth_user = _find_auth_user_by_email(client.auth.admin, email)
    auth_user_id = _extract_user_id(auth_user)

    if auth_user_id is None:
        create_response = client.auth.admin.create_user(
            {
                "email": email,
                "password": password,
                "email_confirm": True,
                "app_metadata": {"role": role},
            }
        )
        create_data = _unwrap_response_data(create_response)
        auth_user = create_data.get("user") if isinstance(create_data, dict) else getattr(create_data, "user", None)
        auth_user_id = _extract_user_id(auth_user)
        if auth_user_id is None:
            raise RuntimeError("Gagal membuat user auth")
        print(f"[Seeder] Auth user created: {email}")
    else:
        print(f"[Seeder] Auth user already exists: {email}")

    existing_rows = _extract_table_rows(
        client.table("users").select("id, auth_id, name, email, role, is_active").eq("auth_id", auth_user_id).limit(1).execute()
    )

    payload = {
        "auth_id": auth_user_id,
        "name": name,
        "email": email,
        "role": role,
        "is_active": True,
    }

    if existing_rows:
        result = client.table("users").update(payload).eq("auth_id", auth_user_id).select("id, auth_id, name, email, role, is_active").limit(1).execute()
        rows = _extract_table_rows(result)
        if not rows:
            raise RuntimeError("Gagal update row users")
        print(f"[Seeder] users row updated for: {email}")
        return rows[0]

    result = client.table("users").insert(payload).select("id, auth_id, name, email, role, is_active").execute()
    rows = _extract_table_rows(result)
    if not rows:
        raise RuntimeError("Gagal insert row users")
    print(f"[Seeder] users row inserted for: {email}")
    return rows[0]


def seed_super_admin_from_env() -> int:
    load_dotenv()

    supabase_url = _require_value(_get_env_value("SUPABASE_URL"), "SUPABASE_URL")
    service_role_key = _require_value(
        _get_env_value("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SERVICE_ROLE"),
        "SUPABASE_SERVICE_ROLE_KEY",
    )
    name = _require_value(_get_env_value("SEED_SUPER_ADMIN_NAME", "SUPER_ADMIN_NAME"), "SEED_SUPER_ADMIN_NAME")
    email = _require_value(_get_env_value("SEED_SUPER_ADMIN_EMAIL", "SUPER_ADMIN_EMAIL"), "SEED_SUPER_ADMIN_EMAIL")
    password = _require_value(_get_env_value("SEED_SUPER_ADMIN_PASSWORD", "SUPER_ADMIN_PASSWORD"), "SEED_SUPER_ADMIN_PASSWORD")
    role = _get_env_value("SEED_SUPER_ADMIN_ROLE", "SUPER_ADMIN_ROLE", "DEFAULT_SUPER_ADMIN_ROLE") or DEFAULT_ROLE

    client = create_client(supabase_url, service_role_key)
    _seed_super_admin(client, name=name, email=email, password=password, role=role)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed initial super admin user into Supabase.")
    parser.add_argument("--name", default=_get_env_value("SEED_SUPER_ADMIN_NAME", "SUPER_ADMIN_NAME"), help="Super admin display name")
    parser.add_argument("--email", default=_get_env_value("SEED_SUPER_ADMIN_EMAIL", "SUPER_ADMIN_EMAIL"), help="Super admin email")
    parser.add_argument("--password", default=_get_env_value("SEED_SUPER_ADMIN_PASSWORD", "SUPER_ADMIN_PASSWORD"), help="Super admin password")
    parser.add_argument("--role", default=_get_env_value("SEED_SUPER_ADMIN_ROLE", "SUPER_ADMIN_ROLE", "DEFAULT_SUPER_ADMIN_ROLE") or DEFAULT_ROLE, help="Role to assign")
    args = parser.parse_args()

    load_dotenv()
    supabase_url = _require_value(_get_env_value("SUPABASE_URL"), "SUPABASE_URL")
    service_role_key = _require_value(
        _get_env_value("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SERVICE_ROLE"),
        "SUPABASE_SERVICE_ROLE_KEY",
    )
    name = _require_value(args.name, "SEED_SUPER_ADMIN_NAME")
    email = _require_value(args.email, "SEED_SUPER_ADMIN_EMAIL")
    password = _require_value(args.password, "SEED_SUPER_ADMIN_PASSWORD")
    role = args.role or DEFAULT_ROLE

    client = create_client(supabase_url, service_role_key)

    try:
        row = _seed_super_admin(client, name=name, email=email, password=password, role=role)
    except Exception as exc:
        print(f"[Seeder] Failed: {exc}")
        return 1

    print("[Seeder] Done")
    print(row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
