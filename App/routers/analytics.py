# ======================================================
# SmartClinic CRM AI — routers/analytics.py
# Endpoint: /api/analytics
#
# Menyediakan data analytics dashboard dari tabel Supabase:
#   messages, patients, feedback, campaigns,
#   appointment_reminders, activity_logs
#
# Last Change   :   17 Jun 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query

from App.config import supabase
from App.helpers import _require_supabase

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])

# ──────────────────────────────────────────────────────────
#  Constants & Helpers
# ──────────────────────────────────────────────────────────

LOCAL_TZ = ZoneInfo("Asia/Jakarta")

VALID_RANGES = {"today", "7d", "30d"}


def _resolve_range(range_key: str) -> tuple[datetime, datetime]:
    """Return (start, end) as UTC-aware datetimes for the given range key."""
    if range_key not in VALID_RANGES:
        raise HTTPException(status_code=422, detail="range harus salah satu dari: today, 7d, 30d")

    now_local = datetime.now(LOCAL_TZ)

    if range_key == "today":
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    elif range_key == "7d":
        start_local = (now_local - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
    else:  # 30d
        start_local = (now_local - timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0)

    return start_local, now_local


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
        "campaigns, reminders, dan handoff. Sumber data: semua tabel Supabase."
    ),
)
async def get_overview(range: str = Query("today", description="today | 7d | 30d")):
    try:
        _require_supabase()
        start, end = _resolve_range(range)

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
                    rating_dist[str(int(r))] = rating_dist.get(str(int(r)), 0) + 1
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
            "range": range,
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

def _auto_group_by(range_key: str) -> str:
    """Pilih granularity otomatis berdasarkan range."""
    return "hour" if range_key == "today" else "day"


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
        "Mengembalikan data inbound/outbound/unique_senders per bucket waktu. "
        "Cocok untuk line chart atau bar chart di dashboard."
    ),
)
async def get_messages_chart(
    range: str = Query("today", description="today | 7d | 30d"),
    group_by: str = Query(None, description="hour | day (default: otomatis)"),
):
    try:
        _require_supabase()
        start, end = _resolve_range(range)

        if group_by is None:
            group_by = _auto_group_by(range)

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
            "range": range,
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
        "Mengembalikan distribusi outbound messages berdasarkan source. "
        "Cocok untuk pie chart atau donut chart."
    ),
)
async def get_source_breakdown(range: str = Query("today", description="today | 7d | 30d")):
    try:
        _require_supabase()
        start, end = _resolve_range(range)

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
            "range": range,
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