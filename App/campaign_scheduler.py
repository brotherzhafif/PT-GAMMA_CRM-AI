# ======================================================
# SmartClinic CRM AI — campaign_scheduler.py
# Background worker untuk memproses campaign terjadwal.
#
# Last Change   :   22 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

import threading
import time
import os
import mimetypes
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from App.config import supabase
from App.helpers import _require_supabase
from App.routers.send import broadcast_to_patients

_scheduler_started = False
_scheduler_lock = threading.Lock()
LOCAL_TZ = ZoneInfo("Asia/Jakarta")


def _parse_schedule_date(schedule_date: str) -> datetime:
    normalized = schedule_date.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _mark_campaign_status(campaign_id: str, status: str):
    supabase.table("campaigns").update({"status": status}).eq("id", campaign_id).execute()


def _process_campaign(campaign: dict):
    campaign_id = campaign.get("id")
    if not campaign_id:
        return

    current_status = campaign.get("status")
    if current_status != "scheduled":
        return

    schedule_date = campaign.get("schedule_date")
    if not schedule_date:
        return

    try:
        campaign_time = _parse_schedule_date(schedule_date)
        if campaign_time > datetime.now(timezone.utc):
            return

        _mark_campaign_status(campaign_id, "processing")

        attachment_url = campaign.get("attachment_url")
        attachment_file_path = None
        if isinstance(attachment_url, str) and attachment_url.startswith("file://"):
            attachment_file_path = attachment_url.removeprefix("file://")
            attachment_url = None

        broadcast_to_patients(
            campaign.get("campaign_message", ""),
            attachment_url=attachment_url,
            filename=campaign.get("filename"),
            attachment_file_path=attachment_file_path,
            image_url=campaign.get("image_url"),
        )

        _mark_campaign_status(campaign_id, "sent")
        print(f"[CampaignScheduler] Campaign '{campaign.get('campaign_name')}' sudah dibroadcast")
    except HTTPException as exc:
        print(f"[CampaignScheduler] Campaign '{campaign.get('campaign_name')}' gagal: {exc.detail}")
        _mark_campaign_status(campaign_id, "failed")
    except Exception as exc:
        print(f"[CampaignScheduler] Campaign '{campaign.get('campaign_name')}' error: {exc}")
        _mark_campaign_status(campaign_id, "failed")


def seed_birthday_campaign():
    try:
        _require_supabase()
        response = (
            supabase.table("campaigns")
            .select("id")
            .eq("campaign_type", "birthday")
            .limit(1)
            .execute()
        )
        if not response.data:
            payload = {
                "campaign_name": "Campaign Ulang Tahun Pasien",
                "campaign_message": "Selamat ulang tahun, {nama}! Semoga sehat selalu. SmartClinic memberikan promo spesial khusus untuk Anda hari ini.",
                "status": "active",
                "campaign_type": "birthday",
                "recurrence": "yearly",
            }
            supabase.table("campaigns").insert(payload).execute()
            print("[CampaignScheduler] Seeded default birthday campaign")
    except Exception as e:
        print(f"[CampaignScheduler] Failed to seed birthday campaign: {e}")


