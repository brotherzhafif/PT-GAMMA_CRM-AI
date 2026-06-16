# ======================================================
# SmartClinic CRM AI — routers/analytics.py
# Endpoint: /api/analytics
#
# Menyediakan data analytics dashboard dari tabel Supabase:
#   messages, patients, feedback, campaigns,
#   appointment_reminders, activity_logs
#
# Filter: start_date & end_date (ISO 8601 datetime)
# Contoh: ?start_date=2026-06-01T00:00:00&end_date=2026-06-17T23:59:59
#
# Last Change   :   17 Jun 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query

from App.config import supabase
from App.helpers import _require_supabase

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])

# ──────────────────────────────────────────────────────────
#  Constants & Helpers
# ──────────────────────────────────────────────────────────

LOCAL_TZ = ZoneInfo("Asia/Jakarta")


def _parse_date_param(value: str, param_name: str) -> datetime:
    """Parse ISO 8601 datetime string ke timezone-aware datetime (WIB)."""
    try:
        dt = datetime.fromisoformat(value)
        # Jika user tidak kasih timezone, anggap WIB
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=LOCAL_TZ)
        return dt
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=422,
            detail=f"{param_name} format tidak valid. Gunakan ISO 8601, contoh: 2026-06-01T00:00:00",
        )


def _default_start() -> datetime:
    """Default start: awal hari ini WIB."""
    return datetime.now(LOCAL_TZ).replace(hour=0, minute=0, second=0, microsecond=0)


def _default_end() -> datetime:
    """Default end: sekarang WIB."""
    return datetime.now(LOCAL_TZ)


def _validate_range(start: datetime, end: datetime) -> None:
    if start >= end:
        raise HTTPException(status_code=422, detail="start_date harus sebelum end_date")


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ──────────────────────────────────────────────────────────
#  Data Fetchers (sync — wrapped with asyncio.to_thread)
# ──────────────────────────────────────────────────────────

def _fetch_messages_in_range(start: datetime, end: datetime) -> list[dict]:
    """Fetch messages dari Supabase dengan filter created_at."""
    return (
        supabase.table("messages")
        .select("sender_number, direction, source, created_at")
        .gte("created_at", _iso(start))
        .lte("created_at", _iso(end))
        .order("created_at", desc=False)
        .execute()
    ).data or []


def _fetch_all_patients() -> list[dict]:
    return (supabase.table("patients").select("id, created_at").execute()).data or []


def _fetch_patients_in_range(start: datetime, end: datetime) -> int:
    rows = (
        supabase.table("patients")
        .select("id")
        .gte("created_at", _iso(start))
        .lte("created_at", _iso(end))
        .execute()
    ).data or []
    return len(rows)


def _fetch_all_feedback() -> list[dict]:
    return (supabase.table("feedback").select("rating").execute()).data or []


def _fetch_campaigns_in_range(start: datetime, end: datetime) -> list[dict]:
    return (
        supabase.table("campaigns")
        .select("status")
        .gte("created_at", _iso(start))
        .lte("created_at", _iso(end))
        .execute()
    ).data or []


def _fetch_reminders_in_range(start: datetime, end: datetime) -> list[dict]:
    return (
        supabase.table("appointment_reminders")
        .select("status")
        .gte("created_at", _iso(start))
        .lte("created_at", _iso(end))
        .execute()
    ).data or []


def _fetch_handoff_started_count(start: datetime, end: datetime) -> int:
    rows = (
        supabase.table("activity_logs")
        .select("id")
        .eq("category", "handoff")
        .eq("action", "HANDOFF_STARTED")
        .gte("created_at", _iso(start))
        .lte("created_at", _iso(end))
        .execute()
    ).data or []
    return len(rows)


# ──────────────────────────────────────────────────────────
#  Endpoint 1: Overview
# ──────────────────────────────────────────────────────────

