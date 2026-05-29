# Random Freeze Investigation

Investigation into the recurring symptom: **the server becomes unreachable on every port
(SSH and all Docker services) and only a physical reboot recovers it.** No monitor or
keyboard is attached, so diagnosis was done entirely over SSH plus the evidence that
survives a reboot.

**Date:** 2026-05-27 · **Host:** `mulo` (192.168.1.10)

## Hardware / OS context

| Item | Value |
|------|-------|
| CPU | Intel Core i5-4590T (**Haswell**, low-power 35 W) |
| RAM | 7.6 GiB (swap 7.9 GiB) |
| SSD | Samsung PM871b 256 GB (SATA) |
| OS | Debian 13, kernel 6.12.63 |
| Network (active) | **USB Realtek RTL8188FTV** 2.4 GHz dongle `wlx84fc144a256c` (USB `0bda:f179`) |
| Network (idle) | Ethernet `enp0s25` — **no cable connected** |
| Watchdog | Intel `iTCO_wdt` (Lynx Point TCO), `/dev/watchdog0` |

## Method

Because a hard freeze destroys volatile state and often prevents writing logs to disk,
the investigation focused on **evidence that survives a reboot**:

- `journalctl` was already **persistent** (`/var/log/journal` exists), giving ~21 boots of history.
- For each past boot we determined whether it ended **cleanly** (orderly `systemd-poweroff`
  sequence) or **abruptly** (log stops mid-operation, no shutdown) — abrupt = a freeze or a
  hard power-cycle.
- We scanned all boots for failure signatures and correlated them with the abrupt endings.

> Note: reading kernel/system logs requires group access. The admin user was added with
> `sudo usermod -aG adm,systemd-journal $USER` (takes effect on next login).

## Findings

### Ruled out (no evidence across ~21 boots)

- Kernel panic / Oops / BUG
- Out-of-memory (6.4 GiB free, swap unused)
- Thermal / MCE / throttling (package ~60 °C, PCH ~64 °C)
- Disk / filesystem / SSD errors (SMART clean)
- Soft/hard lockup, hung task, RCU stall

### Two distinct failure modes

**Mode A — true hard hang (cause of the physical reboots).**
In abrupt boots `-3`, `-8`, `-13` the `cron` heartbeat fired every 10 minutes like clockwork,
healthy until the last second, then stopped **instantly** while the box was idle — no error,
no WiFi storm, no shutdown sequence. Boot `-13` had been up 11 days before stopping cold.
A heartbeat that stops dead from idle with nothing logged is the signature of a
**total CPU/chipset hang**. The kernel command line had **no idle mitigation** (`quiet` only),
so deep C-states (C6, C7s) were active. Low-power **Haswell** CPUs are well known for total
freezes when entering deep idle states — consistent with every observation here.

**Mode B — network death (OS alive, just unreachable).**
The only network path is a flaky USB Realtek 2.4 GHz dongle. WiFi problem events
(beacon-loss / deauth / disconnect) per session reached the thousands
(boot `-15`: 3260, boot `-13`: 1263, boot `-17`: 939). In boot `-7` the logs show a scanning
storm (NetworkManager re-scanning with MAC randomization, supplicant `inactive -> disconnected`)
while `cron` kept running — i.e. the OS was alive but the link would not re-associate, so the
box was unreachable and was rebooted manually (sometimes twice within a minute). Signal was
fine (−56 dBm) but **5070 beacons were missed**, pointing at power-save / driver behavior
rather than weak signal.

## Root cause

- **Mode A:** strong hypothesis — **Haswell deep C-state hang**. Cannot be proven from existing
  logs (a hard hang writes nothing), so it is treated as a hypothesis to test by mitigation
  plus crash capture.
- **Mode B:** confirmed — chronically unstable **USB Realtek 2.4 GHz** link.

## Remediation deployed (2026-05-27)

| # | Change | Addresses | Reboot? |
|---|--------|-----------|---------|
| 1 | systemd hardware watchdog (`iTCO_wdt`) | Auto-recovers from any true hang | No (`daemon-reexec`) |
| 2 | `intel_idle.max_cstate=1` | Removes the suspected Mode-A trigger | Yes |
| 3 | WiFi power-save off + no scan MAC randomization | Reduces Mode-B disconnects | Applied on reconnect |
| 4 | `pstore` panic capture + panic sysctls | Captures the next freeze if detectable | No |

> All file writes use `printf ... | sudo tee` rather than a here-doc. A here-doc closing
> delimiter must sit at column 0; pasted indentation breaks it (`<<'EOF'` never closes).

### 1. Hardware watchdog (arms without a reboot)

```bash
sudo install -d /etc/systemd/system.conf.d
printf '[Manager]\nRuntimeWatchdogSec=20s\nRebootWatchdogSec=2min\n' | sudo tee /etc/systemd/system.conf.d/watchdog.conf
sudo systemctl daemon-reexec
systemctl show -p RuntimeWatchdogUSec        # expect 20000000
```

If the kernel hard-freezes, the Intel TCO timer resets the box in ~20 s — no physical reboot.

### 2. Limit C-states (Haswell idle-hang mitigation)

```bash
sudo sed -i.bak 's/^GRUB_CMDLINE_LINUX_DEFAULT="quiet"$/GRUB_CMDLINE_LINUX_DEFAULT="quiet intel_idle.max_cstate=1"/' /etc/default/grub
grep GRUB_CMDLINE_LINUX_DEFAULT /etc/default/grub
sudo update-grub
# takes effect on next reboot
```

### 3. WiFi stability

```bash
sudo nmcli connection modify pertugio 802-11-wireless.powersave 2
sudo nmcli connection modify pertugio 802-11-wireless.mac-address-randomization 1
printf '[device]\nwifi.scan-rand-mac-address=no\n' | sudo tee /etc/NetworkManager/conf.d/wifi-stability.conf
# fully active after reconnect / reboot
```

### 4. Crash capture (pstore)

```bash
printf 'kernel.panic = 10\nkernel.panic_on_oops = 1\nkernel.softlockup_panic = 1\n' | sudo tee /etc/sysctl.d/99-freeze-capture.conf
sudo sysctl --system
```

`efi_pstore` is already the registered backend. A kernel-detectable hang/oops becomes a panic,
the trace is written to UEFI NVRAM, the box reboots (`kernel.panic=10`), and on the next boot
`systemd-pstore` archives it to `/var/lib/systemd/pstore/`. No external listener needed.

Optional real-time streaming to another always-on host (does **not** persist across reboot):

```bash
# receiver (other host):  nc -u -l 6666 | tee netconsole-mulo.log
sudo modprobe netconsole netconsole="6665@192.168.1.10/wlx84fc144a256c,6666@<RECEIVER_IP>/<RECEIVER_MAC>"
echo "netconsole test $(date)" | sudo tee /dev/kmsg
```

## Verification (post-reboot, all confirmed)

```bash
cat /proc/cmdline                                   # ...intel_idle.max_cstate=1
ls /sys/devices/system/cpu/cpu0/cpuidle/            # only POLL + C1 remain
systemctl show -p RuntimeWatchdogUSec               # 20000000
journalctl -b 0 | grep -i 'hardware watchdog'       # Using hardware watchdog 'iTCO_wdt' ... timeout of 20s
sysctl kernel.panic kernel.panic_on_oops kernel.softlockup_panic
nmcli -g 802-11-wireless.powersave connection show pertugio   # 2 (disabled)
```

## Evaluating effectiveness over time

- **`journalctl --list-boots`** — abrupt endings should stop. A watchdog-triggered reboot
  still shows as abrupt, so also check the cause below.
- **`/sys/fs/pstore/` and `/var/lib/systemd/pstore/`** — any captured panic trace.
- **`/proc/net/wireless`** — the *missed beacon* counter should grow far more slowly.

Interpretation:
- No more abrupt reboots → the C-state limit fixed Mode A.
- Still freezing, but **pstore empty + watchdog reboots** → a hardware-level hang the kernel
  cannot catch. Next steps: disable C1E/ASPM, update the BIOS, or suspect the USB controller.
- WiFi disconnects persist → wire **Ethernet** (`enp0s25`), the definitive Mode-B fix
  (deferred only because no cable is currently run to the server).

## Update 2026-05-29 — live episode proved it was the WiFi, and the fix

A new "unreachable" episode was caught **in real time** and fully reconstructed from the logs.
The conclusion overturned the earlier freeze hypothesis: **the machine never froze — it was
alive the whole time.**

Proof from the journal of the affected boot:

- When the dongle was unplugged/replugged, the kernel **processed the USB hotplug**
  (`USB disconnect` → re-enumerate → firmware load → interface rename). A hung kernel can't.
- The "physical reboot" produced a **clean ACPI shutdown** in the logs (`systemd-poweroff`,
  containers stopped one by one, `Journal stopped`), not an abrupt cut. A hung kernel can't.
- `intel_idle.max_cstate=1` was active (irrelevant), the hardware watchdog correctly did **not**
  fire (kernel wasn't hung), and `pstore` was **empty** (no crash) — all consistent.

Actual root cause: the Realtek link dropped repeatedly that day (25 disconnects, all
`reason=3/4 locally_generated=1` — our side, not the AP), then NetworkManager fell into
`need-auth → no-secrets ("No agents were available") → failed` and **stopped retrying**, leaving
the headless box reachable-by-nobody until reboot. `psk-flags=0` and `autoconnect=yes` were
correctly set, so it's a driver/link-instability + NM-recovery failure, not a credentials issue.
The previously deployed WiFi power-save / scan-MAC mitigations were active and **did not prevent
it** — software mitigations are insufficient for this dongle.

### Resolution: migrated to wired Ethernet

An Ethernet cable was run to the box and the USB WiFi dongle removed. Networking is now on
`enp0s25` via the NM connection `eth`, **keeping the same static IP `192.168.1.10`** so Pi-hole
(DNS/DHCP), WireGuard and all services are unaffected:

```bash
# eth was already pre-configured: ipv4.method manual, 192.168.1.10/24, gw 192.168.1.1, dns 8.8.8.8
sudo nmcli connection modify eth connection.autoconnect-priority 100   # Ethernet wins if both present
sudo nmcli connection modify pertugio connection.autoconnect no        # WiFi never auto-activates
```

Verified: default route via `enp0s25` (metric 100), gateway ping **0.4 ms / 0% loss** (WiFi was
6–21 ms and flapping), all 7 containers healthy, no legacy `/etc/network/interfaces` override.
The flaky USB WiFi link is now out of the critical path, so the recurring "unreachable until
physical reboot" is resolved. The C-state limit, hardware watchdog and pstore capture from
2026-05-27 stay in place as safety nets for any genuine hardware hang.
