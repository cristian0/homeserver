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
| Music Assistant | 8095 | http://192.168.1.10:8095 |
| Coach Ginnastica | 8098 | http://192.168.1.10:8098 |

---

## 1. WiFi Driver Setup (RTL8188FTV)

> **Note (2026-05-29):** The server now runs on **wired Ethernet** (`enp0s25`, static `192.168.1.10`) as its primary and only active connection. The USB WiFi adapter below caused recurring network drops that left the box unreachable until a physical reboot — see [FREEZE-INVESTIGATION.md](FREEZE-INVESTIGATION.md). The WiFi profile is kept for reference / emergency fallback only (`connection.autoconnect=no`); re-enable manually with `nmcli connection up pertugio` if ever needed.

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
mkdir -p /srv/docker/music-assistant/data
mkdir -p /srv/docker/coach/data
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

The `BESZEL_KEY` and `BESZEL_TOKEN` values are obtained from the Beszel web UI when adding a new system. See Section 14 for setup instructions.

---

## 6. Docker Compose Configuration

The full configuration is in `docker-compose.yml` in the repository.

**Key design decisions:**
- `pihole`, `wg-easy`, and `music-assistant` use `network_mode: host` — Pi-hole for real client IPs, Music Assistant for mDNS/uPnP player discovery
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

> **Status (2026-06-02): Pi-hole DHCP is currently DISABLED — the router serves DHCP.**
> This is deliberate: when the server went down, having Pi-hole as the only DHCP server took
> down connectivity for *every* device on the LAN. DHCP was moved back to the router so an
> outage no longer breaks the whole network. Trade-off: devices that get their IP automatically
> use the **router** as DNS (192.168.1.1), so they bypass Pi-hole ad-blocking unless their DNS
> is set to `192.168.1.10` manually. Plan: once the wired-Ethernet box (`enp0s25`) has proven
> stable, re-enable Pi-hole DHCP using the steps below and disable the router's DHCP again.
>
> Live state to verify: `docker exec pihole pihole-FTL --config dhcp.active` (currently `false`).

The original rationale was that the router doesn't allow changing the DNS it advertises, so
Pi-hole acted as DHCP server to push itself as the network DNS. Steps to re-enable that setup:

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

> **Gotcha — port-forward bound to MAC (2026-06-02):** if this rule (or a DHCP reservation
> for `192.168.1.10`) is tied to a *device/MAC* rather than a plain IP, swapping the NIC breaks
> it silently. The WiFi→Ethernet migration changed the MAC to **`90:1b:0e:69:36:9f`** (`enp0s25`),
> and WireGuard stopped receiving any inbound packets (`wg show` showed `endpoint = (none)`,
> `transfer = 0`) until the router rule was re-pointed to the new MAC. To isolate router-vs-server,
> test the client with `Endpoint = 192.168.1.10:51820` (LAN, bypasses the router): if that works
> but the public endpoint doesn't, the router forward is the problem. A healthy hairpin shows the
> peer `endpoint` as the router's LAN IP (`192.168.1.1:<port>`).

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

## 15. Music Assistant

Music Assistant is a music streaming server that manages and plays music across multiple rooms and devices. It discovers players on the network via mDNS and uPnP.

### Requirements

- 64-bit OS, minimum 2GB RAM (4GB+ recommended)
- Host networking required for multicast player discovery
- Players must be on the same network (no VLAN separation)

### Directory Setup

```bash
mkdir -p /srv/docker/music-assistant/data
```

### Docker Compose Configuration

See Section 6 for the complete docker-compose.yml. Key points:
- Uses `network_mode: host` for mDNS/uPnP player discovery
- Requires `SYS_ADMIN` and `DAC_READ_SEARCH` capabilities for SMB/NFS music library mounting
- Web UI on port 8095, streaming on port 8097

### Initial Setup

1. Start the service:

```bash
docker compose up -d music-assistant
```

2. Access web UI: http://192.168.1.10:8095

3. Follow the setup wizard to configure music providers and players

### Adding Music Libraries

Music Assistant supports multiple sources:
- Local files (mount additional volumes in docker-compose.yml)
- Spotify, YouTube Music, and other streaming providers
- SMB/NFS network shares (configured via the web UI)

To add a local music directory, add a volume to `docker-compose.yml`:

```yaml
volumes:
  - ./music-assistant/data:/data/
  - /path/to/music:/media:ro
```

### Troubleshooting

#### Players not discovered

Verify host networking is active:

```bash
docker inspect music-assistant | grep NetworkMode
```

Ensure multicast traffic is not blocked by firewall rules.

#### Check logs

```bash
docker compose logs music-assistant --tail 50
```

#### Restart service

```bash
docker compose restart music-assistant
```

---

## 16. Coach Ginnastica

Coach Ginnastica è un'applicazione Flask locale, custom (nessuna immagine pubblica), per seguire le sessioni di ginnastica di una singola persona o di una piccola rete domestica affidabile. A differenza degli altri servizi, l'immagine viene **costruita da sorgente** a partire dal Dockerfile incluso nella directory `coach/` del repository.

