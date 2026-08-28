#!/usr/bin/env python3
"""
Gatekeeper v3.0 - Protocol Gateway with Cloudflare API Integration
Forwards any TCP protocol (RDP, SSH, VNC, etc.) from internet to local machines

Architecture:
  Client (Android) → Cloudflare Edge → cloudflared → Gateway → Target Machine

Features:
  - Web GUI for managing port forwarding rules
  - Cloudflare API integration for automatic DNS & tunnel management
  - One-click subdomain provisioning (e.g., rdp.yourdomain.com)
  - Real-time connection monitoring
  - Persistent configuration storage
"""

import os
import sys
import json
import socket
import threading
import logging
import requests
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_from_directory
import subprocess
import signal
import yaml

# Configuration
CONFIG_FILE = "gatekeeper_config.json"
CLOUDFLARED_CONFIG_DIR = "cloudflared_configs"
LOG_FILE = "gatekeeper.log"

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("gatekeeper")

app = Flask(__name__)

# In-memory state
active_connections = {}
forwarding_threads = {}
config = {
    "gateway_host": "0.0.0.0",
    "rules": [],
    "cloudflare_enabled": False,
    "cloudflare_tunnel_id": "",
    "cloudflare_api_token": "",
    "cloudflare_account_id": "",
    "cloudflare_zone_id": "",
    "cloudflare_domain": "",
}

# Load existing config
if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, 'r') as f:
            loaded_config = json.load(f)
            config.update(loaded_config)
            logger.info(f"Loaded configuration from {CONFIG_FILE}")
    except Exception as e:
        logger.error(f"Failed to load config: {e}")

def save_config():
    """Save configuration to file"""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        logger.info("Configuration saved")
    except Exception as e:
        logger.error(f"Failed to save config: {e}")

def forward_traffic(client_socket, target_host, target_port, rule_id):
    """Forward traffic between client and target"""
    try:
        target_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        target_socket.settimeout(5)
        target_socket.connect((target_host, target_port))
        target_socket.settimeout(None)
        
        logger.info(f"[Rule {rule_id}] Connected to {target_host}:{target_port}")
        
        def relay(source, destination):
            try:
                while True:
                    data = source.recv(4096)
                    if not data:
                        break
                    destination.sendall(data)
            except Exception as e:
                logger.debug(f"Relay error: {e}")
            finally:
                source.close()
                destination.close()
        
        # Bidirectional forwarding
        client_to_target = threading.Thread(target=relay, args=(client_socket, target_socket))
        target_to_client = threading.Thread(target=relay, args=(target_socket, client_socket))
        
        client_to_target.start()
        target_to_client.start()
        
        client_to_target.join()
        target_to_client.join()
        
    except Exception as e:
        logger.error(f"[Rule {rule_id}] Forwarding error: {e}")
    finally:
        # Update active connections
        if rule_id in active_connections:
            active_connections[rule_id]["current_connections"] -= 1

def start_forwarder(rule):
    """Start a TCP forwarder for a rule"""
    rule_id = rule["id"]
    
    if rule_id in forwarding_threads:
        stop_forwarder(rule_id)
    
    def accept_connections():
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            server_socket.bind((config["gateway_host"], rule["gateway_port"]))
            server_socket.listen(100)
            logger.info(f"[Rule {rule_id}] Listening on {config['gateway_host']}:{rule['gateway_port']} → {rule['target_host']}:{rule['target_port']} ({rule['protocol']})")
            
            while rule["enabled"]:
                try:
                    server_socket.settimeout(1)
                    client_socket, addr = server_socket.accept()
                    logger.info(f"[Rule {rule_id}] New connection from {addr[0]}:{addr[1]}")
                    
                    # Track connection
                    if rule_id not in active_connections:
                        active_connections[rule_id] = {"current_connections": 0, "total_connections": 0}
                    active_connections[rule_id]["current_connections"] += 1
                    active_connections[rule_id]["total_connections"] += 1
                    
                    # Start forwarding thread
                    thread = threading.Thread(
                        target=forward_traffic,
                        args=(client_socket, rule["target_host"], rule["target_port"], rule_id),
                        daemon=True
                    )
                    thread.start()
                    
                except socket.timeout:
                    continue
                except Exception as e:
                    if rule["enabled"]:
                        logger.error(f"[Rule {rule_id}] Accept error: {e}")
                    break
                    
        except Exception as e:
            logger.error(f"[Rule {rule_id}] Server error: {e}")
        finally:
            server_socket.close()
            if rule_id in forwarding_threads:
                del forwarding_threads[rule_id]
            logger.info(f"[Rule {rule_id}] Forwarder stopped")
    
    thread = threading.Thread(target=accept_connections, daemon=True)
    thread.start()
    forwarding_threads[rule_id] = thread
    rule["status"] = "running"

