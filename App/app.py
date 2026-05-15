# ======================================================
# SmartClinic CRM AI — app.py
# Hybrid Routing: Fonnte Webhook → FastAPI → Rasa (intent pasti) | Groq (kontekstual)
#
# Last Change   :   15 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
#                   MHD. Rafy Firdaus
#                   Wahyu Hardiyantara
# ======================================================

import json
import os
from datetime import datetime
from typing import List, Optional

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from supabase import Client, create_client

from App.queue_manager import fonnte_queue
from LLM.groq_service import GroqService

load_dotenv()

app = FastAPI(
    title="SmartClinic CRM AI",
    description="Hybrid routing API untuk webhook Fonnte, Rasa, dan Groq LLM.",
    version="1.0.0",
)

groq = GroqService()

# ── Config ────────────────────────────────────────────────────────────────────
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_ANON_KEY")
supabase: Optional[Client] = (
    create_client(supabase_url, supabase_key) if supabase_url and supabase_key else None
)
FONNTE_TOKEN = os.getenv("FONNTE_TOKEN")
RASA_URL = os.getenv("RASA_URL", "http://rasa:5005")
RASA_CONFIDENCE_THRESHOLD = 0.75

HISTORY_DIR = "chat_history"
if not os.path.exists(HISTORY_DIR):
    os.makedirs(HISTORY_DIR)

RASA_TRUSTED_INTENTS = {
    "greet", "goodbye",
    "ask_schedule", "ask_queue",
    "ask_services", "ask_location", "ask_cost",
    "request_human_agent", "emergency",
    "affirm", "deny", "intent_ingin_booking",
    "intent_berikan_rating",
}

TRIAGE_KEYWORDS = [
    "sakit", "pusing", "nyeri", "gejala", "demam", "batuk",
    "gatel", "gatal", "mual", "muntah", "sesak", "lemas",
    "pilek", "flu", "diare", "panas", "bengkak", "luka",
]


# ======================================================
# 
#   ALL MODELS FOR THE ENDPOINTS API
# 
# ======================================================

class WebhookPayload(BaseModel):
    sender: str = Field(..., description="Nomor WhatsApp pengirim", examples=["6281234567890"])
    message: str = Field(..., description="Isi pesan masuk", examples=["Jadwal dokter hari ini?"])


class ChatRecord(BaseModel):
    id: Optional[str] = Field(default=None)
    sender_number: str
    message_text: str
    direction: str = Field(..., description="inbound atau outbound")
    source: Optional[str] = Field(default=None, description="fonnte, rasa, groq, manual, atau broadcast")
    created_at: Optional[str] = Field(default=None)


class ChatResponse(BaseModel):
    status: str
    source: Optional[str] = None
    reply: Optional[str] = None


class PatientRecord(BaseModel):
    id: Optional[str] = Field(default=None)
    phone_number: str = Field(..., description="Nomor WhatsApp pasien", examples=["6281234567890"])
    name: Optional[str] = Field(default=None, description="Nama pasien")
    created_at: Optional[str] = Field(default=None)


class SavePatientPayload(BaseModel):
    phone_number: str = Field(..., description="Nomor WhatsApp pasien", examples=["6281234567890"])
    name: Optional[str] = Field(default=None, description="Nama pasien (opsional)")


class SendMessagePayload(BaseModel):
    target: str = Field(..., description="Nomor WhatsApp tujuan", examples=["6281234567890"])
    message: str = Field(..., description="Isi pesan yang akan dikirim")


class BroadcastPayload(BaseModel):
    message: str = Field(..., description="Isi pesan yang akan dikirim ke semua pasien")


class BroadcastResult(BaseModel):
    status: str
    total_sent: int
    recipients: List[str]


# ======================================================
# 
#               HELPER FUNCTIONS
# 
# ======================================================

def _require_supabase():
    """Guard: raise 500 jika Supabase belum dikonfigurasi."""
    if supabase is None:
        raise HTTPException(
            status_code=500,
            detail="Supabase belum dikonfigurasi. Cek SUPABASE_URL dan SUPABASE_ANON_KEY di .env",
        )


def get_chat_history_json(no_hp: str, limit: int = 5) -> list:
    """Ambil riwayat chat lokal dari file JSON (dipakai sebagai memori Groq)."""
    file_path = os.path.join(HISTORY_DIR, f"{no_hp}.json")
    if not os.path.exists(file_path):
        return []
    try:
        with open(file_path, "r") as f:
            return json.load(f)[-limit:]
    except Exception as e:
        print(f"[History] Error baca {no_hp}: {e}")
        return []


