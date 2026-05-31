from __future__ import annotations

import os

import requests


DEFAULT_DOCKER_WA_SERVICE_URL = "http://wa-service:3000"
DEFAULT_LOCAL_WA_SERVICE_URL = "http://127.0.0.1:3001"


def wa_service_base_urls() -> list[str]:
    configured = os.getenv("WA_SERVICE_URL", DEFAULT_DOCKER_WA_SERVICE_URL).rstrip("/")

    if configured == DEFAULT_DOCKER_WA_SERVICE_URL:
        return [DEFAULT_DOCKER_WA_SERVICE_URL, DEFAULT_LOCAL_WA_SERVICE_URL]

    if configured == DEFAULT_LOCAL_WA_SERVICE_URL:
        return [DEFAULT_LOCAL_WA_SERVICE_URL, DEFAULT_DOCKER_WA_SERVICE_URL]

    return [configured]


def wa_service_request(method: str, path: str, *, timeout: float = 10.0, **kwargs):
    last_error: Exception | None = None

    for base_url in wa_service_base_urls():
        try:
            return requests.request(method, f"{base_url}{path}", timeout=timeout, **kwargs)
        except requests.RequestException as exc:
            last_error = exc

    if last_error is not None:
        raise last_error

    raise RuntimeError("wa-service request failed without an exception")