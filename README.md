# Home Server

Personal self-hosted infrastructure running on Fujitsu Q916 mini PC with Debian.

## Quick Info

- **Server IP**: 192.168.1.10
- **Public IP**: 2.229.233.252
- **VPN Subnet**: 10.8.0.0/24

## Services

| Service | Port | Purpose |
|---------|------|---------|
| Dashboard | 80 | Service overview |
| Home Assistant | 8123 | Home automation |
| Pi-hole | 8080 | DNS + Ad blocking |
| WireGuard | 51820/UDP | VPN server |
| WireGuard Admin | 51821 | VPN client management |
| KOReader Sync | 7200 | Reading progress sync (Kindle/Mac) |
| Beszel | 8090 | Server monitoring |
| Music Assistant | 8095 | Music streaming & player management |
| Coach Ginnastica | 8098 | Gymnastics coaching sessions (custom-built app) |

## Architecture

- **Security**: Only WireGuard port (51820/UDP) exposed to internet
- **DNS**: Pi-hole serves as network DNS (ad-blocking). **DHCP is currently handled by the router**, not Pi-hole — see the note in §9 of the docs. Devices only use Pi-hole if their DNS is set to `192.168.1.10` (manually or via the router's DHCP-advertised DNS).
- **Remote Access**: All services accessible via VPN only
- **Physical link**: Wired **Ethernet** (`enp0s25`, static `192.168.1.10`). The USB WiFi dongle was retired after causing recurring network drops that left the box unreachable until a physical reboot — see [FREEZE-INVESTIGATION.md](FREEZE-INVESTIGATION.md). WiFi stays configured but with `autoconnect=no` as an emergency-only fallback.
- **Networking**: Pi-hole, WireGuard, and Music Assistant use host networking for proper client IP visibility and player discovery
- **Monitoring**: Beszel provides real-time metrics and Docker container stats

## Quick Start

### Deploy all services

```bash
cd /srv/docker
docker compose up -d
```

### View logs

```bash
docker compose logs -f
```

### Restart a service

```bash
docker compose restart <service_name>
```

### Update all containers

```bash
docker compose pull
docker compose up -d
```

### Deploy local changes to the server

```bash
git push origin main
ssh mulo 'cd /srv/docker && git pull && docker compose restart <service_name>'
```

For a service built from source in this repo (currently `coach`), use `docker compose up -d --build <service_name>` instead of `restart`. See §18 of the docs for details.

## Client Access

### Dashboard

Local: http://192.168.1.10  
VPN: http://192.168.1.10 (connect to VPN first)

### VPN Setup

1. Access http://192.168.1.10:51821
2. Create new client
3. Download config or scan QR code
4. Edit `AllowedIPs` to `192.168.1.0/24, 10.8.0.0/24` (split tunnel)

### KOReader Sync

**Server**: http://192.168.1.10:7200  
**Setup**: Tools → Progress sync → Enter server URL → Register/Login  
**Access**: Local network only

### Beszel (Server Monitoring)

**URL**: http://192.168.1.10:8090
**Features**: CPU, memory, disk, network metrics, Docker container stats, alerts
**Access**: Local network or VPN

### Music Assistant

**URL**: http://192.168.1.10:8095
**Features**: Music streaming, multi-room audio, player discovery via mDNS/uPnP
**Access**: Local network or VPN

### Coach Ginnastica

**URL**: http://192.168.1.10:8098
**Features**: Tracking gymnastics coaching sessions for a single user/household
**Access**: Local network or VPN — no authentication, never expose to the internet

## File Structure

```
/srv/docker/
├── .env                    # Secrets (git-ignored)
├── docker-compose.yml      # Main config
├── dashboard/              # HTML dashboard
├── homeassistant/          # HA config (git-ignored)
├── pihole/                 # Pi-hole config (git-ignored)
├── wireguard/              # WG config (git-ignored)
├── koreader-sync/          # Sync server data (git-ignored)
├── beszel/                 # Beszel data (git-ignored)
│   ├── data/               # Hub database
│   └── socket/             # Unix socket for hub-agent communication
├── music-assistant/        # Music Assistant data (git-ignored)
│   └── data/               # Server data and config
└── coach/                  # Coach Ginnastica (built from source, not pulled)
    └── data/               # SQLite DB + session secret (git-ignored)
```

## Repository Setup

This repository contains the configuration files only. Service data directories are git-ignored.

### Initial setup

```bash
git clone <repo-url>
cd <repo>
cp .env_sample .env
# Edit .env with your passwords
nano .env
```

### Generate WireGuard password hash

```bash
docker run -it --rm ghcr.io/wg-easy/wg-easy wgpw 'YOUR_PASSWORD'
```

## Documentation

See [home-server-documentation.md](home-server-documentation.md) for detailed setup instructions, troubleshooting, and configuration details.

## Notes

- DHCP is currently served by the **router** (Pi-hole DHCP disabled) — deliberate resilience choice so a server outage doesn't take down LAN connectivity; revisit once the wired-Ethernet box proves stable (see §9 of the docs)
- IP forwarding enabled for VPN routing
- WireGuard auto-configures NAT via `WG_POST_UP`/`WG_POST_DOWN` environment variables
- All containers auto-restart unless stopped manually
- Beszel agent uses host networking and Docker socket for container monitoring
- Music Assistant uses host networking for mDNS/uPnP player discovery
- Secrets (passwords, keys, tokens) stored in `.env` file, not in docker-compose.yml
