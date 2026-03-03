# Adding a New Service

Checklist and steps to follow when adding a new Docker service to the home server.

---

## 1. Research

- Check the **official Docker Hub / GitHub** page for the service to find the recommended `docker-compose` configuration
- Note the required **image**, **ports**, **volumes**, **environment variables**, and any **capabilities** (`cap_add`, `security_opt`)
- Check if the service needs `network_mode: host` (e.g. for mDNS, multicast, or real client IP visibility) or standard bridge networking with port mapping
- Check if the service requires secrets or API keys that should go in `.env`

---

## 2. Choose a Port

- Review the [Services Summary](home-server-documentation.md) table to avoid port conflicts
- Pick a port that is not already in use

---

## 3. Create the Directory Structure

Create the data directories following the existing convention:

```bash
mkdir -p /srv/docker/<service-name>/data
sudo chown -R $USER:$USER /srv/docker/<service-name>
```

Adapt subdirectories to what the service actually needs (config, logs, data, etc.).

---

## 4. Add Environment Variables (if needed)

If the service requires secrets or passwords:

1. Add the variables to `/srv/docker/.env`
2. Reference them in `docker-compose.yml` with `${VAR_NAME}` syntax
3. Never hardcode passwords or tokens in `docker-compose.yml`

---

## 5. Add the Service to `docker-compose.yml`

Follow the existing style:

```yaml
  <service-name>:
    container_name: <service-name>
    image: <image>:<tag>
    restart: unless-stopped
    ports:
      - "<host-port>:<container-port>"
    volumes:
      - ./<service-name>/data:/data
    environment:
      TZ: Europe/Rome
```

Key conventions to match:
- `container_name` matches the service name
- Always set `restart: unless-stopped`
- Use `TZ: Europe/Rome` when the service supports timezone configuration
- Mount volumes under `./<service-name>/` relative to the compose file
- Use `network_mode: host` only when required (player discovery, DNS, VPN); otherwise use port mapping

---

## 6. Update the Dashboard (`dashboard/index.html`)

Add a service card inside the `<div class="services">` block, following the existing pattern:

```html
<a href="http://192.168.1.10:<port>" class="service-card">
  <div class="logo-container">
    <!-- icon goes here -->
  </div>
  <div class="service-name">Service Name</div>
  <div class="port">:<port></div>
</a>
```

### Icon selection

Follow this priority order:

1. **Remote image from the service itself** -- Reference the icon served by the running service (e.g. `http://192.168.1.10:<port>/favicon.png`). This only works when the service is running
2. **Inline SVG from the official site** -- Grab the SVG code from the service's official website and paste it directly inside the `<div class="logo-container">` (like done for Beszel). Do not save SVG files to the repository

If neither option works, ask before proceeding.

---

## 7. Update Documentation

### `home-server-documentation.md`

1. Add a row to the **Services Summary** table (Section: Overview)
2. Add a new numbered section with:
   - Service description and purpose
   - Directory setup commands
   - Reference to docker-compose.yml (Section 6)
   - Initial setup / first-run instructions
   - Troubleshooting subsection (check logs, restart commands)
3. Add the service directory to the **File Structure Summary** (Section 19)
4. Add the service URL to the **Accessing Services** table (Section 16)

### `README.md`

1. Add a row to the **Services** table
2. Add a subsection under **Client Access** if the service has a web UI
3. Add the directory to the **File Structure** tree

---

## 8. Handle Secrets and `.env`

- If the service introduces new secrets, also update the `.env` content example in the documentation (Section 5)
- Add instructions on how to generate or obtain the secret values

---

## 9. Start and Verify

```bash
cd /srv/docker
docker compose up -d <service-name>
docker compose ps
docker compose logs <service-name> --tail 30
```

- Confirm the container is running and healthy
- Access the web UI (if any) from the local network
- Test access through VPN if the service should be reachable remotely

---

## 10. Commit

Stage only the changed files:

```bash
git add docker-compose.yml dashboard/index.html home-server-documentation.md README.md
# plus any new icon files under dashboard/
git commit -m "Add <service-name> service"
```
