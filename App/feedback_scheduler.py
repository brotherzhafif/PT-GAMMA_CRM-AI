# ======================================================
# SmartClinic CRM AI — feedback_scheduler.py
# Background worker: auto-goodbye setelah 30 menit idle.
# Kirim prompt rating otomatis jika user tidak aktif.
#
# Last Change   :   29 Jun 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

import asyncio
from datetime import datetime, timezone, timedelta

from App.config import supabase
from App.helpers import (
    normalize_phone_number,
    normalize_whatsapp_target,
    get_session_state,
    set_session_state,
    save_to_supabase,
)
from App.wa_gateway import send_text_best_effort

_scheduler_started = False

# Substring prompt rating — digunakan untuk cek apakah pesan terakhir sudah prompt feedback
FEEDBACK_PROMPT_MARKER = "Apakah ada ulasan atau komentar atas pelayanan"

# Batas waktu idle (detik)
IDLE_THRESHOLD_SECONDS = 30 * 60   # 30 menit
IDLE_MAX_SECONDS = 24 * 60 * 60    # 24 jam — jangan kirim ke chat yang sudah sangat lama

# Interval cek (detik)
CHECK_INTERVAL_SECONDS = 120       # 2 menit


async def _get_latest_messages() -> list[dict]:
    """Ambil pesan terakhir per user dari Supabase via RPC atau query langsung."""
    if supabase is None:
        return []

    try:
        # Coba RPC dulu (lebih efisien jika ada)
        def _sync_rpc():
            return supabase.rpc("get_latest_messages", {}).execute()

        resp = await asyncio.to_thread(_sync_rpc)
        if resp.data:
            return resp.data
    except Exception:
        pass

    # Fallback: ambil pesan terbaru per sender_number via query biasa
    try:
        def _sync_fallback():
            # Ambil 200 pesan terbaru, lalu dedupe per sender di Python
            return (
                supabase.table("messages")
                .select("sender_number, message_text, created_at, direction")
                .order("created_at", desc=True)
                .limit(500)
                .execute()
            )

        resp = await asyncio.to_thread(_sync_fallback)
        rows = resp.data or []

        # Dedupe: ambil pesan paling baru per sender_number
        seen = {}
        for row in rows:
            sender = row.get("sender_number", "")
            if sender and sender not in seen:
                seen[sender] = row
        return list(seen.values())
    except Exception as e:
        print(f"[FeedbackScheduler] Gagal ambil pesan terbaru: {e}")
        return []


async def _has_new_activity_since_last_feedback(sender: str) -> bool:
    """Cek apakah percakapan baru memenuhi syarat kelayakan feedback (UX filters)."""
    if supabase is None:
        return True

    try:
        # ponytail: 24h limit on feedback prompt to avoid spamming the user
        def _sync_check_24h_cooldown():
            one_day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
            return (
                supabase.table("messages")
                .select("id")
                .eq("sender_number", sender)
                .eq("direction", "outbound")
                .like("message_text", f"%{FEEDBACK_PROMPT_MARKER}%")
                .gte("created_at", one_day_ago)
                .limit(1)
                .execute()
            )

        cooldown_resp = await asyncio.to_thread(_sync_check_24h_cooldown)
        if cooldown_resp.data:
            return False

        # ponytail: limit history to 30 to check session goals, fallback, and activity
        def _sync_get_history():
            return (
                supabase.table("messages")
                .select("message_text, direction, created_at")
                .eq("sender_number", sender)
                .order("created_at", desc=True)
                .limit(30)
                .execute()
            )

        resp = await asyncio.to_thread(_sync_get_history)
        rows = resp.data or []
        rows.reverse()

        # Cari index feedback terakhir (baik prompt maupun thank you)
        last_feedback_idx = -1
        for i, row in enumerate(rows):
            text = row.get("message_text", "") or ""
            direction = row.get("direction", "")
            if direction == "outbound" and (
                FEEDBACK_PROMPT_MARKER in text
                or "Terima kasih atas penilaian dan ulasan" in text
            ):
                last_feedback_idx = i

        active_rows = rows[last_feedback_idx + 1:] if last_feedback_idx != -1 else rows

        # 1. Minimal percakapan: 3+ inbound
        inbound_count = sum(1 for r in active_rows if r.get("direction") == "inbound")
        if inbound_count < 3:
            return False

        # 2. Filter Intent / Jangan kirim jika bot jawab "kurang paham" (fallback)
        FALLBACK_MARKERS = [
            "kurang memahami",
            "hanya dapat membantu hal-hal yang berkaitan",
            "layanan AI sedang bermasalah",
            "tidak dapat terhubung ke layanan",
            "kurang paham"
        ]
        SUCCESS_MARKERS = [
            "Pendaftaran Berhasil!",
            "Konfirmasi Kunjungan",
            "Tiket Antrean Bot",
            "Jadwal Dokter Klinik SmartClinic"
        ]

        # Cek outbound terakhir
        last_outbound = None
        for row in reversed(active_rows):
            if row.get("direction") == "outbound":
                last_outbound = row.get("message_text", "") or ""
                break

        if last_outbound and any(m in last_outbound for m in FALLBACK_MARKERS):
            return False

        # 3. Hanya kirim jika user capai tujuan (booking sukses, info jadwal dapat)
        has_success = False
        for row in active_rows:
            text = row.get("message_text", "") or ""
            if row.get("direction") == "outbound" and any(m in text for m in SUCCESS_MARKERS):
                has_success = True
                break

        if not has_success:
            return False

        return True
    except Exception as e:
        print(f"[FeedbackScheduler] Gagal cek activity history untuk {sender}: {e}")
        return True


