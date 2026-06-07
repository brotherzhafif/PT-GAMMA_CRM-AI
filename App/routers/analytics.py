from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from App.config import supabase
from App.helpers import _require_supabase


router = APIRouter(prefix="/api/analytics", tags=["Analytics"])


VALID_RANGES = {"day", "week", "month"}
VALID_BUCKETS = {"hour", "day", "week"}

TOPIC_KEYWORDS = {
    "Book Appointment": ["booking", "book", "janji", "appointment", "reservasi", "daftar"],
    "Operating Hours": ["jam buka", "jam operasional", "operasional", "buka", "tutup"],
    "Pricing Inquiry": ["harga", "biaya", "tarif", "price"],
    "Insurance Claims": ["bpjs", "asuransi", "insurance", "klaim", "rujukan"],
    "Complex Symptoms": ["nyeri", "sakit", "demam", "mual", "sesak", "pusing", "batuk", "diare"],
    "Billing Dispute": ["tagihan", "billing", "invoice", "kwitansi", "pembayaran", "bayar"],
    "Reschedule Request": ["reschedule", "jadwal ulang", "ubah jadwal", "ganti jadwal", "pindah jadwal"],
}

BOOKING_KEYWORDS = TOPIC_KEYWORDS["Book Appointment"]


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _as_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _current_period_start(now: datetime, range_key: str) -> datetime:
    if range_key == "day":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if range_key == "week":
        start = now - timedelta(days=now.weekday())
        return start.replace(hour=0, minute=0, second=0, microsecond=0)
    if range_key == "month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    raise HTTPException(status_code=422, detail="range harus salah satu dari day|week|month")


def _window(range_key: str) -> tuple[datetime, datetime, datetime]:
    now = datetime.now(timezone.utc)
    current_start = _current_period_start(now, range_key)
    elapsed = now - current_start
    previous_end = current_start
    previous_start = previous_end - elapsed
    return previous_start, current_start, now


def _fetch_messages(start_at: date, end_at: date) -> list[dict]:
    _require_supabase()
    start_datetime = datetime.combine(start_at, datetime.min.time(), tzinfo=timezone.utc)
    end_datetime = datetime.combine(end_at, datetime.min.time(), tzinfo=timezone.utc)
    response = (
        supabase.table("messages")
        .select("sender_number, message_text, direction, source, created_at")
        .gte("created_at", _as_iso(start_datetime))
        .lt("created_at", _as_iso(end_datetime))
        .order("created_at", desc=False)
        .execute()
    )
    return response.data or []


def _topic_from_text(text: str | None) -> str:
    payload = (text or "").lower()
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(keyword in payload for keyword in keywords):
            return topic
    return "Other"


def _is_chatbot_response(row: dict) -> bool:
    return (row.get("direction") == "outbound") and (row.get("source") != "admin")


def _is_human_response(row: dict) -> bool:
    return (row.get("direction") == "outbound") and (row.get("source") == "admin")


def _calc_delta(current: float, previous: float) -> float:
    if previous == 0:
        return 100.0 if current > 0 else 0.0
    return round(((current - previous) / previous) * 100, 2)


def _period_label(range_key: str) -> str:
    if range_key == "day":
        return "dibanding kemarin"
    if range_key == "week":
        return "dibanding minggu lalu"
    return "dibanding bulan lalu"


def _trend_payload(current: float, previous: float, *, as_percent_value: bool = False) -> dict:
    delta = _calc_delta(current, previous)
    direction = "naik" if delta > 0 else ("turun" if delta < 0 else "stabil")
    symbol = "+" if delta > 0 else ("-" if delta < 0 else "")
    value = round(current, 2) if as_percent_value else int(current)
    previous_value = round(previous, 2) if as_percent_value else int(previous)
    return {
        "nilai": value,
        "sebelumnya": previous_value,
        "perubahan_persen": delta,
        "arah_tren": direction,
        "simbol_tren": symbol,
    }


