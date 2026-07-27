#!/usr/bin/env python3
"""Out-of-band liveness prober for Home Assistant.

Answers exactly one question that Home Assistant cannot answer about itself:
is Home Assistant reachable? Every alert channel goes to Pushover directly,
never through HA, because HA being down is the thing we are reporting.

Runs on a host that is not the HA machine. Standard library only.
"""

import json
import logging
import os
import signal
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

PUSHOVER_URL = "https://api.pushover.net/1/messages.json"

log = logging.getLogger("ha_sentinel")


class Config:
    """Runtime configuration, read once from the environment."""

    def __init__(self) -> None:
        self.ha_url = os.environ["HA_URL"].rstrip("/")
        self.ha_token = os.environ["HA_TOKEN"]
        self.pushover_token = os.environ.get("PUSHOVER_TOKEN", "")
        self.pushover_user = os.environ.get("PUSHOVER_USER", "")
        self.interval = int(os.environ.get("CHECK_INTERVAL_SECONDS", "60"))
        self.timeout = int(os.environ.get("PROBE_TIMEOUT_SECONDS", "10"))
        self.fail_threshold = int(os.environ.get("FAIL_THRESHOLD", "3"))
        self.remind_minutes = int(os.environ.get("REMIND_MINUTES", "30"))
        # Defaults on: the daily message is the prober's own dead-man's switch,
        # so losing it must take a deliberate act. An explicit empty value disables.
        hour = os.environ.get("DAILY_OK_HOUR", "9").strip()
        self.daily_ok_hour = int(hour) if hour else None

    @property
    def can_notify(self) -> bool:
        return bool(self.pushover_token and self.pushover_user)


def send_pushover(cfg: Config, title: str, message: str, priority: int = 0) -> bool:
    """Send one Pushover message. Returns True on success.

    Never raises: a notification failure must not kill the prober.
    """
    if not cfg.can_notify:
        log.error("WOULD ALERT (Pushover not configured): %s - %s", title, message)
        return False

    payload = urllib.parse.urlencode(
        {
            "token": cfg.pushover_token,
            "user": cfg.pushover_user,
            "title": title,
            "message": message,
            "priority": priority,
        }
    ).encode()

    try:
        req = urllib.request.Request(PUSHOVER_URL, data=payload)
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.load(resp)
        if body.get("status") == 1:
            log.info("Pushover sent: %s", title)
            return True
        log.error("Pushover rejected the message: %s", body)
    except Exception as exc:  # noqa: BLE001 - deliberate catch-all
        log.error("Pushover send failed: %s: %s", type(exc).__name__, exc)
    return False


def probe(cfg: Config) -> tuple[bool, str]:
    """Check whether Home Assistant's API answers. Returns (ok, detail)."""
    req = urllib.request.Request(
        f"{cfg.ha_url}/api/",
        headers={"Authorization": f"Bearer {cfg.ha_token}"},
    )
    try:
        with urllib.request.urlopen(
            req, timeout=cfg.timeout, context=ssl.create_default_context()
        ) as resp:
            if resp.status != 200:
                return False, f"HTTP {resp.status}"
            body = json.load(resp)
            if "message" not in body:
                return False, f"unexpected body: {body!r}"
            return True, body["message"]
    except urllib.error.HTTPError as exc:
        # 401 means HA is up but our token is wrong - a real problem, but not an outage.
        return False, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 - any failure is a failed probe
        return False, f"{type(exc).__name__}: {exc}"