async def _process_idle_users():
    """Cek user idle > 30 menit, kirim auto-goodbye + prompt rating."""
    messages = await _get_latest_messages()
    now = datetime.now(timezone.utc)

    for msg in messages:
        sender = msg.get("sender_number", "")
        if not sender:
            continue

        # Parse timestamp pesan terakhir
        created_at_str = msg.get("created_at", "")
        if not created_at_str:
            continue

        try:
            created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        except Exception:
            continue

        elapsed = (now - created_at).total_seconds()

        # Hanya proses jika 30 menit <= elapsed < 24 jam
        if elapsed < IDLE_THRESHOLD_SECONDS or elapsed >= IDLE_MAX_SECONDS:
            continue

        state = get_session_state(sender)

        # Jika sudah waiting_feedback dan masih idle → bersihkan state (auto-clear)
        if state == "waiting_feedback":
            print(f"[FeedbackScheduler] {sender} masih idle setelah prompt → clear state")
            set_session_state(sender, None)
            continue

        # Jika state bukan None (sedang onboarding dll), skip
        if state is not None:
            continue

        # Cek apakah pesan terakhir (outbound) sudah berisi prompt feedback
        last_text = msg.get("message_text", "")
        if FEEDBACK_PROMPT_MARKER in last_text:
            continue

        # Cek jika tidak ada aktivitas percakapan baru sejak feedback terakhir selesai
        if not await _has_new_activity_since_last_feedback(sender):
            continue


        # Kirim auto-goodbye + prompt rating
        goodbye_msg = (
            "Halo! Sepertinya percakapan kita sudah selesai. "
            "Terima kasih sudah menghubungi SmartClinic! 😊\n\n"
            "Apakah ada ulasan atau komentar atas pelayanan kami?"
        )

        target = normalize_whatsapp_target(sender)
        try:
            result = await asyncio.to_thread(send_text_best_effort, target, goodbye_msg)
            print(f"[FeedbackScheduler] Auto-goodbye terkirim ke {sender}: {result}")
        except Exception as e:
            print(f"[FeedbackScheduler] Gagal kirim ke {sender}: {e}")
            continue

        # Simpan pesan outbound ke Supabase (tidak ke local JSON)
        try:
            await asyncio.to_thread(
                save_to_supabase, sender, goodbye_msg, "outbound", "system"
            )
        except Exception as e:
            print(f"[FeedbackScheduler] Gagal simpan outbound ke Supabase: {e}")

        # Set state ke waiting_feedback
        set_session_state(sender, "waiting_feedback")
        print(f"[FeedbackScheduler] {sender} → state=waiting_feedback")


async def _worker_loop():
    """Worker loop: cek setiap 2 menit."""
    while True:
        try:
            await _process_idle_users()
        except Exception as e:
            print(f"[FeedbackScheduler] Worker error: {e}")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


def start_feedback_scheduler():
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True

    asyncio.create_task(_worker_loop())
    print("[FeedbackScheduler] Scheduler started (check every 2 min, idle threshold 30 min)")
