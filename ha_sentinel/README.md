# HA Sentinel

An out-of-band liveness prober for Home Assistant. It answers the one question
Home Assistant cannot answer about itself: **is Home Assistant reachable?**

Every alert goes to Pushover directly. Nothing routes through Home Assistant —
HA being down is the thing being reported, so an HA-delivered alert would be
useless exactly when it matters. This is the complement to the HA-native device
health automations (`System - Battery Low`, `System - Device Health (Daily
Digest)`, `System - Device Offline`), which handle everything *inside* a working
HA and cannot go blind while HA is up.

Standard library only. No dependencies, no database, no container.

## Deployed layout (host: blackbox)

| Path | Purpose |
|------|---------|
| `/opt/ha-sentinel/ha_sentinel.py` | The prober |
| `/etc/systemd/system/ha-sentinel.service` | systemd unit (`Restart=always`) |
| `/etc/ha-sentinel.env` | Config + secrets, mode 0640 root:jason |

Deliberately **not** a Docker container and with no dependency on
`docker.service`: the watchdog must survive Docker dying.

## Finish the setup

Alerts are inert until Pushover credentials are present. The service logs
`WOULD ALERT (Pushover not configured)` in that state.

1. Create an account at <https://pushover.net> and note your **User Key**.
2. Create an Application (Pushover → *Create an Application/API Token*) to get
   an **API Token**.
3. Fill both into the env file and restart:

   ```bash
   sudo nano /etc/ha-sentinel.env      # set PUSHOVER_TOKEN= and PUSHOVER_USER=
   sudo systemctl restart ha-sentinel
   journalctl -u ha-sentinel -f
   ```

4. Confirm the chain end to end by pointing it at a dead port for a minute:

   ```bash
   sudo systemctl stop ha-sentinel
   sudo HA_URL=https://127.0.0.1:9/ HA_TOKEN=x CHECK_INTERVAL_SECONDS=2 \
        FAIL_THRESHOLD=2 PUSHOVER_TOKEN=... PUSHOVER_USER=... \
        python3 /opt/ha-sentinel/ha_sentinel.py
   # expect a push within ~5s, then Ctrl-C
   sudo systemctl start ha-sentinel
   ```

## Configuration

| Variable | Default | Meaning |
|----------|---------|---------|
| `HA_URL` | *required* | Home Assistant base URL |
| `HA_TOKEN` | *required* | Long-lived access token |
| `PUSHOVER_TOKEN` | — | Pushover application token |
| `PUSHOVER_USER` | — | Pushover user key |
| `CHECK_INTERVAL_SECONDS` | `60` | Seconds between probes |
| `PROBE_TIMEOUT_SECONDS` | `10` | Per-probe HTTP timeout |
| `FAIL_THRESHOLD` | `3` | Consecutive failures before alerting |
| `REMIND_MINUTES` | `30` | Re-alert cadence while still down |
| `DAILY_OK_HOUR` | `9` | Hour for the proof-of-life message; empty disables |

## Behaviour

- Probes `GET {HA_URL}/api/` and requires HTTP 200 with a JSON body.
- Alerts (priority 1) after `FAIL_THRESHOLD` consecutive failures, so a single
  blip or a brief restart does not page you.
- Re-alerts every `REMIND_MINUTES` while down, so the alert cannot be lost.
- Sends a recovery message with the measured downtime when HA returns.
- Sends one low-priority message a day at `DAILY_OK_HOUR`.

That daily message is the point, not noise: it is the dead-man's switch for the
prober itself. It proves in one shot that the process is alive, the network
works, and the Pushover credentials are still valid. **Silence on a day you
expect it is the signal.** Without it, a dead prober is indistinguishable from a
healthy house — which is precisely the failure mode that made the previous
watchdog useless.

## Known limits (deliberate)

- If **blackbox** loses power or network, no alerts. Detecting that needs a
  probe outside the house; the daily proof-of-life is the cheap mitigation.
- A wrong/expired `HA_TOKEN` reports as an outage (HTTP 401). That is a real
  problem worth paging for, but the message will say `HTTP 401` rather than
  "unreachable".
- It reports reachability only. Anything about devices *inside* a working HA is
  the HA-native automations' job, by design.

## Verified 2026-07-27

- Healthy probe against live HA (`API running.`), clean SIGTERM shutdown.
- Outage escalation: alert at the threshold, then reminders.
- Recovery transition with downtime reported.
- `systemctl kill -9` → systemd restarted the service 15s later.