class Sentinel:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.consecutive_failures = 0
        self.down_since: datetime | None = None
        self.alerted = False
        self.last_reminder: datetime | None = None
        self.last_daily_ok: datetime | None = None
        self.running = True

    def stop(self, *_: object) -> None:
        log.info("Shutting down")
        self.running = False

    def _should_record(self, sent_ok: bool) -> bool:
        """Whether a send attempt should advance notification state.

        A transport failure must NOT advance it: otherwise a dropped alert is
        silently swallowed and the outage stays unreported until the next
        reminder. An unconfigured channel is different - it will never succeed,
        so retrying every cycle would just spam the log instead of honouring the
        reminder cadence.
        """
        return sent_ok or not self.cfg.can_notify

    def _handle_failure(self, detail: str, now: datetime) -> None:
        self.consecutive_failures += 1
        if self.down_since is None:
            self.down_since = now
        log.warning(
            "Probe failed (%d/%d): %s",
            self.consecutive_failures,
            self.cfg.fail_threshold,
            detail,
        )

        if self.consecutive_failures < self.cfg.fail_threshold:
            return

        if not self.alerted:
            sent_ok = send_pushover(
                self.cfg,
                "Home Assistant unreachable",
                f"No API response for {self.consecutive_failures} consecutive checks.\n"
                f"Down since {self.down_since:%b %d %H:%M}.\nLast error: {detail}",
                priority=1,
            )
            if self._should_record(sent_ok):
                self.alerted = True
                self.last_reminder = now
            return

        # Still down - remind periodically so the alert cannot be lost in a scroll.
        due = self.last_reminder is None or now - self.last_reminder >= timedelta(
            minutes=self.cfg.remind_minutes
        )
        if due:
            downtime = self._format_duration(now - self.down_since)
            sent_ok = send_pushover(
                self.cfg,
                "Home Assistant still down",
                f"Unreachable for {downtime}.\nLast error: {detail}",
                priority=1,
            )
            if self._should_record(sent_ok):
                self.last_reminder = now

    def _handle_success(self, detail: str, now: datetime) -> None:
        if self.alerted and self.down_since is not None:
            downtime = self._format_duration(now - self.down_since)
            send_pushover(
                self.cfg,
                "Home Assistant back up",
                f"API responding again after {downtime}.",
                priority=0,
            )
        elif self.consecutive_failures:
            log.info(
                "Recovered after %d failed check(s), below alert threshold",
                self.consecutive_failures,
            )

        self.consecutive_failures = 0
        self.down_since = None
        self.alerted = False
        self.last_reminder = None
        log.debug("Probe ok: %s", detail)

    def _maybe_daily_ok(self, now: datetime) -> None:
        """Send one proof-of-life a day.

        This is the dead-man's switch for the prober itself: it proves the
        process is alive, the network works, and the Pushover credentials are
        valid. Silence on the expected day is the signal.
        """
        if self.cfg.daily_ok_hour is None or self.alerted:
            return
        if now.hour != self.cfg.daily_ok_hour:
            return
        if self.last_daily_ok and self.last_daily_ok.date() == now.date():
            return

        sent_ok = send_pushover(
            self.cfg,
            "HA Sentinel daily check",
            f"Home Assistant reachable. Prober healthy at {now:%b %d %H:%M}.",
            priority=-1,
        )
        if self._should_record(sent_ok):
            self.last_daily_ok = now

    @staticmethod
    def _format_duration(delta: timedelta) -> str:
        minutes = int(delta.total_seconds() // 60)
        if minutes < 60:
            return f"{minutes} min"
        hours, minutes = divmod(minutes, 60)
        if hours < 24:
            return f"{hours}h {minutes}m"
        days, hours = divmod(hours, 24)
        return f"{days}d {hours}h"

    def run(self) -> None:
        log.info(
            "HA Sentinel started - probing %s every %ds (alert after %d failures)",
            self.cfg.ha_url,
            self.cfg.interval,
            self.cfg.fail_threshold,
        )
        if not self.cfg.can_notify:
            log.error("PUSHOVER_TOKEN/PUSHOVER_USER are unset - outages will be logged, not sent")

        while self.running:
            now = datetime.now()
            ok, detail = probe(self.cfg)
            if ok:
                self._handle_success(detail, now)
                self._maybe_daily_ok(now)
            else:
                self._handle_failure(detail, now)

            # Sleep in short slices so a stop signal is honoured promptly.
            deadline = time.monotonic() + self.cfg.interval
            while self.running and time.monotonic() < deadline:
                time.sleep(min(1.0, deadline - time.monotonic()))


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        cfg = Config()
    except KeyError as exc:
        log.error("Missing required environment variable: %s", exc)
        return 1

    sentinel = Sentinel(cfg)
    signal.signal(signal.SIGTERM, sentinel.stop)
    signal.signal(signal.SIGINT, sentinel.stop)
    sentinel.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
