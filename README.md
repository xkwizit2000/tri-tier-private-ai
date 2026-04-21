# Tri-Tier Private AI Gateway

A self-hosted, privacy-first AI stack that routes explicitly tagged prompts to a local model and everything else to a cloud model — with zero public internet exposure.

---

## Architecture

```
You (Tailscale only)
        │
        ▼
 OpenClaw Gateway              ← Controller / Orchestrator (host)
        │                         Integrated with Telegram
        ▼
  LiteLLM Proxy :4000           ← Self-hosted router with pre-call hook
     │           │
     ▼           ▼
 Ollama        Together AI
 gemma4:e4b   Qwen-3.5-397B
 [Private]     [Cloud / ZDR]
```

| Tier | Component | Purpose | Cost |
|---|---|---|---|
| Controller | OpenClaw | Orchestration, Telegram interface, tool execution | $0 |
| Router | LiteLLM (self-hosted) | `[priv]`-prefix prompt routing via pre-call hook | $0 |
| Private Layer | Ollama + `gemma4:e4b` | Prompts the user marks with `[priv]` | $0 |
| Intelligence Layer | Together AI Qwen-3.5-397B | Everything else | Pay-per-token |
| Infrastructure | VPS (Ubuntu 22.04) | Hosts everything | ~$6–10/mo |

**Estimated total: $8–12/month** at moderate personal use.

---

## Privacy Model

The router decides per-request where a prompt goes. The control is **explicit**: prefix any prompt with `[priv]` and it is routed to the local Ollama model on the VPS. Nothing with `[priv]` on the last user turn ever touches Together AI.

```
User sends prompt via Telegram / OpenClaw
        │
        ▼
  LiteLLM pre-call hook inspects last user turn
        │
        ├── starts with "[priv]"  → Ollama (local)
        │                           prefix is stripped,
        │                           system prompt + history dropped,
        │                           tool fields removed
        │
        └── otherwise              → Together AI (ZDR enabled)
```

Design notes:

- The check runs only on the **most recent user message**, not recursively through the whole payload. This prevents prior `[priv]` turns (which OpenClaw may replay as conversation history) from forcing every subsequent prompt to the local model.
- On a private-mode request, the hook replaces OpenClaw's large tool-laden system prompt with a minimal "private, local assistant, no tools" system prompt, and forwards only the current user turn. Private mode is therefore single-turn by design — no memory, no tool access, no leakage of prior conversation content into the local model.
- OpenAI-only fields (`tools`, `tool_choice`, `functions`, `function_call`, `response_format`, `parallel_tool_calls`) are stripped before forwarding, since Ollama rejects them. `max_completion_tokens` is renamed to `max_tokens` and capped at 512.
- Together AI Zero Data Retention (account setting + `X-Together-No-Store` header) ensures prompts that do reach the cloud are not stored or used for training.

---

## Files

```
tritier/
├── docker-compose.yml      # Ollama + LiteLLM containers
├── litellm_config.yaml     # Model definitions, ZDR headers, hook registration
├── router_hook.py          # [priv]-prefix pre-call routing hook
├── entrypoint.py           # Execs the LiteLLM CLI with the mounted config
├── .env                    # API keys (never commit this)
├── openclaw.json           # OpenClaw config (Telegram, LiteLLM provider)
├── CHANGELOG.md
└── README.md               # This file
```

---

## Prerequisites

- Ubuntu 22.04 VPS with at least 4GB RAM (8GB recommended)
- Docker and Docker Compose plugin installed
- Tailscale account (free tier is sufficient)
- Together AI account with API key
- OpenClaw installed on the host
- A Telegram bot token (for the Telegram channel)

---

## Deployment

### 1. Install dependencies

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y docker.io docker-compose-plugin ufw curl
```

### 2. Install Tailscale

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Note your Tailscale IP - it will look like `100.x.x.x`. This is the only address you will use to access the stack.

### 3. Lock down the firewall

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow in on tailscale0
sudo ufw enable
sudo ufw status verbose
```

