"""Gemma via Ollama: Ollama cloud (OLLAMA_HOST + OLLAMA_API_KEY), signed-in local Ollama (jaise
gemma4:cloud model), ya koi local model. Gemma sirf translate aur explain karta hai; data kabhi compute nahi karta."""
import json
import os

import ollama

from . import config  # noqa: F401  (settings padhne se pehle .env load karta hai)
from . import trace
from .logs import get_logger

log = get_logger()


class LLMError(RuntimeError):
    """Model tak pahunch nahi paaye ya kuch kaam ka nahi mila. Message users ko dikhana safe hai."""


def model_name() -> str:
    return os.getenv("GEMMA_MODEL", "gemma4:31b")


def client() -> ollama.Client:
    key = os.getenv("OLLAMA_API_KEY")
    headers = {"Authorization": f"Bearer {key}"} if key else None
    hooks = trace.httpx_hooks("ollama")  # DM_TRACE on na ho toh {}
    return ollama.Client(host=os.getenv("OLLAMA_HOST") or None, headers=headers, **({"event_hooks": hooks} if hooks else {}))


def _chat(system: str, user: str, max_tokens: int, **kwargs) -> str:
    try:
        host = os.getenv("OLLAMA_HOST") or "local Ollama"
        with trace.span("GEMMA", f"{model_name()} via {host} | system prompt {len(system)} chars, user message {len(user)} chars, "
                                 f"max_tokens={max_tokens}{', json mode' if kwargs.get('format') else ''}") as info:
            r = client().chat(
                model=model_name(),
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                options={"temperature": 0, "num_predict": max_tokens},
                **kwargs,
            )
            content = r["message"]["content"]
            info.update(response_chars=len(content or ""), prompt_tokens=getattr(r, "prompt_eval_count", None),
                        output_tokens=getattr(r, "eval_count", None))
    except Exception as e:  # network, auth, model-not-found: LLMError ke roop me dobara raise hota hai, asli wajah saath me
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
    """Models JSON ko code fences me wrap kar dete hain ya upar se text jod dete hain; sabse bahar wala {...} object lo."""
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            obj = json.loads(text[start:end + 1])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    return {"action": "unsupported", "message": "The model returned an unreadable response."}
