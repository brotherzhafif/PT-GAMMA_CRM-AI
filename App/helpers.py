# ======================================================
# SmartClinic CRM AI — helpers.py
# Fungsi-fungsi pembantu yang dipakai lintas router
#
# Last Change   :   29 May 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================

import json
import os
import re
import hashlib
from datetime import datetime
from typing import Any, Optional

import httpx
import requests
from fastapi import HTTPException, Response

from App.config import (
    supabase,
    HISTORY_DIR,
    STATE_DIR,
    RASA_URL,
    RASA_CONFIDENCE_THRESHOLD,
    HANDOFF_KEYWORDS,
)
from App.smartclinic_auth import get_smartclinic_token, force_refresh_smartclinic_token


def _get_smartclinic_token_with_retry() -> str:
    """Get SmartClinic token dengan auto-refresh jika login gagal.
    
    Ini adalah wrapper sinkron untuk menangani token refresh dan retry.
    """
    from App.smartclinic_auth import get_smartclinic_token_sync
    return get_smartclinic_token_sync()


def _smartclinic_request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    """Buat request ke SmartClinic dengan auto-retry pada 401 (sync version).

    Jika mendapat 401:
      1. Coba refresh via refreshToken
      2. Jika gagal, login ulang
      3. Retry request satu kali dengan token baru
    """
    from App.smartclinic_auth import _refresh_token_sync, _login_sync

    token = _get_smartclinic_token_with_retry()
    headers = kwargs.get("headers", {})
    headers["Authorization"] = f"Bearer {token}"
    kwargs["headers"] = headers

    response = requests.request(method, url, **kwargs)

    # Handle 401 — token sudah di-reject RME, force refresh lalu retry
    if response.status_code == 401:
        print(f"[SmartClinic] 401 pada {method} {url} — force refresh token dan retry...")
        try:
            refreshed = _refresh_token_sync()
            if not refreshed:
                print("[SmartClinic] refreshToken gagal, fallback ke login ulang...")
                refreshed = _login_sync()
            headers["Authorization"] = f"Bearer {refreshed}"
            kwargs["headers"] = headers
            response = requests.request(method, url, **kwargs)
            if response.status_code == 401:
                print(f"[SmartClinic] Masih 401 setelah force refresh pada {method} {url}.")
        except Exception as exc:
            print(f"[SmartClinic] Force refresh gagal: {exc}")

    return response


# Supabase 

def normalize_phone_number(phone_number: str) -> str:
    """Normalize nomor HP ke format 62xxxxxxxxx."""
    # Hapus suffix chat ID WhatsApp jika ada (e.g., @c.us, @g.us, @lid)
    cleaned_phone = re.sub(r"@[cg]\.us$|@lid$", "", phone_number or "").strip()

    digits = re.sub(r"\D+", "", cleaned_phone)

    if not digits:
        return "" # Mengembalikan string kosong jika tidak ada digit

    if digits.startswith("00"):
        digits = digits[2:]

    if digits.startswith("0"):
        digits = f"62{digits[1:]}"
    elif digits.startswith("8"): # Angka tanpa 0 didepan, dianggap nomor Indo (misal: 812xxxx)
        digits = f"62{digits}"
    elif digits.startswith("203"): # Prefix aneh seperti 203517176328348, anggap itu ID Fonnte yang bukan nomor HP
        return "" # Kembalikan string kosong atau lakukan penanganan error lain jika ini bukan nomor HP valid
    elif not digits.startswith("62"): # Jika tidak diawali 62 dan tidak diawali 0/8, tambahkan 62
        digits = f"62{digits}"

    return digits


def normalize_whatsapp_target(target: str) -> str:
    """Normalize target WA: nomor tetap dinormalisasi, chat ID grup dipertahankan."""
    value = (target or "").strip()

    if not value:
        return ""

    if value.endswith("@g.us") or value.endswith("@c.us"):
        return value

    return normalize_phone_number(value)

def _require_supabase():
    """Guard: raise 500 jika Supabase belum dikonfigurasi."""
    if supabase is None:
        raise HTTPException(
            status_code=500,
            detail="Supabase belum dikonfigurasi. Cek SUPABASE_URL dan SUPABASE_ANON_KEY di .env",
        )