def stop_forwarder(rule_id):
    """Stop a forwarder"""
    if rule_id in forwarding_threads:
        # Find the rule
        rule = next((r for r in config["rules"] if r["id"] == rule_id), None)
        if rule:
            rule["status"] = "stopped"
            rule["enabled"] = False
        # Thread will exit when it checks enabled flag
        del forwarding_threads[rule_id]
        logger.info(f"[Rule {rule_id}] Stop requested")

def generate_cloudflared_config():
    """Generate cloudflared configuration for TCP tunneling"""
    os.makedirs(CLOUDFLARED_CONFIG_DIR, exist_ok=True)
    
    if not config["rules"]:
        return None
    
    # Create ingress rules for cloudflared
    ingress_rules = []
    
    domain = config.get("cloudflare_domain", "yourdomain.com")
    
    for rule in config["rules"]:
        if rule["enabled"] and rule["expose_cloudflare"]:
            # Use custom subdomain if set, otherwise generate from name
            subdomain = rule.get("subdomain", "")
            if not subdomain:
                subdomain = f"{rule['name'].lower().replace(' ', '-')}"
            
            hostname = f"{subdomain}.{domain}"
            rule["_hostname"] = hostname  # Store for API use
            
            ingress_rules.append({
                "hostname": hostname,
                "service": f"tcp://{rule['target_host']}:{rule['target_port']}",
                "originRequest": {
                    "noTLSVerify": True
                }
            })
    
    # Add default rule (404 for unmatched)
    ingress_rules.append({"service": "http_status:404"})
    
    cloudflared_config = {
        "tunnel": config["cloudflare_tunnel_id"],
        "credentials-file": "/home/user/.cloudflared/tunnel_credentials.json",
        "ingress": ingress_rules,
        "warp-routing": {
            "enabled": True
        }
    }
    
    config_file = os.path.join(CLOUDFLARED_CONFIG_DIR, "config.yml")
    with open(config_file, 'w') as f:
        yaml.dump(cloudflared_config, f, default_flow_style=False)
    
    logger.info(f"Generated cloudflared config: {config_file}")
    return config_file