def save_chat_to_json(no_hp: str, pesan_user: str, pesan_bot: str, source: str = "groq"):
    """Simpan satu sesi chat ke file JSON lokal."""
    file_path = os.path.join(HISTORY_DIR, f"{no_hp}.json")
    entry = {
        "waktu": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user": pesan_user,
        "bot": pesan_bot,
        "source": source,
    }
    current = []
    if os.path.exists(file_path):
        try:
            with open(file_path, "r") as f:
                current = json.load(f)
        except Exception:
            current = []
    current.append(entry)
    with open(file_path, "w") as f:
        json.dump(current, f, indent=4)


def save_to_supabase(no_hp: str, message: str, direction: str, source: str = "system"):
    """Insert satu baris pesan ke tabel messages di Supabase."""
    if supabase is None:
        print("[Supabase] Skip save — belum dikonfigurasi.")
        return None
    return supabase.table("messages").insert({
        "sender_number": no_hp,
        "message_text": message,
        "direction": direction,
        "source": source,
    }).execute()


def query_rasa(message: str, sender: str) -> Optional[dict]:
    """
    Kirim pesan ke Rasa dan parse hasilnya.
    Return dict {reply, confidence, intent} atau None jika Rasa error.
    """
    try:
        resp = requests.post(
            f"{RASA_URL}/webhooks/rest/webhook",
            json={"sender": sender, "message": message},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        if not data:
            return None

        bot_reply = "\n\n".join(item.get("text", "") for item in data if "text" in item)

        parse_resp = requests.post(
            f"{RASA_URL}/model/parse",
            json={"text": message},
            timeout=10,
        )
        parse_resp.raise_for_status()
        parse_data = parse_resp.json()

        return {
            "reply": bot_reply,
            "confidence": parse_data.get("intent", {}).get("confidence", 0.0),
            "intent": parse_data.get("intent", {}).get("name", ""),
        }
    except Exception as e:
        print(f"[Rasa Error] {e}")
        return None


# ======================================================
# 
#                   SYSTEM ENDPOINT
# 
# ======================================================

@app.get(
    "/",
    tags=["System"],
    summary="Health check",
)
def home():
    return {
        "status": "ok",
        "message": "SmartClinic CRM AI is running!",
        "docs": "/docs",
    }


@app.post(
    "/webhook",
    response_model=ChatResponse,
    tags=["System"],
    summary="Terima pesan WhatsApp masuk dari Fonnte",
    description=(
        "Entry point utama. Pesan diklasifikasikan oleh Rasa; "
        "jika confidence rendah atau intent tidak dikenal, Groq LLM mengambil alih."
    ),
)
def webhook(payload: WebhookPayload):
    try:
        no_hp = payload.sender
        input_pesan = payload.message
        waktu = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        print(f"\n[{waktu}] [INCOMING] Dari: {no_hp} | Pesan: {input_pesan}")
        save_to_supabase(no_hp, input_pesan, direction="inbound", source="fonnte")

        chat_history = get_chat_history_json(no_hp, limit=5)
        reply = ""
        source = ""

        # ── Step 1: Coba Rasa ─────────────────────────────────────────────
        rasa_result = query_rasa(input_pesan, no_hp)
        if rasa_result:
            print(f"[DEBUG] Rasa → intent: '{rasa_result['intent']}', confidence: {rasa_result['confidence']:.4f}")

        if (
            rasa_result
            and rasa_result["confidence"] >= RASA_CONFIDENCE_THRESHOLD
            and rasa_result["intent"] in RASA_TRUSTED_INTENTS
            and rasa_result["reply"]
        ):
            reply = rasa_result["reply"]
            source = "rasa"
            print("[DEBUG] → Answered by: RASA ✅")
        else:
            # ── Step 2: Groq LLM ──────────────────────────────────────────
            role = "triage" if any(k in input_pesan.lower() for k in TRIAGE_KEYWORDS) else "default"
            reply = groq.get_response(input_pesan, role_type=role, chat_history=chat_history)
            source = "groq"
            print(f"[DEBUG] → Answered by: GROQ LLM ✨ (role: {role})")

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


# ======================================================
# 
#               PATIENTS ENDPOINTS
# 
# ======================================================

@app.get(
    "/api/patients",
    response_model=List[PatientRecord],
    tags=["Patients"],
    summary="Ambil semua nomor pasien tersimpan",
)
def get_all_patients():
    _require_supabase()
    try:
        response = supabase.table("patients").select("*").order("created_at", desc=False).execute()
        return response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/api/patients",
    response_model=PatientRecord,
    tags=["Patients"],
    summary="Simpan nomor pasien baru",
    description="Jika nomor sudah ada, data diupdate (upsert). Tidak akan duplikat.",
)
def save_patient(payload: SavePatientPayload):
    _require_supabase()
    try:
        response = (
            supabase.table("patients")
            .upsert(
                {"phone_number": payload.phone_number, "name": payload.name},
                on_conflict="phone_number",
            )
            .execute()
        )
        return response.data[0]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete(
    "/api/patients/{phone_number}",
    tags=["Patients"],
    summary="Hapus nomor pasien",
)
def delete_patient(phone_number: str):
    _require_supabase()
    try:
        response = (
            supabase.table("patients")
            .delete()
            .eq("phone_number", phone_number)
            .execute()
        )
        if not response.data:
            raise HTTPException(status_code=404, detail=f"Nomor {phone_number} tidak ditemukan")
        return {"status": "ok", "message": f"Nomor {phone_number} berhasil dihapus"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ======================================================
# 
#                  MESSAGES ENDPOINTS
# 
# ======================================================

@app.get(
    "/api/messages",
    response_model=List[ChatRecord],
    tags=["Messages"],
    summary="Ambil semua pesan",
    description="Seluruh pesan dari semua nomor, diurutkan dari terlama. Gunakan query param `?limit=N` untuk batasi jumlah (default: 100).",
)
def get_all_messages(limit: int = 100):
    _require_supabase()
    try:
        response = (
            supabase.table("messages")
            .select("*")
            .order("created_at", desc=False)
            .limit(limit)
            .execute()
        )
        return response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/api/messages/{phone_number}",
    response_model=List[ChatRecord],
    tags=["Messages"],
    summary="Ambil pesan berdasarkan nomor",
    description="Seluruh riwayat inbound dan outbound milik satu nomor WhatsApp.",
)
def get_messages_by_number(phone_number: str):
    _require_supabase()
    try:
        response = (
            supabase.table("messages")
            .select("*")
            .eq("sender_number", phone_number)
            .order("created_at", desc=False)
            .execute()
        )
        if not response.data:
            raise HTTPException(status_code=404, detail=f"Tidak ada pesan untuk nomor {phone_number}")
        return response.data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ======================================================
