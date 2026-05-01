# Tri-Tier Privacy-Focused AI Platform

A self-hosted, privacy-first AI stack that routes sensitive prompts to a local model and complex reasoning to the cloud - with intelligent classification and zero public internet exposure.

---

## Architecture

```
You (Tailscale only)
        │
        ▼
 OpenClaw Gateway          ← Controller / Orchestrator (host)
        │
        ▼
  LiteLLM Proxy :4000      ← $0 open-source router with PrivacyRouter hook
     │           │           │
     │           │           ▼
     │           │    Complexity Classifier (gemma4:e2b)
     │           │           │
     ▼           ▼           ▼
 Ollama        Together AI  Together AI
 Gemma 4 E4B   Qwen 3.5     Qwen3-Coder
 [Private]     [Simple]     [Complex]
               397B-A17B    480B-A35B FP8
```
### Three-Tier Routing

The platform routes queries through three pathways:

1. **Local-Private**: `[priv]` prefixed messages → Ollama gemma4:e4b (local, air-gapped)
2. **Cloud-Simple**: Non-sensitive, simple queries → Together AI Qwen3.5-397B-A17B
3. **Cloud-Complex**: Non-sensitive, complex queries → Together AI Qwen3-Coder-480B-A35B-Instruct-FP8

**Model differentiation:** Simple queries use the 397B general model, while complex queries use the 480B coder-focused model for advanced reasoning.

| Tier | Component | Purpose | Cost | Trigger |
|---|---|---|---|---|
| Controller | OpenClaw | Orchestration, agent routing, UI | $0 | - |
| Router | LiteLLM (self-hosted) | Privacy prefix + complexity routing | $0 | - |
| **Private Layer** | Ollama + Gemma 4 E4B | `[priv]` prefixed prompts | $0 | `[priv]` prefix |
| **Simple Cloud** | Together AI Qwen3.5-397B-A17B | Non-sensitive, simple queries | Pay-per-token | No prefix, simple classification |
| **Complex Cloud** | Together AI Qwen3-Coder-480B-A35B-Instruct-FP8 | Non-sensitive, complex reasoning | Pay-per-token | No prefix, complex classification |
| Infrastructure | VPS (Ubuntu 22.04) | Hosts everything | ~$6–10/mo | - |

**Note:** `cloud-simple` uses Qwen3.5-397B-A17B for general queries, while `cloud-complex` uses Qwen3-Coder-480B-A35B-Instruct-FP8 for complex reasoning and coding tasks.

**Estimated total: $8–12/month** at moderate personal use.

---

## Privacy Model

Sensitive data never reaches Together AI. The prefix router intercepts prompts before they leave your VPS.

```
Prompt starts with [priv] prefix
        │
        ├── YES → Ollama (local, air-gapped)
        │
        └── NO  → Complexity Classifier → Simple/Complex → Together AI (ZDR enabled)

```
### Cloud Privacy Protections

Even for non-sensitive queries that reach the cloud, Together AI provides:

- **Zero Data Retention (ZDR)**: Prompts are not stored after processing
- **No Training on User Data**: Your prompts are never used to train or improve models
- **Account-Level Privacy**: ZDR is enabled at the account level for all requests
- **Header Enforcement**: `X-Together-No-Store: true` header sent with all cloud requests

This means **all three tiers** maintain privacy:
- **Local-Private**: Air-gapped, never leaves your VPS
- **Cloud-Simple**: ZDR + no training (Qwen3.5-397B-A17B)
- **Cloud-Complex**: ZDR + no training (Qwen3-Coder-480B-A35B-Instruct-FP8)

---

## Classification System

The platform uses an intelligent complexity classifier to route non-sensitive queries:

- **Simple queries**: Single factual questions, basic greetings, short straightforward requests → `cloud-simple`
- **Complex queries**: Multiple questions, requires analysis/synthesis, technical domains → `cloud-complex`

### Classification Optimizations

1. **Caching**: Results cached for 5 minutes (100 entries max) - ~50% reduction in classifier calls
2. **Lightweight Model**: `gemma4:e2b` (2B params) for fast classification - 457ms-2s response time
3. **Graceful Timeout**: 6-second timeout falls back to "simple" routing

---

## Files

```
tritier/
├── docker-compose.yml      # Ollama + LiteLLM containers
├── litellm_config.yaml     # Model routing, ZDR headers, classifier config
├── router_hook.py          [PrivacyRouter] prefix interception + complexity classification
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
#install docker repo
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc]
https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
#autoremove, update and upgrade apt packages
sudo apt autoremove
sudo apt update && sudo apt upgrade -y

#install dependencies 
sudo apt install -y docker.io docker-compose-plugin ufw
```

### 2. Install Tailscale

```bash
# Not necessary is you don't intend to access openclaw UI. Skip to firewall setting
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Note your Tailscale IP - it will look like `100.x.x.x`. This is the only address you will use to access the stack.

### 3. Lock down the firewall

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow in on tailscale0 # Only if tailscale is installed and used.  Otherwise, skip
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

### 7. Pull the models

```bash
# Privacy model (local)
docker exec -it ollama ollama pull gemma4:e4b