async def proxy_smartclinic(
    method: str,
    base_url: str,
    path: str,
    *,
    params: Optional[list[tuple[str, str]]] = None,
    json: Optional[dict[str, Any]] = None,
) -> Response:
    """Proxy async request ke SmartClinic dengan auto-retry pada 401.

    Flow:
      1. Ambil token dari cache (atau refresh jika hampir expired).
      2. Kirim request ke RME.
      3. Jika dapat 401 → force_refresh_smartclinic_token() (async-safe, berlock)
         lalu retry sekali.
      4. Jika masih 401 setelah retry → return response 401 apa adanya.
    """
    token   = await get_smartclinic_token()
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        try:
            upstream = await client.request(method, path, params=params, json=json, headers=headers)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="Gagal menghubungi SmartClinic") from exc

        # Handle 401 — RME sudah reject token, force refresh lalu retry
        if upstream.status_code == 401:
            print(f"[SmartClinic] 401 pada {method} {path} — force refresh token dan retry...")
            try:
                # force_refresh_smartclinic_token() sudah membawa async lock;
                # aman dipanggil concurrent dari banyak endpoint sekaligus.
                new_token = await force_refresh_smartclinic_token()
                headers   = {"Authorization": f"Bearer {new_token}"}
            except Exception as exc:
                print(f"[SmartClinic] Force refresh gagal: {exc}")
                return Response(
                    content=upstream.content,
                    status_code=upstream.status_code,
                    media_type=upstream.headers.get("content-type"),
                )

            # Retry dengan token baru
            try:
                upstream = await client.request(method, path, params=params, json=json, headers=headers)
            except httpx.HTTPError as exc:
                raise HTTPException(status_code=502, detail="Gagal menghubungi SmartClinic saat retry") from exc

            if upstream.status_code == 401:
                print(f"[SmartClinic] Masih 401 setelah force refresh pada {method} {path}.")

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
    )


def save_image_from_bytes(file_bytes: bytes, filename: str) -> Optional[str]:
    """Menyimpan bytes gambar ke folder lokal chat_images dengan nama file hash MD5 untuk deduplikasi."""
    if not file_bytes:
        return None
    ext = os.path.splitext(filename)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
        # Jika file bukan gambar, lewati
        return None
    
    os.makedirs("chat_images", exist_ok=True)
    
    file_hash = hashlib.md5(file_bytes).hexdigest()
    stored_name = f"{file_hash}{ext}"
    stored_path = os.path.join("chat_images", stored_name)
    
    try:
        if not os.path.exists(stored_path):
            with open(stored_path, "wb") as f:
                f.write(file_bytes)
        return f"/chat_images/{stored_name}"
    except Exception as e:
        print(f"[ImageHelper] Gagal menyimpan file gambar hash: {e}")
        return None


