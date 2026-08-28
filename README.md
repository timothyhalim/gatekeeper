# Gatekeeper - Protocol Gateway & Port Forwarding Manager

A powerful web-based application that forwards TCP traffic (HTTP/HTTPS, RDP, SSH, VNC, or any custom protocol) from a gateway machine to target machines on your network.

## Features

- **Web-based GUI**: Easy-to-use interface for managing forwarding rules
- **Multiple Protocol Support**: RDP, SSH, VNC, HTTP, HTTPS, or custom TCP protocols
- **Real-time Monitoring**: View active connections and rule status
- **Persistent Configuration**: Rules are saved and restored on restart
- **Multiple Rules**: Configure multiple forwarding rules simultaneously
- **Start/Stop Controls**: Individual or bulk control of forwarding rules
- **Auto-refresh**: Dashboard updates every 5 seconds

## Use Case Example

```
Android Phone → RDP → Cloudflare Tunnel → Gateway (192.168.1.2:1234) → RDP Machine (192.168.1.3:3389)
```

## Installation

### Requirements

- Python 3.8+
- Flask

### Install Dependencies

```bash
pip install flask
```

## Usage

### Basic Start

```bash
python gatekeeper.py
```

This starts the web interface on `http://0.0.0.0:5000`

### Command Line Options

```bash
python gatekeeper.py --host 0.0.0.0 --port 5000 --debug --start-all
```

- `--host`: Host to bind the web interface (default: 0.0.0.0)
- `--port`: Port for the web interface (default: 5000)
- `--debug`: Enable debug mode for development
- `--start-all`: Automatically start all enabled rules on startup

### Running in Background

```bash
# Using nohup
nohup python gatekeeper.py --start-all > gatekeeper.log 2>&1 &

# Or using screen
screen -S gatekeeper
python gatekeeper.py --start-all
# Press Ctrl+A, then D to detach
```

## Web Interface

Access the web interface at `http://your-gateway-ip:5000`

### Creating a Forwarding Rule

1. Open the web interface in your browser
2. Fill in the form:
   - **Rule Name**: A descriptive name (e.g., "Home RDP")
   - **Gateway Port**: The port on the gateway machine (e.g., 3389)
   - **Target Host IP**: The internal IP of the target machine (e.g., 192.168.1.100)
   - **Target Port**: The port on the target machine (e.g., 3389 for RDP)
   - **Protocol**: Select the protocol type (RDP, SSH, VNC, etc.)
   - **Enable immediately**: Check to start forwarding right away
3. Click "Add Rule"

### Managing Rules

- **Enable/Disable**: Toggle individual rules on/off
- **Restart**: Restart a forwarding rule
- **Edit**: Modify rule settings
- **Delete**: Remove a rule permanently
- **Start All/Stop All**: Bulk operations for all rules

## Configuration File

Rules are automatically saved to `gatekeeper_config.json` in the same directory. This file is loaded on startup.

## API Endpoints

The application provides a REST API for programmatic control:

- `GET /api/rules` - Get all rules and status
- `POST /api/rules` - Create a new rule
- `PUT /api/rules/<id>` - Update a rule
- `DELETE /api/rules/<id>` - Delete a rule
- `POST /api/rules/<id>/toggle` - Toggle a rule on/off
- `POST /api/rules/<id>/restart` - Restart a rule
- `POST /api/start-all` - Start all enabled rules
- `POST /api/stop-all` - Stop all rules

## Security Considerations

1. **Firewall**: Ensure only necessary ports are exposed on your gateway
2. **Authentication**: Consider placing the web interface behind authentication
3. **HTTPS**: For production, use a reverse proxy (nginx, Apache) with SSL
4. **Network Isolation**: Keep the gateway on a separate network segment if possible
5. **Port Selection**: Avoid using well-known ports unless necessary

## Example Scenarios

### Remote Desktop Access

```
Gateway Port: 3389
Target: 192.168.1.100:3389
Protocol: RDP
```

### SSH Access to Multiple Machines

```
Rule 1:
  Gateway Port: 2222
  Target: 192.168.1.101:22
  Protocol: SSH

Rule 2:
  Gateway Port: 2223
  Target: 192.168.1.102:22
  Protocol: SSH
```

### Web Server Access

```
Gateway Port: 8080
Target: 192.168.1.50:80
Protocol: HTTP
```

## Troubleshooting

### Port Already in Use

If you get a "Port already in use" error:
- Check if another service is using the port: `netstat -tlnp | grep <port>`
- Choose a different gateway port
- Stop the conflicting service

### Connection Refused

If clients can't connect:
- Verify the gateway firewall allows the port
- Check if the target machine is reachable from the gateway
- Ensure the target service is running

### Rules Not Persisting

- Check write permissions in the installation directory
- Verify `gatekeeper_config.json` is not corrupted

## Alternative Solutions

If you need more advanced features, consider these existing tools:

1. **socat** - Command-line utility for bidirectional data transfer
2. **ngrok** - Secure tunnels to localhost with cloud endpoints
3. **frp (Fast Reverse Proxy)** - High-performance reverse proxy
4. **chisel** - Fast TCP/UDP tunnel over HTTP
5. **sshuttle** - Transparent proxy over SSH
6. **WireGuard/OpenVPN** - Full VPN solutions

## License

MIT License - Feel free to use and modify as needed!

## Support

For issues or feature requests, please check the documentation or submit a bug report.