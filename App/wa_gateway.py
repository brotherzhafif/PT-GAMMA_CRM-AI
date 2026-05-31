from __future__ import annotations

import os
from typing import Any

import requests
from fastapi import HTTPException

from App.helpers import normalize_phone_number


def _wa_service_url() -> str:
    return os.getenv("WA_SERVICE_URL", "http://wa-service:3000").rstrip("/")


def _wa_service_ready() -> bool:
    try:
        response = requests.get(f"{_wa_service_url()}/status", timeout=4)
        if response.status_code != 200:
            return False
        data = response.json() or {}
        return bool(data.get("ready"))
    except Exception:
        return False


def send_text_best_effort(target: str, message: str) -> dict[str, Any]:
    normalized_target = normalize_phone_number(target)

    if _wa_service_ready():
        try:
            response = requests.post(
                f"{_wa_service_url()}/send-message",
                json={"target": normalized_target, "message": message},
                timeout=20,
            )
            response.raise_for_status()
            return {
                "channel": "wa-service",
                "target": normalized_target,
                "response": response.json(),
            }
        except Exception:
            pass

    from App.queue_manager import fonnte_queue

    fonnte_queue.add_to_queue(normalized_target, message)
    return {
        "channel": "fonnte",
        "target": normalized_target,
        "queued": True,
    }


def build_buttons_message(
    body: str,
    buttons: list[dict[str, str]],
    *,
    title: str | None = None,
    footer: str | None = None,
) -> dict[str, Any]:
    return {
        "type": "buttons",
        "body": body,
        "buttons": buttons,
        "title": title,
        "footer": footer,
    }


def build_list_message(
    body: str,
    button_text: str,
    sections: list[dict[str, Any]],
    *,
    title: str | None = None,
    footer: str | None = None,
) -> dict[str, Any]:
    return {
        "type": "list",
        "body": body,
        "buttonText": button_text,
        "sections": sections,
        "title": title,
        "footer": footer,
    }


def build_poll_message(
    poll_name: str,
    poll_options: list[str] | list[dict[str, Any]],
    *,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": "poll",
        "pollName": poll_name,
        "pollOptions": poll_options,
        "options": options or {},
    }


def send_interactive_message(target: str, payload: dict[str, Any]) -> dict[str, Any]:
    normalized_target = normalize_phone_number(target)

    if not _wa_service_ready():
        raise HTTPException(
            status_code=503,
            detail="WhatsApp web belum terkoneksi. Interactive message hanya bisa dikirim saat wa-service ready.",
        )

    response = requests.post(
        f"{_wa_service_url()}/send-interactive",
        json={"target": normalized_target, **payload},
        timeout=30,
    )
    response.raise_for_status()
    return {
        "channel": "wa-service",
        "target": normalized_target,
        "response": response.json(),
    }


def format_buttons_fallback(body: str, buttons: list[dict[str, str]], *, title: str | None = None, footer: str | None = None) -> str:
    lines = []
    if title:
        lines.append(title)
    if body:
        lines.append(body)
    for index, button in enumerate(buttons, start=1):
        label = button.get("body") or button.get("text") or button.get("title") or f"Opsi {index}"
        lines.append(f"{index}. {label}")
    if footer:
        lines.append(footer)
    return "\n".join(lines)


def format_list_fallback(body: str, button_text: str, sections: list[dict[str, Any]], *, title: str | None = None, footer: str | None = None) -> str:
    lines = []
    if title:
        lines.append(title)
    if body:
        lines.append(body)
    lines.append(f"Ketik / pilih: {button_text}")
    for section in sections:
        section_title = section.get("title") or "Bagian"
        lines.append(f"- {section_title}")
        for row in section.get("rows", []):
            row_title = row.get("title") or row.get("body") or "Opsi"
            row_description = row.get("description") or ""
            lines.append(f"  • {row_title}{f' - {row_description}' if row_description else ''}")
    if footer:
        lines.append(footer)
    return "\n".join(lines)


