import asyncio
from typing import Any

from App.config import supabase


def _insert_activity_log(payload: dict[str, Any]) -> None:
    if supabase is None:
        print("[ActivityLog] Skip insert - Supabase is not configured.")
        return

    supabase.table("activity_logs").insert(payload).execute()


async def log_activity(
    category: str,
    action: str,
    from_actor: str,
    message: str,
    ip_address: str | None = None,
    device: str | None = None,
    location: str | None = None,
    metadata: dict | None = None,
) -> None:
    payload: dict[str, Any] = {
        "category": category,
        "action": action,
        "from_actor": from_actor,
        "message": message,
        "ip_address": ip_address,
        "device": device,
        "location": location,
        "metadata": metadata,
    }

    try:
        await asyncio.to_thread(_insert_activity_log, payload)
    except Exception as exc:
        print(f"[ActivityLog] Failed to insert activity log: {exc}")
