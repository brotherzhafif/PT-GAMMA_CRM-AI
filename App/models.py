# ======================================================
# SmartClinic CRM AI — models.py
# Semua Pydantic models untuk request & response API
#
# Last Change   :   22 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

from typing import List, Optional, Literal
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


# Webhook 

class WebhookPayload(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "sender": "6281234567890",
                "message": "Jadwal dokter hari ini?",
            }
        }
    )

    sender: str = Field(..., description="Nomor WhatsApp pengirim", examples=["6281234567890"])
    message: str = Field(..., description="Isi pesan masuk", examples=["Jadwal dokter hari ini?"])


class ChatResponse(BaseModel):
    status: str
    source: Optional[str] = None
    reply: Optional[str] = None


# Auth

class AuthUserProfile(BaseModel):
    id: str = Field(..., description="ID profil user internal", examples=["0c16dc6d-e940-475e-a822-479ffbaca372"])
    name: str = Field(..., description="Nama user", examples=["Super Admin"])
    email: str = Field(..., description="Email login", examples=["superadmin@smartclinic.local"])
    role: str = Field(..., description="Role user internal", examples=["super_admin"])


class AuthLoginResponse(BaseModel):
    access_token: str = Field(..., description="Access token Supabase Auth")
    refresh_token: str = Field(..., description="Refresh token Supabase Auth")
    user: AuthUserProfile


class AuthRefreshResponse(BaseModel):
    access_token: str = Field(..., description="Access token Supabase Auth")
    refresh_token: str = Field(..., description="Refresh token Supabase Auth")


class AuthSimpleMessage(BaseModel):
    message: str


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
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "nik": "3273010101010001",
                "namaLengkap": "Budi Santoso",
                "tanggalLahir": "1990-01-01",
                "jenisKelamin": "LAKI_LAKI",
                "telepon": "6281234567890",
            }
        }
    )

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
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "7f5f4ce1-7d7a-4f6d-9c01-2db0b1f5a111",
                "campaign_name": "Promo Cek Gigi Mei",
                "schedule_date": "2026-05-25T09:00:00Z",
                "campaign_message": "Halo pasien SmartClinic, promo cek gigi bulan ini tersedia sampai akhir Mei.",
                "attachment_url": "https://example.com/promo-cekgigi.jpg",
                "filename": "promo-cekgigi.jpg",
                "status": "scheduled",
                "created_at": "2026-05-22T10:00:00Z",
                "updated_at": "2026-05-22T10:00:00Z",
            }
        }
    )

    id: Optional[str] = Field(default=None)
    campaign_name: str = Field(..., description="Nama campaign", examples=["Promo Cek Gigi Mei"])
    schedule_date: Optional[datetime] = Field(
        default=None,
        description="Waktu campaign (ISO 8601)",
        examples=["2026-05-25T09:00:00Z"],
    )
    campaign_message: str = Field(..., description="Isi pesan campaign", examples=["Halo pasien SmartClinic, promo cek gigi bulan ini tersedia sampai akhir Mei."])
    attachment_url: Optional[str] = Field(
        default=None,
        description="URL attachment campaign atau path lokal file upload",
        examples=["https://example.com/promo-cekgigi.jpg", "file://chat_state/campaign_uploads/promo-cekgigi.jpg"],
    )
    filename: Optional[str] = Field(default=None, description="Nama file attachment yang dikirim ke broadcast", examples=["promo-cekgigi.jpg"])
    status: Optional[str] = Field(default=None, description="Status campaign", examples=["scheduled", "processing", "sent", "failed"])
    created_at: Optional[datetime] = Field(default=None)
    updated_at: Optional[datetime] = Field(default=None)


class SaveCampaignPayload(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "campaign_name": "Promo Cek Gigi Mei",
                "schedule_date": "2026-05-25T09:00:00Z",
                "campaign_message": "Halo pasien SmartClinic, promo cek gigi bulan ini tersedia sampai akhir Mei.",
                "attachment_url": "https://example.com/promo-cekgigi.jpg",
                "filename": "promo-cekgigi.jpg",
                "status": "scheduled",
            }
        }
    )

    campaign_name: str = Field(..., description="Nama campaign", examples=["Promo Cek Gigi Mei"])
    schedule_date: Optional[datetime] = Field(default=None, description="Waktu campaign (ISO 8601)", examples=["2026-05-25T09:00:00Z"])
    campaign_message: str = Field(..., description="Isi pesan campaign", examples=["Halo pasien SmartClinic, promo cek gigi bulan ini tersedia sampai akhir Mei."])
    attachment_url: Optional[str] = Field(default=None, description="URL attachment campaign (opsional)", examples=["https://example.com/promo-cekgigi.jpg"])
    filename: Optional[str] = Field(default=None, description="Nama file attachment (opsional)", examples=["promo-cekgigi.jpg"])
    status: Optional[str] = Field(default=None, description="Status campaign", examples=["scheduled"])