@router.get(
    "/overview",
    summary="Dashboard overview — semua KPI dalam 1 panggilan",
    description=(
        "Mengembalikan ringkasan lengkap: messaging stats, patients, feedback, "
        "campaigns, reminders, dan handoff.\n\n"
        "**Filter:** `start_date` dan `end_date` dalam format ISO 8601.\n"
        "Contoh: `?start_date=2026-06-01T00:00:00&end_date=2026-06-17T23:59:59`\n\n"
        "Jika tidak diisi, default = hari ini (00:00 WIB sampai sekarang)."
    ),
)
async def get_overview(
    start_date: str = Query(None, description="Mulai dari (ISO 8601). Default: awal hari ini WIB", examples=["2026-06-01T00:00:00"]),
    end_date: str = Query(None, description="Sampai (ISO 8601). Default: sekarang WIB", examples=["2026-06-17T23:59:59"]),
):
    try:
        _require_supabase()

        start = _parse_date_param(start_date, "start_date") if start_date else _default_start()
        end = _parse_date_param(end_date, "end_date") if end_date else _default_end()
        _validate_range(start, end)

        # Fetch semua data secara paralel
        (
            messages,
            all_patients,
            new_patients_count,
            all_feedback,
            campaigns,
            reminders,
            handoff_started,
        ) = await asyncio.gather(
            asyncio.to_thread(_fetch_messages_in_range, start, end),
            asyncio.to_thread(_fetch_all_patients),
            asyncio.to_thread(_fetch_patients_in_range, start, end),
            asyncio.to_thread(_fetch_all_feedback),
            asyncio.to_thread(_fetch_campaigns_in_range, start, end),
            asyncio.to_thread(_fetch_reminders_in_range, start, end),
            asyncio.to_thread(_fetch_handoff_started_count, start, end),
        )

        # ── Messaging stats ──
        inbound_count = 0
        outbound_count = 0
        source_counter: dict[str, int] = defaultdict(int)
        unique_senders: set[str] = set()

        for msg in messages:
            direction = msg.get("direction")
            if direction == "inbound":
                inbound_count += 1
                sender = msg.get("sender_number")
                if sender:
                    unique_senders.add(sender)
            elif direction == "outbound":
                outbound_count += 1
                source = msg.get("source") or "unknown"
                source_counter[source] += 1

        unique_conversations = len(unique_senders)
        avg_response = round(outbound_count / unique_conversations, 1) if unique_conversations else 0

        # ── Feedback stats (kumulatif, semua waktu) ──
        total_feedback = len(all_feedback)
        avg_rating = None
        rating_dist = {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}

        if total_feedback:
            rating_sum = 0
            for fb in all_feedback:
                r = fb.get("rating")
                if r is not None:
                    rating_sum += int(r)
                    key = str(int(r))
                    if key in rating_dist:
                        rating_dist[key] += 1
            avg_rating = round(rating_sum / total_feedback, 1)

        # ── Campaign stats ──
        campaign_status_counter: dict[str, int] = defaultdict(int)
        for c in campaigns:
            status = c.get("status") or "unknown"
            campaign_status_counter[status] += 1

        # ── Reminder stats ──
        reminder_status_counter: dict[str, int] = defaultdict(int)
        for r in reminders:
            status = r.get("status") or "unknown"
            reminder_status_counter[status] += 1

        # ── Handoff stats ──
        from App.handoff_manager import get_all_handoff_sessions
        active_handoffs = len(get_all_handoff_sessions())

        return {
            "period": {
                "start": _iso(start),
                "end": _iso(end),
            },
            "messaging": {
                "total_inbound": inbound_count,
                "total_outbound": outbound_count,
                "unique_conversations": unique_conversations,
                "by_source": dict(source_counter),
                "avg_response_per_conversation": avg_response,
            },
            "patients": {
                "total_registered": len(all_patients),
                "new_in_period": new_patients_count,
            },
            "feedback": {
                "total_responses": total_feedback,
                "average_rating": avg_rating,
                "rating_distribution": rating_dist,
            },
            "campaigns": {
                "total": len(campaigns),
                "by_status": dict(campaign_status_counter),
            },
            "reminders": {
                "total": len(reminders),
                "by_status": dict(reminder_status_counter),
            },
            "handoff": {
                "active_sessions": active_handoffs,
                "total_started_in_period": handoff_started,
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ──────────────────────────────────────────────────────────
#  Endpoint 2: Messages Chart (Time-Series)
# ──────────────────────────────────────────────────────────

def _bucket_label(dt: datetime, group_by: str) -> str:
    """Format label bucket sesuai granularity."""
    if group_by == "hour":
        return dt.strftime("%H:%M")
    return dt.strftime("%Y-%m-%d")


def _bucket_key(dt: datetime, group_by: str) -> datetime:
    """Truncate datetime ke awal bucket."""
    local_dt = dt.astimezone(LOCAL_TZ) if dt.tzinfo else dt.replace(tzinfo=LOCAL_TZ)
    if group_by == "hour":
        return local_dt.replace(minute=0, second=0, microsecond=0)
    return local_dt.replace(hour=0, minute=0, second=0, microsecond=0)


@router.get(
    "/messages/chart",
    summary="Time-series data untuk chart messages",
    description=(
        "Mengembalikan data inbound/outbound/unique_senders per bucket waktu.\n\n"
        "**Filter:** `start_date`, `end_date` (ISO 8601), dan `group_by` (hour/day).\n"
        "Contoh: `?start_date=2026-06-10T00:00:00&end_date=2026-06-17T23:59:59&group_by=day`"
    ),
)
async def get_messages_chart(
    start_date: str = Query(None, description="Mulai dari (ISO 8601). Default: awal hari ini WIB", examples=["2026-06-01T00:00:00"]),
    end_date: str = Query(None, description="Sampai (ISO 8601). Default: sekarang WIB", examples=["2026-06-17T23:59:59"]),
    group_by: str = Query("hour", description="Granularity bucket: hour | day"),
):
    try:
        _require_supabase()

        start = _parse_date_param(start_date, "start_date") if start_date else _default_start()
        end = _parse_date_param(end_date, "end_date") if end_date else _default_end()
        _validate_range(start, end)

        if group_by not in {"hour", "day"}:
            raise HTTPException(status_code=422, detail="group_by harus hour atau day")

        messages = await asyncio.to_thread(_fetch_messages_in_range, start, end)

        # Aggregate per bucket
        buckets: dict[datetime, dict] = defaultdict(
            lambda: {"inbound": 0, "outbound": 0, "senders": set()}
        )

        for msg in messages:
            created_at_str = msg.get("created_at")
            if not created_at_str:
                continue

            try:
                created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            except Exception:
                continue

            key = _bucket_key(created_at, group_by)
            direction = msg.get("direction")

            if direction == "inbound":
                buckets[key]["inbound"] += 1
                sender = msg.get("sender_number")
                if sender:
                    buckets[key]["senders"].add(sender)
            elif direction == "outbound":
                buckets[key]["outbound"] += 1

        # Generate semua bucket dalam range (termasuk yang kosong)
        step = timedelta(hours=1) if group_by == "hour" else timedelta(days=1)
        cursor = _bucket_key(start, group_by)
        end_bucket = _bucket_key(end, group_by)

        series = []
        while cursor <= end_bucket:
            data = buckets.get(cursor, {"inbound": 0, "outbound": 0, "senders": set()})
            series.append({
                "label": _bucket_label(cursor, group_by),
                "timestamp": _iso(cursor),
                "inbound": data["inbound"],
                "outbound": data["outbound"],
                "unique_senders": len(data["senders"]),
            })
            cursor += step

        return {
            "group_by": group_by,
            "period": {
                "start": _iso(start),
                "end": _iso(end),
            },
            "series": series,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ──────────────────────────────────────────────────────────
#  Endpoint 3: Source Breakdown (Pie Chart)
# ──────────────────────────────────────────────────────────

@router.get(
    "/source-breakdown",
    summary="Breakdown sumber respons (Rasa vs Groq vs Admin)",
    description=(
        "Mengembalikan distribusi outbound messages berdasarkan source.\n\n"
        "**Filter:** `start_date` dan `end_date` (ISO 8601).\n"
        "Contoh: `?start_date=2026-06-01T00:00:00&end_date=2026-06-17T23:59:59`"
    ),
)
async def get_source_breakdown(
    start_date: str = Query(None, description="Mulai dari (ISO 8601). Default: awal hari ini WIB", examples=["2026-06-01T00:00:00"]),
    end_date: str = Query(None, description="Sampai (ISO 8601). Default: sekarang WIB", examples=["2026-06-17T23:59:59"]),
):
    try:
        _require_supabase()

        start = _parse_date_param(start_date, "start_date") if start_date else _default_start()
        end = _parse_date_param(end_date, "end_date") if end_date else _default_end()
        _validate_range(start, end)

        messages = await asyncio.to_thread(_fetch_messages_in_range, start, end)

        source_counter: dict[str, int] = defaultdict(int)
        total_outbound = 0

        for msg in messages:
            if msg.get("direction") != "outbound":
                continue
            total_outbound += 1
            source = msg.get("source") or "unknown"
            source_counter[source] += 1

        # Sort by count descending
        breakdown = []
        for source, count in sorted(source_counter.items(), key=lambda x: x[1], reverse=True):
            percentage = round((count / total_outbound) * 100, 1) if total_outbound else 0
            breakdown.append({
                "source": source,
                "count": count,
                "percentage": percentage,
            })

        return {
            "period": {
                "start": _iso(start),
                "end": _iso(end),
            },
            "total_outbound": total_outbound,
            "breakdown": breakdown,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc