# ======================================================
# SmartClinic CRM AI — campaign_scheduler.py
# Background worker untuk memproses campaign terjadwal.
#
# Last Change   :   22 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

import threading
import time
from datetime import datetime, timezone

from fastapi import HTTPException

from App.config import supabase
from App.helpers import _require_supabase
from App.models import BroadcastPayload
from App.routers.send import broadcast_message

_scheduler_started = False
_scheduler_lock = threading.Lock()


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

        payload = BroadcastPayload(
            message=campaign.get("campaign_message", ""),
            attachment_url=campaign.get("attachment_url"),
            filename=campaign.get("filename"),
        )
        broadcast_message(payload)

        _mark_campaign_status(campaign_id, "sent")
        print(f"[CampaignScheduler] Campaign '{campaign.get('campaign_name')}' sudah dibroadcast")
    except HTTPException as exc:
        print(f"[CampaignScheduler] Campaign '{campaign.get('campaign_name')}' gagal: {exc.detail}")
        _mark_campaign_status(campaign_id, "failed")
    except Exception as exc:
        print(f"[CampaignScheduler] Campaign '{campaign.get('campaign_name')}' error: {exc}")
        _mark_campaign_status(campaign_id, "failed")


def _worker_loop():
    while True:
        try:
            _require_supabase()
            response = (
                supabase.table("campaigns")
                .select("id, campaign_name, schedule_date, campaign_message, attachment_url, filename, status")
                .eq("status", "scheduled")
                .execute()
            )
            for campaign in response.data or []:
                _process_campaign(campaign)
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