#!/usr/bin/env bash
# ============================================================
# provision.sh — Hetzner VPS Provisioner
# Tri-Tier Private AI Gateway
#
# Requirements (local machine):
#   - hcloud CLI: https://github.com/hetznercloud/cli
#   - HCLOUD_TOKEN env var set
#   - TAILSCALE_AUTHKEY env var set
#
# Usage:
#   export HCLOUD_TOKEN=your-hetzner-api-token
#   export TAILSCALE_AUTHKEY=tskey-auth-your-key-here
#   bash provision.sh
# ============================================================

set -euo pipefail

# ---- Config ------------------------------------------------
if [[ -r provision.config ]]
then
  source provision.config
else
  SERVER_NAME="tritier-ai-gateway"
  SERVER_TYPE="cx22"               # 4GB RAM, 2 vCPU
  LOCATION="ash"                   # ash=US, fsn1/nbg1/hel1=EU, sin=Asia
  IMAGE="ubuntu-22.04"
  SSH_KEY_NAME="tritier-deploy-key"
  SSH_KEY_PATH="$HOME/.ssh/tritier_hetzner"
fi
# ------------------------------------------------------------

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()    { echo -e "${BLUE}==>${NC} $1"; }
success(){ echo -e "${GREEN}✓${NC} $1"; }
warn()   { echo -e "${YELLOW}⚠${NC} $1"; }
error()  { echo -e "${RED}✗ ERROR:${NC} $1"; exit 1; }

# ============================================================
# STEP 0: Preflight checks
# ============================================================
log "Running preflight checks..."

# Check hcloud CLI is installed
if ! command -v hcloud >/dev/null 2>&1; then
  error "hcloud CLI not found.
Install:
  macOS:  brew install hcloud
  Linux:  https://github.com/hetznercloud/cli/releases"
fi

# Export token if provided, then verify API access
if [[ -n "${HCLOUD_TOKEN:-}" ]]; then
  export HCLOUD_TOKEN
fi

if ! hcloud server list >/dev/null 2>&1; then
  error "Cannot reach Hetzner API.
Either set HCLOUD_TOKEN:
  export HCLOUD_TOKEN=your-token-here
Or configure a context:
  hcloud context create tritier"
fi

# Check Tailscale auth key
if [[ -z "${TAILSCALE_AUTHKEY:-}" ]]; then
  error "TAILSCALE_AUTHKEY not set.
Generate one at: https://login.tailscale.com/admin/settings/keys
Then run: export TAILSCALE_AUTHKEY=tskey-auth-your-key-here"
fi

success "Preflight checks passed"
# ============================================================
# STEP 1: SSH key setup
# ============================================================
log "Setting up SSH key..."

if [[ ! -f "$SSH_KEY_PATH" ]]; then
  log "Generating SSH key at $SSH_KEY_PATH..."
  ssh-keygen -t ed25519 -C "tritier-hetzner-deploy" -f "$SSH_KEY_PATH" -N ""
  success "SSH key generated"
else
  warn "SSH key already exists at $SSH_KEY_PATH — reusing"
fi

if hcloud ssh-key describe "$SSH_KEY_NAME" >/dev/null 2>&1; then
  warn "SSH key '$SSH_KEY_NAME' already exists in Hetzner — reusing"
else
  log "Uploading SSH public key to Hetzner..."
  hcloud ssh-key create \
    --name "$SSH_KEY_NAME" \
    --public-key-from-file "${SSH_KEY_PATH}.pub"
  success "SSH key uploaded"
fi

# ============================================================
# STEP 2: Check for existing server
# ============================================================
if hcloud server describe "$SERVER_NAME" >/dev/null 2>&1; then
  warn "Server '$SERVER_NAME' already exists."
  EXISTING_IP=$(hcloud server describe "$SERVER_NAME" -o format='{{.PublicNet.IPv4.IP}}')
  echo "  Existing IP: $EXISTING_IP"
  echo ""
  read -rp "  Delete and recreate? This destroys all data. (yes/no): " CONFIRM
  if [[ "$CONFIRM" == "yes" ]]; then
    log "Deleting existing server..."
    hcloud server delete "$SERVER_NAME"
    success "Server deleted"
  else
    echo "Aborting — existing server kept."
    exit 0
  fi
fi

# ============================================================
# STEP 3: Build cloud-init and write to temp file
# ============================================================
log "Building cloud-init configuration..."

# Read SSH public key into variable
SSH_PUB_KEY=$(cat "${SSH_KEY_PATH}.pub")

# Write cloud-init to a temp file
CLOUD_INIT_FILE=$(mktemp tritier-cloudinit-XXXXXX.yaml)
trap 'rm -f "$CLOUD_INIT_FILE"' EXIT

cat > "$CLOUD_INIT_FILE" << CLOUDINIT
#cloud-config

package_update: true
package_upgrade: true
packages:
  - curl
  - git
  - ufw
  - ca-certificates
  - gnupg
  - lsb-release
  - apt-transport-https

users:
  - name: deploy
    groups: sudo, docker
    shell: /bin/bash
    sudo: ALL=(ALL) NOPASSWD:ALL
    ssh_authorized_keys:
      - ${SSH_PUB_KEY}

write_files:
  - path: /opt/tritier/install_stack.sh
    permissions: '0755'
    content: |
      #!/usr/bin/env bash
      set -euo pipefail
      LOG="/var/log/tritier-install.log"
      exec > >(tee -a \$LOG) 2>&1
      echo "==> Starting Tri-Tier stack install"

      echo "==> Installing Docker..."
      curl -fsSL https://get.docker.com | sh
      usermod -aG docker deploy
      systemctl enable docker
      systemctl start docker

      echo "==> Installing Docker Compose plugin..."
      apt-get install -y docker-compose-plugin

      echo "==> Installing Tailscale..."
      curl -fsSL https://tailscale.com/install.sh | sh
      systemctl enable tailscaled
      systemctl start tailscaled
      sleep 3
      tailscale up --authkey="${TAILSCALE_AUTHKEY}" --hostname="${SERVER_NAME}" --advertise-exit-node=false
      echo "==> Tailscale IP: \$(tailscale ip -4 2>/dev/null || echo pending)"

      echo "==> Configuring UFW..."
      ufw --force reset
      ufw default deny incoming
      ufw default allow outgoing
      ufw allow ssh
      ufw allow in on tailscale0
      ufw --force enable
      ufw status verbose

      echo "==> Installing OpenClaw..."
      curl -fsSL https://deb.nodesource.com/setup_24.x | bash - 
      apt-get install -y nodejs
      npm install -g openclaw@latest
      openclaw --version
      sudo -u deploy bash -c 'mkdir /home/deploy/.openclaw'

      echo "==> Creating project directory..."
      mkdir -p /home/deploy/tritier
      chown deploy:deploy /home/deploy/tritier

      echo "==> Stack install complete"
  - path: /home/deploy/.openclaw/openclaw.json  
    permissions: '0755'
    content: |
      {
        "agents": {
          "defaults": {
            "workspace": "/home/deploy/.openclaw/workspace",
            "models": {
              "litellm/claude-opus-4-6": {
                "alias": "LiteLLM"
              },
              "cloud-reasoning": {}
            },
            "model": {
              "primary": "litellm/cloud-reasoning"
            },
            "params": {
              "tool_choice": "none"
            }
          }
        },
        "gateway": {
          "mode": "local",
          "auth": {
            "mode": "token",
            "token": "openclaw-gateway-token"
          },
          "port": 18789,
          "bind": "loopback",
          "tailscale": {
            "mode": "off",
            "resetOnExit": false
          },
          "controlUi": {
            "allowInsecureAuth": true
          },
          "nodes": {
            "denyCommands": [
              "camera.snap",
              "camera.clip",
              "screen.record",
              "contacts.add",
              "calendar.add",
              "reminders.add",
              "sms.send",
              "sms.search"
            ]
          }
        },
        "session": {
          "dmScope": "per-channel-peer"
        },
        "tools": {
          "profile": "full"
        },
        "models": {
          "mode": "merge",
          "providers": {
            "litellm": {
              "baseUrl": "http://localhost:4000/v1",
              "api": "openai-completions",
              "models": [
                {
                  "id": "cloud-reasoning",
                  "name": "Tri-Tier Router"
                }
              ],
              "apiKey": "litellm_master_key"
            }
          }
        },
        "auth": {
          "profiles": {
            "litellm:default": {
              "provider": "litellm",
              "mode": "api_key"
            }
          }
        },
        "channels": {
          "telegram": {
            "enabled": true,
            "groups": {
              "*": {
                "requireMention": true
              }
            },
            "botToken": "telegram_bot_token"
          }
        },
        "hooks": {
          "internal": {
            "enabled": true,
            "entries": {
              "session-memory": {
                "enabled": true
              }
            }
          }
        },
        "plugins": {
          "entries": {
            "litellm": {
              "enabled": true
            }
          }
        }
      }          

runcmd:
  - bash /opt/tritier/install_stack.sh
CLOUDINIT

success "Cloud-init written to $CLOUD_INIT_FILE"

# ============================================================
# STEP 4: Create the server
# ============================================================
log "Creating Hetzner server '$SERVER_NAME'..."
echo "  Type:     $SERVER_TYPE"
echo "  Location: $LOCATION"
echo "  Image:    $IMAGE"
echo ""

hcloud server create \
  --name "$SERVER_NAME" \
  --type "$SERVER_TYPE" \
  --location "$LOCATION" \
  --image "$IMAGE" \
  --ssh-key "$SSH_KEY_NAME" \
  --user-data-from-file "$CLOUD_INIT_FILE"

# Fetch IP via hcloud describe — no python3 needed
SERVER_IP=$(hcloud server describe "$SERVER_NAME" -o format='{{.PublicNet.IPv4.IP}}')

success "Server created — IP: $SERVER_IP"

# ============================================================
# STEP 5: Wait for SSH
# ============================================================
log "Waiting for SSH to become available (up to 3 min)..."

MAX_WAIT=180
ELAPSED=0
until ssh -i "$SSH_KEY_PATH" \
  -o StrictHostKeyChecking=no \
  -o ConnectTimeout=5 \
  -o BatchMode=yes \
  "deploy@$SERVER_IP" "echo ok" >/dev/null 2>&1; do
  if [[ $ELAPSED -ge $MAX_WAIT ]]; then
    warn "SSH not ready after ${MAX_WAIT}s — server may still be booting."
    warn "Try: ssh -i $SSH_KEY_PATH deploy@$SERVER_IP"
    break
  fi
  printf "."
  sleep 5
  ELAPSED=$((ELAPSED + 5))
done
echo ""

[[ $ELAPSED -lt $MAX_WAIT ]] && success "SSH is reachable"

ssh-keyscan -H "$SERVER_IP" >> ~/.ssh/known_hosts 2>/dev/null
success "Added $SERVER_IP to known_hosts"

# ============================================================
# DONE
# ============================================================
echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}  Tri-Tier AI Gateway — VPS Provisioned${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""
echo "  Server : $SERVER_NAME"
echo "  IP     : $SERVER_IP"
echo "  SSH    : ssh -i $SSH_KEY_PATH deploy@$SERVER_IP"
echo ""
echo -e "${YELLOW}  Stack is installing in background (~3-5 min).${NC}"
echo -e "${YELLOW}  Watch progress:${NC}"
echo ""
echo "    ssh -i $SSH_KEY_PATH deploy@$SERVER_IP"
echo "    tail -f /var/log/tritier-install.log"
echo ""
echo -e "${BLUE}  Next steps after install completes:${NC}"
echo ""
echo "  1. Get Tailscale IP (run on server):"
echo "     tailscale ip -4"
echo ""
echo "  2. Copy project files:"
echo "     rsync -avz -e 'ssh -i $SSH_KEY_PATH' ./ deploy@$SERVER_IP:~/tritier/"
echo ""
echo "  3. Create .env on server:"
echo "     ssh -i $SSH_KEY_PATH deploy@$SERVER_IP"
echo "     cd ~/tritier && nano .env"
echo ""
echo "  4. Start the stack:"
echo "     docker compose up -d"
echo ""
echo "  5. Pull Gemma 4 E4B:"
echo "     docker exec -it ollama ollama pull gemma4:e4b"
echo ""

