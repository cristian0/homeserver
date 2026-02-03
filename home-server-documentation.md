# Home Server Documentation

## Overview

| Item | Value |
|------|-------|
| Hardware | Fujitsu Q916 |
| OS | Debian |
| Server IP | 192.168.1.10 |
| Router IP | 192.168.1.1 |
| Public IP | 2.229.233.252 |
| VPN Subnet | 10.8.0.0/24 |

### Services Summary

| Service | Port | URL |
|---------|------|-----|
| Dashboard | 80 | http://192.168.1.10 |
| Home Assistant | 8123 | http://192.168.1.10:8123 |
| Pi-hole | 8080 | http://192.168.1.10:8080/admin |
| WireGuard Admin | 51821 | http://192.168.1.10:51821 |
| WireGuard VPN | 51820/UDP | - |
| DNS (Pi-hole) | 53 | - |
| KOReader Sync | 7200 | http://192.168.1.10:7200 |
| Beszel | 8090 | http://192.168.1.10:8090 |

---

## 1. WiFi Driver Setup (RTL8188FTV)

The USB WiFi adapter uses chipset **Realtek RTL8188FTV** (USB ID: `0bda:f179`). The driver was already bundled in Debian.

### Verify Interface

```bash
ip a
iwconfig
```

A wireless interface (`wlan0` or `wlx...`) should appear.

### Connect to WiFi

```bash
sudo apt install network-manager
sudo systemctl enable NetworkManager
sudo systemctl start NetworkManager
nmtui
```

Select "Activate a connection" → choose network → enter password.

---

## 2. Network Configuration (Static IP)

### Enable IP Forwarding (required for VPN)

```bash
echo "net.ipv4.ip_forward=1" | sudo tee -a /etc/sysctl.conf
echo "net.ipv4.conf.all.src_valid_mark=1" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

### Configure iptables for VPN (required for internet access via VPN)

**Why this is needed:** The WireGuard container (wg-easy) uses `network_mode: host` so that Pi-hole can see individual VPN client IPs (10.8.0.2, 10.8.0.3, etc.) instead of a single Docker bridge IP. With bridge networking, Docker handles NAT automatically, but with host networking, NAT must be configured.

**Note:** WireGuard now auto-configures these rules via `WG_POST_UP`/`WG_POST_DOWN` environment variables in docker-compose.yml. The manual commands below are only needed for troubleshooting or if the automatic configuration fails.

Manual NAT masquerade and forwarding rules (if needed):

```bash
sudo iptables -t nat -A POSTROUTING -s 10.8.0.0/24 -j MASQUERADE
sudo iptables -A FORWARD -s 10.8.0.0/24 -j ACCEPT
sudo iptables -A FORWARD -d 10.8.0.0/24 -j ACCEPT
```

Save rules to persist across reboots:

```bash
sudo apt install iptables-persistent -y
sudo netfilter-persistent save
```

### Configure WiFi Static IP

Find connection name:

```bash
nmcli connection show
```

Set static IP:

```bash
nmcli connection modify "YOUR_WIFI_NAME" \
  ipv4.method manual \
  ipv4.addresses 192.168.1.10/24 \
  ipv4.gateway 192.168.1.1 \
  ipv4.dns "8.8.8.8"
```

Restart connection:

```bash
nmcli connection down "YOUR_WIFI_NAME"
nmcli connection up "YOUR_WIFI_NAME"
```

### Configure Ethernet Static IP

Create ethernet connection:

```bash
nmcli connection add \
  con-name "Ethernet" \
  type ethernet \
  ifname enp0s25 \
  ipv4.method manual \
  ipv4.addresses 192.168.1.10/24 \
  ipv4.gateway 192.168.1.1 \
  ipv4.dns "8.8.8.8"
```

### Ensure NetworkManager Manages Ethernet

Edit `/etc/network/interfaces` to contain only:

```
auto lo
iface lo inet loopback
```

Then restart NetworkManager:

```bash
sudo systemctl restart NetworkManager
```

---

## 3. Docker Installation

### Install Prerequisites

```bash
sudo apt install -y ca-certificates curl gnupg
```

### Add Docker Repository

```bash
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
```

### Install Docker

```bash
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
```

### Add User to Docker Group

```bash
sudo /usr/sbin/usermod -aG docker $USER
newgrp docker
```

### Enable Docker on Boot

```bash
sudo systemctl enable docker
```

### Verify

```bash
docker --version
docker compose version
```

---

## 4. Directory Structure

```bash
mkdir -p /srv/docker/homeassistant
mkdir -p /srv/docker/pihole/etc-pihole
mkdir -p /srv/docker/pihole/etc-dnsmasq.d
mkdir -p /srv/docker/dashboard
mkdir -p /srv/docker/wireguard
mkdir -p /srv/docker/koreader-sync/logs/app
mkdir -p /srv/docker/koreader-sync/logs/redis
mkdir -p /srv/docker/koreader-sync/data/redis
mkdir -p /srv/docker/beszel/data
mkdir -p /srv/docker/beszel/socket
sudo chown -R $USER:$USER /srv/docker
```

---

## 5. Environment Variables

Create `/srv/docker/.env`:

```bash
nano /srv/docker/.env
```

Content:

```
PIHOLE_PASSWORD=your_pihole_password_here
WG_PASSWORD_HASH=$2a$12$your_bcrypt_hash_here
BESZEL_KEY=ssh-ed25519_your_public_key_here
BESZEL_TOKEN=your_token_here
```

Secure the file:

```bash
chmod 600 /srv/docker/.env
```

### Generate WireGuard Password Hash

```bash
docker run -it --rm ghcr.io/wg-easy/wg-easy wgpw 'YOUR_PASSWORD_HERE'
```

Copy the output hash to `.env`.

### Beszel Key and Token

The `BESZEL_KEY` and `BESZEL_TOKEN` values are obtained from the Beszel web UI when adding a new system. See Section 17 for setup instructions.

---

## 6. Docker Compose Configuration

The full configuration is in `docker-compose.yml` in the repository.

**Key design decisions:**
- Both `pihole` and `wg-easy` use `network_mode: host` so that Pi-hole can see real client IPs instead of Docker's internal bridge IP
- WireGuard auto-configures NAT rules via `WG_POST_UP`/`WG_POST_DOWN`
- The `BESZEL_KEY` and `BESZEL_TOKEN` must be configured in `.env` after initial Beszel setup (see Section 14)

---

## 7. Dashboard

The dashboard HTML is in `dashboard/index.html` in the repository. It is served by the nginx container on port 80.

---

## 8. Start Services

```bash
cd /srv/docker
docker compose up -d
```

### Verify

```bash
docker compose ps
docker compose logs -f
```

---

## 9. Pi-hole DHCP Configuration

Since the router doesn't allow changing DNS settings, Pi-hole acts as DHCP server.

### Steps

1. Disable DHCP on router (192.168.1.1)
2. Go to Pi-hole admin: http://192.168.1.10:8080/admin
3. Settings → DHCP
4. Enable "DHCP server enabled"
5. Set range: `192.168.1.50` - `192.168.1.200`
6. Gateway: `192.168.1.1`
7. Save

### Recovery (if Pi-hole is down)

Set static IP manually on a device:
- IP: `192.168.1.200`
- Subnet: `255.255.255.0`
- Gateway: `192.168.1.1`
- DNS: `8.8.8.8`

---

## 10. Router Configuration

### Port Forwarding

Forward only one port:

| External Port | Protocol | Internal IP | Internal Port |
|---------------|----------|-------------|---------------|
| 51820 | UDP | 192.168.1.10 | 51820 |

### Security

- Close all other inbound ports
- Only WireGuard VPN is exposed to internet
- All other services accessible only via VPN or local network

---

## 11. WireGuard Client Setup

### Access Admin UI

http://192.168.1.10:51821

### Create New Client

1. Click "New Client"
2. Enter name (e.g., "iPhone-Cristiano")
3. Download or scan QR code

### Client Config Example

```ini
[Interface]
Address = 10.8.0.2/24
PrivateKey = xxxxx
DNS = 192.168.1.10

[Peer]
PublicKey = /5rDmoklZVXlOzQNieS0U48CeWmPk4TkTWSgsQfETz4=
AllowedIPs = 192.168.1.0/24, 10.8.0.0/24
Endpoint = 2.229.233.252:51820
```

**Note:** Change `AllowedIPs` from `0.0.0.0/0` to `192.168.1.0/24, 10.8.0.0/24` to only route home network traffic through VPN.

### VPN Client IPs

| Device | VPN IP |
|--------|--------|
| Mac | 10.8.0.2 |
| iPhone | 10.8.0.3 |

---

## 12. Pi-hole Client Naming

To see friendly names instead of IPs in Pi-hole dashboard:

### Option 1: Web UI

Pi-hole admin → Local DNS → DNS Records

Add A records:
- `iphone-cristiano` → `10.8.0.3`
- `mac-cristiano` → `10.8.0.2`

### Option 2: Custom Hosts File

Edit `/srv/docker/pihole/etc-pihole/custom.list`:

```
10.8.0.2 mac-cristiano
10.8.0.3 iphone-cristiano
```

Restart Pi-hole:

```bash
docker compose restart pihole
```

### Dashboard Names

Tools → Network → Find IP → Add name


---

## 13. KOReader Sync Client Configuration

KOReader Sync server runs on port 7200 and syncs reading progress across devices.

- **URL**: `http://192.168.1.10:7200`
- **Access**: Local network or VPN only

### Device Setup

On any device running KOReader (Kindle, Mac, etc.):

1. Open any book → tap top of screen → **Tools** → **Progress sync**
2. Set **Server** to `http://192.168.1.10:7200`
3. Enter a **Username** and **Password**
4. Tap **Register** (first time only), then **Login**

Use the same credentials on all devices to keep reading positions in sync.

---

## 14. Beszel (Server Monitoring)

Beszel is a lightweight server monitoring tool with Docker container stats, historical data, and alerting.

### Architecture

- **Hub**: Web dashboard (port 8090)
- **Agent**: Collects metrics from the host system
- **Communication**: Unix socket (hub and agent on same machine)

### Directory Setup

```bash
mkdir -p /srv/docker/beszel/data
mkdir -p /srv/docker/beszel/socket
```

### Docker Compose Configuration

See Section 6 for the complete docker-compose.yml including Beszel services.

### Initial Setup

1. Start the hub first:

```bash
docker compose up -d beszel
```

2. Access web UI: http://192.168.1.10:8090

3. Create admin account on first visit

4. Click **Add System** → select "Same system (Docker socket)"

5. Copy the **KEY** and **TOKEN** values from the dialog

6. Add the values to `/srv/docker/.env`:

```bash
nano /srv/docker/.env
```

Add:

```
BESZEL_KEY=ssh-ed25519_your_key_here
BESZEL_TOKEN=your_token_here
```

7. Start the agent:

```bash
docker compose up -d beszel-agent
```

8. In the web UI, click **Add System** to complete the connection

### Features

- **System Metrics**: CPU, memory, disk usage, network I/O, temperature
- **Docker Stats**: Per-container CPU, memory, and network usage
- **Historical Data**: View metrics over time
- **Alerts**: Configurable thresholds for CPU, memory, disk, bandwidth, temperature

### Troubleshooting

#### Agent not connecting

Check agent logs:

```bash
docker logs beszel-agent --tail 30
```

Verify socket directory permissions:

```bash
ls -la /srv/docker/beszel/socket/
```

#### No Docker stats showing

Ensure Docker socket is mounted:

```bash
docker inspect beszel-agent | grep -A5 Mounts
```

#### Restart Beszel services

```bash
docker compose restart beszel beszel-agent
```

---

## 15. Accessing Services

### From Local Network

| Service | URL |
|---------|-----|
| Dashboard | http://192.168.1.10 |
| Home Assistant | http://192.168.1.10:8123 |
| Pi-hole | http://192.168.1.10:8080/admin |
| WireGuard Admin | http://192.168.1.10:51821 |
| KOReader Sync | http://192.168.1.10:7200 |
| Beszel | http://192.168.1.10:8090 |

### From Outside (VPN Required)

1. Enable WireGuard VPN on device
2. Use same URLs as local network

**Note:** KOReader Sync is only accessible from local network. Devices must be connected to home network or VPN to sync.

---

## 16. Maintenance Commands

### View running containers

```bash
docker compose ps
```

### View logs

```bash
docker compose logs -f [service_name]
```

### Restart a service

```bash
docker compose restart [service_name]
```

### Update containers

```bash
cd /srv/docker
docker compose pull
docker compose up -d
```

### Reboot server

```bash
sudo reboot
```

All services will restart automatically (restart: unless-stopped).

---

## 17. Troubleshooting

### VPN connected but no internet

WireGuard auto-configures NAT rules via `WG_POST_UP`/`WG_POST_DOWN`. If internet still doesn't work, check the rules manually.

Check iptables rules:

```bash
sudo iptables -t nat -L -n | grep 10.8
sudo iptables -L FORWARD -v -n
```

If missing, add them manually:

```bash
sudo iptables -t nat -A POSTROUTING -s 10.8.0.0/24 -j MASQUERADE
sudo iptables -A FORWARD -s 10.8.0.0/24 -j ACCEPT
sudo iptables -A FORWARD -d 10.8.0.0/24 -j ACCEPT
sudo netfilter-persistent save
```

### Can't connect to VPN

```bash
docker logs wg-easy --tail 30
sudo lsof -i :51820
```

### Pi-hole not resolving

```bash
docker compose restart pihole
```

### Check WireGuard connections

```bash
docker exec wg-easy wg show
```

### Check listening ports

```bash
sudo lsof -i -P -n | grep LISTEN
```

### KOReader Sync not working

Check service status:

```bash
docker compose logs koreader-sync --tail 50
```

Verify service is accessible:

```bash
curl http://192.168.1.10:7200/healthcheck
```

Restart service:

```bash
docker compose restart koreader-sync
```

---

## 18. File Structure Summary

```
/srv/docker/
├── .env                          # Passwords and secrets (chmod 600)
├── docker-compose.yml            # Main configuration
├── homeassistant/                # Home Assistant config
├── pihole/
│   ├── etc-pihole/
│   │   └── custom.list           # Custom DNS names
│   └── etc-dnsmasq.d/
├── dashboard/
│   └── index.html                # Dashboard page
├── wireguard/                    # WireGuard config
├── koreader-sync/                # KOReader sync server
│   ├── logs/
│   │   ├── app/                  # Application logs
│   │   └── redis/                # Redis logs
│   └── data/
│       └── redis/                # Redis data
└── beszel/                       # Beszel monitoring
    ├── data/                     # Hub database
    └── socket/                   # Hub-agent unix socket
```

---
