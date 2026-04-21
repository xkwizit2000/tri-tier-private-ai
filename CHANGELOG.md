# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased] - 2026-04-21

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