# Classification model (lightweight, fast)
docker exec -it ollama ollama pull gemma4:e2b
```

This downloads approximately 4-5GB total. Allow 5–10 minutes depending on your VPS bandwidth.

### 8. Connect OpenClaw to LiteLLM

Edit `~/.openclaw/openclaw.json`:

```json
{
  "models": {
    "mode": "merge",
    "providers": {
      "litellm": {
        "baseUrl": "http://localhost:4000/v1",
        "api": "openai-completions",
        "models": [
          {
            "id": "cloud-simple",
            "name": "Tri-Tier Router (Simple)"
          },
          {
            "id": "cloud-complex",
            "name": "Tri-Tier Router (Complex)"
          },
          {
            "id": "local-private",
            "name": "Tri-Tier Router (Private)"
          }
        ],
        "apiKey": "YOUR_LITELLM_MASTER_KEY"
      }
    }
  },
  "agents": {
    "defaults": {
      "model": {
        "primary": "litellm/cloud-simple"
      }
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

Test that `[priv]` prefixed content routes to Ollama:

```bash
curl -s http://127.0.0.1:4000/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"cloud-simple","messages":[{"role":"user","content":"[priv] what is my account balance"}]}'
```

Check LiteLLM logs - you should see `[PrivacyRouter] *** [priv] -> local-private`.

Test complexity classification:

```bash
# Simple query
curl -s http://127.0.0.1:4000/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"cloud-simple","messages":[{"role":"user","content":"What is 2+2?"}]}'

# Complex query
curl -s http://127.0.0.1:4000/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"cloud-simple","messages":[{"role":"user","content":"Explain how to build a distributed system with load balancing and fault tolerance"}]}'
```

Check LiteLLM logs - you should see classification decisions and routing.

---

## Privacy Router + Classifier

The router in `router_hook.py` uses a two-stage approach:

### Stage 1: Privacy Detection
- Messages starting with `[priv]` → routed to **local-private** (Ollama gemma4:e4b)
- Messages without prefix → proceed to complexity classification

### Stage 2: Complexity Classification
- **Simple**: Single factual questions, greetings, short requests → `cloud-simple` (Qwen3.5-397B-A17B)
- **Complex**: Multi-part questions, analysis, technical domains, coding tasks → `cloud-complex` (Qwen3-Coder-480B-A35B-Instruct-FP8)

**Note:** The complex tier uses a larger, coder-focused model (480B params, FP8 quantized) for advanced reasoning and technical tasks.

### Performance Optimizations
1. **Caching**: 5-minute TTL, 100-entry max, ~50% hit rate
2. **Lightweight Model**: gemma4:e2b (2B) - 457ms-2s response time (vs 9+ seconds for 8B)
3. **Timeout Handling**: 6-second timeout falls back to "simple" routing

To modify routing behavior, edit `router_hook.py` and restart LiteLLM:

```bash
docker compose restart litellm
```

---

## Security Summary

| Control | Implementation |
|---|---|
| Network isolation | UFW blocks all inbound except SSH and Tailscale interface |
| Container isolation | Ollama and LiteLLM bind to `127.0.0.1` only |
| Prefix routing | `[priv]` prefixed prompts hard-blocked from cloud |
| Complexity routing | Intelligent classification before cloud routing |
| **Local privacy** | Ollama air-gapped, never leaves VPS |
| **Cloud privacy** | Together AI ZDR + no training on all cloud requests |
| Together AI ZDR | Account-level setting + `X-Together-No-Store` header |
| No telemetry | LiteLLM external callbacks disabled |
| No prompt caching | `cache: false` in LiteLLM config |
| Classifier caching | In-memory only, 5-minute TTL, auto-expiring |

---

## Maintenance

View logs:
```bash
docker compose logs -f litellm    # See routing decisions in real time
docker compose logs -f ollama     # See classifier activity
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

Monitor performance:
```bash
# Check system load
uptime

# Check container stats
docker stats --no-stream

# Check classification cache hits
docker compose logs litellm --since 10m | grep "cached classification"
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

**Classification timeouts**
Check that `gemma4:e2b` model is pulled. The 6-second timeout should fall back to "simple" routing gracefully.

**High Ollama CPU usage**
This was resolved with classification optimizations (caching + lighter model). Check logs for cache hit rate.

---

## Cost Reference

| Component | Rate |
|---|---|
| Together AI Qwen 3.5 397B input | ~$0.90 / 1M tokens |
| Together AI Qwen 3.5 397B output | ~$0.90 / 1M tokens |
| Ollama / LiteLLM / OpenClaw | $0 |
| Hetzner CX21 VPS (8GB RAM) | ~$10/mo |

At ~500K tokens/month cloud usage, total cost lands around **$10–12/month**.

---

## Performance Metrics

After optimization implementation:

- **Classification speed**: 457ms-2s (gemma4:e2b) vs 9+ seconds (gemma4:e4b)
- **Cache hit rate**: ~50% reduction in classifier calls
- **System load**: 1.76 average (stable)
- **Ollama CPU**: 0.01% (idle between requests)
- **Timeout rate**: <1% (6-second graceful fallback)

---

## License

MIT. Use freely, harden for your own threat model.