def format_poll_fallback(poll_name: str, poll_options: list[str] | list[dict[str, Any]], *, footer: str | None = None) -> str:
    lines = [poll_name]
    for index, option in enumerate(poll_options, start=1):
        if isinstance(option, str):
            label = option
        else:
            label = option.get("name") or option.get("body") or f"Opsi {index}"
        lines.append(f"{index}. {label}")
    if footer:
        lines.append(footer)
    return "\n".join(lines)


def send_buttons_best_effort(
    target: str,
    body: str,
    buttons: list[dict[str, str]],
    *,
    title: str | None = None,
    footer: str | None = None,
) -> dict[str, Any]:
    payload = build_buttons_message(body, buttons, title=title, footer=footer)
    if _wa_service_ready():
        try:
            return send_interactive_message(target, payload)
        except Exception:
            pass

    fallback_text = format_buttons_fallback(body, buttons, title=title, footer=footer)
    return send_text_best_effort(target, fallback_text)


def send_list_best_effort(
    target: str,
    body: str,
    button_text: str,
    sections: list[dict[str, Any]],
    *,
    title: str | None = None,
    footer: str | None = None,
) -> dict[str, Any]:
    payload = build_list_message(body, button_text, sections, title=title, footer=footer)
    if _wa_service_ready():
        try:
            return send_interactive_message(target, payload)
        except Exception:
            pass

    fallback_text = format_list_fallback(body, button_text, sections, title=title, footer=footer)
    return send_text_best_effort(target, fallback_text)


def send_poll_best_effort(
    target: str,
    poll_name: str,
    poll_options: list[str] | list[dict[str, Any]],
    *,
    options: dict[str, Any] | None = None,
    footer: str | None = None,
) -> dict[str, Any]:
    payload = build_poll_message(poll_name, poll_options, options=options)
    if _wa_service_ready():
        try:
            return send_interactive_message(target, payload)
        except Exception:
            pass

    fallback_text = format_poll_fallback(poll_name, poll_options, footer=footer)
    return send_text_best_effort(target, fallback_text)


def buat_menu_booking(target: str) -> dict[str, Any]:
    return send_buttons_best_effort(
        target,
        "Pilih tindakan booking yang kamu butuhkan:",
        [
            {"id": "booking_baru", "body": "Buat Booking Baru"},
            {"id": "cek_jadwal", "body": "Cek Jadwal Dokter"},
            {"id": "reschedule", "body": "Ubah Jadwal Booking"},
        ],
        title="Booking SmartClinic",
        footer="Pilih salah satu opsi di atas.",
    )


def buat_menu_layanan(target: str) -> dict[str, Any]:
    return send_list_best_effort(
        target,
        "Silakan pilih layanan yang kamu cari:",
        "Lihat Layanan",
        [
            {
                "title": "Informasi Klinik",
                "rows": [
                    {"id": "jam_operasional", "title": "Jam Operasional", "description": "Lihat jam buka klinik"},
                    {"id": "lokasi", "title": "Lokasi Klinik", "description": "Alamat dan petunjuk lokasi"},
                ],
            },
            {
                "title": "Pendaftaran & Booking",
                "rows": [
                    {"id": "booking", "title": "Booking Pemeriksaan", "description": "Buat janji temu"},
                    {"id": "antrean", "title": "Cek Antrean", "description": "Lihat status antrean"},
                ],
            },
        ],
        title="Menu Layanan SmartClinic",
        footer="Pilih layanan yang sesuai kebutuhan kamu.",
    )


def buat_poll_feedback(target: str) -> dict[str, Any]:
    return send_poll_best_effort(
        target,
        "Apakah pelayanan kami sudah membantu?",
        ["Sangat membantu", "Cukup membantu", "Belum membantu"],
        footer="Terima kasih sudah mengisi polling.",
    )