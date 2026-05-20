# ======================================================
# SmartClinic CRM AI — routers/messages.py
# Endpoint: /api/messages
#
# Last Change   :   16 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

import asyncio
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from supabase._async.client import AsyncClient, create_client as acreate_client
from App.config import supabase_url, supabase_key
from App.helpers import _require_supabase

router = APIRouter(prefix="/api/messages", tags=["Messages"])

def make_sse(event_type: str, data):
    return f"data: {json.dumps({'type': event_type, 'data': data})}\n\n"

async def get_async_client() -> AsyncClient:
    return await acreate_client(supabase_url, supabase_key)

# ======================================================
#
#                  MESSAGES ENDPOINTS
#
# ======================================================

# @router.get("", summary="Stream semua pesan via SSE")
# async def get_all_messages(limit: int = 100):
#     _require_supabase()

#     async def generator():
#         client = await get_async_client()
#         queue = asyncio.Queue()

#         def on_insert(payload):
#             queue.put_nowait(payload.get("new"))

#         channel = client.channel("msgs-all")
#         channel.on_postgres_changes("INSERT", schema="public", table="messages", callback=on_insert)
#         await channel.subscribe()

#         result = await client.table("messages").select("*").order("created_at", desc=False).limit(limit).execute()
#         yield make_sse("initial", result.data)

#         try:
#             while True:
#                 try:
#                     new_msg = await asyncio.wait_for(queue.get(), timeout=30)
#                     yield make_sse("new_message", new_msg)
#                 except asyncio.TimeoutError:
#                     yield make_sse("heartbeat", None)
#         except asyncio.CancelledError:
#             await client.remove_channel(channel)

#     return StreamingResponse(generator(), media_type="text/event-stream",
#         headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/latest", summary="Stream latest messages via SSE")
async def get_latest_messages(limit: int = Query(default=50, ge=1, le=100)):
    _require_supabase()

    async def generator():
        client = await get_async_client()
        queue = asyncio.Queue()

        def on_change(payload):
            queue.put_nowait(True)

        ch_msg = client.channel("msgs-latest-msg")
        ch_msg.on_postgres_changes("INSERT", schema="public", table="messages", callback=on_change)
        await ch_msg.subscribe()

        ch_pat = client.channel("msgs-latest-pat")
        ch_pat.on_postgres_changes("UPDATE", schema="public", table="patients", callback=on_change)
        await ch_pat.subscribe()

        result = await client.rpc("get_latest_messages", {"lim_val": limit}).execute()
        yield make_sse("initial", result.data)

        try:
            while True:
                try:
                    await asyncio.wait_for(queue.get(), timeout=30)
                    # 2. Oper parameter 'lim_val' juga saat ada update data baru
                    result = await client.rpc("get_latest_messages", {"lim_val": limit}).execute()
                    yield make_sse("update", result.data)
                except asyncio.TimeoutError:
                    yield make_sse("heartbeat", None)
        except asyncio.CancelledError:
            await client.remove_channel(ch_msg)
            await client.remove_channel(ch_pat)

    return StreamingResponse(
        generator(), 
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@router.get("/{phone_number}", summary="Stream pesan per nomor via SSE")
async def get_messages_by_number(phone_number: str, limit: int = 50):
    _require_supabase()

    async def generator():
        client = await get_async_client()
        queue = asyncio.Queue()

        def on_insert(payload):
            new_msg = payload.get("new", {})
            if new_msg.get("sender_number") == phone_number:
                queue.put_nowait(new_msg)

        channel = client.channel(f"msgs-{phone_number}")
        channel.on_postgres_changes("INSERT", schema="public", table="messages", callback=on_insert)
        await channel.subscribe()

        result = await client.table("messages").select("*") \
            .eq("sender_number", phone_number) \
            .order("created_at", desc=True).limit(limit).execute()

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
            await client.remove_channel(channel)

    return StreamingResponse(generator(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})