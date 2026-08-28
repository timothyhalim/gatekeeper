# Gatekeeper v3.0 - Protocol Gateway with Cloudflare API

A web-based application for forwarding TCP traffic (RDP, SSH, VNC, HTTP/HTTPS) from a gateway machine to local machines on your network. Now with **one-click Cloudflare setup** via API!

## Architecture

```
Android Phone → Cloudflare Edge (subdomain.yourdomain.com) → cloudflared tunnel → Gateway Machine → Target Machine
```

## ✨ New Features in v3.0

- **☁️ Cloudflare API Integration**: One-click tunnel creation and DNS setup
- **🔗 Automatic DNS Management**: Creates CNAME records like `rdp.yourdomain.com` automatically
- **⚡ Auto-Setup Wizard**: Enter API token + domain, click one button, done!
- **📋 Manual Mode**: Still supports manual cloudflared setup
- **🖥️ Enhanced Web UI**: New dashboard for Cloudflare management

## Quick Start

### 1. Install Dependencies

```bash
pip install flask requests pyyaml
```

### 2. Run Gatekeeper

```bash
python gatekeeper.py
```

Access the web interface at `http://localhost:5000`

## ☁️ Cloudflare Auto-Setup (Recommended!)

### Step 1: Get Cloudflare API Token

1. Go to https://dash.cloudflare.com/profile/api-tokens
2. Click "Create Token"
3. Use these permissions:
   - **Cloudflare Tunnel**: Edit
   - **Zone**: Edit (for DNS records)
   - **Account**: Read (for tunnel management)
4. Copy the generated token

### Step 2: One-Click Setup in Gatekeeper

1. Open http://localhost:5000
2. In "Cloudflare API Auto-Setup" section:
   - Paste your API token
   - Enter your domain (e.g., `example.com`)
3. Click **"One-Click Setup"**
4. Enter a tunnel name when prompted
5. Done! The app will:
   - Create a Cloudflare Tunnel
   - Setup DNS records for all your rules
   - Generate cloudflared config

### Step 3: Run cloudflared

```bash
cloudflared tunnel run --config cloudflared_configs/config.yml
```

## 📝 Manual Cloudflare Setup (Alternative)

If you prefer manual setup:

```bash
# Install cloudflared
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared-linux-amd64.deb

# Login
cloudflared tunnel login

# Create tunnel
cloudflared tunnel create --name gatekeeper

# Enter Tunnel ID in Gatekeeper UI and click "Generate Config"
cloudflared tunnel run --config cloudflared_configs/config.yml
```

## Creating Forwarding Rules

### Example: RDP Access

| Field | Value |
|-------|-------|
| Name | Home RDP |
| Protocol | TCP |
| Gateway Port | 3389 |
| Target IP | 192.168.1.100 |
| Target Port | 3389 |
| Expose via Cloudflare | ✓ |
| Subdomain (optional) | rdp |

Result: Connect to `rdp.yourdomain.com` from anywhere!

### Example: SSH Access

| Field | Value |
|-------|-------|
| Name | Home SSH |
| Protocol | TCP |
| Gateway Port | 2222 |
| Target IP | 192.168.1.100 |
| Target Port | 22 |
| Expose via Cloudflare | ✓ |
| Subdomain | ssh |

Result: `ssh -p 22 user@ssh.yourdomain.com`

## Client Setup

### Android (RDP)

1. Install **Microsoft Remote Desktop** from Play Store
2. Add PC → Hostname: `rdp.yourdomain.com`
3. Connect!

### iOS/macOS (SSH)

```bash
ssh -p 22 user@ssh.yourdomain.com
```

### Windows (RDP)

```
mstsc /v:rdp.yourdomain.com
```

## API Endpoints

### Configuration
- `GET /api/config` - Get current configuration
- `POST /api/config` - Update configuration

### Rules
- `POST /api/rules` - Create a new rule
- `PUT /api/rules/<id>` - Update a rule
- `DELETE /api/rules/<id>` - Delete a rule
- `POST /api/rules/<id>/toggle` - Toggle rule enabled/disabled

### Cloudflare API
- `POST /api/cloudflare/test` - Test API connection
- `GET /api/cloudflare/tunnels` - List existing tunnels
- `POST /api/cloudflare/tunnel/create` - Create new tunnel
- `POST /api/cloudflare/dns/setup` - Setup DNS for all rules
- `POST /api/cloudflare/dns/delete` - Delete a DNS record
- `POST /api/cloudflare/auto-setup` - One-click complete setup
- `GET /api/cloudflare/setup-guide` - Get setup instructions

### Legacy (Manual)
- `POST /api/cloudflared/generate` - Generate cloudflared config file

## Configuration File

Stored in `gatekeeper_config.json`:

```json
{
  "gateway_host": "0.0.0.0",
  "cloudflare_enabled": true,
  "cloudflare_tunnel_id": "abc123-def456",
  "cloudflare_api_token": "your-api-token",
  "cloudflare_zone_id": "zone123",
  "cloudflare_domain": "example.com",
  "rules": [
    {
      "id": "20240101120000",
      "name": "Home RDP",
      "protocol": "tcp",
      "gateway_port": 3389,
      "target_host": "192.168.1.100",
      "target_port": 3389,
      "enabled": true,
      "expose_cloudflare": true,
      "subdomain": "rdp"
    }
  ]
}
```

## How It Works

1. **Client connects** to `rdp.yourdomain.com` (Cloudflare Edge)
2. **Cloudflare routes** traffic through the encrypted tunnel
3. **cloudflared daemon** on gateway receives traffic
4. **Gatekeeper forwards** to target machine (192.168.1.100:3389)
5. **Response flows back** through the same path

No ports opened on your firewall! No dynamic DNS needed!

## Security Best Practices

✅ **Use Cloudflare Tunnel** - All traffic encrypted end-to-end
✅ **Strong passwords** on target machines
✅ **Enable 2FA** where possible
✅ **Use custom subdomains** - Don't use obvious names
✅ **Disable rules** when not needed
❌ **Don't expose** unauthenticated services
❌ **Don't share** your API token

## Troubleshooting

### "Connection refused"
- Check if cloudflared is running: `ps aux | grep cloudflared`
- Verify tunnel ID in config matches created tunnel

### DNS not resolving
- Wait 1-2 minutes for DNS propagation
- Check DNS record in Cloudflare dashboard
- Verify zone ID is correct

### API errors
- Ensure API token has correct permissions
- Check domain is managed by Cloudflare
- Verify account has Tunnel feature enabled

## Alternatives

For different use cases:

| Tool | Best For | TCP Support |
|------|----------|-------------|
| **Gatekeeper** | Easy web UI + Cloudflare | ✅ Full |
| **Tailscale** | Personal VPN mesh | ✅ Full |
| **cloudflared** | CLI-only Cloudflare | ✅ Full |
| **ngrok** | Quick temporary tunnels | ⚠️ Paid |
| **frp** | Self-hosted reverse proxy | ✅ Full |
| **socat** | Simple CLI forwarding | ✅ Full |

## License

MIT License - Feel free to modify and distribute!