> **Attenzione:** l'applicazione non ha autenticazione. Chiunque sulla LAN (o connesso via VPN) può leggere o modificare i dati. La porta 8098 non deve mai essere esposta su Internet né inoltrata dal router.

### Directory Setup

```bash
mkdir -p /srv/docker/coach/data
```

### Docker Compose Configuration

See Section 6 for the complete docker-compose.yml. Key points:
- `build: context: ./coach` builds the image from the Dockerfile in the repository (no `image:` pull)
- `APP_UID`/`APP_GID` build args match the container's user to the host user so it can write to the bind-mounted `data/` directory (default `1000:1000` if unset)
- Web UI and healthcheck on container port 8080, published on host port 8098
- SQLite database (`coach.db`) and the session secret (`app-secret`) live in `./coach/data`, which is git-ignored — back it up like any other service data directory

### Initial Setup

1. Build and start the service:

```bash
cd /srv/docker
APP_UID="$(id -u)" APP_GID="$(id -g)" docker compose up -d --build coach
```

2. Access the web UI: http://192.168.1.10:8098

The app creates `coach.db` and `app-secret` in `./coach/data` automatically on first run if they are not already present.

### Troubleshooting

#### Check logs

```bash
docker compose logs coach --tail 50
```

#### Restart service

```bash
docker compose restart coach
```

#### Rebuild after updating the app source

```bash
cd /srv/docker
APP_UID="$(id -u)" APP_GID="$(id -g)" docker compose up -d --build coach
```

#### Permission denied on `data/`

Make sure the service was started with `APP_UID`/`APP_GID` matching the host user that owns `/srv/docker/coach/data`.

---

## 17. Accessing Services

### From Local Network

| Service | URL |
|---------|-----|
| Dashboard | http://192.168.1.10 |
| Home Assistant | http://192.168.1.10:8123 |
| Pi-hole | http://192.168.1.10:8080/admin |
| WireGuard Admin | http://192.168.1.10:51821 |
| KOReader Sync | http://192.168.1.10:7200 |
| Beszel | http://192.168.1.10:8090 |
| Music Assistant | http://192.168.1.10:8095 |
| Coach Ginnastica | http://192.168.1.10:8098 |

### From Outside (VPN Required)

1. Enable WireGuard VPN on device
2. Use same URLs as local network

**Note:** KOReader Sync is only accessible from local network. Devices must be connected to home network or VPN to sync.

---

## 18. Maintenance Commands

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

### Deploy Repository Changes

The server (host `mulo`, alias in `~/.ssh/config`, `192.168.1.10`) has a clone of this repository at `/srv/docker`, checked out on `main`. Any change made locally (docker-compose.yml, dashboard, docs, source of a custom-built service, etc.) must be pushed and then pulled on the server to take effect:

```bash
# 1. on the dev machine: commit and push
git push origin main

# 2. on mulo: pull and apply
ssh mulo 'cd /srv/docker && git pull && docker compose restart <service>'
```

For a service whose image is **built from source** in this repo (currently only `coach`, see Section 16) rather than pulled from a registry, use `up -d --build` instead of `restart` so the image is rebuilt from the new source, and pass the host UID/GID so the container can write to its bind-mounted `data/`:

```bash
ssh mulo 'cd /srv/docker && git pull && APP_UID="$(id -u)" APP_GID="$(id -g)" docker compose up -d --build <service>'
```

If the change affects multiple/all services, drop the service name (`docker compose restart` / `docker compose up -d --build` with no argument) to apply it to all of them.

**Before pulling**, check for local uncommitted changes on the server (`ssh mulo 'cd /srv/docker && git status'`) — some directories (e.g. `homeassistant/`) can accumulate runtime edits made through a service's own UI. `git pull` only fails/conflicts if the incoming commits touch the same file; otherwise the local edit is simply left uncommitted.

### Reboot server

```bash
sudo reboot
```

All services will restart automatically (restart: unless-stopped).

---

## 19. Troubleshooting

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

### Server randomly freezes / unreachable on all ports

If the whole server becomes unreachable (SSH and every Docker service) and only a physical
reboot recovers it, see **[FREEZE-INVESTIGATION.md](FREEZE-INVESTIGATION.md)**. Root causes were
a Haswell deep C-state hang and a flaky USB WiFi link. Mitigations in place: a hardware watchdog
auto-recovers true hangs, deep C-states are disabled (`intel_idle.max_cstate=1`), WiFi power-save
is off, and kernel crashes are captured via pstore (`/var/lib/systemd/pstore/`).

---

## 20. File Structure Summary

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
├── beszel/                       # Beszel monitoring
│   ├── data/                     # Hub database
│   └── socket/                   # Hub-agent unix socket
├── music-assistant/              # Music Assistant
│   └── data/                     # Server data and config
└── coach/                        # Coach Ginnastica (built from source)
    ├── app/, seed/, wsgi.py, Dockerfile, requirements.txt
    └── data/                     # SQLite DB and session secret
```

---
