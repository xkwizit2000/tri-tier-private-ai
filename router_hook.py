import json
import logging
import re
import urllib.request
import time
from litellm.integrations.custom_logger import CustomLogger

# Import utility functions
from utils.privacy import extract_user_message_text

# Simple in-memory cache for classification results
CLASSIFICATION_CACHE = {}
CACHE_MAX_SIZE = 100
CACHE_TTL_SECONDS = 300  # 5 minutes

# Import local memory module for [priv] conversation storage
try:
    from local_memory import store_message, load_context
    LOCAL_MEMORY_ENABLED = True
    print("[PrivacyRouter] Local memory module loaded", flush=True)
except ImportError as e:
    LOCAL_MEMORY_ENABLED = False
    print(f"[PrivacyRouter] Local memory module not available: {e}", flush=True)

print("[PrivacyRouter] MODULE LOADED", flush=True)
logger = logging.getLogger(__name__)

# Ollama endpoint for classification
OLLAMA_CLASSIFIER_URL = "http://ollama:11434/api/generate"
CLASSIFIER_MODEL = "gemma4:e2b"  # Lighter 2B model for faster classification

PRIV_PREFIX = re.compile(r"^\s*\[priv\]\s*", re.IGNORECASE)

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
def extract_chat_id(data):
    """Extract chat ID from request metadata."""
    try:
        return data.get("metadata", {}).get("chat_id", "unknown")
    except Exception:
        return "unknown"


CLASSIFICATION_PROMPT = """You are a query complexity classifier. Analyze the user's message and classify it as either "simple" or "complex".

**Simple queries:**
- Single factual question
- Basic greeting or acknowledgment
- Simple preference or preference check
- Short, straightforward requests
- Casual conversation

**Complex queries:**
- Multiple questions in one message
- Requires analysis, comparison, or synthesis
- Technical domains (code, math, research, architecture)
- Detailed explanations or step-by-step reasoning
- Creative work (stories, plans, designs)
- Ambiguous or nuanced topics requiring judgment

Respond with exactly one word: "simple" or "complex".

User message: {message}
"""


