# ======================================================
# SmartClinic CRM AI — routers/send.py
# Endpoint: /api/send
#
# Last Change   :   11 Jun 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

import asyncio
import os
import io
import mimetypes

from fastapi import APIRouter, Body, File, Form, HTTPException, Request, UploadFile

from App.activity_logger import log_activity
from App.config import supabase
from App.models import SendMessagePayload, BroadcastPayload, BroadcastResult, SendInteractiveTargetPayload
from App.helpers import (
    save_to_supabase,
    _require_supabase,
    normalize_phone_number,
    normalize_whatsapp_target,
    save_image_from_bytes,
    save_image_from_url,
)
from App.queue_manager import fonnte_queue
from App.wa_gateway import send_text_best_effort
from App.wa_gateway import buat_menu_booking, buat_menu_layanan, buat_poll_feedback
from App.wa_service_client import wa_service_request

router = APIRouter(prefix="/api/send", tags=["Send"])


SEND_EXAMPLE = {
    "status": "ok",
    "message": "Pesan untuk 6281234567890 masuk antrian",
}

SEND_ATTACHMENT_EXAMPLE = {
    "status": "ok",
    "message": "Pesan untuk 6281234567890 masuk antrian",
}

SEND_ERROR_EXAMPLE = {"detail": "..."}

BROADCAST_EXAMPLE = {
    "status": "ok",
    "total_sent": 2,
    "recipients": ["6281234567890", "6289876543210"],
}

SEND_MEDIA_EXAMPLE = {
    "status": "ok",
    "message": "Media untuk 6281234567890 masuk antrian",
}

SEND_INTERACTIVE_EXAMPLE = {
    "status": "ok",
    "message": "Interactive message untuk 6281234567890 masuk antrian",
}

SEND_BROADCAST_UPLOAD_EXAMPLE = {
    "status": "ok",
    "total_sent": 2,
    "recipients": ["6281234567890", "6289876543210"],
}


def _send_media_to_target(
    target: str,
    message: str,
    *,
    file_name: str,
    file_bytes: bytes,
    content_type: str,
):
    return wa_service_request(
        "POST",
        "/send-media",
        data={
            "target": target,
            "message": message,
        },
        files={
            "file": (
                file_name,
                io.BytesIO(file_bytes),
                content_type,
            )
        },
        timeout=60,
    )


# ======================================================
#
#               SEND MESSAGE ENDPOINTS
#
# ======================================================

