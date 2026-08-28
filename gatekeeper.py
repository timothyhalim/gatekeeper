#!/usr/bin/env python3
"""
Gatekeeper - A gateway application that forwards HTTP/HTTPS requests to RDP, SSH, or any TCP protocol.
Features:
- Web-based GUI for easy configuration
- Multiple forwarding rules support
- Real-time status monitoring
- Support for any TCP protocol (RDP, SSH, VNC, etc.)
"""

import socket
import threading
import json
import os
import sys
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration file path
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gatekeeper_config.json')


@dataclass
class ForwardingRule:
    """Represents a single forwarding rule"""
    id: int
    name: str
    gateway_port: int
    target_host: str
    target_port: int
    protocol: str  # rdp, ssh, vnc, custom
    enabled: bool = True
    created_at: str = ""
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


class GatekeeperManager:
    """Manages all forwarding rules and connections"""
    
    def __init__(self):
        self.rules: Dict[int, ForwardingRule] = {}
        self.active_connections: Dict[int, List[threading.Thread]] = {}
        self.running_servers: Dict[int, socket.socket] = {}
        self.next_id = 1
        self.load_config()
    
    def load_config(self):
        """Load configuration from file"""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    data = json.load(f)
                    self.next_id = data.get('next_id', 1)
                    for rule_data in data.get('rules', []):
                        rule = ForwardingRule(**rule_data)
                        self.rules[rule.id] = rule
                logger.info(f"Loaded {len(self.rules)} rules from config")
            except Exception as e:
                logger.error(f"Error loading config: {e}")
    
    def save_config(self):
        """Save configuration to file"""
        try:
            data = {
                'next_id': self.next_id,
                'rules': [asdict(rule) for rule in self.rules.values()]
            }
            with open(CONFIG_FILE, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info("Configuration saved")
        except Exception as e:
            logger.error(f"Error saving config: {e}")
    
    def add_rule(self, name: str, gateway_port: int, target_host: str, 
                 target_port: int, protocol: str) -> ForwardingRule:
        """Add a new forwarding rule"""
        rule = ForwardingRule(
            id=self.next_id,
            name=name,
            gateway_port=gateway_port,
            target_host=target_host,
            target_port=target_port,
            protocol=protocol.lower()
        )
        self.rules[rule.id] = rule
        self.next_id += 1
        self.save_config()
        return rule
    
    def remove_rule(self, rule_id: int) -> bool:
        """Remove a forwarding rule"""
        if rule_id in self.rules:
            self.stop_forwarding(rule_id)
            del self.rules[rule_id]
            self.save_config()
            return True
        return False
    
    def update_rule(self, rule_id: int, **kwargs) -> Optional[ForwardingRule]:
        """Update an existing rule"""
        if rule_id in self.rules:
            rule = self.rules[rule_id]
            for key, value in kwargs.items():
                if hasattr(rule, key):
                    setattr(rule, key, value)
            self.save_config()
            return rule
        return None
    
    def start_forwarding(self, rule_id: int) -> bool:
        """Start port forwarding for a rule"""
        if rule_id not in self.rules:
            return False
        
        rule = self.rules[rule_id]
        
        if not rule.enabled:
            return False
        
        if rule_id in self.running_servers:
            logger.warning(f"Forwarding already active for rule {rule_id}")
            return True
        
        try:
            # Create server socket
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind(('0.0.0.0', rule.gateway_port))
            server_socket.listen(5)
            server_socket.settimeout(1.0)  # Allow periodic checking
            
            self.running_servers[rule_id] = server_socket
            self.active_connections[rule_id] = []
            
            # Start accepting connections in a thread
            def accept_loop():
                while rule_id in self.running_servers:
                    try:
                        client_socket, addr = server_socket.accept()
                        logger.info(f"New connection from {addr} on port {rule.gateway_port}")
                        
                        # Create connection to target
                        try:
                            target_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            target_socket.connect((rule.target_host, rule.target_port))
                            logger.info(f"Connected to target {rule.target_host}:{rule.target_port}")
                            
                            # Start bidirectional forwarding
                            def forward(source, dest, rule_id, conn_id):
                                try:
                                    while True:
                                        data = source.recv(4096)
                                        if not data:
                                            break
                                        dest.sendall(data)
                                except Exception as e:
                                    logger.debug(f"Forwarding stopped: {e}")
                                finally:
                                    try:
                                        source.close()
                                        dest.close()
                                    except:
                                        pass
                            
                            # Forward client -> target
                            t1 = threading.Thread(
                                target=forward, 
                                args=(client_socket, target_socket, rule_id, f"{addr}-out"),
                                daemon=True
                            )
                            # Forward target -> client
                            t2 = threading.Thread(
                                target=forward, 
                                args=(target_socket, client_socket, rule_id, f"{addr}-in"),
                                daemon=True
                            )
                            
                            t1.start()
                            t2.start()
                            self.active_connections[rule_id].extend([t1, t2])
                            
                        except Exception as e:
                            logger.error(f"Failed to connect to target: {e}")
                            client_socket.close()
                    
                    except socket.timeout:
                        continue
                    except Exception as e:
                        if rule_id in self.running_servers:
                            logger.error(f"Error accepting connection: {e}")
                        break
            
            server_thread = threading.Thread(target=accept_loop, daemon=True)
            server_thread.start()
            
            logger.info(f"Started forwarding: 0.0.0.0:{rule.gateway_port} -> {rule.target_host}:{rule.target_port}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start forwarding: {e}")
            return False
    
    def stop_forwarding(self, rule_id: int) -> bool:
        """Stop port forwarding for a rule"""
        if rule_id in self.running_servers:
            try:
                self.running_servers[rule_id].close()
            except:
                pass
            del self.running_servers[rule_id]
            
            # Wait for active connections to close
            if rule_id in self.active_connections:
                self.active_connections[rule_id] = []  # Threads are daemon, will exit
            
            logger.info(f"Stopped forwarding for rule {rule_id}")
            return True
        return False
    
    def restart_forwarding(self, rule_id: int) -> bool:
        """Restart forwarding for a rule"""
        self.stop_forwarding(rule_id)
        return self.start_forwarding(rule_id)
    
    def start_all(self):
        """Start forwarding for all enabled rules"""
        for rule_id, rule in self.rules.items():
            if rule.enabled:
                self.start_forwarding(rule_id)
    
    def get_status(self) -> Dict:
        """Get current status of all rules"""
        status = {
            'rules': [],
            'total_rules': len(self.rules),
            'active_forwards': len(self.running_servers)
        }
        
        for rule in self.rules.values():
            rule_status = asdict(rule)
            rule_status['is_running'] = rule_id in self.running_servers if (rule_id := rule.id) else False
            status['rules'].append(rule_status)
        
        return status


# Global manager instance
manager = GatekeeperManager()


@app.route('/')
def index():
    """Main dashboard"""
    return render_template('index.html')


@app.route('/api/rules', methods=['GET'])
def get_rules():
    """Get all forwarding rules"""
    return jsonify(manager.get_status())


@app.route('/api/rules', methods=['POST'])
def create_rule():
    """Create a new forwarding rule"""
    data = request.json
    
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    required_fields = ['name', 'gateway_port', 'target_host', 'target_port', 'protocol']
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'Missing required field: {field}'}), 400
    
    # Validate port numbers
    try:
        gateway_port = int(data['gateway_port'])
        target_port = int(data['target_port'])
        if not (1 <= gateway_port <= 65535) or not (1 <= target_port <= 65535):
            raise ValueError("Port must be between 1 and 65535")
    except ValueError as e:
        return jsonify({'error': f'Invalid port number: {e}'}), 400
    
    # Check if port is already in use
    for rule in manager.rules.values():
        if rule.gateway_port == gateway_port and rule.id != data.get('id'):
            return jsonify({'error': f'Port {gateway_port} is already in use'}), 400
    
    rule = manager.add_rule(
        name=data['name'],
        gateway_port=gateway_port,
        target_host=data['target_host'],
        target_port=target_port,
        protocol=data['protocol']
    )
    
    # Auto-start if enabled
    if data.get('enabled', True):
        manager.start_forwarding(rule.id)
    
    return jsonify(asdict(rule)), 201


@app.route('/api/rules/<int:rule_id>', methods=['PUT'])
def update_rule(rule_id: int):
    """Update an existing rule"""
    data = request.json
    
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    rule = manager.update_rule(rule_id, **data)
    if rule:
        # Restart forwarding if rule was modified
        if rule.enabled:
            manager.restart_forwarding(rule_id)
        else:
            manager.stop_forwarding(rule_id)
        return jsonify(asdict(rule))
    else:
        return jsonify({'error': 'Rule not found'}), 404


@app.route('/api/rules/<int:rule_id>', methods=['DELETE'])
def delete_rule(rule_id: int):
    """Delete a forwarding rule"""
    if manager.remove_rule(rule_id):
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Rule not found'}), 404


@app.route('/api/rules/<int:rule_id>/toggle', methods=['POST'])
def toggle_rule(rule_id: int):
    """Toggle a rule on/off"""
    if rule_id not in manager.rules:
        return jsonify({'error': 'Rule not found'}), 404
    
    rule = manager.rules[rule_id]
    rule.enabled = not rule.enabled
    
    if rule.enabled:
        manager.start_forwarding(rule_id)
    else:
        manager.stop_forwarding(rule_id)
    
    manager.save_config()
    return jsonify(asdict(rule))


@app.route('/api/rules/<int:rule_id>/restart', methods=['POST'])
def restart_rule(rule_id: int):
    """Restart forwarding for a rule"""
    if rule_id not in manager.rules:
        return jsonify({'error': 'Rule not found'}), 404
    
    if manager.restart_forwarding(rule_id):
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Failed to restart forwarding'}), 500


@app.route('/api/start-all', methods=['POST'])
def start_all():
    """Start all enabled rules"""
    manager.start_all()
    return jsonify({'success': True})


@app.route('/api/stop-all', methods=['POST'])
def stop_all():
    """Stop all forwarding"""
    for rule_id in list(manager.running_servers.keys()):
        manager.stop_forwarding(rule_id)
    return jsonify({'success': True})


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Gatekeeper - Protocol Gateway')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind the web interface')
    parser.add_argument('--port', type=int, default=5000, help='Port for the web interface')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    parser.add_argument('--start-all', action='store_true', help='Start all rules on startup')
    
    args = parser.parse_args()
    
    # Create templates directory if it doesn't exist
    template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
    os.makedirs(template_dir, exist_ok=True)
    
    if args.start_all:
        logger.info("Starting all enabled rules...")
        manager.start_all()
    
    logger.info(f"Starting Gatekeeper web interface on {args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)