# 
#               SEND MESSAGE ENDPOINTS
# 
# ======================================================

@app.post(
    "/api/send",
    tags=["Send"],
    summary="Kirim pesan ke satu nomor",
    description="Kirim pesan manual ke satu nomor WhatsApp melalui antrian Fonnte. Tercatat di Supabase sebagai outbound/manual.",
)
def send_message(payload: SendMessagePayload):
    try:
        fonnte_queue.add_to_queue(payload.target, payload.message)
        save_to_supabase(payload.target, payload.message, direction="outbound", source="manual")
        print(f"[SEND] Manual → {payload.target}: {payload.message[:60]}...")
        return {"status": "ok", "message": f"Pesan untuk {payload.target} masuk antrian"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/api/send/broadcast",
    response_model=BroadcastResult,
    tags=["Send"],
    summary="Broadcast pesan ke semua nomor pasien",
    description=(
        "Kirim satu pesan ke seluruh nomor di tabel patients. "
        "Setiap pesan dimasukkan ke antrian Fonnte dengan delay acak (anti-blokir WA). "
        "Semua pengiriman dicatat di Supabase sebagai outbound/broadcast."
    ),
)
def broadcast_message(payload: BroadcastPayload):
    _require_supabase()
    try:
        response = supabase.table("patients").select("phone_number").execute()
        patients = response.data

        if not patients:
            raise HTTPException(
                status_code=404,
                detail="Tidak ada nomor pasien tersimpan. Tambahkan dulu via POST /api/patients",
            )

        recipients = []
        for patient in patients:
            number = patient.get("phone_number")
            if not number:
                continue
            fonnte_queue.add_to_queue(number, payload.message)
            save_to_supabase(number, payload.message, direction="outbound", source="broadcast")
            recipients.append(number)

        print(f"[BROADCAST] {len(recipients)} pesan masuk antrian")
        return BroadcastResult(status="ok", total_sent=len(recipients), recipients=recipients)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ======================================================
# 
#               APP SYSTEM ENTRYPOINT
# 
# ======================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("App.app:app", host="0.0.0.0", port=5000, reload=False)