def classify_complexity(message_content) -> str:
    """
    Classify message complexity using Ollama.
    Returns "simple" or "complex".
    Falls back to "simple" if classification fails.
    """
    # FIRST: Extract the actual user message text (strip OpenClaw metadata wrapper)
    user_text = extract_user_message_text(message_content)
    print(f"[PrivacyRouter] classify_complexity: Extracted user text: '{user_text[:50]}...' (len={len(user_text)})", flush=True)
    message_str = user_text
    
    # Skip classification for very short messages (likely greetings/simple acks)
    if len(message_str.strip()) < 10:
        print(f"[PrivacyRouter] Skipping classification for short message: '{message_str[:20]}...'", flush=True)
        return "simple"
    
    # Check cache first
    message_key = message_str.strip()[:100]  # Use first 100 chars as cache key
    current_time = time.time()
    
    # Clean up expired cache entries
    expired_keys = [k for k, v in CLASSIFICATION_CACHE.items() if current_time - v['timestamp'] > CACHE_TTL_SECONDS]
    for key in expired_keys:
        del CLASSIFICATION_CACHE[key]
    
    # Return cached result if available
    if message_key in CLASSIFICATION_CACHE:
        cached_result = CLASSIFICATION_CACHE[message_key]
        print(f"[PrivacyRouter] Using cached classification: {cached_result['result']} for '{message_key[:20]}...'", flush=True)
        return cached_result['result']
    
    try:
        # Prepare the classification prompt
        prompt = CLASSIFICATION_PROMPT.format(message=message_str[:500])  # Truncate long messages
        
        # Call Ollama API
        request_data = {
            "model": CLASSIFIER_MODEL,
            "prompt": prompt,
            "stream": False
        }
        
        req = urllib.request.Request(
            OLLAMA_CLASSIFIER_URL,
            data=json.dumps(request_data).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                # Ollama returns 'response' field with the generated text
                raw_response = result.get("response", "")
                
                # DEBUG: Log the raw Ollama response
                print(f"[PrivacyRouter] Ollama raw response: '{raw_response}'", flush=True)
                
                if not raw_response:
                    print(f"[PrivacyRouter] Ollama returned empty response, fallback to simple", flush=True)
                    result = "simple"
                else:
                    classification = raw_response.strip().lower()
                    # Extract just "simple" or "complex" from response
                    if "complex" in classification:
                        result = "complex"
                        print(f"[PrivacyRouter] Classification result: complex", flush=True)
                    else:
                        result = "simple"
                        print(f"[PrivacyRouter] Classification result: simple", flush=True)
            
            # Cache the result (success path)
            if len(CLASSIFICATION_CACHE) >= CACHE_MAX_SIZE:
                # Remove oldest entry if cache is full
                oldest_key = min(CLASSIFICATION_CACHE.keys(), key=lambda k: CLASSIFICATION_CACHE[k]['timestamp'])
                del CLASSIFICATION_CACHE[oldest_key]
            
            CLASSIFICATION_CACHE[message_key] = {
                'result': result,
                'timestamp': current_time
            }
            
            return result
            
        except Exception as e:
            print(f"[PrivacyRouter] Classification request failed: {e}, fallback to simple", flush=True)
            result = "simple"
            
            # Cache the result (error path)
            if len(CLASSIFICATION_CACHE) >= CACHE_MAX_SIZE:
                # Remove oldest entry if cache is full
                oldest_key = min(CLASSIFICATION_CACHE.keys(), key=lambda k: CLASSIFICATION_CACHE[k]['timestamp'])
                del CLASSIFICATION_CACHE[oldest_key]
            
            CLASSIFICATION_CACHE[message_key] = {
                'result': result,
                'timestamp': current_time
            }
            
            return result
    
    except Exception as e:
        print(f"[PrivacyRouter] Classification failed: {e} -> fallback to simple", flush=True)
        return "simple"  # Fallback to simple if classification fails    msgs = data.get("messages") or []
    last_user_idx = next(
        (i for i in range(len(msgs) - 1, -1, -1)
         if isinstance(msgs[i], dict) and msgs[i].get("role") == "user"),
        None,
    )

    is_private = False
    if last_user_idx is not None:
        content = msgs[last_user_idx].get("content", "")
        print(f"[PrivacyRouter] >>> DEBUG: Raw content type: {type(content)}", flush=True)
        
        # Extract the actual user message text (may include OpenClaw metadata wrapper)
        user_text = extract_user_message_text(content)
        print(f"[PrivacyRouter] >>> DEBUG: Extracted user text: '{user_text[:100]}...'", flush=True)
        
        if isinstance(content, str):
            # Check the extracted user text for [priv] prefix
            is_private = bool(PRIV_PREFIX.search(user_text))
            match = PRIV_PREFIX.search(user_text)
            if match:
                print(f"[PrivacyRouter] >>> FOUND [priv] match in user text: '{match.group()}'", flush=True)
            print(f"[PrivacyRouter] >>> Checking user text for [priv]: {user_text[:100]}... match={is_private}", flush=True)
        elif isinstance(content, list):
            print(f"[PrivacyRouter] >>> DEBUG: Content is list, checking extracted user text...", flush=True)
            # Check the extracted user text for [priv] prefix
            is_private = bool(PRIV_PREFIX.search(user_text))
            match = PRIV_PREFIX.search(user_text)
            if match:
                print(f"[PrivacyRouter] >>> FOUND [priv] match in user text: '{match.group()}'", flush=True)
            print(f"[PrivacyRouter] >>> Checking user text for [priv]: {user_text[:100]}... match={is_private}", flush=True)
        else:
            print(f"[PrivacyRouter] >>> DEBUG: Unexpected content type: {type(content)}", flush=True)
    else:
        print(f"[PrivacyRouter] >>> DEBUG: No last user message found", flush=True)

    print(f"[PrivacyRouter] >>> private={is_private} (checked extracted user text)", flush=True)

    if is_private:
        print("[PrivacyRouter] *** [priv] -> local-private", flush=True)
        
        # Extract chat ID for memory storage
        chat_id = extract_chat_id(data)
        
        # Get the user's message content (before stripping [priv])
        user_content = msgs[last_user_idx].get("content", "")
        
        # Store this message in local memory
        if LOCAL_MEMORY_ENABLED:
            try:
                store_message(chat_id, "user", user_content)
                print(f"[PrivacyRouter] Stored user message in local memory: {chat_id}", flush=True)
            except Exception as e:
                print(f"[PrivacyRouter] Failed to store message: {e}", flush=True)
        
        # Strip [priv] prefix from the message
        _strip_prefix_in_place(msgs[last_user_idx])
        
        # Load prior context from local memory
        prior_context = ""
        if LOCAL_MEMORY_ENABLED:
            try:
                prior_context = load_context(chat_id, limit=10)
                if prior_context:
                    context_lines = len(prior_context.split('\n'))
                    print(f"[PrivacyRouter] Loaded {context_lines} prior messages from local memory", flush=True)
            except Exception as e:
                print(f"[PrivacyRouter] Failed to load context: {e}", flush=True)
        
        data["model"] = "local-private"
        for k in STRIP_FOR_OLLAMA:
            data.pop(k, None)

        msgs = data.get("messages", [])
        last_user = next(
            (m for m in reversed(msgs)
             if isinstance(m, dict) and m.get("role") == "user"),
            None,
        )
        
        # Build system prompt with context injection
        if prior_context:
            system_content = (f"You are a private, local assistant. Answer the user concisely. "
                              f"You have no tools. You have access to prior conversation history below:\n\n"
                              f"{prior_context}\n\n")
        else:
            system_content = "You are a private, local assistant. Answer the user concisely. You have no tools and no prior conversation context."
        
        data["messages"] = [
            {
                "role": "system",
                "content": system_content,
            },
        ]
        if last_user is not None:
            data["messages"].append(last_user)

        data.pop("max_completion_tokens", None)
        data.setdefault("max_tokens", 512)
        context_lines = len(prior_context.split('\n')) if prior_context else 0
        last_user_len = len(str(last_user.get('content', ''))) if last_user else 0
        print(f"[PrivacyRouter] *** local payload msgs={len(data['messages'])} "
              f"last_user_len={last_user_len} "
              f"context_lines={context_lines}",
              flush=True)
    else:
        # Non-[priv] message: classify complexity and route accordingly
        chat_id = extract_chat_id(data)
        user_content = msgs[last_user_idx].get("content", "") if last_user_idx is not None else ""
        
        # Classify the message
        complexity = classify_complexity(user_content)
        
        # Log classification decision
        print(f"[PrivacyRouter] >>> Classification: {complexity} (chat_id={chat_id})", flush=True)
        
        # Route based on complexity
        if complexity == "complex":
            print("[PrivacyRouter] >>> Complex query -> cloud-complex (Qwen 480B)", flush=True)
            data["model"] = "cloud-complex"
        else:
            print("[PrivacyRouter] >>> Simple query -> cloud-simple (Qwen 3.5 397B)", flush=True)
            data["model"] = "cloud-simple"

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


# Hook to store assistant responses in local memory
async def store_assistant_response(chat_id: str, content: str):
    """Store assistant response in local memory after successful generation."""
    if LOCAL_MEMORY_ENABLED:
        try:
            store_message(chat_id, "assistant", content)
            print(f"[PrivacyRouter] Stored assistant response in local memory: {chat_id}", flush=True)
        except Exception as e:
            print(f"[PrivacyRouter] Failed to store assistant response: {e}", flush=True)

proxy_handler_instance = PrivacyRouter()
print(f"[PrivacyRouter] INSTANCE READY: {proxy_handler_instance}", flush=True)
