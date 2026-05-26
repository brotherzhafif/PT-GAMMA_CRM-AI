# ======================================================
# SmartClinic CRM AI — routers/webhook.py
# Endpoint: GET / dan POST /webhook
#
# Last Change   :   16 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

import re
from datetime import datetime
from fastapi import APIRouter, Body, HTTPException

from App.config import RASA_CONFIDENCE_THRESHOLD, RASA_TRUSTED_INTENTS, TRIAGE_KEYWORDS, MAX_FALLBACK_BEFORE_HANDOFF
from App.models import WebhookPayload, ChatResponse
from App.helpers import (
    save_to_supabase,
    save_chat_to_json,
    get_chat_history_json,
    get_session_state,
    set_session_state,
    get_onboarding_data,
    is_patient_registered,
    upsert_patient,
    normalize_phone_number,
    query_rasa,
    is_handoff_keyword,
    increment_fallback,
    reset_fallback,
)
from App.handoff_manager import is_in_handoff, start_handoff
from App.queue_manager import fonnte_queue
from LLM.groq_service import GroqService

router = APIRouter()
groq = GroqService()


WEBHOOK_REQUEST_EXAMPLE = {
    "sender": "6281234567890",
    "message": "Halo, jadwal dokter hari ini apa ya?",
}

WEBHOOK_RESPONSE_EXAMPLE = {
    "status": "ok",
    "source": "rasa",
    "reply": "Jadwal dokter hari ini tersedia pukul 09.00 - 17.00.",
}


# ======================================================
#
#                   SYSTEM ENDPOINT
#
# ======================================================

@router.get(
    "/",
    tags=["System"],
    summary="Health check",
    responses={
        200: {
            "description": "Service aktif",
            "content": {"application/json": {"example": {"status": "ok", "message": "SmartClinic CRM AI is running!", "docs": "/docs"}}},
        },
    },
)
def home():
    return {
        "status": "ok",
        "message": "SmartClinic CRM AI is running!",
        "docs": "/docs",
    }


