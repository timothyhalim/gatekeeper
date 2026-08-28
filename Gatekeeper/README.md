# Gatekeeper - Protocol Gateway with Cloudflare Tunnel Support

A web-based application that forwards TCP traffic (RDP, SSH, VNC, HTTP/HTTPS, or any custom protocol) from the internet through Cloudflare Tunnel to machines on your local network.

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌───────────┐     ┌─────────────┐     ┌──────────────┐
│   Android   │ ──► │  Cloudflare  │ ──► │ cloudflared│ ──► │  Gateway    │ ──► │   Target     │
│    Phone    │     │    Edge      │     │  Tunnel    │     │ (192.168.1.2)│     │  Machine     │
│             │     │              │     │           │     │  Port: 1234  │     │ 192.168.1.3  │
│  RDP Client │     │  yourdomain  │     │ encrypted │     │             │     │   :3389      │
└─────────────┘     └──────────────┘     └───────────┘     └─────────────┘     └──────────────┘
```

## Features

- **Web GUI**: Modern, responsive interface for managing forwarding rules
- **Cloudflare Tunnel Integration**: Secure tunneling without port forwarding
- **Multi-Protocol Support**: RDP, SSH, VNC, HTTP/HTTPS, or any TCP protocol
- **Real-time Monitoring**: View active connections and statistics
- **Persistent Configuration**: Rules saved to JSON file
- **Auto-generated cloudflared config**: One-click configuration generation

## Installation

### Prerequisites

- Python 3.7+
- Flask (`pip install flask`)
- PyYAML (optional, for better config generation): `pip install pyyaml`

### Quick Start

```bash
# Install dependencies
pip install flask pyyaml

# Run the application
python gatekeeper.py
```

Access the web interface at: **http://localhost:5000**

## Usage

### 1. Create a Forwarding Rule

1. Open the web interface
2. Fill in the rule details:
   - **Rule Name**: e.g., "Home RDP"
   - **Protocol**: TCP (for RDP, SSH, etc.)
   - **Gateway Port**: Port on gateway machine (e.g., 1234)
   - **Target IP**: Local machine IP (e.g., 192.168.1.3)
   - **Target Port**: Service port (e.g., 3389 for RDP)
   - **Expose via Cloudflare**: Check if you want internet access

### 2. Setup Cloudflare Tunnel (Optional but Recommended)

#### On Gateway Machine:

```bash
# Install cloudflared
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared-linux-amd64.deb

# Authenticate
cloudflared tunnel login

# Create tunnel
cloudflared tunnel create --name gatekeeper

# Note the Tunnel ID displayed
```

#### In Gatekeeper Web UI:

1. Enter the Tunnel ID in the Cloudflare section
2. Click "Generate Config"
3. Run the tunnel:
   ```bash
   cloudflared tunnel run --config cloudflared_configs/config.yml
   ```

### 3. Connect from Android

#### With Cloudflare:

1. **For RDP**:
   - Install "Microsoft Remote Desktop" from Play Store
   - Add PC with hostname: `rdp-home.yourdomain.com`
   - Connect!

2. **For SSH**:
   - Install "Termux" or "JuiceSSH"
   - Connect to: `ssh-home.yourdomain.com:22`

#### Without Cloudflare (Local Network Only):

- **RDP**: Connect to `GATEWAY_IP:GATEWAY_PORT`
- **SSH**: `ssh -p GATEWAY_PORT user@GATEWAY_IP`
- **VNC**: `vncviewer GATEWAY_IP::GATEWAY_PORT`

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/config` | Get current configuration |
| POST | `/api/config` | Update configuration |
| POST | `/api/rules` | Create new rule |
| PUT | `/api/rules/<id>` | Update rule |
| DELETE | `/api/rules/<id>` | Delete rule |
| POST | `/api/rules/<id>/toggle` | Enable/disable rule |
| POST | `/api/cloudflared/generate` | Generate cloudflared config |
| GET | `/api/cloudflared/setup-guide` | Get setup instructions |

## Example Configuration

Your example scenario:
```
Android → RDP → Cloudflare Tunnel → Gateway:1234 → RDP Machine:3389
```

**Setup in Gatekeeper:**

1. Create rule:
   - Name: "Home RDP"
   - Protocol: TCP
   - Gateway Port: 1234
   - Target IP: 192.168.1.3
   - Target Port: 3389
   - Expose via Cloudflare: ✓

2. From Android, connect to: `rdp-home.yourdomain.com` (or direct IP if no Cloudflare)

## Alternative Solutions

If you're looking for existing tools:

| Tool | Best For | Complexity |
|------|----------|------------|
| **Gatekeeper (this)** | Web GUI, multi-protocol | Easy |
| **socat** | CLI port forwarding | Medium |
| **ngrok** | Quick temporary tunnels | Easy |
| **frp** | Production reverse proxy | Medium |
| **chisel** | TCP over HTTP tunnel | Medium |
| **Tailscale** | Personal mesh network (recommended!) | Very Easy |
| **WireGuard** | Full VPN access | Medium |
| **sshuttle** | VPN over SSH | Easy |

### Tailscale Alternative (Highly Recommended for Personal Use)

For personal remote access without Cloudflare setup:

1. Install Tailscale on gateway and all devices
2. Enable subnet routes on gateway
3. Connect directly using internal IPs
4. No port forwarding, no Cloudflare needed!

## Security Considerations

- **Authentication**: This app doesn't include authentication. Use behind a firewall or add auth
- **Encryption**: Cloudflare provides encryption; without it, traffic is unencrypted
- **Access Control**: Be careful which services you expose
- **Logging**: All connections are logged to `gatekeeper.log`

## Files

- `gatekeeper.py` - Main application
- `templates/index.html` - Web interface
- `gatekeeper_config.json` - Configuration (auto-created)
- `gatekeeper.log` - Log file
- `cloudflared_configs/` - Cloudflare tunnel configs

## License

MIT License - Feel free to modify and distribute!