class UpdateCampaignPayload(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "campaign_name": "Promo Cek Gigi Mei Revisi",
                "schedule_date": "2026-05-26T09:00:00Z",
                "campaign_message": "Promo cek gigi diperpanjang sampai akhir Mei.",
                "attachment_url": "https://example.com/promo-cekgigi.jpg",
                "filename": "promo-cekgigi.jpg",
                "status": "scheduled",
            }
        }
    )

    campaign_name: Optional[str] = Field(default=None, description="Nama campaign baru", examples=["Promo Cek Gigi Mei Revisi"])
    schedule_date: Optional[datetime] = Field(default=None, description="Waktu campaign baru (ISO 8601)", examples=["2026-05-26T09:00:00Z"])
    campaign_message: Optional[str] = Field(default=None, description="Isi pesan campaign baru", examples=["Promo cek gigi diperpanjang sampai akhir Mei."])
    attachment_url: Optional[str] = Field(default=None, description="URL attachment campaign baru (opsional)", examples=["https://example.com/promo-cekgigi.jpg"])
    filename: Optional[str] = Field(default=None, description="Nama file attachment baru (opsional)", examples=["promo-cekgigi.jpg"])
    status: Optional[str] = Field(default=None, description="Status campaign baru", examples=["scheduled"])

# Send 

class SendMessagePayload(BaseModel):
    target: str = Field(..., description="Nomor WhatsApp tujuan atau chat ID grup WhatsApp", examples=["6281234567890", "1203630xxxxxxxx@g.us"])
    message: str = Field(..., description="Isi pesan yang akan dikirim")
    attachment_url: Optional[str] = Field(default=None, description="URL file attachment (PDF, gambar). Jika diisi, dikirim via whatsapp-web.js")
    filename: Optional[str] = Field(default=None, description="Nama file yang tampil di WhatsApp (opsional)")


class SendInteractiveTargetPayload(BaseModel):
    target: str = Field(..., description="Nomor WhatsApp tujuan atau chat ID grup WhatsApp", examples=["6281234567890", "1203630xxxxxxxx@g.us"])


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
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "2f4d52c2-1111-4b5f-9b5d-1b2c3d4e5f67",
                "ai_name": "SmartClinic AI",
                "primary_language": "id",
                "conversation_tone": "friendly",
                "handoff_threshold": 70,
                "handoff_message": "Mohon tunggu sebentar, admin kami akan segera membantu.",
                "ai_badge_enabled": True,
                "api_key": "gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                "quota_used_tokens": 12500,
                "quota_limit_tokens": 50000,
                "quota": "12500/50000",
                "created_at": "2026-05-25T10:00:00Z",
                "updated_at": "2026-05-25T10:00:00Z",
            }
        }
    )

    id: Optional[str] = Field(default=None)
    ai_name: Optional[str] = Field(default=None)
    primary_language: Optional[str] = Field(default=None)
    conversation_tone: Optional[Literal["friendly", "professional", "caring"]] = Field(default=None)
    handoff_threshold: Optional[int] = Field(default=None, ge=0, le=100)
    handoff_message: Optional[str] = Field(default=None)
    ai_badge_enabled: Optional[bool] = Field(default=None)
    api_key: Optional[str] = Field(
        default=None,
        description="Groq API key aktif yang dipakai proses runtime saat ini.",
        examples=["gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"],
    )
    quota_used_tokens: Optional[int] = Field(
        default=None,
        description="Total token dari respons Groq terakhir yang tersimpan di memory proses.",
        examples=[12500],
    )
    quota_limit_tokens: Optional[int] = Field(
        default=None,
        description="Batas token dari header rate limit Groq terakhir.",
        examples=[50000],
    )
    quota: Optional[str] = Field(
        default=None,
        description="Format quota token used/limit dari request Groq terakhir.",
        examples=["12500/50000"],
    )
    created_at: Optional[str] = Field(default=None)
    updated_at: Optional[str] = Field(default=None)


class UpdateChatbotSettingsPayload(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ai_name": "SmartClinic AI",
                "primary_language": "id",
                "conversation_tone": "friendly",
                "handoff_threshold": 70,
                "handoff_message": "Mohon tunggu sebentar, admin kami akan segera membantu.",
                "ai_badge_enabled": True,
                "api_key": "gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            }
        }
    )

    ai_name: Optional[str] = Field(default=None, description="Nama AI")
    primary_language: Optional[str] = Field(default=None, description="Bahasa utama percakapan")
    conversation_tone: Optional[Literal["friendly", "professional", "caring"]] = Field(
        default=None,
        description="Nada percakapan",
    )
    handoff_threshold: Optional[int] = Field(default=None, ge=0, le=100, description="Ambang handoff 0-100")
    handoff_message: Optional[str] = Field(default=None, description="Pesan handoff")
    ai_badge_enabled: Optional[bool] = Field(default=None, description="Tampilkan badge AI")
    api_key: Optional[str] = Field(
        default=None,
        description="Groq API key aktif yang akan dipakai runtime.",
        examples=["gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"],
    )


# Feedback

class FeedbackPayload(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "no_hp": "6281234567890",
                "rating": 5,
                "ulasan": "Pelayanan ramah dan cepat.",
            }
        }
    )

    no_hp: str = Field(..., description="Nomor WhatsApp pasien", examples=["6281234567890"])
    rating: int = Field(..., ge=1, le=5, description="Rating 1-5")
    ulasan: str = Field(default="", description="Ulasan pasien")


class FeedbackRecord(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "nama": "Budi Santoso",
                "no_hp": "6281234567890",
                "rating": 5,
                "ulasan": "Pelayanan ramah dan cepat.",
            }
        }
    )

    nama: Optional[str] = Field(default=None)
    no_hp: str
    rating: int
    ulasan: str


class FeedbackDashboardRecord(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "total_feedback": 12,
                "rata_rating": 4.8,
                "total_survey_terkirim": 20,
                "total_ngisi": 12,
                "total_gak_ngisi": 8,
            }
        }
    )

    total_feedback: int
    rata_rating: Optional[float]
    total_survey_terkirim: int
    total_ngisi: int
    total_gak_ngisi: int
