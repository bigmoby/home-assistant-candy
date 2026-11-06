"""Tests for tools/simplyfi.py diagnose sanitization and CLI options."""

from __future__ import annotations

import contextlib
import io
import sys
from unittest.mock import patch

# Ensure tools directory is accessible for simplyfi import
sys.path.insert(0, "tools")
import custom_components.candy  # noqa: F401
import simplyfi  # noqa: E402

import custom_components.candy  # noqa: F401


def test_run_diagnose_sanitizes_key_in_step_1_and_report() -> None:
    """Ensure run_diagnose redacts encryption key in Step 1 and in report when sanitize is True."""
    mock_telemetry = {
        "statusLavatrice": {
            "MachMd": "1",
            "PrPh": "2",
            "WiFiStatus": "1",
            "WiFi": "1",
        }
    }
    secret_key = "secret_key_12345"
    stdout_buf = io.StringIO()

    with (
        patch(
            "simplyfi.fetch_or_discover_telemetry",
            return_value=(mock_telemetry, secret_key, True),
        ),
        patch("simplyfi.fetch_statistics_json", return_value={"statusCounters": {}}),
        patch(
            "simplyfi.fetch_config_json",
            return_value={"ssid": "MyWiFi", "mac": "00-11-22-33-44-55"},
        ),
        patch("time.sleep"),
        contextlib.redirect_stdout(stdout_buf),
    ):
        simplyfi.run_diagnose("192.168.1.50", 80, "", True, 5)

    captured = stdout_buf.getvalue()

    # Verify Step 1 log output masks the key
    assert "Recovered encryption key: ***REDACTED***" in captured
    # Verify report output masks the key
    assert "**Key**: `***REDACTED***`" in captured
    # Ensure raw secret key never appears in stdout
    assert secret_key not in captured


def test_run_diagnose_reveals_cleartext_key_when_raw() -> None:
    """Ensure run_diagnose prints plaintext encryption key when sanitize is False."""
    mock_telemetry = {
        "statusLavatrice": {
            "MachMd": "1",
            "PrPh": "2",
            "WiFiStatus": "1",
            "WiFi": "1",
        }
    }
    secret_key = "secret_key_12345"
    stdout_buf = io.StringIO()

    with (
        patch(
            "simplyfi.fetch_or_discover_telemetry",
            return_value=(mock_telemetry, secret_key, True),
        ),
        patch("simplyfi.fetch_statistics_json", return_value={"statusCounters": {}}),
        patch("simplyfi.fetch_config_json", return_value={"ssid": "MyWiFi"}),
        patch("time.sleep"),
        contextlib.redirect_stdout(stdout_buf),
    ):
        simplyfi.run_diagnose("192.168.1.50", 80, "", False, 5)

    captured = stdout_buf.getvalue()

    # Verify Step 1 log output displays cleartext key
    assert f"Recovered encryption key: {secret_key}" in captured
    # Verify report displays cleartext key
    assert f"**Key**: `{secret_key}`" in captured


def test_main_diagnose_defaults_to_sanitized() -> None:
    """Test CLI diagnose without flags sets sanitize to True."""
    with (
        patch("sys.argv", ["simplyfi.py", "192.168.1.50", "diagnose"]),
        patch("simplyfi.run_diagnose") as mock_diagnose,
    ):
        simplyfi.main()
        mock_diagnose.assert_called_once_with("192.168.1.50", 80, "", True, 10)


def test_main_diagnose_raw_flag() -> None:
    """Test CLI diagnose with --raw flag sets sanitize to False."""
    with (
        patch("sys.argv", ["simplyfi.py", "192.168.1.50", "diagnose", "--raw"]),
        patch("simplyfi.run_diagnose") as mock_diagnose,
    ):
        simplyfi.main()
        mock_diagnose.assert_called_once_with("192.168.1.50", 80, "", False, 10)


def test_main_diagnose_short_raw_flag() -> None:
    """Test CLI diagnose with -r flag sets sanitize to False."""
    with (
        patch("sys.argv", ["simplyfi.py", "192.168.1.50", "diagnose", "-r"]),
        patch("simplyfi.run_diagnose") as mock_diagnose,
    ):
        simplyfi.main()
        mock_diagnose.assert_called_once_with("192.168.1.50", 80, "", False, 10)


def test_main_diagnose_key_and_raw() -> None:
    """Test CLI diagnose with positional key and --raw flag."""
    with (
        patch(
            "sys.argv",
            ["simplyfi.py", "192.168.1.50", "diagnose", "custom_key", "--raw"],
        ),
        patch("simplyfi.run_diagnose") as mock_diagnose,
    ):
        simplyfi.main()
        mock_diagnose.assert_called_once_with(
            "192.168.1.50", 80, "custom_key", False, 10
        )


def test_main_diagnose_key_without_raw() -> None:
    """Test CLI diagnose with positional key defaults to sanitized."""
    with (
        patch("sys.argv", ["simplyfi.py", "192.168.1.50", "diagnose", "custom_key"]),
        patch("simplyfi.run_diagnose") as mock_diagnose,
    ):
        simplyfi.main()
        mock_diagnose.assert_called_once_with(
            "192.168.1.50", 80, "custom_key", True, 10
        )


def test_main_shortcut_raw() -> None:
    """Test direct CLI shortcut --raw runs diagnose in raw mode."""
    with (
        patch("sys.argv", ["simplyfi.py", "192.168.1.50", "--raw"]),
        patch("simplyfi.run_diagnose") as mock_diagnose,
    ):
        simplyfi.main()
        mock_diagnose.assert_called_once_with("192.168.1.50", 80, "", False, 10)


def test_main_no_subcommand_defaults_to_sanitized() -> None:
    """Test CLI without subcommand defaults to diagnose sanitized."""
    stdout_buf = io.StringIO()
    with (
        patch("sys.argv", ["simplyfi.py", "192.168.1.50"]),
        patch("simplyfi.run_diagnose") as mock_diagnose,
        contextlib.redirect_stdout(stdout_buf),
    ):
        simplyfi.main()
        mock_diagnose.assert_called_once_with("192.168.1.50", 80, "", True, 10)
    assert "Defaulting to 'diagnose' (sanitized)" in stdout_buf.getvalue()


def test_main_legacy_diagnose_defaults_to_sanitized() -> None:
    """Test legacy syntax simplyfi.py <ip> <key> diagnose defaults to sanitized."""
    with (
        patch("sys.argv", ["simplyfi.py", "192.168.1.50", "legacy_key", "diagnose"]),
        patch("simplyfi.run_diagnose") as mock_diagnose,
    ):
        simplyfi.main()
        mock_diagnose.assert_called_once_with(
            "192.168.1.50", 80, "legacy_key", True, 10
        )


def test_main_legacy_diagnose_raw() -> None:
    """Test legacy syntax simplyfi.py <ip> <key> diagnose --raw runs raw."""
    with (
        patch(
            "sys.argv",
            ["simplyfi.py", "192.168.1.50", "legacy_key", "diagnose", "--raw"],
        ),
        patch("simplyfi.run_diagnose") as mock_diagnose,
    ):
        simplyfi.main()
        mock_diagnose.assert_called_once_with(
            "192.168.1.50", 80, "legacy_key", False, 10
        )
