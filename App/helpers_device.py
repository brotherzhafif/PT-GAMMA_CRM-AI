# ======================================================
# SmartClinic CRM AI — helpers_device.py
# Helper untuk parse User-Agent & resolve IP ke lokasi
#
# Last Change   :   07 Jul 2026
# Developer     :   Raja Zhafif Raditya Harahap
# ======================================================
#
# Fungsi:
#   - parse_user_agent(ua_string) → label manusiawi, misal:
#       "Chrome 124 on Windows 10"
#       "Mobile Safari on iOS 17"
#   - resolve_ip_location(ip) → string lokasi, misal:
#       "Jakarta, Indonesia"
#   - get_real_ip(request) → ambil IP publik dengan
#     memperhatikan header X-Forwarded-For (Docker/proxy)
# ======================================================

from __future__ import annotations

import re
from typing import Optional

import httpx
from fastapi import Request


# ──────────────────────────────────────────────────────────
# IP helpers
# ──────────────────────────────────────────────────────────

# IP private/loopback/Docker internal — tidak bisa di-geolocate
_PRIVATE_IP_PREFIXES = (
    "127.",
    "10.",
    "192.168.",
    "172.16.", "172.17.", "172.18.", "172.19.",
    "172.20.", "172.21.", "172.22.", "172.23.",
    "172.24.", "172.25.", "172.26.", "172.27.",
    "172.28.", "172.29.", "172.30.", "172.31.",
    "::1",
    "localhost",
)


def _is_private_ip(ip: str) -> bool:
    if not ip:
        return True
    return any(ip.startswith(prefix) for prefix in _PRIVATE_IP_PREFIXES)


def get_real_ip(request: Request) -> Optional[str]:
    """Ambil IP publik klien dengan memprioritaskan header proxy.

    Urutan prioritas:
      1. X-Forwarded-For (header pertama yang bukan private IP)
      2. X-Real-IP
      3. request.client.host (fallback langsung)
    """
    xff = request.headers.get("X-Forwarded-For") or request.headers.get("x-forwarded-for")
    if xff:
        for candidate in [ip.strip() for ip in xff.split(",")]:
            if candidate and not _is_private_ip(candidate):
                return candidate

    x_real = request.headers.get("X-Real-IP") or request.headers.get("x-real-ip")
    if x_real and not _is_private_ip(x_real):
        return x_real

    host = request.client.host if request.client else None
    return host  # bisa jadi private IP / None — tetap return untuk keperluan log


# ──────────────────────────────────────────────────────────
# User-Agent parser (tanpa library eksternal berat)
# ──────────────────────────────────────────────────────────