> **Important:** Run `ufw allow ssh` before enabling UFW or you will lose access to your VPS.

### 4. Install OpenClaw

```bash
curl -fsSL https://deb.nodesource.com/setup_24.x | sudo bash -
sudo apt-get install -y nodejs
sudo npm install -g openclaw@latest
openclaw --version
```

### 5. Configure environment

```bash
mkdir -p ~/tritier && cd ~/tritier
cp .env.template .env
```

Edit `.env` with **literal values** — Docker Compose parses `.env` as plain `KEY=VALUE` and does **not** evaluate shell substitutions like `$(cat .secrets/...)`:

```bash
# Generate a master key (LiteLLM requires an sk- prefix)
echo "LITELLM_MASTER_KEY=sk-$(openssl rand -hex 32)" >> .env
echo "TOGETHER_API_KEY=<your-together-key>" >> .env
```

### 6. Start the containers

```bash
docker compose up -d
docker compose ps        # Both services should show "healthy"
```

### 7. Pull the local model

```bash
docker compose exec ollama ollama pull gemma3n:e4b
```

This downloads the Gemma 3n E4B model. Allow several minutes depending on your VPS bandwidth.

### 8. Connect OpenClaw to LiteLLM

Edit `~/.openclaw/openclaw.json` to add LiteLLM as a provider and expose the routed model:

```json
{
  "models": {
    "mode": "merge",
    "providers": {
      "litellm": {
        "baseUrl": "http://localhost:4000/v1",
        "api": "openai-completions",
        "models": [
          { "id": "cloud-reasoning", "name": "Tri-Tier Router" }
        ],
        "apiKey": "litellm_master_key"
      }
    }
  },
  "auth": {
    "profiles": {
      "litellm:default": { "provider": "litellm", "mode": "api_key" }
    }
  }
}
```

> The `apiKey` field is a **secret-name reference** in OpenClaw. Store the actual value in `~/.openclaw/.secrets/litellm_master_key` (or wherever your OpenClaw install resolves secrets). It must match `LITELLM_MASTER_KEY` in `.env` byte-for-byte, including the `sk-` prefix.

To expose the router through Telegram, add the channel block:

```json
"channels": {
  "telegram": {
    "enabled": true,
    "botToken": "telegram_bot_token",
    "groups": { "*": { "requireMention": true } }
  }
}
```

Store the real token in `~/.openclaw/.secrets/telegram_bot_token`.

### 9. Enable Together AI Zero Data Retention

