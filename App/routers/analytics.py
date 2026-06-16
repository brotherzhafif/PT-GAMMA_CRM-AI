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
from collections import Counter, defaultdict
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

# Keyword mapping untuk deteksi topik dari teks pesan
TOPIC_KEYWORDS = {
    "Book Appointment": ["booking", "book", "janji", "appointment", "reservasi", "daftar"],
    "Operating Hours": ["jam buka", "jam operasional", "operasional", "buka", "tutup"],
    "Pricing Inquiry": ["harga", "biaya", "tarif", "price"],
    "Insurance / BPJS": ["bpjs", "asuransi", "insurance", "klaim", "rujukan"],
    "Health Complaints": ["nyeri", "sakit", "demam", "mual", "sesak", "pusing", "batuk", "diare"],
    "Billing": ["tagihan", "billing", "invoice", "kwitansi", "pembayaran", "bayar"],
    "Reschedule": ["reschedule", "jadwal ulang", "ubah jadwal", "ganti jadwal", "pindah jadwal"],
}

BOOKING_KEYWORDS = TOPIC_KEYWORDS["Book Appointment"]


def _parse_date_param(value: str, param_name: str) -> datetime:
    """Parse ISO 8601 datetime string ke timezone-aware datetime (WIB)."""
    try:
        dt = datetime.fromisoformat(value)
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


def _calc_trend(current: float, previous: float) -> dict:
    """Hitung delta/trend antara periode sekarang dan sebelumnya."""
    if previous == 0:
        delta = 100.0 if current > 0 else 0.0
    else:
        delta = round(((current - previous) / previous) * 100, 1)

    if delta > 0:
        direction = "up"
    elif delta < 0:
        direction = "down"
    else:
        direction = "stable"

    return {
        "value": current,
        "previous": previous,
        "change_percent": abs(delta),
        "direction": direction,
    }


def _topic_from_text(text: str | None) -> str:
    """Deteksi topik dari teks pesan berdasarkan keyword matching."""
    payload = (text or "").lower()
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(keyword in payload for keyword in keywords):
            return topic
    return "Other"


# ──────────────────────────────────────────────────────────
#  Data Fetchers (sync — wrapped with asyncio.to_thread)
# ──────────────────────────────────────────────────────────

def _fetch_messages_in_range(start: datetime, end: datetime) -> list[dict]:
    return (
        supabase.table("messages")
        .select("sender_number, message_text, direction, source, created_at")
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


def _fetch_activity_logs(start: datetime, end: datetime, limit: int, category: str | None = None) -> list[dict]:
    query = (
        supabase.table("activity_logs")
        .select("*")
        .gte("created_at", _iso(start))
        .lte("created_at", _iso(end))
        .order("created_at", desc=True)
        .limit(limit)
    )
    if category:
        query = query.eq("category", category)
    return query.execute().data or []


# ──────────────────────────────────────────────────────────
#  KPI Helpers
# ──────────────────────────────────────────────────────────

def _compute_kpis(messages: list[dict]) -> dict:
    """Hitung semua KPI dari list messages."""
    inbound = 0
    outbound = 0
    chatbot_response = 0
    admin_response = 0
    unique_senders: set[str] = set()
    booking_senders: set[str] = set()

    for msg in messages:
        direction = msg.get("direction")
        source = msg.get("source") or ""
        sender = msg.get("sender_number") or ""
        text = (msg.get("message_text") or "").lower()

        if direction == "inbound":
            inbound += 1
            if sender:
                unique_senders.add(sender)
                if any(kw in text for kw in BOOKING_KEYWORDS):
                    booking_senders.add(sender)

        elif direction == "outbound":
            outbound += 1
            if source == "admin":
                admin_response += 1
            else:
                chatbot_response += 1

    total_conversations = len(unique_senders)
    booking_conversion = round((len(booking_senders) / total_conversations) * 100, 1) if total_conversations else 0.0

    return {
        "total_conversations": total_conversations,
        "chatbot_response": chatbot_response,
        "admin_response": admin_response,
        "booking_conversion": booking_conversion,
    }


# ──────────────────────────────────────────────────────────
#  Endpoint 1: Overview (with trend)
# ──────────────────────────────────────────────────────────

@router.get(
    "/overview",
    summary="Dashboard overview — semua KPI + trend dalam 1 panggilan",
    description=(
        "Mengembalikan ringkasan lengkap dengan perbandingan trend terhadap "
        "periode sebelumnya yang sama panjang.\n\n"
        "**Filter:** `start_date` dan `end_date` dalam format ISO 8601.\n"
        "Default = hari ini (00:00 WIB sampai sekarang).\n\n"
        "Trend dihitung otomatis: jika range = 7 hari, maka dibandingkan dengan 7 hari sebelumnya."
    ),
)
async def get_overview(
    start_date: str = Query(None, description="Mulai dari (ISO 8601)", examples=["2026-06-01T00:00:00"]),
    end_date: str = Query(None, description="Sampai (ISO 8601)", examples=["2026-06-17T23:59:59"]),
):
    try:
        _require_supabase()

        start = _parse_date_param(start_date, "start_date") if start_date else _default_start()
        end = _parse_date_param(end_date, "end_date") if end_date else _default_end()
        _validate_range(start, end)

        # Hitung periode sebelumnya (panjang sama)
        duration = end - start
        prev_start = start - duration
        prev_end = start

        # Fetch data paralel: current + previous + global
        (
            current_messages,
            previous_messages,
            all_patients,
            new_patients_count,
            all_feedback,
            campaigns,
            reminders,
            handoff_started,
        ) = await asyncio.gather(
            asyncio.to_thread(_fetch_messages_in_range, start, end),
            asyncio.to_thread(_fetch_messages_in_range, prev_start, prev_end),
            asyncio.to_thread(_fetch_all_patients),
            asyncio.to_thread(_fetch_patients_in_range, start, end),
            asyncio.to_thread(_fetch_all_feedback),
            asyncio.to_thread(_fetch_campaigns_in_range, start, end),
            asyncio.to_thread(_fetch_reminders_in_range, start, end),
            asyncio.to_thread(_fetch_handoff_started_count, start, end),
        )

        # ── KPI cards with trend ──
        current_kpi = _compute_kpis(current_messages)
        previous_kpi = _compute_kpis(previous_messages)

        cards = {
            "total_conversations": _calc_trend(
                current_kpi["total_conversations"],
                previous_kpi["total_conversations"],
            ),
            "chatbot_response": _calc_trend(
                current_kpi["chatbot_response"],
                previous_kpi["chatbot_response"],
            ),
            "admin_response": _calc_trend(
                current_kpi["admin_response"],
                previous_kpi["admin_response"],
            ),
            "booking_conversion": {
                **_calc_trend(
                    current_kpi["booking_conversion"],
                    previous_kpi["booking_conversion"],
                ),
                "unit": "%",
            },
        }

        # ── Messaging detail ──
        source_counter: dict[str, int] = defaultdict(int)
        for msg in current_messages:
            if msg.get("direction") == "outbound":
                source_counter[msg.get("source") or "unknown"] += 1

        # ── Feedback stats (kumulatif) ──
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
        campaign_status: dict[str, int] = defaultdict(int)
        for c in campaigns:
            campaign_status[c.get("status") or "unknown"] += 1

        # ── Reminder stats ──
        reminder_status: dict[str, int] = defaultdict(int)
        for r in reminders:
            reminder_status[r.get("status") or "unknown"] += 1

        # ── Handoff stats ──
        from App.handoff_manager import get_all_handoff_sessions
        active_handoffs = len(get_all_handoff_sessions())

        return {
            "period": {
                "start": _iso(start),
                "end": _iso(end),
                "previous_start": _iso(prev_start),
                "previous_end": _iso(prev_end),
            },
            "cards": cards,
            "messaging": {
                "total_inbound": sum(1 for m in current_messages if m.get("direction") == "inbound"),
                "total_outbound": sum(1 for m in current_messages if m.get("direction") == "outbound"),
                "unique_conversations": current_kpi["total_conversations"],
                "by_source": dict(source_counter),
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
                "by_status": dict(campaign_status),
            },
            "reminders": {
                "total": len(reminders),
                "by_status": dict(reminder_status),
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
    if group_by == "hour":
        return dt.strftime("%H:%M")
    return dt.strftime("%Y-%m-%d")


def _bucket_key(dt: datetime, group_by: str) -> datetime:
    local_dt = dt.astimezone(LOCAL_TZ) if dt.tzinfo else dt.replace(tzinfo=LOCAL_TZ)
    if group_by == "hour":
        return local_dt.replace(minute=0, second=0, microsecond=0)
    return local_dt.replace(hour=0, minute=0, second=0, microsecond=0)


@router.get(
    "/messages/chart",
    summary="Time-series data untuk chart messages",
    description=(
        "Data inbound/outbound/unique_senders per bucket waktu.\n\n"
        "**Filter:** `start_date`, `end_date` (ISO 8601), `group_by` (hour/day)."
    ),
)
async def get_messages_chart(
    start_date: str = Query(None, description="Mulai dari (ISO 8601)", examples=["2026-06-01T00:00:00"]),
    end_date: str = Query(None, description="Sampai (ISO 8601)", examples=["2026-06-17T23:59:59"]),
    group_by: str = Query("hour", description="Granularity: hour | day"),
):
    try:
        _require_supabase()

        start = _parse_date_param(start_date, "start_date") if start_date else _default_start()
        end = _parse_date_param(end_date, "end_date") if end_date else _default_end()
        _validate_range(start, end)

        if group_by not in {"hour", "day"}:
            raise HTTPException(status_code=422, detail="group_by harus hour atau day")

        messages = await asyncio.to_thread(_fetch_messages_in_range, start, end)

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
            "period": {"start": _iso(start), "end": _iso(end)},
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
    description="Distribusi outbound messages berdasarkan source. Cocok untuk pie/donut chart.",
)
async def get_source_breakdown(
    start_date: str = Query(None, description="Mulai dari (ISO 8601)", examples=["2026-06-01T00:00:00"]),
    end_date: str = Query(None, description="Sampai (ISO 8601)", examples=["2026-06-17T23:59:59"]),
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
            source_counter[msg.get("source") or "unknown"] += 1

        breakdown = []
        for source, count in sorted(source_counter.items(), key=lambda x: x[1], reverse=True):
            percentage = round((count / total_outbound) * 100, 1) if total_outbound else 0
            breakdown.append({"source": source, "count": count, "percentage": percentage})

        return {
            "period": {"start": _iso(start), "end": _iso(end)},
            "total_outbound": total_outbound,
            "breakdown": breakdown,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ──────────────────────────────────────────────────────────
#  Endpoint 4: AI Chatbot Insights
# ──────────────────────────────────────────────────────────

@router.get(
    "/insights",
    summary="AI chatbot insights — top intents, low confidence, escalated topics",
    description=(
        "Heuristik berbasis tabel messages:\n"
        "- **top_detected_intents**: topik inbound paling sering muncul\n"
        "- **low_confidence_intents**: topik yang sering di-handle Groq (proxy low confidence Rasa)\n"
        "- **frequently_escalated**: topik yang sering berakhir di admin/handoff"
    ),
)
async def get_insights(
    start_date: str = Query(None, description="Mulai dari (ISO 8601)", examples=["2026-06-01T00:00:00"]),
    end_date: str = Query(None, description="Sampai (ISO 8601)", examples=["2026-06-17T23:59:59"]),
):
    try:
        _require_supabase()

        start = _parse_date_param(start_date, "start_date") if start_date else _default_start()
        end = _parse_date_param(end_date, "end_date") if end_date else _default_end()
        _validate_range(start, end)

        messages = await asyncio.to_thread(_fetch_messages_in_range, start, end)

        inbound_topic_counter: Counter[str] = Counter()
        groq_topic_counter: Counter[str] = Counter()
        escalated_topic_counter: Counter[str] = Counter()
        last_inbound_topic_by_sender: dict[str, tuple[str, datetime]] = {}

        for msg in messages:
            created_at_str = msg.get("created_at")
            if not created_at_str:
                continue
            try:
                created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            except Exception:
                continue

            sender = msg.get("sender_number") or ""
            direction = msg.get("direction")
            source = msg.get("source")
            topic = _topic_from_text(msg.get("message_text"))

            if direction == "inbound":
                inbound_topic_counter[topic] += 1
                if sender:
                    last_inbound_topic_by_sender[sender] = (topic, created_at)
                continue

            # Outbound — korelasikan dengan inbound terakhir dari sender yang sama
            if direction == "outbound" and sender in last_inbound_topic_by_sender:
                last_topic, last_time = last_inbound_topic_by_sender[sender]
                # Hanya korelasikan jika jarak < 15 menit
                if (created_at - last_time) > timedelta(minutes=15):
                    continue
                if source == "groq":
                    groq_topic_counter[last_topic] += 1
                if source == "admin":
                    escalated_topic_counter[last_topic] += 1

        # Top detected intents (exclude "Other")
        top_detected = [
            {"intent": topic, "count": count}
            for topic, count in inbound_topic_counter.most_common(5)
            if topic != "Other"
        ]

        # Low confidence — topik yang sering jatuh ke Groq
        low_confidence = []
        for topic, total in inbound_topic_counter.items():
            if topic == "Other" or total < 2:
                continue
            groq_hits = groq_topic_counter.get(topic, 0)
            if groq_hits > 0:
                estimated_conf = round(max(0.0, 100.0 * (1.0 - (groq_hits / total))), 1)
                low_confidence.append({
                    "intent": topic,
                    "estimated_confidence": estimated_conf,
                    "groq_fallback_count": groq_hits,
                })
        low_confidence.sort(key=lambda x: (x["estimated_confidence"], -x["groq_fallback_count"]))
        low_confidence = low_confidence[:5]

        # Frequently escalated — topik yang sering di-handle admin
        frequently_escalated = [
            {"topic": topic, "handoff_count": count}
            for topic, count in escalated_topic_counter.most_common(5)
            if topic != "Other"
        ]

        return {
            "period": {"start": _iso(start), "end": _iso(end)},
            "top_detected_intents": top_detected,
            "low_confidence_intents": low_confidence,
            "frequently_escalated": frequently_escalated,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ──────────────────────────────────────────────────────────
#  Endpoint 5: Live Activity Feed
# ──────────────────────────────────────────────────────────

@router.get(
    "/activities",
    summary="Live activity feed dari activity logs",
    description=(
        "Daftar aktivitas terbaru dari seluruh sistem. "
        "Bisa difilter berdasarkan category: auth, messaging, patients, "
        "appointments, feedback, handoff, marketing, system_config."
    ),
)
async def get_activities(
    start_date: str = Query(None, description="Mulai dari (ISO 8601)", examples=["2026-06-01T00:00:00"]),
    end_date: str = Query(None, description="Sampai (ISO 8601)", examples=["2026-06-17T23:59:59"]),
    category: str | None = Query(None, description="Filter category (opsional)"),
    limit: int = Query(50, description="Jumlah aktivitas", ge=1, le=500),
):
    try:
        _require_supabase()

        start = _parse_date_param(start_date, "start_date") if start_date else _default_start()
        end = _parse_date_param(end_date, "end_date") if end_date else _default_end()
        _validate_range(start, end)

        activities = await asyncio.to_thread(_fetch_activity_logs, start, end, limit, category)

        formatted = []
        for a in activities:
            formatted.append({
                "id": a.get("id"),
                "category": a.get("category"),
                "action": a.get("action"),
                "actor": a.get("from_actor"),
                "message": a.get("message"),
                "ip_address": a.get("ip_address"),
                "device": a.get("device"),
                "location": a.get("location"),
                "metadata": a.get("metadata"),
                "created_at": a.get("created_at"),
            })

        return {
            "period": {"start": _iso(start), "end": _iso(end)},
            "category_filter": category,
            "total": len(formatted),
            "activities": formatted,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc