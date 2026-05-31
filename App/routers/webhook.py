# ======================================================
# SmartClinic CRM AI — routers/webhook.py
# Endpoint: GET / dan POST /webhook
#
# Last Change   :   29 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

import re
from datetime import datetime
from fastapi import APIRouter, Body, HTTPException

from App.config import RASA_CONFIDENCE_THRESHOLD, RASA_TRUSTED_INTENTS, TRIAGE_KEYWORDS, EMERGENCY_KEYWORDS
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
from App.routers.chatbot_settings import get_max_fallback_before_handoff
from App.handoff_manager import is_in_handoff, start_handoff
from App.wa_gateway import send_text_best_effort
from LLM.groq_service import GroqService

router = APIRouter()
groq = GroqService()

# ======================================================
#   KONSTANTA
# ======================================================

ONBOARDING_STATES = {"waiting_name", "waiting_nik", "waiting_dob", "waiting_gender"}

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
#   HELPER — kirim balasan & simpan ke semua storage
# ======================================================

def _send_reply(no_hp: str, input_pesan: str, reply: str, source: str) -> ChatResponse:
    """Kirim reply ke queue Fonnte, simpan ke JSON dan Supabase, lalu return ChatResponse."""
    send_result = send_text_best_effort(no_hp, reply)
    save_chat_to_json(no_hp, input_pesan, reply, source=source)
    save_to_supabase(no_hp, reply, direction="outbound", source=send_result.get("channel", source))
    return ChatResponse(status="ok", source=source, reply=reply)


# ======================================================
#   SYSTEM ENDPOINT
# ======================================================

@router.get(
    "/",
    tags=["System"],
    summary="Health check",
    responses={
        200: {
            "description": "Service aktif",
            "content": {"application/json": {"example": {
                "status": "ok",
                "message": "SmartClinic CRM AI is running!",
                "docs": "/docs",
            }}},
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
                "normalReply": {
                    "summary": "Contoh respons normal",
                    "value": WEBHOOK_RESPONSE_EXAMPLE,
                },
                "handoffReply": {
                    "summary": "Contoh saat handoff aktif",
                    "value": {"status": "handoff", "source": "handoff", "reply": None},
                },
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

        # ── Step 0: Cek mode handoff 
        # Bot diam selama handoff aktif — admin yang balas dari dashboard.
        if is_in_handoff(no_hp):
            print(f"[Handoff] {no_hp} dalam mode handoff — bot diam")
            return ChatResponse(status="handoff", source="handoff", reply=None)

        # ── Step 1: Onboarding 
        # Ambil session_state SEKALI di sini — tidak diambil ulang di bawah.
        session_state = get_session_state(no_hp)
        is_registered = is_patient_registered(no_hp)

        # Nomor baru yang belum masuk alur onboarding sama sekali
        if not is_registered and session_state not in ONBOARDING_STATES:
            set_session_state(no_hp, "waiting_name")
            reply = (
                "Halo! Selamat datang di SmartClinic 👋\n\n"
                "Sebelum mulai, boleh kami tahu *nama lengkap* kamu sesuai KTP?\n"
                "Ketik nama kamu untuk melanjutkan pendaftaran."
            )
            print(f"[Onboarding] Nomor baru {no_hp} → tanya nama")
            return _send_reply(no_hp, input_pesan, reply, source="system")

        # ── Langkah 1: Nama 
        if session_state == "waiting_name":
            nama = input_pesan.strip()
            if len(nama) < 2:
                reply = "⚠️ Nama terlalu pendek. Silakan masukkan nama lengkap Anda."
                return _send_reply(no_hp, input_pesan, reply, source="system")

            # Simpan nama sementara di state, lanjut ke NIK
            set_session_state(no_hp, "waiting_nik", data={"namaLengkap": nama})
            reply = (
                f"Terima kasih, *{nama}*! ✅\n\n"
                "Selanjutnya, ketik *16 digit NIK* (Nomor Induk Kependudukan) kamu untuk melanjutkan pendaftaran."
            )
            print(f"[Onboarding] {no_hp} → nama '{nama}' → tanya NIK")
            return _send_reply(no_hp, input_pesan, reply, source="system")

        # ── Langkah 2: NIK 
        if session_state == "waiting_nik":
            nik_digits = re.sub(r"\D", "", input_pesan)
            if len(nik_digits) != 16:
                reply = (
                    "⚠️ NIK harus terdiri dari *16 digit angka*.\n"
                    "Silakan cek kembali dan kirim ulang."
                )
                print(f"[Onboarding] {no_hp} → NIK invalid '{input_pesan}'")
                return _send_reply(no_hp, input_pesan, reply, source="system")

            onboarding_data = get_onboarding_data(no_hp)
            onboarding_data["nik"] = nik_digits
            set_session_state(no_hp, "waiting_dob", data=onboarding_data)
            reply = (
                "NIK valid! ✅\n\n"
                "Selanjutnya, masukkan *Tanggal Lahir* kamu dengan format *DD/MM/YYYY*\n"
                "(Contoh: 15/08/1995)."
            )
            print(f"[Onboarding] {no_hp} → NIK valid → tanya DOB")
            return _send_reply(no_hp, input_pesan, reply, source="system")

        # ── Langkah 3: Tanggal Lahir 
        if session_state == "waiting_dob":
            match = re.search(r"(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})", input_pesan)
            if not match:
                reply = (
                    "⚠️ Format tanggal tidak dikenali. Gunakan format *DD/MM/YYYY*\n"
                    "(Contoh: 15/08/1995)."
                )
                print(f"[Onboarding] {no_hp} → DOB invalid '{input_pesan}'")
                return _send_reply(no_hp, input_pesan, reply, source="system")

            day, month, year = match.groups()
            try:
                dob_date = datetime(int(year), int(month), int(day))
                tanggal_lahir = dob_date.strftime("%Y-%m-%d")
            except ValueError:
                reply = (
                    "⚠️ Tanggal tidak valid. Gunakan format *DD/MM/YYYY*\n"
                    "(Contoh: 15/08/1995)."
                )
                return _send_reply(no_hp, input_pesan, reply, source="system")

            onboarding_data = get_onboarding_data(no_hp)
            onboarding_data["tanggalLahir"] = tanggal_lahir
            set_session_state(no_hp, "waiting_gender", data=onboarding_data)
            reply = (
                "Terima kasih! ✅\n\n"
                "Terakhir, apa *jenis kelamin* kamu?\n"
                "Balas *Laki-laki* atau *Perempuan*."
            )
            print(f"[Onboarding] {no_hp} → DOB '{tanggal_lahir}' → tanya Gender")
            return _send_reply(no_hp, input_pesan, reply, source="system")

        # ── Langkah 4: Gender → selesai onboarding 
        if session_state == "waiting_gender":
            gender_input = input_pesan.strip().lower()
            LAKI_KEYWORDS    = {"laki-laki", "laki laki", "lakilaki", "pria", "cowok", "cowo", "l", "lk", "male"}
            PEREMPUAN_KEYWORDS = {"perempuan", "wanita", "cewek", "cewe", "p", "pr", "female"}

            if gender_input in LAKI_KEYWORDS:
                jenis_kelamin = "LAKI_LAKI"
            elif gender_input in PEREMPUAN_KEYWORDS:
                jenis_kelamin = "PEREMPUAN"
            else:
                reply = (
                    "⚠️ Mohon balas dengan *Laki-laki* atau *Perempuan*."
                )
                print(f"[Onboarding] {no_hp} → Gender invalid '{gender_input}'")
                return _send_reply(no_hp, input_pesan, reply, source="system")

            onboarding_data = get_onboarding_data(no_hp)
            onboarding_data["jenisKelamin"] = jenis_kelamin

            # Semua langkah selesai → simpan ke DB
            upsert_patient(
                no_hp,
                namaLengkap=onboarding_data.get("namaLengkap"),
                nik=onboarding_data.get("nik"),
                tanggalLahir=onboarding_data.get("tanggalLahir"),
                jenisKelamin=onboarding_data.get("jenisKelamin"),
            )
            set_session_state(no_hp, None)

            nama = onboarding_data.get("namaLengkap", "")
            reply = (
                f"Terima kasih{', *' + nama + '*' if nama else ''}! "
                "Data kamu sudah lengkap tersimpan. "
                "Ada yang bisa kami bantu hari ini? 😊"
            )
            print(f"[Onboarding] {no_hp} selesai lengkap → data: {onboarding_data}")
            return _send_reply(no_hp, input_pesan, reply, source="system")

        # ── Step 2: Cek keyword handoff ───────────────────────────────────────
        if is_handoff_keyword(input_pesan):
            start_handoff(no_hp)
            reset_fallback(no_hp)
            reply = (
                "Baik, kami akan menghubungkan kamu dengan admin kami. "
                "Mohon tunggu sebentar ya 🙏\n\n"
                "_Bot sementara tidak aktif. Admin akan segera membalas._"
            )
            print(f"[Handoff] {no_hp} minta handoff via keyword")
            return _send_reply(no_hp, input_pesan, reply, source="system")
        

        # ── Step 3: Routing normal Rasa → Groq ───────────────────────────────
        # Cek  keyword dipisah antara emergency vs gejala umum
        pesan_lower = input_pesan.lower()
        is_emergency_keyword = any(k in pesan_lower for k in EMERGENCY_KEYWORDS)
        is_triage_keyword    = any(k in pesan_lower for k in TRIAGE_KEYWORDS)

        # kondisi penentuan Router
        # Ambil history lokal untuk Groq & panggil server Rasa
        chat_history = get_chat_history_json(no_hp)
        rasa_result = query_rasa(input_pesan, no_hp)
        
        rasa_intent     = rasa_result["intent"]     if rasa_result else "N/A"
        rasa_confidence = rasa_result["confidence"] if rasa_result else 0.0
        rasa_form       = rasa_result["is_form_active"] if rasa_result else False
        rasa_trusted    = rasa_intent in RASA_TRUSTED_INTENTS
        rasa_requested_slot  = rasa_result.get("requested_slot") if rasa_result else None
        rasa_was_form_active = rasa_form  # simpan snapshot untuk handle timeout

        print(
            f"[DEBUG][RASA] intent={rasa_intent} | "
            f"confidence={rasa_confidence:.4f} | "
            f"threshold={RASA_CONFIDENCE_THRESHOLD} | "
            f"trusted={rasa_trusted} | "
            f"form_active={rasa_form} | "
            f"requested_slot={rasa_requested_slot}"
        )

        if (
            rasa_result 
            and (
                (rasa_result["confidence"] >= RASA_CONFIDENCE_THRESHOLD and rasa_result["intent"] in RASA_TRUSTED_INTENTS) 
                or rasa_result["is_form_active"]
            )
        ):
            reply = rasa_result["reply"]
            source = "rasa"
            reset_fallback(no_hp)
            print(f"[DEBUG] → Direspons oleh: RASA ✅ (Intent: {rasa_intent} | confidence={rasa_confidence:.4f})")
            
            # Rasa mendeteksi intent 'emergency' ATAU keyword terpicu
            if rasa_result["intent"] == "emergency" or (is_emergency_keyword and not rasa_form):
                print(f"[EMERGENCY] → Kondisi kritis terdeteksi via Rasa/Keyword! Mengaktifkan Auto-Handoff...")
                start_handoff(no_hp)
                reset_fallback(no_hp)
                # Sisipkan pesan tambahan di akhir agar pasien tau di takeover admin
                reply += (
                    "\n\n🚨 *Pemberitahuan Sistem:* Kondisi darurat terdeteksi. "
                    "Bot telah dinonaktifkan dan admin medis kami telah dihubungi untuk langsung mengambil alih percakapan ini. Mohon tunggu."
                )
            
        elif rasa_result is None and rasa_was_form_active:
            # ── Graceful timeout: Rasa timeout tapi form booking sedang aktif ──
            # Kemungkinan besar action booking_confirm sedang diproses (POST ke SmartClinic)
            # Jangan fallback ke Groq — tampilkan pesan tunggu agar user tidak bingung
            print(f"[TIMEOUT] Rasa timeout saat form aktif — kemungkinan action booking sedang diproses. Skip Groq fallback.")
            reply = (
                "⏳ Sistem sedang memproses permintaan Anda, mohon tunggu sebentar...\n\n"
                "Jika tidak ada konfirmasi dalam 1 menit, silakan ketik *status booking* atau hubungi admin klinik. 🙏"
            )
            source = "system"
            reset_fallback(no_hp)
            
        else:
            # Di luar form: keyword Emergency → handoff, keyword gejala → triage Groq tanpa handoff
            if is_emergency_keyword:
                role = "triage"
                reply = groq.get_response(input_pesan, role_type=role, chat_history=chat_history)
                source = "groq"
                start_handoff(no_hp)
                reset_fallback(no_hp)
                reply += "\n\n🚨 *Sistem mendeteksi kondisi darurat.* Sesi dialihkan ke admin medis."
                print(f"[EMERGENCY] → Keyword darurat lolos dari Rasa. Ditangani oleh Groq Triage + Auto-Handoff.")
            elif is_triage_keyword:
                role = "triage"
                reply = groq.get_response(input_pesan, role_type=role, chat_history=chat_history)
                source = "groq"
                print(f"[DEBUG] → Direspons oleh: GROQ LLM ✨ (role: triage | rasa_intent={rasa_intent} | confidence={rasa_confidence:.4f})")
            else:
                role = "default"
                reply = groq.get_response(input_pesan, role_type=role, chat_history=chat_history)
                source = "groq"
                print(f"[DEBUG] → Direspons oleh: GROQ LLM ✨ (role: {role} | rasa_intent={rasa_intent} | confidence={rasa_confidence:.4f} | trusted={rasa_trusted})")

        # Logika Auto Handoff jika source adalah "groq" (bukan triage/emergency)
        if source == "groq" and not is_emergency_keyword and not is_triage_keyword:
            fallback_count = increment_fallback(no_hp)
            if fallback_count >= get_max_fallback_before_handoff():
                start_handoff(no_hp)
                reset_fallback(no_hp)
                reply += (
                    "\n\n_Sepertinya pertanyaan kamu membutuhkan bantuan lebih lanjut. "
                    "Kami sambungkan ke admin ya — mohon tunggu sebentar 🙏_"
                )
                print(f"[Handoff] {no_hp} auto-handoff setelah {fallback_count}x fallback")

        # Kirim pesan ke antrean Fonnte dan simpan ke DB
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