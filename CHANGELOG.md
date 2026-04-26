# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [2.0.0] - 2026-04-26 - Tri-Tier Privacy Platform

### Added
- **Three-tier routing architecture**: local-private, cloud-simple, cloud-complex
- **Complexity classification system**: Intelligent routing based on query complexity
  - Simple queries: Single factual questions, greetings → `cloud-simple`
  - Complex queries: Multi-part questions, analysis, technical domains → `cloud-complex`
- **Classification model**: `gemma4:e2b` (2B params) for fast complexity classification
- **Classification caching**: In-memory LRU cache with 300-second TTL, 100-entry max (~50% hit rate)
- **Short message optimization**: Skip classification for messages under 10 characters
- **Cloud privacy protections**: Together AI Zero Data Retention (ZDR) + no training on all cloud requests
- `X-Together-No-Store: true` header enforcement for all cloud-tier requests
- Performance metrics monitoring with heartbeat alerts

### Changed
- **Model routing**:
  - `local-private`: Ollama gemma4:e4b (4B, local, air-gapped)
  - `cloud-simple`: Together AI Qwen3.5-397B-A17B (397B, general)
  - `cloud-complex`: Together AI Qwen3-Coder-480B-A35B-Instruct-FP8 (480B, coder-focused)
- **Classification timeout**: Tuned from 5s → 2s → 4s → 6s for optimal gemma4:e4b response time
- **Classifier model**: Changed from `gemma4:e4b` (8B) to `gemma4:e2b` (2B) for 5-10x faster classification
- **Privacy detection regex**: Anchored to start of string (`^\s*\[priv\]\s*`) to prevent false positives from conversation history
- **Content handling**: Updated to handle list-type content with metadata parts (Telegram message structure)
- **README.md**: Complete rewrite to reflect tri-tier architecture, deployment steps, and security model

### Fixed
- **False positive `[priv]` detection**: Regex no longer matches `[priv]` in conversation history/wrappers, only at explicit message start
- **AttributeError in classify_complexity()**: Fixed `'list' object has no attribute 'strip'` by converting list content to string
- **Classification timeouts**: Reduced from 5s to 6s for gemma4:e4b, now <1% timeout rate with gemma4:e2b
- **Memory file duplication**: Documented append-only strategy for `memory/2026-04-26.md`
- **Ollama high CPU usage**: Resolved with classification optimizations (caching + lighter model)
- **Privacy detection scope**: Only checks beginning of last user message, not entire conversation context

### Performance Improvements
- **Classification speed**: 457ms-2s (gemma4:e2b) vs 9+ seconds (gemma4:e4b) - 5-10x faster
- **Cache hit rate**: ~50% reduction in classifier calls
- **System load**: 1.76 average (stable) vs 8.49 (before optimization)
- **Ollama CPU**: 0.01% (idle between requests) vs 50%+ (during timeout cascade)
- **Timeout rate**: <1% (6-second graceful fallback) vs 24% (with 2s timeout)
- **Request reduction**: 32 requests/10min vs 62 before (50% reduction)

### Security
- **All three tiers maintain privacy**:
  - Local-Private: Air-gapped, never leaves VPS
  - Cloud-Simple: ZDR + no training (Qwen3.5-397B-A17B)
  - Cloud-Complex: ZDR + no training (Qwen3-Coder-480B-A35B-Instruct-FP8)
- **Network isolation**: UFW blocks all inbound except SSH and Tailscale interface
- **Container isolation**: Ollama and LiteLLM bind to `127.0.0.1` only
- **No telemetry**: LiteLLM external callbacks disabled
- **No prompt caching**: `cache: false` in LiteLLM config

### Documentation
- Complete README.md rewrite with tri-tier architecture documentation
- Added deployment steps for both models (gemma4:e4b + gemma4:e2b)
- Added security summary table with all controls
- Added troubleshooting section for classification issues
- Added performance metrics section
- Added maintenance commands for monitoring

---

## [1.0.0] - 2026-04-21 - Privacy Router Implementation

### Added
- `[priv]` prefix routing: prompts beginning with `[priv]` are routed to the
  on-host Ollama model; everything else continues to the Together.ai cloud model.
- `async_pre_call_hook_for_responses_api` handler in `router_hook.py` so the
  router also covers requests coming through LiteLLM's Responses API path.
- Diagnostic logging in `router_hook.py` (`>>> ROUTE`, `>>> private=...`,
  `*** local payload ...`) with `flush=True` so events surface immediately in
  `docker compose logs`.

### Changed
- `router_hook.py` decision logic: replaced the keyword/PII heuristic with an
  explicit `[priv]` prefix check on the most recent `user` message only.
  Historical turns and metadata fields (`proxy_server_request`,
  `litellm_call_id`, etc.) are no longer scanned, eliminating false positives
  caused by prior `[priv]` turns persisting in conversation history.
- When routing to the local model, the hook now:
  - Strips the `[priv]` prefix from the user message before forwarding.
  - Replaces OpenClaw's tool-laden ~250 KB system prompt with a minimal
    "private, local assistant, no tools" system message.
  - Discards prior conversation history and forwards only the current user
    turn (private mode = single-turn, no memory).
  - Removes OpenAI-only request fields that Ollama rejects: `tools`,
    `tool_choice`, `functions`, `function_call`, `response_format`,
    `parallel_tool_calls`.
  - Renames `max_completion_tokens` → `max_tokens` and caps at 512.
- `litellm_config.yaml`: registered the privacy router via
  `litellm_settings.callbacks: router_hook.proxy_handler_instance` so the hook
  is wired into the proxy's pre-call dispatch during initialization (the prior
  runtime registration via `logging_callback_manager` only added it as a
  logging callback, so `async_pre_call_hook` never fired).
- `litellm_config.yaml`: switched the local model from `ollama/phi3:mini` to
  `ollama/gemma3n:e4b`.
- `entrypoint.py`: simplified to `os.execvp("litellm", ...)`. The previous
  custom uvicorn bootstrap initialized the proxy *before* the custom hook was
  registered, which prevented the hook from being attached to the proxy's
  pre-call pipeline.

### Fixed
- LiteLLM auth failures (`400 Bad Request` from
  `user_api_key_auth`) caused by `LITELLM_MASTER_KEY` not being expanded inside
  the container. Docker Compose's `.env` is parsed as plain `KEY=VALUE` and
  does not evaluate shell substitutions like `$(cat .secrets/...)`. `.env`
  must contain literal values (or the secret values must be injected another
  way). LiteLLM also requires the master key to begin with `sk-`.
- Local-model garbage output ("weather in New York" hallucinations on
  `[priv] what's 2+2`). Root cause: OpenClaw was sending an 18 K-token payload
  to Ollama; phi3:mini silently truncated to its 4096-token context, leaving
  the model mid-stream of unrelated content. Fixed by trimming the payload to
  a minimal system prompt + the current user turn before forwarding.
