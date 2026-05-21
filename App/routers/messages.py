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
        # 1. Ambil data awal (kita biarkan desc=True untuk limitasi data terbaru di database)
        result = supabase.table("messages").select("*") \
            .eq("sender_number", phone_number) \
            .order("created_at", desc=True).limit(limit).execute()

        # Kita balik urutan datanya di Python biar kronologis sejak awal (Lama -> Baru)
        initial_data = list(reversed(result.data)) if result.data else []

        # Kirim data awal ke frontend dengan event 'initial'
        yield {"event": "initial", "data": __import__('json').dumps(initial_data)}

        # Simpan state ID pesan yang sudah diketahui
        known_ids = {r["id"] for r in result.data} if result.data else set()

        while True:
            if await request.is_disconnected():
                break
                
            await asyncio.sleep(2)
            
            # Cek apakah ada pesan baru masuk
            check_new = supabase.table("messages").select("id") \
                .eq("sender_number", phone_number) \
                .order("created_at", desc=True).limit(5).execute()
                
            has_new = any(m["id"] not in known_ids for m in check_new.data) if check_new.data else False

            if has_new:
                # 2. Jika terdeteksi ada pesan baru, tarik riwayat utuh terupdate sesuai limit
                updated_result = supabase.table("messages").select("*") \
                    .eq("sender_number", phone_number) \
                    .order("created_at", desc=True).limit(limit).execute()
                
                # Update daftar known_ids
                known_ids = {r["id"] for r in updated_result.data}
                
                # Balik urutan agar kronologis (Lama -> Baru)
                updated_data = list(reversed(updated_result.data))
                
                # Kirim data utuh menggunakan event 'update' agar frontend merender ulang secara realtime
                yield {"event": "update", "data": __import__('json').dumps(updated_data)}
            else:
                yield {"event": "heartbeat", "data": "null"}

    return EventSourceResponse(generator())