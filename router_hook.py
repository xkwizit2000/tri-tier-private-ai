import hashlib
import json
import logging
import os
import re
import time

import httpx

from litellm.integrations.custom_logger import CustomLogger

print("[PrivacyRouter] MODULE LOADED", flush=True)
logger = logging.getLogger(__name__)

PRIV_PREFIX = re.compile(r"\[priv\]\s*", re.IGNORECASE)

STRIP_FOR_OLLAMA = (
    "tools", "tool_choice", "functions", "function_call",
    "response_format", "parallel_tool_calls",
)

MODEL_PRIVATE = "local-private"
MODEL_MIDDLE = "cloud-middle"
MODEL_HEAVY = "cloud-heavy"

CLASSIFIER_OLLAMA_URL = os.environ.get("CLASSIFIER_OLLAMA_URL", "http://ollama:11434")
CLASSIFIER_OLLAMA_MODEL = os.environ.get("CLASSIFIER_OLLAMA_MODEL", "gemma3n:e4b")
CLASSIFIER_TIMEOUT_S = float(os.environ.get("CLASSIFIER_TIMEOUT_S", "8"))
CLASSIFIER_CACHE_TTL_S = 300

COMPLEX_HINTS = (
    "step by step", "step-by-step", "prove", "derive", "explain why",
    "refactor", "design", "architecture", "plan", "debug", "trace",
    "analyze", "compare and contrast", "pros and cons", "optimize",
)

SIMPLE_PATTERNS = (
    re.compile(r"^\s*(hi|hello|hey|yo|thanks|thank you|ok|okay|cool|nice|got it|cheers|bye)[.!?\s]*$", re.IGNORECASE),
    re.compile(r"^\s*what('?s| is) \d+\s*[\+\-\*/xX]\s*\d+\s*\??\s*$", re.IGNORECASE),
    re.compile(r"^\s*(what|who|when|where)\s+(is|was|are|were)\s+[\w\s'?-]{1,40}\??\s*$", re.IGNORECASE),
)

_classification_cache = {}


def _cache_get(key):
    entry = _classification_cache.get(key)
    if entry is None:
        return None
    decision, expiry = entry
    if time.monotonic() > expiry:
        _classification_cache.pop(key, None)
        return None
    return decision


def _cache_set(key, decision):
    _classification_cache[key] = (decision, time.monotonic() + CLASSIFIER_CACHE_TTL_S)


def _extract_user_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict) and p.get("type") in ("text", "input_text"):
                parts.append(p.get("text", ""))
        return "\n".join(parts)
    return ""


def _heuristic_decision(text):
    stripped = text.strip()
    low = stripped.lower()

    if len(stripped) > 500:
        return "complex", "len>500"
    if "```" in stripped:
        return "complex", "code_fence"
    if stripped.count("?") >= 3:
        return "complex", "multi_question"
    for hint in COMPLEX_HINTS:
        if hint in low:
            return "complex", f"hint:{hint}"

    if len(stripped) < 40:
        for pat in SIMPLE_PATTERNS:
            if pat.match(stripped):
                return "simple", f"pattern:{pat.pattern[:30]}"
        return "simple", "len<40"

    return None, None


async def _classify_with_local(text):
    prompt = (
        "You are a routing classifier. Reply with exactly ONE word: SIMPLE or COMPLEX.\n"
        "SIMPLE: greetings, short factual questions, basic arithmetic, acknowledgments, "
        "anything a small model can answer well in under 100 words.\n"
        "COMPLEX: multi-step reasoning, code generation, long analysis, creative writing, "
        "research-style questions, architecture/design questions.\n\n"
        f"Question: {text[:1200]}\n\nAnswer:"
    )
    body = {
        "model": CLASSIFIER_OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 4},
    }
    try:
        async with httpx.AsyncClient(timeout=CLASSIFIER_TIMEOUT_S) as client:
            r = await client.post(f"{CLASSIFIER_OLLAMA_URL}/api/generate", json=body)
            r.raise_for_status()
            out = (r.json().get("response") or "").strip().upper()
            if "COMPLEX" in out:
                return "complex"
            if "SIMPLE" in out:
                return "simple"
            print(f"[PrivacyRouter] classifier unparseable response: {out!r}", flush=True)
            return "complex"
    except Exception as e:
        print(f"[PrivacyRouter] classifier error: {e!r} -> defaulting to middle", flush=True)
        return "simple"