def _run_birthday_campaign_if_time():
    try:
        _require_supabase()
        resp = (
            supabase.table("campaigns")
            .select("id, campaign_name, campaign_message, attachment_url, filename, status, last_run_date, image_url")
            .eq("campaign_type", "birthday")
            .limit(1)
            .execute()
        )
        if not resp.data:
            return

        campaign = resp.data[0]
        if campaign.get("status") != "active":
            return

        local_now = datetime.now(LOCAL_TZ)
        if local_now.hour < 8:
            return

        today_str = local_now.strftime("%Y-%m-%d")
        if campaign.get("last_run_date") == today_str:
            return

        print(f"[CampaignScheduler] Running Birthday Campaign '{campaign.get('campaign_name')}' for {today_str}...")

        patients_resp = supabase.table("patients").select("phone_number, name, birthdate").execute()
        patients = patients_resp.data or []

        today_month_day = local_now.strftime("%m-%d")

        birthday_patients = []
        for p in patients:
            birthdate_str = p.get("birthdate")
            if birthdate_str:
                try:
                    parts = birthdate_str.split("-")
                    if len(parts) >= 3:
                        m = parts[1]
                        d = parts[2][:2]
                        if f"{m}-{d}" == today_month_day:
                            birthday_patients.append(p)
                except Exception:
                    pass

        if not birthday_patients:
            supabase.table("campaigns").update({"last_run_date": today_str}).eq("id", campaign.get("id")).execute()
            print(f"[CampaignScheduler] No patient celebrating birthday today ({today_str}).")
            return

        from App.routers.send import send_text_best_effort, save_to_supabase, _send_media_to_target, wa_service_request

        attachment_url = campaign.get("attachment_url")
        attachment_file_path = None
        if isinstance(attachment_url, str) and attachment_url.startswith("file://"):
            attachment_file_path = attachment_url.removeprefix("file://")
            attachment_url = None

        file_bytes = None
        file_name = None
        file_content_type = "application/octet-stream"

        if attachment_file_path and os.path.exists(attachment_file_path):
            try:
                with open(attachment_file_path, "rb") as fh:
                    file_bytes = fh.read()
                file_name = os.path.basename(attachment_file_path)
                file_content_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
            except Exception as e:
                print(f"[CampaignScheduler] Error reading birthday attachment file: {e}")

        sent_count = 0
        for patient in birthday_patients:
            number = patient.get("phone_number")
            name = patient.get("name") or "Pasien"
            if not number:
                continue

            original_msg = campaign.get("campaign_message") or ""
            msg = original_msg.replace("{nama}", name).replace("{name}", name)

            try:
                if file_bytes is not None and file_name is not None:
                    _send_media_to_target(
                        number,
                        msg,
                        file_name=file_name,
                        file_bytes=file_bytes,
                        content_type=file_content_type
                    )
                    source = "wa-service"
                elif attachment_url:
                    wa_service_request(
                        "POST",
                        "/send-attachment",
                        json={
                            "target": number,
                            "message": msg,
                            "attachment_url": attachment_url,
                            "filename": campaign.get("filename"),
                        },
                        timeout=30,
                    )
                    source = "wa-service"
                else:
                    send_result = send_text_best_effort(number, msg)
                    source = send_result.get("channel", "broadcast")

                save_to_supabase(number, msg, direction="outbound", source=source, image_url=campaign.get("image_url"))
                sent_count += 1
            except Exception as e:
                print(f"[CampaignScheduler] Failed to send birthday campaign to {number}: {e}")

        supabase.table("campaigns").update({"last_run_date": today_str}).eq("id", campaign.get("id")).execute()
        print(f"[CampaignScheduler] Finished Birthday Campaign. Sent to {sent_count} patient(s).")

    except Exception as e:
        print(f"[CampaignScheduler] Birthday campaign process error: {e}")


def _worker_loop():
    # Seed default birthday campaign if missing
    seed_birthday_campaign()
    while True:
        try:
            _require_supabase()
            
            # 1. Standard scheduled campaigns (only standard type)
            response = (
                supabase.table("campaigns")
                .select("id, campaign_name, schedule_date, campaign_message, attachment_url, filename, status, image_url")
                .eq("status", "scheduled")
                .eq("campaign_type", "standard")
                .execute()
            )
            for campaign in response.data or []:
                _process_campaign(campaign)

            # 2. Daily birthday campaign check
            _run_birthday_campaign_if_time()

        except HTTPException:
            pass
        except Exception as exc:
            print(f"[CampaignScheduler] Worker error: {exc}")

        time.sleep(30)


def start_campaign_scheduler():
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_started = True

    thread = threading.Thread(target=_worker_loop, name="CampaignScheduler", daemon=True)
    thread.start()
    print(f"[CampaignScheduler] Worker thread '{thread.name}' started")