class CloudflareAPI:
    """Cloudflare API client for managing tunnels and DNS"""
    
    def __init__(self, api_token, account_id=None, zone_id=None, domain=None):
        self.api_token = api_token
        self.account_id = account_id
        self.zone_id = zone_id
        self.domain = domain
        self.base_url = "https://api.cloudflare.com/client/v4"
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }
    
    def _request(self, method, endpoint, data=None):
        """Make API request"""
        url = f"{self.base_url}/{endpoint}"
        try:
            if method == "GET":
                resp = requests.get(url, headers=self.headers, timeout=10)
            elif method == "POST":
                resp = requests.post(url, headers=self.headers, json=data, timeout=10)
            elif method == "PUT":
                resp = requests.put(url, headers=self.headers, json=data, timeout=10)
            elif method == "DELETE":
                resp = requests.delete(url, headers=self.headers, timeout=10)
            else:
                raise ValueError(f"Unknown method: {method}")
            
            resp.raise_for_status()
            result = resp.json()
            return result.get("result"), None
        except requests.exceptions.RequestException as e:
            return None, str(e)
    
    def get_account_id(self):
        """Get the first account ID if not provided"""
        if self.account_id:
            return self.account_id, None
        
        result, error = self._request("GET", "accounts?per_page=1")
        if error:
            return None, error
        
        if result and len(result) > 0:
            return result[0]["id"], None
        return None, "No accounts found"
    
    def get_zone_id(self, domain):
        """Get zone ID for a domain"""
        result, error = self._request("GET", f"zones?name={domain}")
        if error:
            return None, error
        
        if result and len(result) > 0:
            return result[0]["id"], None
        return None, f"Zone not found for domain: {domain}"
    
    def create_tunnel(self, name):
        """Create a new Cloudflare Tunnel"""
        account_id, error = self.get_account_id()
        if error:
            return None, error
        
        data = {"name": name}
        result, error = self._request("POST", f"accounts/{account_id}/cfd_tunnel", data)
        if error:
            return None, error
        
        return result, None
    
    def get_tunnel_credentials(self, tunnel_id):
        """Get tunnel credentials (secret)"""
        account_id, error = self.get_account_id()
        if error:
            return None, error
        
        result, error = self._request("GET", f"accounts/{account_id}/cfd_tunnel/{tunnel_id}/token")
        if error:
            return None, error
        
        return result.get("token"), None
    
    def update_tunnel_config(self, tunnel_id, config_data):
        """Update tunnel configuration"""
        account_id, error = self.get_account_id()
        if error:
            return None, error
        
        data = {"config": config_data}
        result, error = self._request("PUT", f"accounts/{account_id}/cfd_tunnel/{tunnel_id}/config", data)
        return result is not None, error
    
    def create_dns_record(self, subdomain, tunnel_id, record_type="CNAME"):
        """Create DNS record pointing to tunnel"""
        if not self.zone_id:
            return None, "Zone ID not configured"
        
        # For Cloudflare Tunnels, we use CNAME to tunnel ID
        full_name = f"{subdomain}.{self.domain}"
        
        # Check if record exists
        existing, error = self._request("GET", f"zones/{self.zone_id}/dns_records?name={full_name}")
        if existing and len(existing) > 0:
            # Update existing record
            record_id = existing[0]["id"]
            data = {
                "type": "CNAME",
                "name": full_name,
                "content": f"{tunnel_id}.cfargotunnel.com",
                "proxied": False  # Don't proxy TCP traffic
            }
            result, error = self._request("PUT", f"zones/{self.zone_id}/dns_records/{record_id}", data)
            return result is not None, error
        else:
            # Create new record
            data = {
                "type": "CNAME",
                "name": full_name,
                "content": f"{tunnel_id}.cfargotunnel.com",
                "proxied": False
            }
            result, error = self._request("POST", f"zones/{self.zone_id}/dns_records", data)
            return result is not None, error
    
    def delete_dns_record(self, subdomain):
        """Delete DNS record"""
        if not self.zone_id:
            return None, "Zone ID not configured"
        
        full_name = f"{subdomain}.{self.domain}"
        existing, error = self._request("GET", f"zones/{self.zone_id}/dns_records?name={full_name}")
        
        if existing and len(existing) > 0:
            record_id = existing[0]["id"]
            result, error = self._request("DELETE", f"zones/{self.zone_id}/dns_records/{record_id}")
            return result is not None, error
        
        return True, None
    
    def list_tunnels(self):
        """List all tunnels in account"""
        account_id, error = self.get_account_id()
        if error:
            return None, error
        
        result, error = self._request("GET", f"accounts/{account_id}/cfd_tunnel")
        return result, error

@app.route('/')
def index():
    """Serve the main dashboard"""
    return render_template('index.html')

@app.route('/api/config', methods=['GET'])
def get_config():
    """Get current configuration"""
    # Update connection stats
    for rule in config["rules"]:
        rule_id = rule["id"]
        if rule_id in active_connections:
            rule["current_connections"] = active_connections[rule_id]["current_connections"]
            rule["total_connections"] = active_connections[rule_id]["total_connections"]
        else:
            rule["current_connections"] = 0
            rule["total_connections"] = 0
        rule["status"] = "running" if rule["enabled"] and rule_id in forwarding_threads else "stopped"
    
    return jsonify({
        "gateway_host": config["gateway_host"],
        "cloudflare_enabled": config["cloudflare_enabled"],
        "cloudflare_tunnel_id": config["cloudflare_tunnel_id"],
        "rules": config["rules"]
    })

@app.route('/api/config', methods=['POST'])
def update_config():
    """Update configuration"""
    data = request.json
    
    if "gateway_host" in data:
        config["gateway_host"] = data["gateway_host"]
    if "cloudflare_enabled" in data:
        config["cloudflare_enabled"] = data["cloudflare_enabled"]
    if "cloudflare_tunnel_id" in data:
        config["cloudflare_tunnel_id"] = data["cloudflare_tunnel_id"]
    
    save_config()
    
    # Restart forwarders if needed
    for rule in config["rules"]:
        if rule["enabled"]:
            start_forwarder(rule)
    
    return jsonify({"success": True})

