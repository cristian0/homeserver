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
| Pi-hole | 8080 | DNS/DHCP + Ad blocking |
| WireGuard | 51820/UDP | VPN server |
| WireGuard Admin | 51821 | VPN client management |
| KOReader Sync | 7200 | Reading progress sync (Kindle/Mac) |

## Architecture

- **Security**: Only WireGuard port (51820/UDP) exposed to internet
- **DNS/DHCP**: Pi-hole serves as network DNS and DHCP server
- **Remote Access**: All services accessible via VPN only
- **Networking**: Pi-hole and WireGuard use host networking for proper client IP visibility

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

## File Structure

```
/srv/docker/
├── .env                    # Secrets (git-ignored)
├── docker-compose.yml      # Main config
├── dashboard/              # HTML dashboard
├── homeassistant/          # HA config (git-ignored)
├── pihole/                 # Pi-hole config (git-ignored)
├── wireguard/              # WG config (git-ignored)
└── koreader-sync/          # Sync server data (git-ignored)
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

- Pi-hole acts as DHCP server (router DHCP disabled)
- IP forwarding enabled for VPN routing
- WireGuard auto-configures NAT via environment variables
- All containers auto-restart unless stopped manually
