"""Tests for the out-of-band HA liveness prober.

Scope is deliberately the decision logic only - thresholding, escalation,
recovery and reminder cadence. The network seams (HA probe, Pushover send) were
verified against real endpoints on the deploy host rather than against mocks,
because every historical failure in this project lived at a seam where the mock
and the real payload disagreed.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ha_sentinel"))

import ha_sentinel  # noqa: E402


@pytest.fixture
def cfg(monkeypatch):
    monkeypatch.setenv("HA_URL", "https://ha.example/")
    monkeypatch.setenv("HA_TOKEN", "token")
    monkeypatch.setenv("PUSHOVER_TOKEN", "ptoken")
    monkeypatch.setenv("PUSHOVER_USER", "puser")
    monkeypatch.setenv("FAIL_THRESHOLD", "3")
    monkeypatch.setenv("REMIND_MINUTES", "30")
    monkeypatch.setenv("DAILY_OK_HOUR", "")
    return ha_sentinel.Config()


@pytest.fixture
def sent(monkeypatch):
    """Capture outbound notifications instead of sending them."""
    captured = []

    def fake_send(_cfg, title, message, priority=0):
        captured.append((title, message, priority))
        return True

    monkeypatch.setattr(ha_sentinel, "send_pushover", fake_send)
    return captured


def test_below_threshold_does_not_alert(cfg, sent):
    """A brief blip or a restart must not page."""
    s = ha_sentinel.Sentinel(cfg)
    now = datetime(2026, 7, 27, 12, 0)

    for i in range(cfg.fail_threshold - 1):
        s._handle_failure("boom", now + timedelta(seconds=i))

    assert sent == []
    assert not s.alerted


def test_alerts_once_at_threshold(cfg, sent):
    s = ha_sentinel.Sentinel(cfg)
    now = datetime(2026, 7, 27, 12, 0)

    for i in range(cfg.fail_threshold):
        s._handle_failure("boom", now + timedelta(seconds=i))

    assert len(sent) == 1
    title, message, priority = sent[0]
    assert title == "Home Assistant unreachable"
    assert priority == 1
    assert "boom" in message


def test_reminder_waits_for_the_configured_gap(cfg, sent):
    s = ha_sentinel.Sentinel(cfg)
    start = datetime(2026, 7, 27, 12, 0)

    for i in range(cfg.fail_threshold):
        s._handle_failure("boom", start + timedelta(seconds=i))
    assert len(sent) == 1

    # The window is measured from when the alert was sent, not from the first
    # failure, so probe either side of that anchor rather than of `start`.
    anchor = s.last_reminder
    assert anchor is not None

    # Still inside the reminder window - must stay quiet.
    s._handle_failure("boom", anchor + timedelta(minutes=cfg.remind_minutes) - timedelta(seconds=1))
    assert len(sent) == 1

    # Window elapsed - one reminder, and only one.
    s._handle_failure("boom", anchor + timedelta(minutes=cfg.remind_minutes))
    assert len(sent) == 2
    assert sent[1][0] == "Home Assistant still down"


def test_recovery_reports_downtime_and_rearms(cfg, sent):
    s = ha_sentinel.Sentinel(cfg)
    start = datetime(2026, 7, 27, 12, 0)

    for i in range(cfg.fail_threshold):
        s._handle_failure("boom", start + timedelta(seconds=i))
    s._handle_success("API running.", start + timedelta(minutes=90))

    assert sent[-1][0] == "Home Assistant back up"
    assert "1h 30m" in sent[-1][1]

    # State must be clean so the next outage alerts again.
    assert not s.alerted
    assert s.down_since is None
    assert s.consecutive_failures == 0


def test_recovery_below_threshold_is_silent(cfg, sent):
    """Recovering from a sub-threshold blip must not send an all-clear."""
    s = ha_sentinel.Sentinel(cfg)
    now = datetime(2026, 7, 27, 12, 0)

    s._handle_failure("boom", now)
    s._handle_success("API running.", now + timedelta(seconds=30))

    assert sent == []


def test_daily_ok_sends_once_per_day(cfg, monkeypatch, sent):
    monkeypatch.setenv("DAILY_OK_HOUR", "9")
    cfg = ha_sentinel.Config()
    s = ha_sentinel.Sentinel(cfg)

    s._maybe_daily_ok(datetime(2026, 7, 27, 9, 0))
    s._maybe_daily_ok(datetime(2026, 7, 27, 9, 30))
    assert len(sent) == 1

    s._maybe_daily_ok(datetime(2026, 7, 28, 9, 0))
    assert len(sent) == 2


def test_daily_ok_suppressed_during_an_outage(cfg, monkeypatch, sent):
    """A proof-of-life during a known outage would be actively misleading."""
    monkeypatch.setenv("DAILY_OK_HOUR", "9")
    cfg = ha_sentinel.Config()
    s = ha_sentinel.Sentinel(cfg)
    s.alerted = True

    s._maybe_daily_ok(datetime(2026, 7, 27, 9, 0))

    assert sent == []


def test_failed_send_is_retried_not_swallowed(cfg, monkeypatch):
    """A dropped alert must be retried, not silently recorded as delivered.

    Recording an undelivered notification is the exact failure mode that made
    the previous watchdog useless: state advanced, nothing was sent, and the
    outage stayed invisible.
    """
    attempts = []

    def failing_send(_cfg, title, _message, priority=0):
        attempts.append(title)
        return False

    monkeypatch.setattr(ha_sentinel, "send_pushover", failing_send)
    s = ha_sentinel.Sentinel(cfg)
    now = datetime(2026, 7, 27, 12, 0)

    for i in range(cfg.fail_threshold):
        s._handle_failure("boom", now + timedelta(seconds=i))

    assert attempts == ["Home Assistant unreachable"]
    assert not s.alerted  # not recorded, so the next cycle retries

    s._handle_failure("boom", now + timedelta(seconds=60))
    assert attempts == ["Home Assistant unreachable"] * 2


def test_unconfigured_channel_does_not_retry_every_cycle(monkeypatch):
    """Without credentials there is nothing to retry, so state must advance.

    The fake returns False, matching what the real send_pushover() does when
    credentials are missing - otherwise this passes whether or not the
    unconfigured branch actually works.
    """
    monkeypatch.setenv("HA_URL", "https://ha.example/")
    monkeypatch.setenv("HA_TOKEN", "token")
    monkeypatch.delenv("PUSHOVER_TOKEN", raising=False)
    monkeypatch.delenv("PUSHOVER_USER", raising=False)
    monkeypatch.setenv("FAIL_THRESHOLD", "1")
    cfg = ha_sentinel.Config()
    assert not cfg.can_notify

    attempts = []

    def unconfigured_send(_cfg, title, _message, priority=0):
        attempts.append(title)
        return False

    monkeypatch.setattr(ha_sentinel, "send_pushover", unconfigured_send)
    s = ha_sentinel.Sentinel(cfg)
    start = datetime(2026, 7, 27, 12, 0)

    s._handle_failure("boom", start)
    assert s.alerted
    assert len(attempts) == 1

    # Inside the reminder window there must be no second attempt: a missing
    # credential will never start working, so retrying would only spam the log.
    s._handle_failure("boom", start + timedelta(minutes=1))
    assert len(attempts) == 1


def test_daily_ok_retries_after_a_failed_send(cfg, monkeypatch):
    monkeypatch.setenv("DAILY_OK_HOUR", "9")
    cfg = ha_sentinel.Config()
    calls = []

    def failing_send(_cfg, title, _message, priority=0):
        calls.append(title)
        return False

    monkeypatch.setattr(ha_sentinel, "send_pushover", failing_send)
    s = ha_sentinel.Sentinel(cfg)

    s._maybe_daily_ok(datetime(2026, 7, 27, 9, 0))
    s._maybe_daily_ok(datetime(2026, 7, 27, 9, 1))

    assert len(calls) == 2  # same day, still retrying
    assert s.last_daily_ok is None


def test_daily_ok_hour_defaults_on(monkeypatch):
    """The dead-man's switch must be opt-out, not opt-in."""
    monkeypatch.setenv("HA_URL", "https://ha.example/")
    monkeypatch.setenv("HA_TOKEN", "token")
    monkeypatch.delenv("DAILY_OK_HOUR", raising=False)

    assert ha_sentinel.Config().daily_ok_hour == 9

    monkeypatch.setenv("DAILY_OK_HOUR", "")
    assert ha_sentinel.Config().daily_ok_hour is None


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(seconds=30), "0 min"),
        (timedelta(minutes=59), "59 min"),
        (timedelta(minutes=60), "1h 0m"),
        (timedelta(hours=25), "1d 1h"),
    ],
)
def test_duration_formatting(delta, expected):
    assert ha_sentinel.Sentinel._format_duration(delta) == expected


def test_unconfigured_pushover_is_reported_not_raised(monkeypatch, caplog):
    """A missing credential must degrade to a loud log, never kill the prober."""
    monkeypatch.setenv("HA_URL", "https://ha.example/")
    monkeypatch.setenv("HA_TOKEN", "token")
    monkeypatch.delenv("PUSHOVER_TOKEN", raising=False)
    monkeypatch.delenv("PUSHOVER_USER", raising=False)
    cfg = ha_sentinel.Config()

    assert not cfg.can_notify
    assert ha_sentinel.send_pushover(cfg, "t", "m") is False
    assert "WOULD ALERT" in caplog.text