async def _decide_non_private_tier(text):
    key = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
    cached = _cache_get(key)
    if cached is not None:
        return cached, "cache"

    heur, reason = _heuristic_decision(text)
    if heur is not None:
        _cache_set(key, heur)
        return heur, f"heuristic:{reason}"

    decision = await _classify_with_local(text)
    _cache_set(key, decision)
    return decision, "classifier"

def _strip_envelope(text):
    """Strip OpenClaw/Telegram metadata envelope to get actual user message."""
    if not isinstance(text, str):
        return text
    
    # If no envelope markers, return as-is
    if "Conversation info (untrusted metadata)" not in text:
        return text
    
    # Try to extract the actual message content
    # Look for the last clean line that's not metadata
    lines = text.split("\n")
    for line in reversed(lines):
        stripped = line.strip()
        if stripped and len(stripped) < 200:
            # Skip metadata lines
            if stripped.startswith(("```", "{", "[", "Conversation", "Sender", "label", "---")):
                continue
            # Skip JSON-like lines
            if ":" in stripped and stripped.count('"') > 2:
                continue
            return stripped
    
    # Fallback: return original if we couldn't find clean text
    return text


async def _route(data):
    print(f"[PrivacyRouter] >>> ROUTE keys={list(data.keys())} model_in={data.get('model')!r}", flush=True)

    msgs = data.get("messages") or []
    last_user_idx = next(
        (i for i in range(len(msgs) - 1, -1, -1)
         if isinstance(msgs[i], dict) and msgs[i].get("role") == "user"),
        None,
    )

    user_text = ""
    is_private = False
    if last_user_idx is not None:
        content = msgs[last_user_idx].get("content", "")
        user_text = _extract_user_text(content)
        is_private = bool(PRIV_PREFIX.search(user_text))

    if is_private:
        if isinstance(msgs[last_user_idx].get("content"), str):
            msgs[last_user_idx]["content"] = PRIV_PREFIX.sub(
                "", msgs[last_user_idx]["content"], count=1,
            )
        elif isinstance(msgs[last_user_idx].get("content"), list):
            for part in msgs[last_user_idx]["content"]:
                if isinstance(part, dict) and part.get("type") in ("text", "input_text"):
                    part["text"] = PRIV_PREFIX.sub("", part.get("text", ""), count=1)
                    break

        data["model"] = MODEL_PRIVATE
        for k in STRIP_FOR_OLLAMA:
            data.pop(k, None)

        last_user = msgs[last_user_idx]
        data["messages"] = [
            {
                "role": "system",
                "content": "You are a private, local assistant. Answer the user concisely. You have no tools and no prior conversation context.",
            },
            last_user,
        ]
        data.pop("max_completion_tokens", None)
        data.setdefault("max_tokens", 512)
        print(f"[PrivacyRouter] *** [priv] -> {MODEL_PRIVATE}", flush=True)
        return data

    if not user_text.strip():
        data["model"] = MODEL_MIDDLE
        print(f"[PrivacyRouter] empty user text -> {MODEL_MIDDLE}", flush=True)
        return data

    # Strip Envelope prior to routing decision
    clean_text = _strip_envelope(user_text)

    decision, reason = await _decide_non_private_tier(clean_text)
    target = MODEL_HEAVY if decision == "complex" else MODEL_MIDDLE
    data["model"] = target
    print(f"[PrivacyRouter] non-priv decision={decision} ({reason}) -> {target}", flush=True)
    return data


class PrivacyRouter(CustomLogger):

    def __init__(self):
        super().__init__()
        print("[PrivacyRouter] INSTANCE CREATED", flush=True)

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        print(f"[PrivacyRouter] HOOK CALLED call_type={call_type}", flush=True)
        return await _route(data)

    async def async_pre_call_hook_for_responses_api(self, user_api_key_dict, cache, data, call_type):
        print(f"[PrivacyRouter] RESPONSES HOOK CALLED call_type={call_type}", flush=True)
        return await _route(data)


proxy_handler_instance = PrivacyRouter()
print(f"[PrivacyRouter] INSTANCE READY: {proxy_handler_instance}", flush=True)