def save_image_from_url(url: str, filename: str | None = None) -> Optional[str]:
    """Mengambil bytes dari URL (atau file path lokal) dan menyimpannya sebagai file hash ter-deduplikasi."""
    if not url:
        return None
    try:
        # Jika berupa link file lokal
        if url.startswith("file://"):
            local_path = url.removeprefix("file://")
            if os.path.exists(local_path):
                with open(local_path, "rb") as f:
                    file_bytes = f.read()
                name = filename or os.path.basename(local_path)
                return save_image_from_bytes(file_bytes, name)
            return None

        # Request HTTP ke URL
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            name = filename or url.split("/")[-1] or "image.jpg"
            content_type = resp.headers.get("content-type", "")
            if content_type.startswith("image/") or any(name.lower().endswith(e) for e in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")):
                return save_image_from_bytes(resp.content, name)
    except Exception as e:
        print(f"[ImageHelper] Gagal mengambil gambar dari URL {url}: {e}")
    return None


def save_to_supabase(no_hp: str, message: str, direction: str, source: str = "system", image_url: Optional[str] = None):
    """Insert satu baris pesan ke tabel messages di Supabase, beserta opsional image_url."""
    if supabase is None:
        print("[Supabase] Skip save — belum dikonfigurasi.")
        return None
    normalized_phone = normalize_phone_number(no_hp)
    return supabase.table("messages").insert({
        "sender_number": normalized_phone,
        "message_text": message,
        "direction": direction,
        "source": source,
        "image_url": image_url,
    }).execute()


def upsert_patient(
    no_hp: str,
    namaLengkap: Optional[str] = None,
    nik: Optional[str] = None,
    tanggalLahir: Optional[str] = None,
    jenisKelamin: Optional[str] = None,
):
    """
    Daftarkan pasien ke SmartClinic API, lalu simpan mapping ke Supabase.
    Alur:
      1. Susun body dari variabel yang sudah dipisah
      2. POST ke /patients SmartClinic
      3. Simpan phone_number + name + rme_patient_id ke Supabase
    """
    from App.config import SMARTCLINIC_BASE_URL

    normalized_phone = normalize_phone_number(no_hp)

    # Susun req body sesuai format endpoint /patients (persis sama dengan format di API)
    patient_body: dict = {"telepon": normalized_phone}
    if namaLengkap:
        patient_body["namaLengkap"] = namaLengkap
    if nik:
        patient_body["nik"] = nik
    if tanggalLahir:
        patient_body["tanggalLahir"] = tanggalLahir
    if jenisKelamin:
        patient_body["jenisKelamin"] = jenisKelamin
    
    # Dapatkan token secara sinkron
    token = _get_smartclinic_token_with_retry()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    
    # POST ke endpoint patient SmartClinic
    rme_patient_id = None
    try:
        resp = _smartclinic_request_with_retry(
            "POST",
            f"{SMARTCLINIC_BASE_URL.rstrip('/')}/patients",
            headers=headers,
            json=patient_body,
            timeout=15,
        )
        if resp.status_code < 400:
            resp_data = resp.json()
            rme_patient_id = (resp_data.get("data") or {}).get("id")
            print(f"[Patient] SmartClinic registered: {rme_patient_id}")
        elif resp.status_code == 409:
            # Pasien sudah ada — ambil ID via GET by NIK
            lookup_param = {"nik": nik} if nik else {"telepon": normalized_phone}
            get_resp = _smartclinic_request_with_retry(
                "GET",
                f"{SMARTCLINIC_BASE_URL.rstrip('/')}/patients",
                params=lookup_param,
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
            if get_resp.status_code < 400:
                get_data = get_resp.json()
                data = get_data.get("data", get_data)
                if isinstance(data, list) and len(data) > 0:
                     rme_patient_id = data[0].get("id")
                elif isinstance(data, dict):
                     rme_patient_id = data.get("id")
                print(f"[Patient] SmartClinic 409 — retrieved existing ID: {rme_patient_id}")
            else:
                print(f"[Patient] SmartClinic 409 — GET failed: {get_resp.status_code}")
        else:
            print(f"[Patient] SmartClinic error {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"[Patient] Gagal POST ke SmartClinic: {e}")

    # Simpan mapping ke Supabase
    if supabase is None:
        print(f"[Patient] Skip Supabase upsert — belum dikonfigurasi.")
        return

    sb_payload: dict = {"phone_number": normalized_phone}
    if namaLengkap:
        sb_payload["name"] = namaLengkap
    if rme_patient_id:
        sb_payload["rme_patient_id"] = rme_patient_id
    if tanggalLahir:
        sb_payload["birthdate"] = tanggalLahir.split("T")[0]

    supabase.table("patients").upsert(
        sb_payload,
        on_conflict="phone_number",
    ).execute()

    parts = []
    if namaLengkap:
        parts.append(f"nama: {namaLengkap}")
    if nik:
        parts.append(f"nik: ***{nik[-4:]}")
    if tanggalLahir:
        parts.append(f"tglLahir: {tanggalLahir}")
    if rme_patient_id:
        parts.append(f"rmeId: {rme_patient_id}")
    print(f"[Patient] Upsert {normalized_phone} ({', '.join(parts) if parts else 'tanpa data tambahan'})")


def is_patient_registered(no_hp: str) -> bool:
    """Cek apakah nomor sudah ada di tabel patients."""
    if supabase is None:
        return False
    normalized_phone = normalize_phone_number(no_hp)
    result = supabase.table("patients").select("id").eq("phone_number", normalized_phone).execute()
    return len(result.data) > 0


def get_rme_patient_id_by_phone(no_hp: str, *, not_found_detail: str = "Pasien tidak ditemukan") -> str:
    """Ambil rme_patient_id dari tabel patients berdasarkan nomor HP."""
    _require_supabase()

    normalized_phone = normalize_phone_number(no_hp)
    response = (
        supabase.table("patients")
        .select("rme_patient_id")
        .eq("phone_number", normalized_phone)
        .limit(1)
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=404, detail=not_found_detail)

    rme_patient_id = response.data[0].get("rme_patient_id")
    if not rme_patient_id:
        raise HTTPException(status_code=404, detail=not_found_detail)

    return rme_patient_id


# Chat History (JSON lokal) 

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


# Session State (onboarding) 

def get_session_state(no_hp: str) -> Optional[str]:
    """Ambil state sesi saat ini untuk nomor tertentu. Return None jika tidak ada."""
    file_path = os.path.join(STATE_DIR, f"{no_hp}.json")
    if not os.path.exists(file_path):
        return None
    try:
        with open(file_path, "r") as f:
            return json.load(f).get("state")
    except Exception:
        return None


def set_session_state(no_hp: str, state: Optional[str], data: Optional[dict] = None):
    """Set atau hapus state sesi. Kirim state=None untuk clear. data adalah dict opsional untuk menyimpan data onboarding sementara."""
    file_path = os.path.join(STATE_DIR, f"{no_hp}.json")
    if state is None:
        if os.path.exists(file_path):
            os.remove(file_path)
        return
    payload = {
        "state": state,
        "updated_at": datetime.utcnow().isoformat()
    }
    if data is not None:
        payload["data"] = data
    with open(file_path, "w") as f:
        json.dump(payload, f)


def get_session_updated_at(no_hp: str) -> Optional[str]:
    """Ambil waktu update sesi terakhir untuk nomor tertentu. Return None jika tidak ada."""
    file_path = os.path.join(STATE_DIR, f"{no_hp}.json")
    if not os.path.exists(file_path):
        return None
    try:
        with open(file_path, "r") as f:
            return json.load(f).get("updated_at")
    except Exception:
        return None


def get_onboarding_data(no_hp: str) -> dict:
    """Ambil data onboarding sementara dari file state. Return {} jika tidak ada."""
    file_path = os.path.join(STATE_DIR, f"{no_hp}.json")
    if not os.path.exists(file_path):
        return {}
    try:
        with open(file_path, "r") as f:
            return json.load(f).get("data", {})
    except Exception:
        return {}


# Rasa 
def query_rasa(message: str, sender: str) -> Optional[dict]:
    """
    Kirim pesan ke Rasa dan parse hasilnya.
    Return dict {reply, confidence, intent, is_form_active, requested_slot}
    atau None jika Rasa error.

    PENTING — urutan eksekusi ini disengaja:
      1. Snapshot tracker SEBELUM pesan dikirim ke Rasa.
         Ini mencegah false-negative is_form_active=False pada slot terakhir form
         (misal booking_tgl_kunjungan), di mana Rasa menutup active_loop tepat
         setelah slot diisi — sehingga jika dicek SESUDAH, form sudah null.
      2. Baru kirim pesan ke Rasa.
      3. Parse NLU untuk keperluan logging & routing di webhook.py.
    """
    try:
        # Snapshot tracker SEBELUM pesan diproses
        is_form_active = False
        requested_slot = None
        try:
            tracker_pre = requests.get(
                f"{RASA_URL}/conversations/{sender}/tracker",
                timeout=5,
            )
            if tracker_pre.status_code == 200:
                tracker_data = tracker_pre.json()
                active_loop = tracker_data.get("active_loop") or {}
                is_form_active = active_loop.get("name") is not None
                # requested_slot disimpan untuk keperluan debug log di webhook.py
                requested_slot = (tracker_data.get("slots") or {}).get("requested_slot")
        except Exception as tracker_err:
            print(f"[Rasa] Tracker pre-check gagal (non-fatal): {tracker_err}")

        # Kirim pesan ke Rasa untuk diproses
        # Timeout 30 detik karena action booking memanggil 2x external API
        resp = requests.post(
            f"{RASA_URL}/webhooks/rest/webhook",
            json={"sender": sender, "message": message},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        # Ambil reply teks dari Rasa
        bot_reply = "\n\n".join(item.get("text", "") for item in data if "text" in item) if data else ""

        # Parse NLU untuk logging & routing di webhook.py
        parse_resp = requests.post(
            f"{RASA_URL}/model/parse",
            json={"text": message},
            timeout=15,
        )
        parse_resp.raise_for_status()
        parse_data = parse_resp.json()

        intent = parse_data.get("intent", {}).get("name", "")
        confidence = parse_data.get("intent", {}).get("confidence", 0.0)

        # Safe override — hanya aktif kalau Rasa sendiri yang set requested_slot booking_*
        if requested_slot and requested_slot.startswith("booking_"):
            is_form_active = True

        return {
            "reply": bot_reply,
            "confidence": confidence,
            "intent": intent,
            "is_form_active": is_form_active,   # snapshot PRE-message + safe override
            "requested_slot": requested_slot,   # untuk debug log di webhook.py
        }
    except Exception as e:
        print(f"[Rasa Error] {e}")
        return None


# Handoff helpers 

def is_handoff_keyword(pesan: str) -> bool:
    """Cek apakah pesan mengandung keyword trigger handoff."""
    pesan_lower = pesan.lower().strip()
    return any(keyword in pesan_lower for keyword in HANDOFF_KEYWORDS)


# Fallback counter per nomor (in-memory, reset saat restart)
_fallback_counter: dict = {}


def increment_fallback(no_hp: str) -> int:
    """Tambah counter fallback Groq, return jumlah sekarang."""
    _fallback_counter[no_hp] = _fallback_counter.get(no_hp, 0) + 1
    return _fallback_counter[no_hp]


def reset_fallback(no_hp: str):
    """Reset counter fallback untuk nomor tertentu."""
    _fallback_counter.pop(no_hp, None)