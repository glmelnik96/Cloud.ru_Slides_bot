"""Shared helpers: parse the non-standard .env and build OpenAI client."""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

from openai import OpenAI

BASE_URL = "https://foundation-models.api.cloud.ru/v1"
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def load_api_key() -> str:
    text = ENV_PATH.read_text(encoding="utf-8")
    # Format observed:  apiKey: 'XXXX.YYYY'
    m = re.search(r"['\"]([A-Za-z0-9+/=._-]+\.[A-Za-z0-9+/=._-]+)['\"]", text)
    if not m:
        raise RuntimeError(f"Could not extract API key from {ENV_PATH}")
    return m.group(1)


def make_client() -> OpenAI:
    return OpenAI(api_key=load_api_key(), base_url=BASE_URL)


def timed_chat(client: OpenAI, *, model: str, **kwargs):
    """Run a chat completion, return (response, elapsed_seconds, error_str_or_None)."""
    t0 = time.perf_counter()
    try:
        resp = client.chat.completions.create(model=model, **kwargs)
        return resp, time.perf_counter() - t0, None
    except Exception as e:  # noqa: BLE001
        return None, time.perf_counter() - t0, f"{type(e).__name__}: {e}"


MODELS = [
    "zai-org/GLM-5.1",
    "moonshotai/Kimi-K2.6",
    "deepseek-ai/DeepSeek-V4-Pro",
]
