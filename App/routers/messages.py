# ======================================================
# SmartClinic CRM AI — routers/messages.py
# Endpoint: /api/messages
#
# Last Change   :   21 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

import asyncio
from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse
from App.config import supabase
from App.helpers import _require_supabase

router = APIRouter(prefix="/api/messages", tags=["Messages"])


# @router.get("", summary="Stream semua pesan via SSE")
# async def get_all_messages(request: Request, limit: int = 100):
#     _require_supabase()

#     async def generator():
#         result = supabase.table("messages").select("*") \
#             .order("created_at", desc=True).limit(limit).execute()

#         known_ids = {r["id"] for r in result.data}
#         yield {"event": "initial", "data": __import__('json').dumps(result.data)}

#         while True:
#             if await request.is_disconnected():
#                 break
#             await asyncio.sleep(2)
#             new = supabase.table("messages").select("*") \
#                 .order("created_at", desc=True).limit(20).execute()
#             new_msgs = [m for m in new.data if m["id"] not in known_ids]
#             if new_msgs:
#                 for m in new_msgs:
#                     known_ids.add(m["id"])
#                 yield {"event": "new_message", "data": __import__('json').dumps(new_msgs)}
#             else:
#                 yield {"event": "heartbeat", "data": "null"}

#     return EventSourceResponse(generator())


@router.get("/latest", summary="Stream latest messages via SSE")
async def get_latest_messages(request: Request):
    _require_supabase()

    async def generator():
        result = supabase.rpc("get_latest_messages").execute()
        last_data = {r["sender_number"]: r for r in result.data}
        yield {"event": "initial", "data": __import__('json').dumps(result.data)}

        while True:
            if await request.is_disconnected():
                break
            await asyncio.sleep(2)
            new_result = supabase.rpc("get_latest_messages").execute()
            new_data = {r["sender_number"]: r for r in new_result.data}
            if new_data != last_data:
                last_data = new_data
                yield {"event": "update", "data": __import__('json').dumps(new_result.data)}
            else:
                yield {"event": "heartbeat", "data": "null"}

    return EventSourceResponse(generator())


@router.get("/{phone_number}", summary="Stream pesan per nomor via SSE")
async def get_messages_by_number(request: Request, phone_number: str, limit: int = 50):
    _require_supabase()

    async def generator():
        result = supabase.table("messages").select("*") \
            .eq("sender_number", phone_number) \
            .order("created_at", desc=True).limit(limit).execute()

        if not result.data:
            yield {"event": "error", "data": __import__('json').dumps(
                {"detail": f"Tidak ada pesan untuk nomor {phone_number}"}
            )}
            return

        known_ids = {r["id"] for r in result.data}
        yield {"event": "initial", "data": __import__('json').dumps(result.data)}

        while True:
            if await request.is_disconnected():
                break
            await asyncio.sleep(2)
            new = supabase.table("messages").select("*") \
                .eq("sender_number", phone_number) \
                .order("created_at", desc=True).limit(10).execute()
            new_msgs = [m for m in new.data if m["id"] not in known_ids]
            if new_msgs:
                for m in new_msgs:
                    known_ids.add(m["id"])
                yield {"event": "new_message", "data": __import__('json').dumps(new_msgs)}
            else:
                yield {"event": "heartbeat", "data": "null"}

    return EventSourceResponse(generator())