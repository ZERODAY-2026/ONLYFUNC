"""Gemma via Ollama: Ollama cloud (OLLAMA_HOST + OLLAMA_API_KEY), a signed-in local Ollama (model such as
gemma4:cloud), or a local model. Gemma only translates and explains; it never computes the data."""
import json
import os

import ollama

from . import config  # noqa: F401  (loads .env before settings are read)
from .logs import get_logger

log = get_logger()


class LLMError(RuntimeError):
    """The model could not be reached or returned nothing usable. The message is safe to show to users."""


def model_name() -> str:
    return os.getenv("GEMMA_MODEL", "gemma4:31b")


def client() -> ollama.Client:
    key = os.getenv("OLLAMA_API_KEY")
    headers = {"Authorization": f"Bearer {key}"} if key else None
    return ollama.Client(host=os.getenv("OLLAMA_HOST") or None, headers=headers)


def _chat(system: str, user: str, max_tokens: int, **kwargs) -> str:
    try:
        r = client().chat(
            model=model_name(),
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            options={"temperature": 0, "num_predict": max_tokens},
            **kwargs,
        )
        content = r["message"]["content"]
    except Exception as e:  # network, auth, model-not-found: re-raised as LLMError with the cause attached
        log.exception("Gemma call failed (model %s)", model_name())
        if getattr(e, "status_code", None) == 401:
            raise LLMError("Gemma rejected the credentials. Check OLLAMA_API_KEY, or run `ollama signin`.") from e
        raise LLMError(f"Gemma is unavailable ({type(e).__name__}): {str(e).splitlines()[0] if str(e) else 'no details'}") from e
    if not isinstance(content, str) or not content.strip():
        raise LLMError("Gemma returned an empty response.")
    return content.strip()


def chat_json(system: str, user: str) -> dict:
    return parse_json(_chat(system, user, 700, format="json"))


def chat_text(system: str, user: str) -> str:
    return _chat(system, user, 400)


def parse_json(text: str) -> dict:
    """Models may wrap JSON in code fences or add prose; take the outermost {...} object."""
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            obj = json.loads(text[start:end + 1])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    return {"action": "unsupported", "message": "The model returned an unreadable response."}
