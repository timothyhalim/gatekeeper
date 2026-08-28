#!/usr/bin/env python3
"""
Gatekeeper v2.0 - Complete Protocol Gateway with Cloudflare Tunnel Support
Forwards any TCP protocol (RDP, SSH, VNC, etc.) from internet to local machines

Architecture:
  Client (Android) → Cloudflare Edge → cloudflared → Gateway → Target Machine

Features:
  - Web GUI for managing port forwarding rules
  - Cloudflare Tunnel TCP configuration generator
  - Real-time connection monitoring
  - Persistent configuration storage
"""

import os
import sys
import json
import socket
import threading
import logging
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_from_directory
import subprocess
import signal

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
    
    for rule in config["rules"]:
        if rule["enabled"] and rule["expose_cloudflare"]:
            ingress_rules.append({
                "hostname": f"{rule['name'].lower().replace(' ', '-')}.yourdomain.com",
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
    try:
        import yaml
        with open(config_file, 'w') as f:
            yaml.dump(cloudflared_config, f, default_flow_style=False)
        
        logger.info(f"Generated cloudflared config: {config_file}")
        return config_file
    except ImportError:
        # Fallback to manual YAML generation
        with open(config_file, 'w') as f:
            f.write(f"tunnel: {config['cloudflare_tunnel_id']}\n")
            f.write("credentials-file: /home/user/.cloudflared/tunnel_credentials.json\n")
            f.write("ingress:\n")
            for rule_ingress in ingress_rules:
                if "hostname" in rule_ingress:
                    f.write(f"  - hostname: {rule_ingress['hostname']}\n")
                    f.write(f"    service: {rule_ingress['service']}\n")
                else:
                    f.write(f"  - service: {rule_ingress['service']}\n")
            f.write("warp-routing:\n")
            f.write("  enabled: true\n")
        
        logger.info(f"Generated cloudflared config (manual YAML): {config_file}")
        return config_file

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

@app.route('/api/cloudflared/setup-guide', methods=['GET'])
def get_setup_guide():
    """Get setup guide for clients"""
    guide = {
        "server_setup": """
# Server Setup (Gateway Machine)

1. Install cloudflared:
   # Linux
   wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
   sudo dpkg -i cloudflared-linux-amd64.deb
   
   # Or download from: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/

2. Authenticate with Cloudflare:
   cloudflared tunnel login

3. Create a tunnel:
   cloudflared tunnel create --name gatekeeper

4. Copy the generated config to ./cloudflared_configs/config.yml
   (or use the Generate Config button in this UI)

5. Run the tunnel:
   cloudflared tunnel run --config ./cloudflared_configs/config.yml
""",
        "android_client": """
# Android Client Setup

## For RDP Access:
1. Install Microsoft Remote Desktop from Play Store
2. Add PC → Enter hostname: rdp-yourname.yourdomain.com
3. Port: Auto (3389)
4. Connect

## For SSH Access:
1. Install Termux or JuiceSSH from Play Store
2. Create new connection:
   - Host: ssh-yourname.yourdomain.com
   - Port: 22
   - Username: your_username

## Important Notes:
- You need a Cloudflare domain configured
- DNS records are automatically created by cloudflared
- Traffic is encrypted end-to-end through Cloudflare network
- No ports need to be opened on your firewall!
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
    ║           Gatekeeper v2.0 - Protocol Gateway             ║
    ║     Forward any TCP protocol through Cloudflare Tunnel   ║
    ╚══════════════════════════════════════════════════════════╝
    
    Web Interface: http://localhost:5000
    Log File: gatekeeper.log
    Config File: gatekeeper_config.json
    
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
