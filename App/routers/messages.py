# ======================================================
# SmartClinic CRM AI — routers/messages.py
# Endpoint: /api/messages
#
# Last Change   :   16 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

import asyncio
import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from supabase import create_client
from App.config import supabase_url, supabase_key
from App.helpers import _require_supabase

router = APIRouter(prefix="/api/messages", tags=["Messages"])

def make_sse(event_type: str, data):
    return f"data: {json.dumps({'type': event_type, 'data': data})}\n\n"

# ======================================================
#
#                  MESSAGES ENDPOINTS
#
# ======================================================

@router.get(
    "",
    summary="Stream semua pesan via SSE",
    description="SSE — kirim initial data lalu push update setiap ada pesan baru. Gunakan EventSource di frontend.",
)
async def get_all_messages(limit: int = 100):
    _require_supabase()

    async def generator():
        queue = asyncio.Queue()
        client = create_client(supabase_url, supabase_key)

        def on_insert(payload):
            queue.put_nowait(payload.get("new"))

        client.channel("msgs-all") \
            .on("postgres_changes", {"event": "INSERT", "schema": "public", "table": "messages"}, on_insert) \
            .subscribe()

        # Initial data
        result = client.table("messages").select("*").order("created_at", desc=False).limit(limit).execute()
        yield make_sse("initial", result.data)

        try:
            while True:
                try:
                    new_msg = await asyncio.wait_for(queue.get(), timeout=30)
                    yield make_sse("new_message", new_msg)
                except asyncio.TimeoutError:
                    yield make_sse("heartbeat", None)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(generator(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get(
    "/latest",
    summary="Stream latest messages via SSE",
    description="SSE — 1 pesan terbaru per nomor beserta nama dan status handoff. Push setiap ada pesan baru atau perubahan handoff.",
)
async def get_latest_messages():
    _require_supabase()

    async def generator():
        queue = asyncio.Queue()
        client = create_client(supabase_url, supabase_key)

        def on_change(payload):
            queue.put_nowait(True)

        client.channel("msgs-latest-msg") \
            .on("postgres_changes", {"event": "INSERT", "schema": "public", "table": "messages"}, on_change) \
            .subscribe()

        client.channel("msgs-latest-pat") \
            .on("postgres_changes", {"event": "UPDATE", "schema": "public", "table": "patients"}, on_change) \
            .subscribe()

        # Initial data
        result = client.rpc("get_latest_messages").execute()
        yield make_sse("initial", result.data)

        try:
            while True:
                try:
                    await asyncio.wait_for(queue.get(), timeout=30)
                    result = client.rpc("get_latest_messages").execute()
                    yield make_sse("update", result.data)
                except asyncio.TimeoutError:
                    yield make_sse("heartbeat", None)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(generator(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get(
    "/{phone_number}",
    summary="Stream pesan per nomor via SSE",
    description="SSE — stream semua pesan satu nomor lalu push setiap ada pesan baru dari nomor tersebut.",
)
async def get_messages_by_number(phone_number: str):
    _require_supabase()

    async def generator():
        queue = asyncio.Queue()
        client = create_client(supabase_url, supabase_key)

        def on_insert(payload):
            new_msg = payload.get("new", {})
            if new_msg.get("sender_number") == phone_number:
                queue.put_nowait(new_msg)

        client.channel(f"msgs-{phone_number}") \
            .on("postgres_changes", {"event": "INSERT", "schema": "public", "table": "messages"}, on_insert) \
            .subscribe()

        # Initial data
        result = client.table("messages").select("*") \
            .eq("sender_number", phone_number) \
            .order("created_at", desc=False).execute()

        if not result.data:
            yield make_sse("error", {"detail": f"Tidak ada pesan untuk nomor {phone_number}"})
            return

        yield make_sse("initial", result.data)

        try:
            while True:
                try:
                    new_msg = await asyncio.wait_for(queue.get(), timeout=30)
                    yield make_sse("new_message", new_msg)
                except asyncio.TimeoutError:
                    yield make_sse("heartbeat", None)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(generator(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})