def _kpi_from_rows(rows: list[dict]) -> dict[str, float]:
    senders = {row.get("sender_number") for row in rows if row.get("sender_number")}
    outbound_rows = [row for row in rows if row.get("direction") == "outbound"]

    chatbot_count = sum(1 for row in outbound_rows if _is_chatbot_response(row))
    human_count = sum(1 for row in outbound_rows if _is_human_response(row))

    booking_senders = set()
    for row in rows:
        sender = row.get("sender_number")
        text = (row.get("message_text") or "").lower()
        if sender and any(keyword in text for keyword in BOOKING_KEYWORDS):
            booking_senders.add(sender)

    total_conversations = len(senders)
    booking_conversion = round((len(booking_senders) / total_conversations) * 100, 2) if total_conversations else 0.0

    return {
        "total_conversations": float(total_conversations),
        "total_chatbot_response": float(chatbot_count),
        "total_human_response": float(human_count),
        "booking_conversion": booking_conversion,
    }


def _bucket_start(value: datetime, bucket: str) -> datetime:
    if bucket == "hour":
        return value.replace(minute=0, second=0, microsecond=0)
    if bucket == "day":
        return value.replace(hour=0, minute=0, second=0, microsecond=0)
    if bucket == "week":
        start = value - timedelta(days=value.weekday())
        return start.replace(hour=0, minute=0, second=0, microsecond=0)
    raise HTTPException(status_code=422, detail="bucket harus salah satu dari hour|day|week")


def _bucket_step(bucket: str) -> timedelta:
    if bucket == "hour":
        return timedelta(hours=1)
    if bucket == "day":
        return timedelta(days=1)
    if bucket == "week":
        return timedelta(days=7)
    raise HTTPException(status_code=422, detail="bucket harus salah satu dari hour|day|week")


def _validate_bucket(range_key: str, bucket: str) -> None:
    if range_key == "day" and bucket not in {"hour", "day"}:
        raise HTTPException(status_code=422, detail="range=day hanya mendukung bucket=hour|day")
    if range_key == "week" and bucket not in {"day", "week"}:
        raise HTTPException(status_code=422, detail="range=week hanya mendukung bucket=day|week")


