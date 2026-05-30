# ======================================================
# SmartClinic CRM AI — routers/feedback.py
# Endpoint: /api/feedback
#
# Last Change   :   30 May 2026
# Developer     :   Raja Zhafif Raditya Harahp
# ======================================================

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, HTTPException

from App.config import supabase
from App.helpers import _require_supabase, normalize_phone_number
from App.models import FeedbackDashboardRecord, FeedbackPayload, FeedbackRecord


router = APIRouter(prefix="/api/feedback", tags=["Feedback"])


FEEDBACK_EXAMPLE = {
    "nama": "Budi Santoso",
    "no_hp": "6281234567890",
    "rating": 5,
    "ulasan": "Pelayanannya cepat dan ramah.",
}


DASHBOARD_EXAMPLE = {
    "total_feedback": 12,
    "rata_rating": 4.7,
    "total_survey_terkirim": 20,
    "total_ngisi": 12,
    "total_gak_ngisi": 8,
}


def _feedback_columns() -> str:
    return "id_user, rating, ulasan"


def _feedback_row(record: dict, name: Optional[str] = None) -> dict:
    return {
        "nama": name,
        "no_hp": record.get("id_user"),
        "rating": record.get("rating"),
        "ulasan": record.get("ulasan") or "",
    }


def _get_patient_name_by_phone(no_hp: str) -> Optional[str]:
    if supabase is None:
        return None

    response = (
        supabase.table("patients")
        .select("name, phone_number")
        .eq("phone_number", normalize_phone_number(no_hp))
        .limit(1)
        .execute()
    )
    if not response.data:
        return None

    return response.data[0].get("name")


def _get_feedback_rows() -> list[dict]:
    _require_supabase()
    response = supabase.table("feedback").select(_feedback_columns()).order("id_user", desc=False).execute()
    return response.data or []


@router.get(
    "",
    response_model=list[FeedbackRecord],
    summary="Ambil semua feedback",
    description="Mengembalikan semua feedback pasien beserta nama dan nomor HP yang terhubung ke tabel patients.",
    responses={
        200: {
            "description": "Feedback berhasil diambil",
            "content": {"application/json": {"example": [FEEDBACK_EXAMPLE]}},
        },
        500: {
            "description": "Gagal mengambil feedback",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
def get_all_feedback():
    try:
        rows = _get_feedback_rows()
        return [_feedback_row(row, _get_patient_name_by_phone(row.get("id_user", ""))) for row in rows]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "",
    response_model=FeedbackRecord,
    summary="Kirim feedback",
    description="Menyimpan feedback pasien berdasarkan nomor WhatsApp.",
    responses={
        200: {
            "description": "Feedback berhasil disimpan",
            "content": {"application/json": {"example": FEEDBACK_EXAMPLE}},
        },
        500: {
            "description": "Gagal menyimpan feedback",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
def create_feedback(
    payload: FeedbackPayload = Body(
        ...,
        examples={
            "feedbackExample": {
                "summary": "Contoh feedback",
                "value": {
                    "no_hp": "6281234567890",
                    "rating": 5,
                    "ulasan": "Pelayanannya cepat dan ramah.",
                },
            }
        },
    )
):
    try:
        _require_supabase()
        normalized_phone = normalize_phone_number(payload.no_hp)
        feedback_data = {
            "id_user": normalized_phone,
            "rating": payload.rating,
            "ulasan": payload.ulasan or "",
        }

        response = (
            supabase.table("feedback")
            .upsert(feedback_data, on_conflict="id_user")
            .select(_feedback_columns())
            .execute()
        )

        row = (response.data or [feedback_data])[0]
        return _feedback_row(row, _get_patient_name_by_phone(normalized_phone))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/dashboard",
    response_model=FeedbackDashboardRecord,
    summary="Dashboard feedback",
    description="Ringkasan feedback untuk dashboard admin.",
    responses={
        200: {
            "description": "Ringkasan dashboard berhasil diambil",
            "content": {"application/json": {"example": DASHBOARD_EXAMPLE}},
        },
        500: {
            "description": "Gagal mengambil dashboard feedback",
            "content": {"application/json": {"example": {"detail": "..."}}},
        },
    },
)
def get_feedback_dashboard():
    try:
        _require_supabase()

        feedback_rows = _get_feedback_rows()
        patient_rows = supabase.table("patients").select("phone_number").execute().data or []

        total_feedback = len(feedback_rows)
        rata_rating = None
        if total_feedback:
            rata_rating = round(sum(int(row.get("rating") or 0) for row in feedback_rows) / total_feedback, 2)

        total_survey_terkirim = len(patient_rows)
        total_ngisi = total_feedback
        total_gak_ngisi = max(total_survey_terkirim - total_ngisi, 0)

        return {
            "total_feedback": total_feedback,
            "rata_rating": rata_rating,
            "total_survey_terkirim": total_survey_terkirim,
            "total_ngisi": total_ngisi,
            "total_gak_ngisi": total_gak_ngisi,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc