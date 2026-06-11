# ======================================================
# SmartClinic CRM AI — routers/messages.py
# Endpoint: /api/messages
#
# Last Change   :   11 Jun 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

import asyncio
import json

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from App.config import supabase
from App.helpers import _require_supabase, normalize_phone_number
from App.wa_service_client import wa_service_request

router = APIRouter(prefix="/api/messages", tags=["Unified Chat"])


# Source yang dikirim oleh AI/bot
AI_SOURCES = {"rasa", "groq", "system", "bot", "ai"}

# Source yang dikirim oleh human agent
HUMAN_SOURCES = {"agent", "admin", "human", "manual", "dashboard"}


def _enrich_messages(wa_messages: list, phone_number: str) -> list:
    """
    Merge pesan dari wa-service dengan metadata dari Supabase.
    Tambahkan field: sender, senderType, isEscalation, isBotReturn.
    """
    if not wa_messages:
        return []

    # Ambil data Supabase untuk nomor ini (source, direction, created_at)
    supabase_map: dict = {}
    if supabase:
        try:
            normalized = normalize_phone_number(phone_number)
            result = (
                supabase.table("messages")
                .select("id, message_text, direction, source, created_at")
                .eq("sender_number", normalized)
                .order("created_at", desc=False)
                .limit(200)
                .execute()
            )
            # Index by message_text + direction untuk matching (wa-service tidak punya Supabase ID)
            for row in (result.data or []):
                key = (row.get("message_text", "").strip(), row.get("direction", ""))
                # Simpan yang terbaru jika duplikat
                supabase_map[key] = row
        except Exception as e:
            print(f"[enrich_messages] Gagal ambil data Supabase: {e}")

    enriched = []
    for msg in wa_messages:
        body = (msg.get("body") or "").strip()
        from_me = msg.get("fromMe", False)
        direction = "outbound" if from_me else "inbound"

        # Default values
        sender = "agent" if from_me else "user"
        sender_type = "ai"  # default outbound = ai

        # Cari di Supabase untuk tahu source-nya
        sb_row = supabase_map.get((body, direction))
        if sb_row:
            source = sb_row.get("source", "")
            if direction == "outbound":
                if source in HUMAN_SOURCES:
                    sender_type = "human"
                else:
                    sender_type = "ai"
        elif direction == "inbound":
            sender_type = "user"

        enriched.append({
            **msg,
            "sender": sender,
            "senderType": sender_type,
            "isEscalation": False,   # dihitung di FE via processedMessages
            "isBotReturn": False,    # dihitung di FE via processedMessages
        })

    return enriched


LATEST_MESSAGES_EXAMPLE = [
    {
        "id": "c7e1c0a8-5d0f-4a6f-9a84-8c3b5f6c1111",
        "sender_number": "6281234567890",
        "message_text": "Halo, jadwal dokter hari ini apa ya?",
        "direction": "inbound",
        "source": "fonnte",
        "created_at": "2026-05-22T10:00:00Z",
    }
]

MESSAGES_BY_NUMBER_EXAMPLE = [
    {
        "id": "d4b4e12a-91cd-4c8f-9f5f-31a9d0b21111",
        "body": "Halo, saya ingin cek jadwal dokter.",
        "fromMe": False,
        "sender": "user",
        "senderType": "user",
    },
    {
        "id": "f0d2a1a7-4f71-4d35-bf23-2c0d62d51111",
        "body": "Jadwal dokter hari ini pukul 09.00 - 17.00.",
        "fromMe": True,
        "sender": "agent",
        "senderType": "ai",
    },
]

SSE_INITIAL_EVENT_EXAMPLE = "event: initial\ndata: [...]"
SSE_UPDATE_EVENT_EXAMPLE = "event: update\ndata: [...]"


@router.get(
    "/latest",
    summary="Stream latest messages via SSE",
    description="Mengirim snapshot pesan terbaru per nomor, lalu update realtime jika ada perubahan di tabel messages.",
    responses={
        200: {
            "description": "Stream SSE aktif",
            "content": {
                "text/event-stream": {
                    "examples": {
                        "initial": {"summary": "Event awal", "value": SSE_INITIAL_EVENT_EXAMPLE},
                        "update": {"summary": "Event update", "value": SSE_UPDATE_EVENT_EXAMPLE},
                    }
                }
            },
        },
        500: {
            "description": "Gagal memulai stream",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
async def get_latest_messages(request: Request):
    _require_supabase()

    async def generator():
        result = supabase.rpc("get_latest_messages").execute()
        last_data = {r["sender_number"]: r for r in result.data}
        yield {"event": "initial", "data": json.dumps(result.data)}

        while True:
            if await request.is_disconnected():
                break
            await asyncio.sleep(2)
            new_result = supabase.rpc("get_latest_messages").execute()
            new_data = {r["sender_number"]: r for r in new_result.data}
            if new_data != last_data:
                last_data = new_data
                yield {"event": "update", "data": json.dumps(new_result.data)}
            else:
                yield {"event": "heartbeat", "data": "null"}

    return EventSourceResponse(generator())


@router.get(
    "/{phone_number}",
    summary="Stream pesan per nomor via SSE",
    description="Mengirim riwayat pesan untuk satu nomor dengan metadata senderType (ai/human/user), lalu memperbarui stream jika ada pesan baru masuk.",
    responses={
        200: {
            "description": "Stream SSE aktif",
            "content": {
                "text/event-stream": {
                    "examples": {
                        "initial": {
                            "summary": "Event awal",
                            "value": f"event: initial\ndata: {json.dumps(MESSAGES_BY_NUMBER_EXAMPLE)}",
                        },
                        "update": {
                            "summary": "Event update",
                            "value": f"event: update\ndata: {json.dumps(MESSAGES_BY_NUMBER_EXAMPLE)}",
                        },
                    }
                }
            },
        },
        500: {
            "description": "Gagal memulai stream",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
async def get_messages_by_number(request: Request, phone_number: str, limit: int = 50):
    async def generator():
        # 1. Ambil data awal dari wa-service
        initial_data = []
        try:
            resp = wa_service_request(
                "GET", "/messages", params={"target": phone_number, "limit": limit}, timeout=10.0
            )
            if resp.status_code == 200:
                initial_data = resp.json().get("data", [])
        except Exception as e:
            print(f"[SSE] Error fetching initial messages from wwebjs: {e}")

        # 2. Enrich dengan senderType dari Supabase
        enriched = await asyncio.to_thread(_enrich_messages, initial_data, phone_number)

        yield {"event": "initial", "data": json.dumps(enriched)}

        known_ids = {m["id"] for m in initial_data} if initial_data else set()

        while True:
            if await request.is_disconnected():
                break

            await asyncio.sleep(2)

            current_data = []
            try:
                resp = wa_service_request(
                    "GET", "/messages", params={"target": phone_number, "limit": limit}, timeout=10.0
                )
                if resp.status_code == 200:
                    current_data = resp.json().get("data", [])
            except Exception as e:
                print(f"[SSE] Error polling messages from wwebjs: {e}")
                yield {"event": "heartbeat", "data": "null"}
                continue

            current_ids = {m["id"] for m in current_data} if current_data else set()
            has_new = not current_ids.issubset(known_ids) if current_ids else False

            if has_new:
                known_ids = current_ids
                # Enrich ulang dengan data Supabase terbaru
                enriched = await asyncio.to_thread(_enrich_messages, current_data, phone_number)
                yield {"event": "update", "data": json.dumps(enriched)}
            else:
                yield {"event": "heartbeat", "data": "null"}

    return EventSourceResponse(generator())