@router.post(
    "",
    summary="Kirim pesan ke satu nomor",
    description=(
        "Kirim pesan teks ke satu nomor via Fonnte, atau kirim attachment via wa-service "
        "jika attachment_url diisi. Pesan tetap dicatat ke Supabase sebagai outbound."
    ),
    responses={
        200: {
            "description": "Pesan berhasil dimasukkan antrian",
            "content": {
                "application/json": {
                    "examples": {
                        "textMessage": {"summary": "Pesan teks", "value": SEND_EXAMPLE},
                        "attachmentMessage": {"summary": "Pesan dengan attachment", "value": SEND_ATTACHMENT_EXAMPLE},
                    }
                }
            },
        },
        500: {
            "description": "Gagal mengirim pesan",
            "content": {"application/json": {"example": SEND_ERROR_EXAMPLE}},
        },
    },
)
async def send_message(
    request: Request,
    payload: SendMessagePayload = Body(
        ...,
        examples={
            "sendMessageExample": {
                "summary": "Contoh request kirim pesan",
                "value": {
                    "target": "6281234567890",
                    "message": "Halo, ini pesan dari admin SmartClinic.",
                    "attachment_url": None,
                    "filename": None,
                },
            }
        },
    )
):
    try:
        target = normalize_whatsapp_target(payload.target)
        delivery = None
        
        # Resolve local image_url if not already provided
        image_url = payload.image_url
        if not image_url and payload.attachment_url:
            image_url = save_image_from_url(payload.attachment_url, payload.filename)

        if payload.attachment_url:
            # Kirim via whatsapp-web.js (attachment) 
            response = wa_service_request(
                "POST",
                "/send-attachment",
                json={
                    "target": target,
                    "message": payload.message,
                    "attachment_url": payload.attachment_url,
                    "filename": payload.filename,
                },
                timeout=30,
            )
            response.raise_for_status()
            source = "wa-service"
            delivery = response.json()
        else:
            send_result = send_text_best_effort(target, payload.message)
            source = send_result.get("channel", "manual")
            delivery = send_result

        save_to_supabase(target, payload.message, direction="outbound", source=source, image_url=image_url)
        
        await log_activity(
            category="messaging",
            action="SEND_MESSAGE",
            from_actor=request.client.host if request.client else "system",
            message=f"Pesan dikirim ke {target} via {source}",
            metadata={"target": target, "source": source, "message_preview": payload.message[:100]},
        )
        
        print(f"[SEND] {source} → {target}: {payload.message[:60]}...")
        return {
            "status": "ok",
            "message": f"Pesan untuk {target} diproses via {source}",
            "source": source,
            "delivery": delivery,
        }

    except Exception as e:
        await log_activity(
            category="messaging",
            action="SEND_MESSAGE_FAILED",
            from_actor=request.client.host if request.client else "system",
            message=f"Gagal mengirim pesan ke {payload.target}",
            metadata={"target": payload.target, "error": str(e)},
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/media",
    summary="Kirim media via upload langsung",
    description=(
        "Upload file langsung tanpa link. File disimpan lokal di chat_files pada wa-service, lalu dikirim sesuai tipe media: "
        "image/video/audio/document."
    ),
    responses={
        200: {
            "description": "Media berhasil dimasukkan antrian",
            "content": {"application/json": {"example": SEND_MEDIA_EXAMPLE}},
        },
        400: {
            "description": "Request tidak valid",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
        500: {
            "description": "Gagal mengirim media",
            "content": {"application/json": {"example": SEND_ERROR_EXAMPLE}},
        },
    },
)
async def send_media(
    request: Request,
    target: str = Form(..., description="Nomor WhatsApp tujuan"),
    message: str = Form(default="", description="Caption/pesan pendamping"),
    file: UploadFile = File(..., description="File media yang akan dikirim"),
):
    try:
        normalized_target = normalize_whatsapp_target(target)

        file_bytes = file.file.read()
        image_url = save_image_from_bytes(file_bytes, file.filename or "upload")

        response = _send_media_to_target(
            normalized_target,
            message,
            file_name=file.filename or "upload",
            file_bytes=file_bytes,
            content_type=file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream",
        )
        response.raise_for_status()

        save_to_supabase(normalized_target, message or file.filename or "media", direction="outbound", source="wa-service", image_url=image_url)
        
        await log_activity(
            category="messaging",
            action="SEND_MEDIA",
            from_actor=request.client.host if request.client else "system",
            message=f"Media dikirim ke {normalized_target}",
            metadata={"target": normalized_target, "filename": file.filename, "content_type": file.content_type},
        )
        
        print(f"[SEND] wa-service/media → {normalized_target}: {file.filename or 'upload'}")
        return {
            "status": "ok",
            "message": f"Media untuk {normalized_target} masuk antrian",
            "wa_service_response": response.json(),
        }

    except Exception as e:
        await log_activity(
            category="messaging",
            action="SEND_MEDIA_FAILED",
            from_actor=request.client.host if request.client else "system",
            message=f"Gagal mengirim media ke {target}",
            metadata={"target": target, "filename": file.filename, "error": str(e)},
        )
        raise HTTPException(status_code=500, detail=str(e))


# @router.post(
#     "/interactive/booking",
#     summary="Kirim menu booking ke nomor tertentu",
#     description="Mengirim menu booking interaktif ke satu nomor. Jika wa-service tidak ready, otomatis fallback ke teks biasa.",
#     responses={
#         200: {"description": "Menu booking berhasil dikirim", "content": {"application/json": {"example": SEND_INTERACTIVE_EXAMPLE}}},
#         500: {"description": "Gagal mengirim menu booking", "content": {"application/json": {"example": SEND_ERROR_EXAMPLE}}},
#     },
# )
# def send_interactive_booking(
#     payload: SendInteractiveTargetPayload = Body(
#         ...,
#         examples={
#             "interactiveBookingExample": {
#                 "summary": "Contoh request menu booking",
#                 "value": {"target": "6281234567890"},
#             }
#         },
#     ),
# ):
#     try:
#         target = normalize_whatsapp_target(payload.target)
#         result = buat_menu_booking(target)
#         save_to_supabase(target, "[interactive] booking menu", direction="outbound", source=result.get("channel", "interactive"))
#         return {
#             "status": "ok",
#             "message": f"Menu booking untuk {target} masuk antrian",
#             "result": result,
#         }
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# @router.post(
#     "/interactive/services",
#     summary="Kirim menu layanan ke nomor tertentu",
#     description="Mengirim menu layanan interaktif ke satu nomor. Jika wa-service tidak ready, otomatis fallback ke teks biasa.",
#     responses={
#         200: {"description": "Menu layanan berhasil dikirim", "content": {"application/json": {"example": SEND_INTERACTIVE_EXAMPLE}}},
#         500: {"description": "Gagal mengirim menu layanan", "content": {"application/json": {"example": SEND_ERROR_EXAMPLE}}},
#     },
# )
# def send_interactive_services(
#     payload: SendInteractiveTargetPayload = Body(
#         ...,
#         examples={
#             "interactiveServicesExample": {
#                 "summary": "Contoh request menu layanan",
#                 "value": {"target": "6281234567890"},
#             }
#         },
#     ),
# ):
#     try:
#         target = normalize_whatsapp_target(payload.target)
#         result = buat_menu_layanan(target)
#         save_to_supabase(target, "[interactive] layanan menu", direction="outbound", source=result.get("channel", "interactive"))
#         return {
#             "status": "ok",
#             "message": f"Menu layanan untuk {target} masuk antrian",
#             "result": result,
#         }
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


# @router.post(
#     "/interactive/poll-feedback",
#     summary="Kirim polling feedback ke nomor tertentu",
#     description="Mengirim poll interaktif ke satu nomor. Jika wa-service tidak ready, otomatis fallback ke teks biasa.",
#     responses={
#         200: {"description": "Polling berhasil dikirim", "content": {"application/json": {"example": SEND_INTERACTIVE_EXAMPLE}}},
#         500: {"description": "Gagal mengirim polling", "content": {"application/json": {"example": SEND_ERROR_EXAMPLE}}},
#     },
# )
# def send_interactive_poll(
#     payload: SendInteractiveTargetPayload = Body(
#         ...,
#         examples={
#             "interactivePollExample": {
#                 "summary": "Contoh request polling",
#                 "value": {"target": "6281234567890"},
#             }
#         },
#     ),
# ):
#     try:
#         target = normalize_whatsapp_target(payload.target)
#         result = buat_poll_feedback(target)
#         save_to_supabase(target, "[interactive] poll feedback", direction="outbound", source=result.get("channel", "interactive"))
#         return {
#             "status": "ok",
#             "message": f"Polling feedback untuk {target} masuk antrian",
#             "result": result,
#         }
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


def broadcast_to_patients(
    message: str,
    *,
    attachment_url: str | None = None,
    filename: str | None = None,
    file: UploadFile | None = None,
    attachment_file_path: str | None = None,
    image_url: str | None = None,
) -> BroadcastResult:
    _require_supabase()

    response = supabase.table("patients").select("phone_number").execute()
    patients = response.data

    if not patients:
        raise HTTPException(
            status_code=404,
            detail="Tidak ada nomor pasien tersimpan.",
        )

    recipients = []

    file_bytes: bytes | None = None
    file_name: str | None = None
    file_content_type = "application/octet-stream"

    # Resolve image_url once for the whole broadcast (deduplicated file saving)
    if file is not None:
        file.file.seek(0)
        file_bytes = file.file.read()
        file.file.seek(0)
        file_name = file.filename or "upload"
        file_content_type = file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"
        if not image_url:
            image_url = save_image_from_bytes(file_bytes, file_name)
    elif attachment_file_path:
        with open(attachment_file_path, "rb") as file_handle:
            file_bytes = file_handle.read()
        file_name = os.path.basename(attachment_file_path) or "upload"
        file_content_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        if not image_url:
            image_url = save_image_from_bytes(file_bytes, file_name)
    elif attachment_url:
        if not image_url:
            image_url = save_image_from_url(attachment_url, filename)

    for patient in patients:
        number = normalize_phone_number(patient.get("phone_number", ""))
        if not number:
            continue

        if file_bytes is not None and file_name is not None:
            _send_media_to_target(
                number,
                message,
                file_name=file_name,
                file_bytes=file_bytes,
                content_type=file_content_type,
            )
            source = "wa-service"
        elif attachment_url:
            wa_service_request(
                "POST",
                "/send-attachment",
                json={
                    "target": number,
                    "message": message,
                    "attachment_url": attachment_url,
                    "filename": filename,
                },
                timeout=30,
            )
            source = "wa-service"
        else:
            send_result = send_text_best_effort(number, message)
            source = send_result.get("channel", "broadcast")

        save_to_supabase(number, message, direction="outbound", source=source, image_url=image_url)
        recipients.append(number)

    return BroadcastResult(status="ok", total_sent=len(recipients), recipients=recipients)


@router.post(
    "/broadcast",
    response_model=BroadcastResult,
    summary="Broadcast pesan ke semua nomor pasien",
    description=(
        "Kirim satu pesan ke seluruh nomor di tabel patients. Endpoint ini memakai multipart/form-data "
        "agar bisa kirim teks + attachment upload langsung."
    ),
    responses={
        200: {
            "description": "Broadcast berhasil dikirim",
            "content": {"application/json": {"example": SEND_BROADCAST_UPLOAD_EXAMPLE}},
        },
        404: {
            "description": "Tidak ada nomor pasien",
            "content": {"application/json": {"example": {"detail": "Tidak ada nomor pasien tersimpan."}}},
        },
        500: {
            "description": "Broadcast gagal",
            "content": {"application/json": {"example": SEND_ERROR_EXAMPLE}},
        },
    },
)
async def broadcast_message(
    request: Request,
    message: str = Form(..., description="Isi pesan yang akan dikirim ke semua pasien"),
    file: UploadFile | None = File(default=None, description="Attachment upload langsung (opsional)"),
):
    try:
        result = await asyncio.to_thread(broadcast_to_patients, message, None, None, file, None)
        
        await log_activity(
            category="messaging",
            action="BROADCAST_MESSAGE",
            from_actor=request.client.host if request.client else "system",
            message=f"Broadcast dikirim ke {result.total_sent} pasien",
            metadata={"total_sent": result.total_sent, "message_preview": message[:100]},
        )
        
        print(f"[BROADCAST] {result.total_sent} pesan masuk antrian")
        return result

    except HTTPException:
        await log_activity(
            category="messaging",
            action="BROADCAST_MESSAGE_FAILED",
            from_actor=request.client.host if request.client else "system",
            message="Broadcast gagal - tidak ada pasien",
        )
        raise
    except Exception as e:
        await log_activity(
            category="messaging",
            action="BROADCAST_MESSAGE_FAILED",
            from_actor=request.client.host if request.client else "system",
            message=f"Broadcast gagal: {str(e)}",
            metadata={"error": str(e)},
        )
        raise HTTPException(status_code=500, detail=str(e))
