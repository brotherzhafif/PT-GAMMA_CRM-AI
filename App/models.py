# ======================================================
# SmartClinic CRM AI — models.py
# Semua Pydantic models untuk request & response API
#
# Last Change   :   22 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

from typing import List, Optional, Literal
from pydantic import BaseModel, Field


# Webhook 

class WebhookPayload(BaseModel):
    sender: str = Field(..., description="Nomor WhatsApp pengirim", examples=["6281234567890"])
    message: str = Field(..., description="Isi pesan masuk", examples=["Jadwal dokter hari ini?"])


class ChatResponse(BaseModel):
    status: str
    source: Optional[str] = None
    reply: Optional[str] = None


# Messages 

class ChatRecord(BaseModel):
    id: Optional[str] = Field(default=None)
    sender_number: str
    message_text: str
    direction: str = Field(..., description="inbound atau outbound")
    source: Optional[str] = Field(default=None, description="fonnte, rasa, groq, manual, broadcast, atau admin")
    created_at: Optional[str] = Field(default=None)


# Patients 

class PatientPayload(BaseModel):
    nik: str = Field(..., description="NIK pasien")
    namaLengkap: str = Field(..., description="Nama lengkap pasien")
    tanggalLahir: str = Field(..., description="Tanggal lahir pasien")
    jenisKelamin: Literal["LAKI_LAKI", "PEREMPUAN"] = Field(..., description="Jenis kelamin pasien")
    telepon: str = Field(..., description="Nomor telepon")


# class SavePatientPayload(BaseModel):
#     phone_number: str = Field(..., description="Nomor WhatsApp pasien", examples=["6281234567890"])
#     name: Optional[str] = Field(default=None, description="Nama pasien (opsional)")


# class UpdatePatientPayload(BaseModel):
#     name: Optional[str] = Field(default=None, description="Nama baru pasien")
#     phone_number: Optional[str] = Field(default=None, description="Nomor HP baru pasien")


# Marketing Campaigns

class CampaignRecord(BaseModel):
    id: Optional[str] = Field(default=None)
    campaign_name: str = Field(..., description="Nama campaign")
    schedule_date: Optional[str] = Field(default=None, description="Tanggal/jadwal campaign")
    campaign_message: str = Field(..., description="Isi pesan campaign")
    attachment_url: Optional[str] = Field(default=None, description="URL attachment campaign (gambar/PDF)")
    filename: Optional[str] = Field(default=None, description="Nama file attachment yang dikirim ke broadcast")
    status: Optional[str] = Field(default=None, description="Status campaign")
    created_at: Optional[str] = Field(default=None)
    updated_at: Optional[str] = Field(default=None)


class SaveCampaignPayload(BaseModel):
    campaign_name: str = Field(..., description="Nama campaign")
    schedule_date: Optional[str] = Field(default=None, description="Tanggal/jadwal campaign")
    campaign_message: str = Field(..., description="Isi pesan campaign")
    attachment_url: Optional[str] = Field(default=None, description="URL attachment campaign (opsional)")
    filename: Optional[str] = Field(default=None, description="Nama file attachment (opsional)")
    status: Optional[str] = Field(default=None, description="Status campaign")


class UpdateCampaignPayload(BaseModel):
    campaign_name: Optional[str] = Field(default=None, description="Nama campaign baru")
    schedule_date: Optional[str] = Field(default=None, description="Tanggal/jadwal campaign baru")
    campaign_message: Optional[str] = Field(default=None, description="Isi pesan campaign baru")
    attachment_url: Optional[str] = Field(default=None, description="URL attachment campaign baru (opsional)")
    filename: Optional[str] = Field(default=None, description="Nama file attachment baru (opsional)")
    status: Optional[str] = Field(default=None, description="Status campaign baru")

# Send 

class SendMessagePayload(BaseModel):
    target: str = Field(..., description="Nomor WhatsApp tujuan", examples=["6281234567890"])
    message: str = Field(..., description="Isi pesan yang akan dikirim")
    attachment_url: Optional[str] = Field(default=None, description="URL file attachment (PDF, gambar). Jika diisi, dikirim via whatsapp-web.js")
    filename: Optional[str] = Field(default=None, description="Nama file yang tampil di WhatsApp (opsional)")


class BroadcastPayload(BaseModel):
    message: str = Field(..., description="Isi pesan yang akan dikirim ke semua pasien")
    attachment_url: Optional[str] = Field(default=None, description="URL file attachment (PDF, gambar). Jika diisi, dikirim via whatsapp-web.js")
    filename: Optional[str] = Field(default=None, description="Nama file yang tampil di WhatsApp (opsional)")


class BroadcastResult(BaseModel):
    status: str
    total_sent: int
    recipients: List[str]


# Handoff 

class AdminReplyPayload(BaseModel):
    message: str = Field(..., description="Pesan balasan dari admin ke pasien")


class HandoffSession(BaseModel):
    phone_number: str
    started_at: str
    last_admin_reply_at: Optional[str] = None
    timeout_at: str


# Chatbot Settings

class ChatbotSettingsRecord(BaseModel):
    id: Optional[str] = Field(default=None)
    ai_name: Optional[str] = Field(default=None)
    primary_language: Optional[str] = Field(default=None)
    conversation_tone: Optional[Literal["friendly", "professional", "caring"]] = Field(default=None)
    handoff_threshold: Optional[int] = Field(default=None, ge=0, le=100)
    handoff_message: Optional[str] = Field(default=None)
    ai_badge_enabled: Optional[bool] = Field(default=None)
    created_at: Optional[str] = Field(default=None)
    updated_at: Optional[str] = Field(default=None)


class UpdateChatbotSettingsPayload(BaseModel):
    ai_name: Optional[str] = Field(default=None, description="Nama AI")
    primary_language: Optional[str] = Field(default=None, description="Bahasa utama percakapan")
    conversation_tone: Optional[Literal["friendly", "professional", "caring"]] = Field(
        default=None,
        description="Nada percakapan",
    )
    handoff_threshold: Optional[int] = Field(default=None, ge=0, le=100, description="Ambang handoff 0-100")
    handoff_message: Optional[str] = Field(default=None, description="Pesan handoff")
    ai_badge_enabled: Optional[bool] = Field(default=None, description="Tampilkan badge AI")