def parse_user_agent(ua_string: Optional[str]) -> str:
    """Parse raw User-Agent string menjadi label singkat yang manusiawi.

    Contoh output:
        "Chrome 124 on Windows 10"
        "Firefox 126 on macOS"
        "Mobile Safari on iOS 17"
        "Edge 124 on Windows 11"
        "Postman / curl"
        "Unknown Browser"
    """
    if not ua_string:
        return "Unknown Device"

    ua = ua_string

    # ── Detect OS ──────────────────────────────────────────
    os_label = ""
    if "Windows NT 10.0" in ua:
        os_label = "Windows 10/11"
    elif "Windows NT 6.3" in ua:
        os_label = "Windows 8.1"
    elif "Windows NT 6.1" in ua:
        os_label = "Windows 7"
    elif "Windows" in ua:
        os_label = "Windows"
    elif "iPhone" in ua:
        ios_m = re.search(r"iPhone OS ([\d_]+)", ua)
        ver = ios_m.group(1).replace("_", ".").split(".")[0] if ios_m else ""
        os_label = f"iOS {ver}" if ver else "iOS"
    elif "iPad" in ua:
        ios_m = re.search(r"CPU OS ([\d_]+)", ua)
        ver = ios_m.group(1).replace("_", ".").split(".")[0] if ios_m else ""
        os_label = f"iPadOS {ver}" if ver else "iPadOS"
    elif "Android" in ua:
        and_m = re.search(r"Android ([\d.]+)", ua)
        ver = and_m.group(1).split(".")[0] if and_m else ""
        os_label = f"Android {ver}" if ver else "Android"
    elif "Mac OS X" in ua:
        os_label = "macOS"
    elif "Linux" in ua:
        os_label = "Linux"
    elif "CrOS" in ua:
        os_label = "ChromeOS"

    # ── Detect Browser ─────────────────────────────────────
    browser_label = ""

    # Postman / curl / non-browser
    if "PostmanRuntime" in ua:
        return "Postman"
    if ua.startswith("curl/"):
        return "curl"
    if "python-httpx" in ua or "python-requests" in ua:
        return "Python HTTP Client"

    # Edge harus dicek sebelum Chrome (karena Edge juga berisi "Chrome")
    edge_m = re.search(r"Edg(?:e|A|iOS)?/([\d.]+)", ua)
    if edge_m:
        ver = edge_m.group(1).split(".")[0]
        browser_label = f"Edge {ver}"
    # Samsung Internet
    elif "SamsungBrowser" in ua:
        sam_m = re.search(r"SamsungBrowser/([\d.]+)", ua)
        ver = sam_m.group(1).split(".")[0] if sam_m else ""
        browser_label = f"Samsung Browser {ver}" if ver else "Samsung Browser"
    # Chrome (harus sebelum Safari)
    elif "CriOS" in ua:  # Chrome on iOS
        crios_m = re.search(r"CriOS/([\d.]+)", ua)
        ver = crios_m.group(1).split(".")[0] if crios_m else ""
        browser_label = f"Chrome {ver}" if ver else "Chrome"
    elif "Chrome" in ua and "Safari" in ua:
        chrome_m = re.search(r"Chrome/([\d.]+)", ua)
        ver = chrome_m.group(1).split(".")[0] if chrome_m else ""
        browser_label = f"Chrome {ver}" if ver else "Chrome"
    # Firefox
    elif "FxiOS" in ua:  # Firefox on iOS
        ff_m = re.search(r"FxiOS/([\d.]+)", ua)
        ver = ff_m.group(1).split(".")[0] if ff_m else ""
        browser_label = f"Firefox {ver}" if ver else "Firefox"
    elif "Firefox" in ua:
        ff_m = re.search(r"Firefox/([\d.]+)", ua)
        ver = ff_m.group(1).split(".")[0] if ff_m else ""
        browser_label = f"Firefox {ver}" if ver else "Firefox"
    # Safari
    elif "Safari" in ua:
        safari_m = re.search(r"Version/([\d.]+)", ua)
        ver = safari_m.group(1).split(".")[0] if safari_m else ""
        browser_label = f"Safari {ver}" if ver else "Safari"
    # Opera
    elif "OPR" in ua or "Opera" in ua:
        op_m = re.search(r"OPR/([\d.]+)", ua)
        ver = op_m.group(1).split(".")[0] if op_m else ""
        browser_label = f"Opera {ver}" if ver else "Opera"

    if not browser_label:
        browser_label = "Unknown Browser"

    if os_label:
        return f"{browser_label} on {os_label}"
    return browser_label


# ──────────────────────────────────────────────────────────
# IP → Lokasi (ip-api.com, gratis tanpa API key)
# ──────────────────────────────────────────────────────────

async def resolve_ip_location(ip: Optional[str]) -> Optional[str]:
    """Resolve IP publik ke string lokasi "Kota, Negara".

    - Private/internal IP → return None (tidak bisa di-geolocate)
    - Gagal request / timeout → return None (non-fatal)
    """
    if not ip or _is_private_ip(ip):
        return None

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"http://ip-api.com/json/{ip}",
                params={"fields": "status,city,country"},
            )
            data = resp.json()

        if data.get("status") == "success":
            city    = data.get("city", "")
            country = data.get("country", "")
            parts   = [p for p in (city, country) if p]
            return ", ".join(parts) if parts else None

    except Exception as exc:
        print(f"[DeviceHelper] Gagal resolve IP {ip} ke lokasi: {exc}")

    return None
