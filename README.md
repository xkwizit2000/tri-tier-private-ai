# Tri-Tier Private AI Gateway

A self-hosted, privacy-first AI stack that routes sensitive prompts to a local model and complex reasoning to the cloud - with zero public internet exposure.

---

## Architecture

```
You (Tailscale only)
        │
        ▼
 OpenClaw Gateway          ← Controller / Orchestrator (host)
        │
        ▼
  LiteLLM Proxy :4000      ← $0 open-source router
     │           │
     ▼           ▼
 Ollama        Together AI
 Llama 3.1 8B  Qwen-2.5-72B
 [Private]     [Cloud / ZDR]
```

| Tier | Component | Purpose | Cost |
|---|---|---|---|
| Controller | OpenClaw | Orchestration, agent routing, UI | $0 |
| Router | LiteLLM (self-hosted) | Keyword-based model routing | $0 |
| Private Layer | Ollama + Llama 3.1 8B | Sensitive / PII / financial prompts | $0 |
| Intelligence Layer | Together AI Qwen-2.5-72B | Reasoning, large context, non-sensitive | Pay-per-token |
| Infrastructure | VPS (Ubuntu 22.04) | Hosts everything | ~$6–10/mo |

**Estimated total: $8–12/month** at moderate personal use.

---

## Privacy Model

Sensitive data never reaches Together AI. The keyword router intercepts prompts before they leave your VPS.

```
Prompt contains "tax", "file", "ssn", etc.
        │
        ├── YES → Ollama (local, air-gapped)
        │
        └── NO  → Together AI (ZDR enabled at account level)
```

Together AI Zero Data Retention ensures prompts that do reach the cloud are not stored or used for training.

---

## Files

```
tritier/
├── docker-compose.yml      # Ollama + LiteLLM containers
├── litellm_config.yaml     # Model routing and ZDR headers
├── router_hook.py          # Keyword interception logic
├── .env                    # API keys (never commit this)
└── README.md               # This file
```

---

## Prerequisites

- Ubuntu 22.04 VPS with at least 4GB RAM (8GB recommended)
- Docker and Docker Compose plugin installed
- Tailscale account (free tier is sufficient)
- Together AI account with API key
- OpenClaw installed on the host

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
curl -fsSL https://raw.githubusercontent.com/openclaw/openclaw/main/install.sh | bash
openclaw doctor
```

### 5. Configure environment

```bash
mkdir -p ~/tritier && cd ~/tritier
cp .env.template .env
```

Edit `.env` and fill in your keys:

```bash
# Generate a secure LiteLLM master key
openssl rand -hex 32

# Paste output as LITELLM_MASTER_KEY
# Paste your Together AI key as TOGETHER_API_KEY
```

### 6. Start the containers

```bash
docker compose up -d
docker compose ps        # Both services should show "healthy"
```

### 7. Pull the local model

```bash
docker exec -it ollama ollama pull llama3.1:8b
```

This downloads approximately 4.7GB. Allow 5–10 minutes depending on your VPS bandwidth.

### 8. Connect OpenClaw to LiteLLM

Edit `~/.openclaw/openclaw.json`:

```json
{
  "providers": {
    "openai": {
      "apiKey": "YOUR_LITELLM_MASTER_KEY",
      "apiBase": "http://127.0.0.1:4000"
    }
  }
}
```

### 9. Enable Together AI Zero Data Retention

1. Log into [together.ai](https://together.ai)
2. Go to **Account → Privacy & Security**
3. Set **Store prompts** → No
4. Set **Train on my data** → No

> ZDR applies only from the moment you enable it. Do this before making any cloud-tier requests.

### 10. Verify routing

Test that sensitive content routes to Ollama:

```bash
curl -s http://127.0.0.1:4000/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"cloud-reasoning","messages":[{"role":"user","content":"my tax file is private"}]}'
```

Check LiteLLM logs - you should see `[PrivacyRouter] Sensitive keywords detected`.

Test that non-sensitive content routes to Together AI:

```bash
curl -s http://127.0.0.1:4000/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"cloud-reasoning","messages":[{"role":"user","content":"explain transformer attention mechanisms"}]}'
```

---

## Keyword Router

Sensitive keywords are defined in `router_hook.py`. The default list covers:

- **Financial / tax:** tax, irs, w2, 1099, ein, invoice, payroll, ledger, balance sheet
- **Identity / PII:** ssn, social security, passport, date of birth, home address
- **Documents:** file, document, upload, pdf, contract, nda, agreement
- **Credentials:** password, api key, secret, token, credential
- **Medical:** medical, diagnosis, prescription, hipaa, health record
- **Legal:** attorney, lawsuit, litigation, settlement, privileged
- **Markers:** private, confidential, classified, proprietary

To add keywords, edit the `PRIVATE_KEYWORDS` set in `router_hook.py` and restart LiteLLM:

```bash
docker compose restart litellm
```

---

## Security Summary

| Control | Implementation |
|---|---|
| Network isolation | UFW blocks all inbound except SSH and Tailscale interface |
| Container isolation | Ollama and LiteLLM bind to `127.0.0.1` only |
| Keyword routing | PII/financial prompts hard-blocked from cloud |
| Together AI ZDR | Account-level setting + `X-Together-No-Store` header |
| No telemetry | LiteLLM external callbacks disabled |
| No prompt caching | `cache: false` in LiteLLM config |

---

## Maintenance

View logs:
```bash
docker compose logs -f litellm    # See routing decisions in real time
docker compose logs -f ollama
```

Update containers:
```bash
docker compose pull
docker compose up -d
```

Check Ollama models:
```bash
docker exec -it ollama ollama list
```

---

## Troubleshooting

**LiteLLM container won't start**
Check that `litellm_config.yaml` and `router_hook.py` are in the same directory as `docker-compose.yml`.

**Ollama healthcheck failing**
The first startup can take 30–60 seconds. Run `docker compose ps` again after a minute.

**Together AI requests failing**
Verify `TOGETHER_API_KEY` in `.env` is correct and that your Together AI account has credits.

**Can't access OpenClaw UI**
Confirm Tailscale is running on both your VPS and your local machine. Access via `http://<tailscale-ip>:8080`.

---

## Cost Reference

| Component | Rate |
|---|---|
| Together AI Qwen-2.5-72B input | ~$0.90 / 1M tokens |
| Together AI Qwen-2.5-72B output | ~$0.90 / 1M tokens |
| Ollama / LiteLLM / OpenClaw | $0 |
| Hetzner CX21 VPS (4GB RAM) | ~$6–10/mo |

At ~500K tokens/month cloud usage, total cost lands around **$10–12/month**.

---

## License

MIT. Use freely, harden for your own threat model.