@router.post(
    "/webhook",
    response_model=ChatResponse,
    tags=["System"],
    summary="Terima pesan WhatsApp masuk dari Fonnte",
    description=(
        "Entry point utama. Pesan diklasifikasikan oleh Rasa; "
        "jika confidence rendah atau intent tidak dikenal, Groq LLM mengambil alih."
    ),
    responses={
        200: {
            "description": "Pesan berhasil diproses",
            "content": {"application/json": {"examples": {
                "normalReply": {"summary": "Contoh respons normal", "value": WEBHOOK_RESPONSE_EXAMPLE},
                "handoffReply": {"summary": "Contoh saat handoff aktif", "value": {"status": "handoff", "source": "handoff", "reply": None}},
            }}},
        },
        500: {
            "description": "Gagal memproses webhook",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
def webhook(
    payload: WebhookPayload = Body(
        ...,
        examples={
            "webhookExample": {
                "summary": "Contoh payload webhook masuk",
                "value": WEBHOOK_REQUEST_EXAMPLE,
            }
        },
    )
):
    try:
        no_hp = normalize_phone_number(payload.sender)
        input_pesan = payload.message.strip()
        waktu = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        print(f"\n[{waktu}] [INCOMING] Dari: {no_hp} | Pesan: {input_pesan}")
        save_to_supabase(no_hp, input_pesan, direction="inbound", source="fonnte")

        #  Step 0: Cek mode handoff 
        # Jika sedang handoff, bot diam — admin yang balas dari dashboard.
        if is_in_handoff(no_hp):
            print(f"[Handoff] {no_hp} dalam mode handoff — bot diam")
            return ChatResponse(status="handoff", source="handoff", reply=None)

    
        #  Step 1: Alur Registrasi & Onboarding (Nomor Baru)
        session_state = get_session_state(no_hp)
        reply = ""
        source = "system"

        # KONDISI A: Pasien benar-benar baru (Belum terdaftar & belum masuk state menunggu nama)
        if not is_patient_registered(no_hp) and session_state != "waiting_name":
            set_session_state(no_hp, "waiting_name")
            reply = (
                "Halo! Selamat datang di SmartClinic 👋\n\n"
                "Sebelum mulai, boleh kami tahu nama lengkap kamu sesuai KTP? "
                "Ketik nama kamu, atau ketik *skip* jika ingin melewati."
            )
            print(f"[Onboarding] Nomor baru {no_hp} → tanya nama")
            fonnte_queue.add_to_queue(no_hp, reply)
            save_chat_to_json(no_hp, input_pesan, reply, source=source)
            save_to_supabase(no_hp, reply, direction="outbound", source=source)
            return ChatResponse(status="ok", source=source, reply=reply)

        # KONDISI B: Pasien sedang berada di dalam proses memasukkan nama
        elif session_state == "waiting_name":
            nama = input_pesan.strip()
            SKIP_KEYWORDS = {"tidak", "ga", "gak", "nggak", "skip", "lewati", "batal", "-", "no", "tidak mau"}

            if len(nama) < 2 or nama.lower() in SKIP_KEYWORDS:
                # USER SKIP ONBOARDING
                upsert_patient(no_hp, name=None)
                set_session_state(no_hp, None)
                
                reply = (
                    "Oke, tidak apa-apa! Data kamu sudah kami simpan tanpa nama. "
                    "Ada keluhan atau hal medis apa yang bisa SmartClinic bantu hari ini? 😊"
                )
                print(f"[Onboarding] {no_hp} skip nama → disimpan tanpa nama.")
                
                # Selesaikan proses onboarding di sini secara bersih
                fonnte_queue.add_to_queue(no_hp, reply)
                save_chat_to_json(no_hp, input_pesan, reply, source=source)
                save_to_supabase(no_hp, reply, direction="outbound", source=source)
                return ChatResponse(status="ok", source=source, reply=reply)
                
            else:
                # USER MENGINPUT NAMA DENGAN BENAR
                upsert_patient(no_hp, name=nama)
                set_session_state(no_hp, None)
                reply = (
                    f"Terima kasih, *{nama}*! Data kamu sudah kami simpan. "
                    f"Ada yang bisa kami bantu hari ini? 😊"
                )
                print(f"[Onboarding] {no_hp} → nama '{nama}' disimpan")
                fonnte_queue.add_to_queue(no_hp, reply)
                save_chat_to_json(no_hp, input_pesan, reply, source=source)
                save_to_supabase(no_hp, reply, direction="outbound", source=source)
                return ChatResponse(status="ok", source=source, reply=reply)

        #  Step 2: Cek keyword handoff 
        if is_handoff_keyword(input_pesan):
            start_handoff(no_hp)
            reset_fallback(no_hp)
            reply = (
                "Baik, kami akan menghubungkan kamu dengan admin kami. "
                "Mohon tunggu sebentar ya 🙏\n\n"
                "_Bot sementara tidak aktif. Admin akan segera membalas._"
            )
            source = "system"
            print(f"[Handoff] {no_hp} minta handoff via keyword")
            fonnte_queue.add_to_queue(no_hp, reply)
            save_chat_to_json(no_hp, input_pesan, reply, source=source)
            save_to_supabase(no_hp, reply, direction="outbound", source=source)
            return ChatResponse(status="ok", source=source, reply=reply)

        #  Step 3: Routing normal Rasa → Groq 
        chat_history = get_chat_history_json(no_hp, limit=5)

        rasa_result = query_rasa(input_pesan, no_hp)
        if rasa_result:
            print(f"[DEBUG] Rasa → intent: '{rasa_result['intent']}', confidence: {rasa_result['confidence']:.4f}, form_active: {rasa_result.get('is_form_active')}")

        is_form_active = rasa_result and rasa_result.get("is_form_active")

        # Prioritaskan Rasa jika form sedang aktif, ATAU jika intent sangat dipercaya
        if rasa_result and (
            (is_form_active and rasa_result["reply"]) or 
            (
                rasa_result["confidence"] >= RASA_CONFIDENCE_THRESHOLD
                and rasa_result["intent"] in RASA_TRUSTED_INTENTS
                and rasa_result["reply"]
            )
        ):
            reply = rasa_result["reply"]
            source = "rasa"
            reset_fallback(no_hp)
            print("[DEBUG] → Answered by: RASA ✅")
        else:
            #  Step 3b: Groq LLM 
            role = "triage" if any(k in input_pesan.lower() for k in TRIAGE_KEYWORDS) else "default"
            reply = groq.get_response(input_pesan, role_type=role, chat_history=chat_history)
            source = "groq"
            print(f"[DEBUG] → Answered by: GROQ LLM ✨ (role: {role})")

            # Auto handoff jika Groq fallback terlalu sering
            fallback_count = increment_fallback(no_hp)
            if fallback_count >= MAX_FALLBACK_BEFORE_HANDOFF:
                start_handoff(no_hp)
                reset_fallback(no_hp)
                reply += (
                    "\n\n_Sepertinya pertanyaan kamu membutuhkan bantuan lebih lanjut. "
                    "Kami sambungkan ke admin ya — mohon tunggu sebentar 🙏_"
                )
                print(f"[Handoff] {no_hp} auto-handoff setelah {fallback_count}x fallback")

        fonnte_queue.add_to_queue(no_hp, reply)
        save_chat_to_json(no_hp, input_pesan, reply, source=source)
        save_to_supabase(no_hp, reply, direction="outbound", source=source)

        print(f"[{waktu}] Selesai proses dari {no_hp} (source: {source})")
        return ChatResponse(status="ok", source=source, reply=reply)

    except HTTPException:
        raise
    except Exception as e:
        print(f"--- ERROR WEBHOOK: {e} ---")
        raise HTTPException(status_code=500, detail=str(e))
