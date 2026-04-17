from __future__ import annotations

import json
import os
from typing import Any

from openai import OpenAI


def _client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY", "local-key")
    base_url = os.getenv("LLM_BASE_URL")
    if base_url:
        return OpenAI(api_key=api_key, base_url=base_url)
    return OpenAI(api_key=api_key)


def _model_name() -> str:
    return os.getenv("LLM_MODEL", "gpt-4o-mini")


def llm_json(prompt: str, system: str = "You are a senior code review assistant.") -> dict[str, Any]:
    if not os.getenv("OPENAI_API_KEY") and not os.getenv("LLM_BASE_URL"):
        return {}
    try:
        response = _client().chat.completions.create(
            model=_model_name(),
            temperature=0.1,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        content = response.choices[0].message.content or "{}"
        return json.loads(content)
    except Exception:
        return {}


def llm_text(prompt: str, system: str = "You are a senior code review assistant.") -> str:
    if not os.getenv("OPENAI_API_KEY") and not os.getenv("LLM_BASE_URL"):
        return ""
    try:
        response = _client().chat.completions.create(
            model=_model_name(),
            temperature=0.2,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content or ""
    except Exception:
        return ""