@app.route('/api/rules', methods=['POST'])
def create_rule():
    """Create a new forwarding rule"""
    data = request.json
    
    rule = {
        "id": datetime.now().strftime("%Y%m%d%H%M%S"),
        "name": data.get("name", "Unnamed Rule"),
        "protocol": data.get("protocol", "tcp"),
        "gateway_port": int(data["gateway_port"]),
        "target_host": data["target_host"],
        "target_port": int(data["target_port"]),
        "enabled": data.get("enabled", True),
        "expose_cloudflare": data.get("expose_cloudflare", False),
        "status": "stopped",
        "current_connections": 0,
        "total_connections": 0,
        "created_at": datetime.now().isoformat()
    }
    
    config["rules"].append(rule)
    save_config()
    
    if rule["enabled"]:
        start_forwarder(rule)
    
    if rule["expose_cloudflare"]:
        generate_cloudflared_config()
    
    return jsonify({"success": True, "rule": rule})

@app.route('/api/rules/<rule_id>', methods=['PUT'])
def update_rule(rule_id):
    """Update an existing rule"""
    data = request.json
    rule = next((r for r in config["rules"] if r["id"] == rule_id), None)
    
    if not rule:
        return jsonify({"error": "Rule not found"}), 404
    
    # Update fields
    for key in ["name", "protocol", "gateway_port", "target_host", "target_port", "enabled", "expose_cloudflare"]:
        if key in data:
            if key in ["gateway_port", "target_port"]:
                rule[key] = int(data[key])
            else:
                rule[key] = data[key]
    
    save_config()
    
    if rule["enabled"]:
        start_forwarder(rule)
    else:
        stop_forwarder(rule_id)
    
    if rule["expose_cloudflare"]:
        generate_cloudflared_config()
    
    return jsonify({"success": True, "rule": rule})

@app.route('/api/rules/<rule_id>', methods=['DELETE'])
def delete_rule(rule_id):
    """Delete a rule"""
    config["rules"] = [r for r in config["rules"] if r["id"] != rule_id]
    save_config()
    
    if rule_id in forwarding_threads:
        stop_forwarder(rule_id)
    if rule_id in active_connections:
        del active_connections[rule_id]
    
    return jsonify({"success": True})

@app.route('/api/rules/<rule_id>/toggle', methods=['POST'])
def toggle_rule(rule_id):
    """Toggle rule enabled/disabled"""
    rule = next((r for r in config["rules"] if r["id"] == rule_id), None)
    
    if not rule:
        return jsonify({"error": "Rule not found"}), 404
    
    rule["enabled"] = not rule["enabled"]
    save_config()
    
    if rule["enabled"]:
        start_forwarder(rule)
    else:
        stop_forwarder(rule_id)
    
    return jsonify({"success": True, "enabled": rule["enabled"]})

@app.route('/api/cloudflared/generate', methods=['POST'])
def generate_cloudflared():
    """Generate cloudflared configuration"""
    config_file = generate_cloudflared_config()
    
    if config_file:
        return jsonify({
            "success": True,
            "config_file": config_file,
            "message": "Cloudflared configuration generated successfully"
        })
    else:
        return jsonify({
            "success": False,
            "message": "No rules with Cloudflare exposure enabled"
        }), 400

@app.route('/api/cloudflare/test', methods=['POST'])
def test_cloudflare_connection():
    """Test Cloudflare API connection"""
    data = request.json
    api_token = data.get("api_token", config.get("cloudflare_api_token"))
    
    if not api_token:
        return jsonify({"success": False, "error": "API token required"}), 400
    
    cf = CloudflareAPI(api_token)
    
    # Test by getting account ID
    account_id, error = cf.get_account_id()
    if error:
        return jsonify({"success": False, "error": error}), 400
    
    return jsonify({
        "success": True,
        "account_id": account_id,
        "message": "Cloudflare API connection successful"
    })


@app.route('/api/cloudflare/tunnels', methods=['GET'])
def list_tunnels():
    """List all Cloudflare tunnels"""
    api_token = config.get("cloudflare_api_token")
    account_id = config.get("cloudflare_account_id")
    
    if not api_token:
        return jsonify({"success": False, "error": "API token not configured"}), 400
    
    cf = CloudflareAPI(api_token, account_id)
    tunnels, error = cf.list_tunnels()
    
    if error:
        return jsonify({"success": False, "error": error}), 400
    
    return jsonify({"success": True, "tunnels": tunnels})


@app.route('/api/cloudflare/tunnel/create', methods=['POST'])
def create_tunnel():
    """Create a new Cloudflare tunnel"""
    data = request.json
    name = data.get("name", "gatekeeper-tunnel")
    api_token = config.get("cloudflare_api_token")
    
    if not api_token:
        return jsonify({"success": False, "error": "API token not configured"}), 400
    
    cf = CloudflareAPI(api_token)
    tunnel, error = cf.create_tunnel(name)
    
    if error:
        return jsonify({"success": False, "error": error}), 400
    
    # Get credentials
    credentials, _ = cf.get_tunnel_credentials(tunnel["id"])
    
    # Update config
    config["cloudflare_tunnel_id"] = tunnel["id"]
    save_config()
    
    return jsonify({
        "success": True,
        "tunnel_id": tunnel["id"],
        "tunnel_name": tunnel["name"],
        "credentials": credentials,
        "message": f"Tunnel '{name}' created successfully"
    })


@app.route('/api/cloudflare/dns/setup', methods=['POST'])
def setup_dns_records():
    """Setup DNS records for all enabled rules"""
    api_token = config.get("cloudflare_api_token")
    zone_id = config.get("cloudflare_zone_id")
    domain = config.get("cloudflare_domain")
    tunnel_id = config.get("cloudflare_tunnel_id")
    
    if not all([api_token, zone_id, domain, tunnel_id]):
        return jsonify({
            "success": False,
            "error": "Missing Cloudflare configuration (token, zone_id, domain, or tunnel_id)"
        }), 400
    
    cf = CloudflareAPI(api_token, zone_id=zone_id, domain=domain)
    results = []
    
    for rule in config["rules"]:
        if rule["enabled"] and rule["expose_cloudflare"]:
            subdomain = rule.get("subdomain", rule['name'].lower().replace(' ', '-'))
            success, error = cf.create_dns_record(subdomain, tunnel_id)
            results.append({
                "rule": rule["name"],
                "hostname": f"{subdomain}.{domain}",
                "success": success,
                "error": error
            })
    
    failed = [r for r in results if not r["success"]]
    return jsonify({
        "success": len(failed) == 0,
        "results": results,
        "message": f"DNS setup complete. {len(results) - len(failed)}/{len(results)} succeeded"
    })


@app.route('/api/cloudflare/dns/delete', methods=['POST'])
def delete_dns_record():
    """Delete a DNS record"""
    data = request.json
    subdomain = data.get("subdomain")
    
    if not subdomain:
        return jsonify({"success": False, "error": "Subdomain required"}), 400
    
    api_token = config.get("cloudflare_api_token")
    zone_id = config.get("cloudflare_zone_id")
    domain = config.get("cloudflare_domain")
    
    if not all([api_token, zone_id, domain]):
        return jsonify({"success": False, "error": "Cloudflare configuration incomplete"}), 400
    
    cf = CloudflareAPI(api_token, zone_id=zone_id, domain=domain)
    success, error = cf.delete_dns_record(subdomain)
    
    if error:
        return jsonify({"success": False, "error": error}), 400
    
    return jsonify({"success": True, "message": f"DNS record for {subdomain}.{domain} deleted"})


@app.route('/api/cloudflare/auto-setup', methods=['POST'])
def auto_setup_cloudflare():
    """One-click Cloudflare setup: create tunnel + DNS records"""
    data = request.json
    api_token = data.get("api_token")
    domain = data.get("domain")
    tunnel_name = data.get("tunnel_name", "gatekeeper")
    
    if not api_token or not domain:
        return jsonify({"success": False, "error": "API token and domain required"}), 400
    
    cf = CloudflareAPI(api_token, domain=domain)
    
    # Step 1: Get zone ID
    zone_id, error = cf.get_zone_id(domain)
    if error:
        return jsonify({"success": False, "error": f"Zone lookup failed: {error}"}), 400
    
    config["cloudflare_zone_id"] = zone_id
    config["cloudflare_domain"] = domain
    config["cloudflare_api_token"] = api_token
    
    # Step 2: Create tunnel
    tunnel, error = cf.create_tunnel(tunnel_name)
    if error:
        return jsonify({"success": False, "error": f"Tunnel creation failed: {error}"}), 400
    
    config["cloudflare_tunnel_id"] = tunnel["id"]
    
    # Step 3: Get credentials
    credentials, error = cf.get_tunnel_credentials(tunnel["id"])
    if error:
        logger.warning(f"Could not get tunnel credentials: {error}")
    
    # Step 4: Setup DNS for all rules
    cf.zone_id = zone_id
    dns_results = []
    for rule in config["rules"]:
        if rule["enabled"] and rule["expose_cloudflare"]:
            subdomain = rule.get("subdomain", rule['name'].lower().replace(' ', '-'))
            success, err = cf.create_dns_record(subdomain, tunnel["id"])
            dns_results.append({
                "hostname": f"{subdomain}.{domain}",
                "success": success,
                "error": err
            })
    
    save_config()
    generate_cloudflared_config()
    
    return jsonify({
        "success": True,
        "tunnel_id": tunnel["id"],
        "tunnel_name": tunnel["name"],
        "zone_id": zone_id,
        "credentials": credentials,
        "dns_results": dns_results,
        "message": f"Cloudflare setup complete! Tunnel '{tunnel_name}' created with {len(dns_results)} DNS records"
    })