@router.get(
    "/summary",
    summary="Ringkasan KPI dari messages",
    description=(
        "Menyediakan 4 KPI utama (total conversation, chatbot response, human response, booking conversion) "
        "dengan delta persen terhadap periode sebelumnya. Sumber data: tabel messages saja."
    ),
)
def get_analytics_summary(range: str = Query("day", description="day | week | month")):
    if range not in VALID_RANGES:
        raise HTTPException(status_code=422, detail="range harus salah satu dari day|week|month")

    try:
        previous_start, current_start, now = _window(range)
        rows = _fetch_messages(previous_start, now)

        previous_rows: list[dict] = []
        current_rows: list[dict] = []
        for row in rows:
            created_at = _parse_ts(row.get("created_at"))
            if not created_at:
                continue
            if created_at < current_start:
                previous_rows.append(row)
            else:
                current_rows.append(row)

        current_kpi = _kpi_from_rows(current_rows)
        previous_kpi = _kpi_from_rows(previous_rows)

        total_conversations = _trend_payload(
            current_kpi["total_conversations"],
            previous_kpi["total_conversations"],
        )
        total_chatbot_response = _trend_payload(
            current_kpi["total_chatbot_response"],
            previous_kpi["total_chatbot_response"],
        )
        total_human_response = _trend_payload(
            current_kpi["total_human_response"],
            previous_kpi["total_human_response"],
        )
        booking_conversion = _trend_payload(
            current_kpi["booking_conversion"],
            previous_kpi["booking_conversion"],
            as_percent_value=True,
        )

        period_label = _period_label(range)

        cards = [
            {
                "kunci": "total_percakapan",
                "judul": "Total Percakapan",
                "nilai": total_conversations["nilai"],
                "sebelumnya": total_conversations["sebelumnya"],
                "perubahan_persen": total_conversations["perubahan_persen"],
                "arah_tren": total_conversations["arah_tren"],
                "simbol_tren": total_conversations["simbol_tren"],
                "label_tren": f"{total_conversations['simbol_tren']}{abs(total_conversations['perubahan_persen'])}% {period_label}",
            },
            {
                "kunci": "total_respons_chatbot",
                "judul": "Total Respons Chatbot",
                "nilai": total_chatbot_response["nilai"],
                "sebelumnya": total_chatbot_response["sebelumnya"],
                "perubahan_persen": total_chatbot_response["perubahan_persen"],
                "arah_tren": total_chatbot_response["arah_tren"],
                "simbol_tren": total_chatbot_response["simbol_tren"],
                "label_tren": f"{total_chatbot_response['simbol_tren']}{abs(total_chatbot_response['perubahan_persen'])}% {period_label}",
            },
            {
                "kunci": "total_respons_admin",
                "judul": "Total Respons Admin",
                "nilai": total_human_response["nilai"],
                "sebelumnya": total_human_response["sebelumnya"],
                "perubahan_persen": total_human_response["perubahan_persen"],
                "arah_tren": total_human_response["arah_tren"],
                "simbol_tren": total_human_response["simbol_tren"],
                "label_tren": f"{total_human_response['simbol_tren']}{abs(total_human_response['perubahan_persen'])}% {period_label}",
            },
            {
                "kunci": "konversi_booking",
                "judul": "Konversi Booking",
                "nilai": booking_conversion["nilai"],
                "sebelumnya": booking_conversion["sebelumnya"],
                "perubahan_persen": booking_conversion["perubahan_persen"],
                "arah_tren": booking_conversion["arah_tren"],
                "simbol_tren": booking_conversion["simbol_tren"],
                "label_tren": f"{booking_conversion['simbol_tren']}{abs(booking_conversion['perubahan_persen'])}% {period_label}",
                "satuan": "%",
            },
        ]

        return {
            "rentang": range,
            "jendela_waktu": {
                "mulai_saat_ini": _as_iso(current_start),
                "selesai_saat_ini": _as_iso(now),
                "mulai_sebelumnya": _as_iso(previous_start),
                "selesai_sebelumnya": _as_iso(current_start),
            },
            "kartu": cards,
            "ringkasan_kpi": {
                "total_percakapan": total_conversations,
                "total_respons_chatbot": total_chatbot_response,
                "total_respons_admin": total_human_response,
                "konversi_booking": booking_conversion,
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/timeseries",
    summary="Tren conversations dan handling per waktu",
    description=(
        "Endpoint khusus grouping waktu. Mengembalikan conversation count serta handling chatbot vs human "
        "dalam bucket waktu (hour/day/week). Sumber data: tabel messages saja."
    ),
)
def get_analytics_timeseries(
    range: str = Query("day", description="day | week | month"),
    bucket: str = Query("hour", description="hour | day | week"),
):
    if range not in VALID_RANGES:
        raise HTTPException(status_code=422, detail="range harus salah satu dari day|week|month")
    if bucket not in VALID_BUCKETS:
        raise HTTPException(status_code=422, detail="bucket harus salah satu dari hour|day|week")
    _validate_bucket(range, bucket)

    try:
        _, current_start, now = _window(range)
        rows = _fetch_messages(current_start, now)

        aggregate: dict[datetime, dict] = defaultdict(
            lambda: {"senders": set(), "chatbot_response": 0, "human_response": 0}
        )

        for row in rows:
            created_at = _parse_ts(row.get("created_at"))
            if not created_at:
                continue

            slot = _bucket_start(created_at, bucket)
            sender = row.get("sender_number")
            if sender:
                aggregate[slot]["senders"].add(sender)

            if _is_chatbot_response(row):
                aggregate[slot]["chatbot_response"] += 1
            if _is_human_response(row):
                aggregate[slot]["human_response"] += 1

        step = _bucket_step(bucket)
        cursor = _bucket_start(current_start, bucket)
        end_slot = _bucket_start(now, bucket)

        points = []
        while cursor <= end_slot:
            item = aggregate.get(cursor, {"senders": set(), "chatbot_response": 0, "human_response": 0})
            points.append(
                {
                    "mulai_bucket": _as_iso(cursor),
                    "total_percakapan": len(item["senders"]),
                    "total_respons_chatbot": item["chatbot_response"],
                    "total_respons_admin": item["human_response"],
                }
            )
            cursor = cursor + step

        return {
            "rentang": range,
            "kelompok_waktu": bucket,
            "jendela_waktu": {"mulai": _as_iso(current_start), "selesai": _as_iso(now)},
            "seri": {
                "kunci_percakapan": "total_percakapan",
                "kunci_penanganan": ["total_respons_chatbot", "total_respons_admin"],
            },
            "titik": points,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/insights",
    summary="AI chatbot insights berbasis messages",
    description=(
        "Mengembalikan top detected intents, low-confidence intents (proxy), dan frequently escalated topics. "
        "Semua dihitung heuristik dari tabel messages tanpa tabel tambahan."
    ),
)
def get_analytics_insights(range: str = Query("day", description="day | week | month")):
    if range not in VALID_RANGES:
        raise HTTPException(status_code=422, detail="range harus salah satu dari day|week|month")

    try:
        _, current_start, now = _window(range)
        rows = _fetch_messages(current_start, now)

        inbound_topic_counter: Counter[str] = Counter()
        groq_topic_counter: Counter[str] = Counter()
        escalated_topic_counter: Counter[str] = Counter()
        last_inbound_topic_by_sender: dict[str, tuple[str, datetime]] = {}

        for row in rows:
            created_at = _parse_ts(row.get("created_at"))
            if not created_at:
                continue

            sender = row.get("sender_number") or ""
            direction = row.get("direction")
            source = row.get("source")
            topic = _topic_from_text(row.get("message_text"))

            if direction == "inbound":
                inbound_topic_counter[topic] += 1
                if sender:
                    last_inbound_topic_by_sender[sender] = (topic, created_at)
                continue

            if direction == "outbound" and sender in last_inbound_topic_by_sender:
                last_topic, last_time = last_inbound_topic_by_sender[sender]
                if (created_at - last_time) > timedelta(minutes=15):
                    continue

                if source == "groq":
                    groq_topic_counter[last_topic] += 1
                if source == "admin":
                    escalated_topic_counter[last_topic] += 1

        top_detected = [
            {"intent": topic, "jumlah": count}
            for topic, count in inbound_topic_counter.most_common(3)
            if topic != "Other"
        ]

        low_confidence_candidates = []
        for topic, total in inbound_topic_counter.items():
            if topic == "Other" or total < 3:
                continue
            groq_hits = groq_topic_counter.get(topic, 0)
            estimated_conf = round(max(0.0, 100.0 * (1.0 - (groq_hits / total))), 1)
            if groq_hits > 0:
                low_confidence_candidates.append(
                    {
                        "intent": topic,
                        "estimasi_persen_kepercayaan": estimated_conf,
                        "jumlah": groq_hits,
                    }
                )

        low_confidence = sorted(
            low_confidence_candidates,
            key=lambda x: (x["estimasi_persen_kepercayaan"], -x["jumlah"]),
        )[:3]

        frequently_escalated = [
            {"topik": topic, "jumlah_handoff": count}
            for topic, count in escalated_topic_counter.most_common(3)
            if topic != "Other"
        ]

        return {
            "rentang": range,
            "jendela_waktu": {"mulai": _as_iso(current_start), "selesai": _as_iso(now)},
            "intent_terdeteksi_teratas": top_detected,
            "intent_kepercayaan_rendah": low_confidence,
            "sering_dieskalasi": frequently_escalated,
            "catatan": [
                "Insights dihitung dari messages dengan pendekatan heuristik.",
                "Nilai low-confidence menggunakan proxy berbasis respons source=groq, bukan confidence asli model.",
            ],
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc