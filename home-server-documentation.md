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

**Note:** NAT and forwarding rules for VPN are now automatically configured by WireGuard via the `WG_POST_UP` and `WG_POST_DOWN` environment variables in docker-compose.yml. Manual iptables configuration is no longer required.

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

---

## 6. Docker Compose Configuration

Create `/srv/docker/docker-compose.yml`:

**Note:** Both `pihole` and `wg-easy` use `network_mode: host` so that Pi-hole can see real client IPs instead of Docker's internal bridge IP. WireGuard now automatically configures NAT via `WG_POST_UP` and `WG_POST_DOWN` environment variables.

```yaml
services:
  homeassistant:
    container_name: homeassistant
    image: "ghcr.io/home-assistant/home-assistant:stable"
    volumes:
      - ./homeassistant:/config
      - /etc/localtime:/etc/localtime:ro
      - /run/dbus:/run/dbus:ro
    restart: unless-stopped
    privileged: true
    network_mode: host
    environment:
      TZ: Europe/Rome

  pihole:
    container_name: pihole
    image: pihole/pihole:latest
    network_mode: host
    environment:
      TZ: Europe/Rome
      FTLCONF_webserver_api_password: ${PIHOLE_PASSWORD}
      FTLCONF_dns_listeningMode: all
      FTLCONF_webserver_port: 8080
    volumes:
      - ./pihole/etc-pihole:/etc/pihole
      - ./pihole/etc-dnsmasq.d:/etc/dnsmasq.d
    cap_add:
      - NET_ADMIN
    restart: unless-stopped

  dashboard:
    container_name: dashboard
    image: nginx:alpine
    ports:
      - "80:80"
    volumes:
      - ./dashboard:/usr/share/nginx/html:ro
    restart: unless-stopped

  wg-easy:
    container_name: wg-easy
    image: ghcr.io/wg-easy/wg-easy
    network_mode: host
    environment:
      WG_HOST: 2.229.233.252
      PASSWORD_HASH: ${WG_PASSWORD_HASH}
      WG_DEFAULT_DNS: 192.168.1.10
      WG_PORT: 51820
      PORT: 51821
      WG_POST_UP: iptables -t nat -A POSTROUTING -s 10.8.0.0/24 -j MASQUERADE
      WG_POST_DOWN: iptables -t nat -D POSTROUTING -s 10.8.0.0/24 -j MASQUERADE
    volumes:
      - ./wireguard:/etc/wireguard
    cap_add:
      - NET_ADMIN
      - SYS_MODULE
    restart: unless-stopped

  koreader-sync:
    container_name: koreader-sync
    image: koreader/kosync:latest
    ports:
      - "7200:7200"
    environment:
      - ENABLE_USER_REGISTRATION=true
    volumes:
      - ./koreader-sync/logs/app:/app/koreader-sync-server/logs
      - ./koreader-sync/logs/redis:/var/log/redis
      - ./koreader-sync/data/redis:/var/lib/redis
    restart: unless-stopped
```

---

## 7. Dashboard HTML

Create `/srv/docker/dashboard/index.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Home Server</title>
  <style>
    body {
      font-family: system-ui, sans-serif;
      background: #1a1a2e;
      color: #eee;
      display: flex;
      justify-content: center;
      align-items: center;
      min-height: 100vh;
      margin: 0;
    }
    .container { text-align: center; }
    h1 { margin-bottom: 2rem; }
    .services { display: flex; gap: 1rem; flex-wrap: wrap; justify-content: center; }
    a {
      display: block;
      background: #16213e;
      padding: 1.5rem 2rem;
      border-radius: 8px;
      color: #fff;
      text-decoration: none;
      min-width: 150px;
    }
    a:hover { background: #0f3460; }
    .port { font-size: 0.8rem; color: #888; }
  </style>
</head>
<body>
  <div class="container">
    <h1>🏠 Home Server</h1>
    <div class="services">
      <a href="http://192.168.1.10:8123">
        Home Assistant
        <div class="port">:8123</div>
      </a>
      <a href="http://192.168.1.10:8080/admin">
        Pi-hole
        <div class="port">:8080</div>
      </a>
      <a href="http://192.168.1.10:51821">
        WireGuard
        <div class="port">:51821</div>
      </a>
      <a href="http://192.168.1.10:7200">
        KOReader Sync
        <div class="port">:7200</div>
      </a>
    </div>
  </div>
</body>
</html>
```

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

## 13. KOReader Sync Server Setup

KOReader Sync Server synchronizes reading progress across devices running KOReader.

### Service Details

- **Access**: Local network only (http://192.168.1.10:7200)
- **Registration**: Open (enabled via `ENABLE_USER_REGISTRATION=true`)
- **Function**: Syncs reading positions between devices

### Configure KOReader on Kindle

1. On your jailbroken Kindle with KOReader installed:
2. Open any book in KOReader
3. Tap the top of the screen → Tools (⚙️) → Progress sync
4. Enable "Progress sync"
5. Configure server settings:
   - **Server**: `http://192.168.1.10:7200`
   - **Username**: (create your username)
   - **Password**: (create your password)
6. Tap "Register" (first time only)
7. Tap "Login"

### Configure KOReader on Mac

1. Install KOReader on Mac (if not already installed)
2. Open KOReader
3. Access Settings → Network → Progress sync
4. Enable "Progress sync"
5. Configure server settings:
   - **Server**: `http://192.168.1.10:7200`
   - **Username**: (same as Kindle)
   - **Password**: (same as Kindle)
6. Tap "Login"

### Sync Behavior

- Reading positions sync automatically when online and connected to local network
- Sync occurs when you close a book or at regular intervals
- Last read position is synced across all devices using the same account

### Troubleshooting

Check if service is running:

```bash
docker compose logs koreader-sync
```

Test server access:

```bash
curl http://192.168.1.10:7200/healthcheck
```

---

## 14. Accessing Services

### From Local Network

| Service | URL |
|---------|-----|
| Dashboard | http://192.168.1.10 |
| Home Assistant | http://192.168.1.10:8123 |
| Pi-hole | http://192.168.1.10:8080/admin |
| WireGuard Admin | http://192.168.1.10:51821 |
| KOReader Sync | http://192.168.1.10:7200 |

### From Outside (VPN Required)

1. Enable WireGuard VPN on device
2. Use same URLs as local network

**Note:** KOReader Sync is only accessible from local network. Devices must be connected to home network or VPN to sync.

---

## 15. Maintenance Commands

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

## 16. Troubleshooting

### VPN connected but no internet

NAT/forwarding is configured automatically via WireGuard's `WG_POST_UP` environment variable. If issues persist, verify IP forwarding is enabled:

```bash
sudo sysctl net.ipv4.ip_forward
```

Should return `net.ipv4.ip_forward = 1`. If not, see Section 2.

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

## 17. File Structure Summary

```
/srv/docker/
├── .env                          # Passwords (chmod 600)
├── docker-compose.yml            # Main configuration
├── homeassistant/                # Home Assistant config
├── pihole/
│   ├── etc-pihole/
│   │   └── custom.list           # Custom DNS names
│   └── etc-dnsmasq.d/
├── dashboard/
│   └── index.html                # Dashboard page
├── wireguard/                    # WireGuard config
└── koreader-sync/
    ├── logs/
    │   ├── app/                  # Application logs
    │   └── redis/                # Redis logs
    └── data/
        └── redis/                # Redis data
```