@app.route('/api/cloudflare/setup-guide', methods=['GET'])
def get_setup_guide():
    """Get setup guide for clients"""
    guide = {
        "quick_start": """
# Quick Start with Cloudflare API

1. Get your Cloudflare API Token:
   - Go to https://dash.cloudflare.com/profile/api-tokens
   - Create a token with permissions:
     * Cloudflare Tunnel: Edit
     * Zone: Edit (for DNS)
     * Account: Read (for tunnel management)

2. In Gatekeeper UI:
   - Go to Cloudflare Settings tab
   - Enter your API token and domain
   - Click "Auto Setup" - it will create tunnel and DNS records automatically!

3. Download the generated config from cloudflared_configs/config.yml

4. Run cloudflared:
   cloudflared tunnel run --config cloudflared_configs/config.yml
""",
        "server_setup": """
# Manual Server Setup (Gateway Machine)

1. Install cloudflared:
   # Linux
   wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
   sudo dpkg -i cloudflared-linux-amd64.deb
   
   # macOS
   brew install cloudflared
   
   # Windows: Download from https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/

2. Authenticate with Cloudflare:
   cloudflared tunnel login

3. Create a tunnel:
   cloudflared tunnel create --name gatekeeper

4. Use the Generate Config button in Gatekeeper UI

5. Run the tunnel:
   cloudflared tunnel run --config ./cloudflared_configs/config.yml
   
   # Or as a service:
   cloudflared service install
""",
        "android_client": """
# Android Client Setup

## For RDP Access:
1. Install Microsoft Remote Desktop from Play Store
2. Add PC → Enter hostname: rdp.yourdomain.com (or your custom subdomain)
3. Port: Auto (3389)
4. Connect

## For SSH Access:
1. Install Termux or JuiceSSH from Play Store
2. Create new connection:
   - Host: ssh.yourdomain.com (or your custom subdomain)
   - Port: 22
   - Username: your_username

## Important Notes:
- Traffic is encrypted end-to-end through Cloudflare network
- No ports need to be opened on your firewall!
- Works from anywhere with internet access
""",
        "alternative_clients": """
# Alternative: Direct Connection (No Cloudflare)

If you're on the same network or have port forwarding:
- RDP: mstsc /v:GATEWAY_IP:GATEWAY_PORT
- SSH: ssh -p GATEWAY_PORT user@GATEWAY_IP
- VNC: vncviewer GATEWAY_IP::GATEWAY_PORT

# Alternative: Tailscale (Recommended for Personal Use)

1. Install Tailscale on Gateway and Android
2. Enable subnet routes on Gateway
3. Connect from Android using internal IPs directly
4. No port forwarding or Cloudflare needed!
"""
    }
    
    return jsonify(guide)

if __name__ == '__main__':
    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║        Gatekeeper v3.0 - Protocol Gateway + API          ║
    ║     Forward any TCP protocol with Cloudflare Auto-Setup  ║
    ╚══════════════════════════════════════════════════════════╝
    
    Web Interface: http://localhost:5000
    Log File: gatekeeper.log
    Config File: gatekeeper_config.json
    
    Features:
    • One-click Cloudflare tunnel creation via API
    • Automatic DNS record management (subdomain.yourdomain.com)
    • Manual tunnel configuration support
    • Real-time connection monitoring
    
    Press Ctrl+C to stop
    """)
    
    # Start all enabled forwarders
    for rule in config["rules"]:
        if rule["enabled"]:
            start_forwarder(rule)
    
    try:
        app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\nShutting down...")
        # Cleanup happens automatically as threads are daemon threads