1. Log into [together.ai](https://together.ai)
2. Go to **Account → Privacy & Security**
3. Set **Store prompts** → No
4. Set **Train on my data** → No

> ZDR applies only from the moment you enable it. Do this before making any cloud-tier requests.

### 10. Verify routing

Non-private prompt → cloud:

```bash
curl -s http://127.0.0.1:4000/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"cloud-reasoning","messages":[{"role":"user","content":"explain transformer attention"}]}'
```

Private prompt → local Ollama:

```bash
curl -s http://127.0.0.1:4000/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"cloud-reasoning","messages":[{"role":"user","content":"[priv] what is 2+2"}]}'
```

Watch the hook's decisions in real time:

```bash
docker compose logs -f litellm 2>&1 | grep -E "PrivacyRouter|>>>"
```

You should see lines like:

```
[PrivacyRouter] HOOK CALLED call_type=acompletion
[PrivacyRouter] >>> private=True (checked last user message only)
[PrivacyRouter] *** [priv] -> local-private
[PrivacyRouter] *** local payload msgs=2 last_user_len=...
```

From Telegram, the same behavior applies: messages to the bot without a prefix go to the cloud, messages prefixed with `[priv]` go to the local model.

---

## Router Internals

The router is a LiteLLM `CustomLogger` subclass implementing `async_pre_call_hook` (chat completions) and `async_pre_call_hook_for_responses_api` (Responses API). It is registered via `litellm_settings.callbacks: router_hook.proxy_handler_instance` in `litellm_config.yaml`, which attaches it to the proxy's pre-call dispatch during initialization.

Per request, the hook:

1. Locates the most recent message with `role == "user"`.
2. Tests the message content against the case-insensitive regex `\[priv\]\s*`.
3. If it matches:
   - Strips the `[priv]` prefix.
   - Sets `data["model"] = "local-private"`.
   - Replaces `messages` with `[<minimal system>, <current user turn>]`.
   - Removes `tools`, `tool_choice`, `functions`, `function_call`, `response_format`, `parallel_tool_calls`.
   - Renames `max_completion_tokens` → `max_tokens` and defaults to 512.
4. Otherwise: sets `data["model"] = "cloud-reasoning"` and forwards unchanged.

To change the trigger, edit `PRIV_PREFIX` in `router_hook.py` and run `docker compose restart litellm`.

---

## Security Summary

| Control | Implementation |
|---|---|
| Network isolation | UFW blocks all inbound except SSH and Tailscale interface |
| Container isolation | Ollama and LiteLLM bind to `127.0.0.1` only |
| Explicit privacy routing | `[priv]` prefix forces prompt to local Ollama; no heuristic guessing |
| Private-mode scrub | Tool-laden OpenClaw system prompt + prior history dropped before local forward |
| Together AI ZDR | Account-level setting + `X-Together-No-Store` header |
| No telemetry | LiteLLM external callbacks disabled |
| No prompt caching | `cache: false` in LiteLLM config |

---

## Maintenance

View logs:
```bash
docker compose logs -f litellm    # Routing decisions
docker compose logs -f ollama     # Local model activity
```

Update containers:
```bash
docker compose pull
docker compose up -d
```

Check Ollama models:
```bash
docker compose exec ollama ollama list
```

Swap the local model (e.g., to a different Ollama tag):

1. `docker compose exec ollama ollama pull <new-tag>`
2. Edit `litellm_config.yaml` → `local-private` → `model: ollama/<new-tag>`
3. `docker compose restart litellm`

---

## Troubleshooting

**LiteLLM returns 400 on every request, `user_api_key_auth` exception in logs**
The API key OpenClaw sends does not match `LITELLM_MASTER_KEY` inside the container. Two common causes:

- `.env` uses `$(cat .secrets/...)` syntax. Docker Compose does not expand shell substitutions — replace with literal values.
- The master key is missing the `sk-` prefix. LiteLLM requires it.

Confirm what the container actually has:
```bash
docker compose exec litellm printenv LITELLM_MASTER_KEY
```

**`[priv]` prompts reach the cloud anyway**
Check the hook is firing: `docker compose logs litellm | grep "HOOK CALLED"`. If no output, the hook is not registered with the pre-call dispatcher — ensure `litellm_settings.callbacks: router_hook.proxy_handler_instance` is present in `litellm_config.yaml` and that `entrypoint.py` execs the standard `litellm` CLI (so the config is honored at startup).

**Local model returns gibberish or hallucinated answers**
Check the Ollama log for `truncating input prompt`. If the payload arriving at Ollama exceeds its context window, the prompt is chopped and the model continues mid-stream. The router already trims to a minimal payload; if you relax that, you'll reintroduce the problem.

**Ollama healthcheck failing**
First startup can take 30–60 seconds. Run `docker compose ps` again after a minute.

**Together AI requests failing**
Verify `TOGETHER_API_KEY` in `.env` is correct and the model name in `litellm_config.yaml` matches a currently available Together model ID.

**Can't access OpenClaw UI**
Confirm Tailscale is running on both your VPS and your local machine. Access via `http://<tailscale-ip>:<port>`.

---

## Cost Reference

| Component | Rate |
|---|---|
| Together AI cloud model input | ~$0.90 / 1M tokens |
| Together AI cloud model output | ~$0.90 / 1M tokens |
| Ollama / LiteLLM / OpenClaw | $0 |
| Hetzner CX21 VPS (8GB RAM) | ~$10/mo |

At ~500K tokens/month cloud usage, total cost lands around **$10–12/month**.

---

## License

MIT. Use freely, harden for your own threat model.
