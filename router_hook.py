import json
import logging
import re
from litellm.integrations.custom_logger import CustomLogger

print("[PrivacyRouter] MODULE LOADED", flush=True)
logger = logging.getLogger(__name__)

PRIV_PREFIX = re.compile(r"\[priv\]\s*", re.IGNORECASE)

STRIP_FOR_OLLAMA = (
    "tools", "tool_choice", "functions", "function_call",
    "response_format", "parallel_tool_calls",
)


def _safe_dump(obj, limit=4000):
    try:
        s = json.dumps(obj, default=str)
    except Exception as e:
        s = f"<unjsonable: {e}>"
    return s if len(s) <= limit else s[:limit] + f"...(+{len(s) - limit} chars)"


def _walk_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_strings(v)


def _strip_prefix_in_place(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and PRIV_PREFIX.search(v):
                obj[k] = PRIV_PREFIX.sub("", v, count=1)
            else:
                _strip_prefix_in_place(v)
    elif isinstance(obj, list):
        for v in obj:
            _strip_prefix_in_place(v)


def _route(data):
    print(f"[PrivacyRouter] >>> ROUTE keys={list(data.keys())} model_in={data.get('model')!r}", flush=True)

    msgs = data.get("messages") or []
    last_user_idx = next(
        (i for i in range(len(msgs) - 1, -1, -1)
         if isinstance(msgs[i], dict) and msgs[i].get("role") == "user"),
        None,
    )

    is_private = False
    if last_user_idx is not None:
        content = msgs[last_user_idx].get("content", "")
        if isinstance(content, str):
            is_private = bool(PRIV_PREFIX.search(content))
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") in ("text", "input_text"):
                    if PRIV_PREFIX.search(part.get("text", "")):
                        is_private = True
                        break

    print(f"[PrivacyRouter] >>> private={is_private} (checked last user message only)", flush=True)

    if is_private:
        print("[PrivacyRouter] *** [priv] -> local-private", flush=True)
        _strip_prefix_in_place(msgs[last_user_idx])
        data["model"] = "local-private"
        for k in STRIP_FOR_OLLAMA:
            data.pop(k, None)

        msgs = data.get("messages", [])
        last_user = next(
            (m for m in reversed(msgs)
             if isinstance(m, dict) and m.get("role") == "user"),
            None,
        )
        data["messages"] = [
            {
                "role": "system",
                "content": "You are a private, local assistant. Answer the user concisely. You have no tools and no prior conversation context.",
            },
        ]
        if last_user is not None:
            data["messages"].append(last_user)

        data.pop("max_completion_tokens", None)
        data.setdefault("max_tokens", 512)
        print(f"[PrivacyRouter] *** local payload msgs={len(data['messages'])} "
              f"last_user_len={len(str(last_user.get('content', ''))) if last_user else 0}",
              flush=True)
    else:
        print("[PrivacyRouter] no [priv] in payload -> cloud-reasoning", flush=True)
        data["model"] = "cloud-reasoning"

    return data


class PrivacyRouter(CustomLogger):

    def __init__(self):
        super().__init__()
        print("[PrivacyRouter] INSTANCE CREATED", flush=True)

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        print(f"[PrivacyRouter] HOOK CALLED call_type={call_type}", flush=True)
        return _route(data)

    async def async_pre_call_hook_for_responses_api(self, user_api_key_dict, cache, data, call_type):
        print(f"[PrivacyRouter] RESPONSES HOOK CALLED call_type={call_type}", flush=True)
        return _route(data)


proxy_handler_instance = PrivacyRouter()
print(f"[PrivacyRouter] INSTANCE READY: {proxy_handler_instance}", flush=True)
