#!/usr/bin/env python3
"""
Candy Simply-Fi Diagnostic & Telemetry Dissection Tool

Version: 2.0.0
Original concept & XOR decryption by Melvin Groenendaal (Python Port)
Overhauled and expanded for the Home Assistant Candy Integration Team (@bigmoby and @auanasgheps).
"""

from __future__ import annotations

import json
import socket
import sys
import time
from typing import Any

VERSION = "2.0.0"

# ---------------------------------------------------------------------------
# Cryptographic Signatures (Known-Plaintexts)
# Covering all Simply-Fi & Hoover appliance families (classes4.dex ground truth)
# ---------------------------------------------------------------------------

KNOWN_PLAINTEXTS: list[str] = [
    # Washers & Dryers
    '{"statusLavatrice',
    '{"statusTD":{"Pr',
    '{"statusTD": {"Pr',
    '{\r\n\t"statusLavat',
    '{\r\n  "statusLavat',
    '{\n\t"statusLavatri',
    '{\n  "statusLavatri',
    '{\r\n\t"statusTD":{',
    '{\r\n  "statusTD":{',
    '"WiFiStatus":"0"',
    '"WiFiStatus":"1"',
    '"WiFiStatus": "0"',
    '"WiFiStatus": "1"',
    '{"WiFiStatus":"0"',
    '{"WiFiStatus":"1"',
    '{"StatoWiFi":"0"',
    '{"StatoWiFi":"1"',
    '"StatoWiFi":"0",',
    '"StatoWiFi":"1",',
    '"StatoWiFi": "0"',
    '"StatoWiFi": "1"',
    # Dishwashers & Ovens
    '{"statusDWash":{"',
    '{"statusDWash": {"',
    '{\r\n\t"statusDWash',
    '{\r\n  "statusDWash',
    '{\n\t"statusDWash":',
    '{\n  "statusDWash":',
    '{"statusForno":{"',
    '{"statusForno": {"',
    '{\r\n\t"statusForno',
    '{\r\n  "statusForno',
    '{\n\t"statusForno":',
    '{\n  "statusForno":',
    '"StatoDWash":"0"',
    '"StatoDWash":"1"',
    '"StatoDWash":"2"',
    '"StatoDWash": "0"',
    '"StatoDWash": "1"',
    '"StatoDWash": "2"',
    # Wine Coolers
    '{"statusWCool":{',
    '{"statusWCool": {',
    '{\r\n\t"statusWCool',
    '{\r\n  "statusWCool',
    '{\n\t"statusWCool"',
    '{\n  "statusWCool":',
    '"statusWCool": {',
    '"statusWCool":{"',
    # Refrigerators & Freezers (CandyFridgeStatus.java)
    '{"statusRefrigera',
    '{\r\n\t"statusRefri',
    '{\r\n  "statusRefri',
    '{\n\t"statusRefrig',
    '{\n  "statusRefrig',
    '"statusRefrigera',
    # Kitchen Hoods (CandyHoodStatus.java)
    '{"StatusHood":{"',
    '{"StatusHood": {"',
    '{\r\n\t"StatusHood',
    '{\r\n  "StatusHood',
    '{\n\t"StatusHood":',
    '{\n  "StatusHood":',
    '"CarbonFilter":"',
    '"GreaseFilter":"',
    # Induction & Gas Cooktops (CandyCookStatus.java)
    '{"statusHob":{"Z',
    '{"statusHob": {"Z',
    '{\r\n\t"statusHob"',
    '{\r\n  "statusHob"',
    '{\n\t"statusHob":',
    '{\n  "statusHob":',
    # Robot Vacuums (CandyVacuumCleanerStatus.java)
    '{"StatusVacuumCl',
    '{\r\n\t"StatusVacu',
    '{\r\n  "StatusVacu',
    '{\n\t"StatusVacuum',
    '{\n  "StatusVacuum',
    '"StatusVacuumCle',
    # General status registers
    '"CodiceErrore":"',
    '"CheckUpState":"',
]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CandyCommunicationError(Exception):
    """Raised when low-level network communication fails."""


class CandyProtocolError(Exception):
    """Raised when device returns invalid or unparseable payload."""


class CandyKeyNotFoundError(Exception):
    """Raised when XOR key recovery fails."""


class CandyCommandError(Exception):
    """Raised when a write command fails."""


# ---------------------------------------------------------------------------
# Cryptographic Primitives
# ---------------------------------------------------------------------------


def is_ascii_printable(text: bytearray) -> bool:
    """Check if bytearray contains only printable ASCII or common whitespace."""
    for ch in text:
        if ch != 0xFF and ch not in (ord("\r"), ord("\n"), ord("\t")):
            if not (0x20 <= ch <= 0x7E):
                return False
    return True


def is_valid_json_bytes(decrypted: bytes) -> bool:
    """Validate that decrypted bytes represent parseable UTF-8 JSON object or array."""
    try:
        parsed = json.loads(decrypted.decode("utf-8", errors="replace"))
        return isinstance(parsed, (dict, list))
    except (json.JSONDecodeError, ValueError):
        return False


def xor_decrypt_bytes(ciphertext: bytes, key: str) -> bytes:
    """Decrypt raw bytes using repeating 16-character ASCII key."""
    if not key:
        return ciphertext
    key_bytes = key.encode("utf-8")
    key_len = len(key_bytes)
    decrypted = bytearray()
    for i, b in enumerate(ciphertext):
        decrypted.append(b ^ key_bytes[i % key_len])
    return bytes(decrypted)


def xor_encrypt_string(plaintext: str, key: str) -> str:
    """Encrypt plaintext string using sliding XOR key into uppercase hex."""
    pt_bytes = plaintext.encode("utf-8")
    if not key:
        return pt_bytes.hex().upper()
    k_bytes = key.encode("utf-8")
    key_len = len(k_bytes)
    encrypted = bytes([pt_bytes[i] ^ k_bytes[i % key_len] for i in range(len(pt_bytes))])
    return encrypted.hex().upper()



def find_xor_key_fragment(ciphertext: bytes, known_plaintext: str) -> str:
    """Search for matching XOR key using sliding window known-plaintext attack."""
    known_bytes = known_plaintext.encode("utf-8")
    if len(known_bytes) < 15:
        raise CandyProtocolError("Known plaintext length must be at least 15 bytes")

    search_bytes = known_bytes[:16] if len(known_bytes) >= 16 else known_bytes

    for pp in range(len(ciphertext) - len(search_bytes) + 1):
        partial_key = bytearray()
        for j in range(len(search_bytes)):
            partial_key.append(ciphertext[pp + j] ^ search_bytes[j])

        if not is_ascii_printable(partial_key):
            continue

        if len(partial_key) == 16:
            for kp in range(16):
                rotated_key = partial_key[kp:] + partial_key[:kp]
                decrypted_text = bytearray()
                for x in range(len(ciphertext)):
                    decrypted_text.append(ciphertext[x] ^ rotated_key[x % 16])

                if is_ascii_printable(decrypted_text) and search_bytes in decrypted_text:
                    if is_valid_json_bytes(bytes(decrypted_text)):
                        return rotated_key.decode("utf-8", errors="replace")

        elif len(partial_key) == 15:
            for missing_b in range(32, 127):
                candidate_16 = bytearray(partial_key)
                candidate_16.append(missing_b)
                for kp in range(16):
                    rotated_key = candidate_16[kp:] + candidate_16[:kp]
                    decrypted_text = bytearray()
                    for x in range(len(ciphertext)):
                        decrypted_text.append(ciphertext[x] ^ rotated_key[x % 16])

                    if is_ascii_printable(decrypted_text) and search_bytes in decrypted_text:
                        if is_valid_json_bytes(bytes(decrypted_text)):
                            return rotated_key.decode("utf-8", errors="replace")

    return ""


def discover_xor_key(ciphertext: bytes, known_plaintexts: list[str]) -> str | None:
    """Iterate through signature table to recover 16-character encryption key."""
    for kp in known_plaintexts:
        key = find_xor_key_fragment(ciphertext, kp)
        if key:
            return key
    return None


# ---------------------------------------------------------------------------
# Low-Level Network Transport
# ---------------------------------------------------------------------------


def parse_http_status_code(header_bytes: bytes) -> int | None:
    """Extract HTTP status code from response status line (e.g., HTTP/1.1 200 OK -> 200)."""
    header_str = header_bytes.decode("latin1", errors="ignore")
    lines = header_str.splitlines()
    if not lines:
        return None
    parts = lines[0].strip().split(" ", 2)
    if len(parts) >= 2 and parts[1].isdigit():
        return int(parts[1])
    return None


def parse_content_length_header(header_bytes: bytes) -> int | None:
    """Extract Content-Length header value if present."""
    header_str = header_bytes.decode("latin1", errors="ignore")
    for line in header_str.split("\n"):
        line_clean = line.strip().lower()
        if line_clean.startswith("content-length:"):
            val_str = line_clean.split(":", 1)[1].strip()
            if val_str.isdigit():
                return int(val_str)
    return None


def parse_device_address(target_addr: str) -> tuple[str, int]:
    """Parse IP address and optional port from input string, stripping URI schemes."""
    addr = target_addr.strip()
    if addr.startswith("http://"):
        addr = addr[7:]
    elif addr.startswith("https://"):
        addr = addr[8:]
    addr = addr.rstrip("/")

    port = 80
    if ":" in addr:
        host_part, port_part = addr.rsplit(":", 1)
        if port_part.isdigit():
            return host_part, int(port_part)
    return addr, port


def is_truthy_value(val: Any) -> bool:
    """Check if value represents a truthy flag ('1', 1, True, 'true')."""
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    return s in ("1", "true")


def send_raw_http_get(device_ip: str, port: int, path: str, timeout_sec: int) -> bytes:
    """Send raw HTTP GET over TCP socket and return body bytes."""
    response = bytearray()
    body_start = -1
    content_length: int | None = None
    status_code: int | None = None

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(float(timeout_sec))
            sock.connect((device_ip, port))
            request = f"GET {path} HTTP/1.1\r\nHost: {device_ip}\r\nConnection: close\r\n\r\n"
            sock.sendall(request.encode("utf-8"))

            while True:
                try:
                    chunk = sock.recv(2048)
                except (TimeoutError, socket.timeout):
                    # If Content-Length was not specified and we already received body data,
                    # treat connection idle as completed response.
                    if content_length is None and body_start != -1 and len(response) > body_start:
                        break
                    raise

                if not chunk:
                    break
                response.extend(chunk)

                # Check if headers are received
                if body_start == -1:
                    header_split = response.find(b"\r\n\r\n")
                    if header_split != -1:
                        body_start = header_split + 4
                        header_chunk = bytes(response[:header_split])
                        content_length = parse_content_length_header(header_chunk)
                        status_code = parse_http_status_code(header_chunk)
                    else:
                        header_split_alt = response.find(b"\n\n")
                        if header_split_alt != -1:
                            body_start = header_split_alt + 2
                            header_chunk = bytes(response[:header_split_alt])
                            content_length = parse_content_length_header(header_chunk)
                            status_code = parse_http_status_code(header_chunk)

                # If Content-Length is satisfied, break immediately without waiting for TCP FIN
                if content_length is not None and body_start != -1:
                    if len(response) - body_start >= content_length:
                        break

    except Exception as exc:
        if content_length is None and body_start != -1 and len(response) > body_start:
            pass
        else:
            raise CandyCommunicationError(
                f"Failed to connect to {device_ip}:{port} on path '{path}': {exc}"
            ) from exc

    if status_code is not None and status_code >= 400:
        raise CandyProtocolError(f"Appliance returned HTTP error {status_code} on path '{path}'")

    if body_start == -1:
        return b""

    return bytes(response[body_start:])


def parse_hex_response_body(body_bytes: bytes) -> bytes:
    """Clean body and convert hex string to raw binary bytes or return UTF-8 JSON bytes."""
    raw_str = body_bytes.decode("utf-8", errors="ignore").strip().strip("\x00").strip()
    if not raw_str:
        return b""

    # If already JSON plaintext (single-line or multi-line)
    if (raw_str.startswith("{") and raw_str.endswith("}")) or (raw_str.startswith("[") and raw_str.endswith("]")):
        return raw_str.encode("utf-8")

    # If hex payload contains embedded newlines, isolate the hex line
    lines = [line.strip() for line in raw_str.splitlines() if line.strip()]
    hex_line = lines[-1] if lines else ""

    if hex_line.startswith("{") and hex_line.endswith("}"):
        return hex_line.encode("utf-8")

    # Strip any embedded spaces or tabs that could corrupt fromhex
    hex_line = hex_line.replace(" ", "").replace("\t", "")

    if len(hex_line) % 2 == 1:
        hex_line = "0" + hex_line

    try:
        return bytes.fromhex(hex_line)
    except ValueError as exc:
        raise CandyProtocolError(f"Could not parse hex payload from device: {exc}") from exc



def fetch_endpoint_payload(
    device_ip: str, port: int, endpoint: str, query_string: str, timeout_sec: int
) -> bytes:
    """Fetch endpoint payload with query string over raw socket."""
    path = f"/http-{endpoint}.json"
    if query_string:
        path = f"{path}?{query_string}"
    body = send_raw_http_get(device_ip, port, path, timeout_sec)
    return parse_hex_response_body(body)


def fetch_or_discover_telemetry(
    device_ip: str, port: int, key: str, timeout_sec: int
) -> tuple[dict[str, Any], str, bool]:
    """Fetch telemetry in a single request, discovering XOR key if not provided."""
    raw_bytes = fetch_endpoint_payload(device_ip, port, "read", "encrypted=1", timeout_sec)
    if not raw_bytes:
        raise CandyProtocolError("Empty response received from /http-read.json")

    # Case 1: Plaintext JSON already
    if is_valid_json_bytes(raw_bytes):
        return json.loads(raw_bytes.decode("utf-8", errors="replace")), "", False

    # Case 2: Explicit key provided
    if key:
        decrypted = xor_decrypt_bytes(raw_bytes, key)
        if not is_valid_json_bytes(decrypted):
            raise CandyProtocolError(f"Provided key '{key}' failed to decrypt valid JSON")
        return json.loads(decrypted.decode("utf-8", errors="replace")), key, True

    # Case 3: Key not provided -> discover from ciphertext
    discovered_key = discover_xor_key(raw_bytes, KNOWN_PLAINTEXTS)
    if not discovered_key:
        raise CandyKeyNotFoundError(
            "Could not discover encryption key automatically. Please provide key explicitly."
        )

    decrypted = xor_decrypt_bytes(raw_bytes, discovered_key)
    return json.loads(decrypted.decode("utf-8", errors="replace")), discovered_key, True


def family_key_supports_statistics(family_key: str) -> bool:
    """Return True if the appliance family supports cycle statistics counters."""
    return family_key in ("statusLavatrice", "statusWD", "statusWM", "statusTD")


def fetch_config_json(
    device_ip: str, port: int, key: str, use_encryption: bool, timeout_sec: int
) -> dict[str, Any]:
    """Fetch and decrypt device configuration dictionary."""
    query = "encrypted=1" if use_encryption else "encrypted=0"
    raw_bytes = fetch_endpoint_payload(device_ip, port, "config", query, timeout_sec)
    if not raw_bytes:
        return {"status": "Empty config payload"}

    decrypted = xor_decrypt_bytes(raw_bytes, key) if (use_encryption and key) else raw_bytes
    text = decrypted.decode("utf-8", errors="replace").strip().strip("\x00").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw_config": text}


def fetch_statistics_json(
    device_ip: str, port: int, key: str, use_encryption: bool, timeout_sec: int
) -> dict[str, Any]:
    """Perform mandatory two-step statistics handshake (prepareStatistics -> getStatistics)."""
    query = "encrypted=1" if use_encryption else "encrypted=0"

    # Step 1: Prepare statistics buffer in firmware
    try:
        fetch_endpoint_payload(device_ip, port, "prepareStatistics", query, timeout_sec)
    except Exception:
        # DualTech and older appliances do not support prepareStatistics; proceed to getStatistics
        pass

    # Step 2: Fetch populated statistics counters
    raw_bytes = fetch_endpoint_payload(device_ip, port, "getStatistics", query, timeout_sec)
    if not raw_bytes:
        raise CandyProtocolError("Empty statistics payload returned")

    decrypted = xor_decrypt_bytes(raw_bytes, key) if use_encryption else raw_bytes
    text = decrypted.decode("utf-8", errors="replace").strip().strip("\x00").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise CandyProtocolError(f"Invalid JSON in statistics response: {exc}") from exc


def send_write_command_payload(
    device_ip: str,
    port: int,
    key: str,
    use_encryption: bool,
    command_query: str,
    timeout_sec: int,
) -> str:
    """Send write command over /http-write.json."""
    if use_encryption and key:
        encrypted_hex = xor_encrypt_string(command_query, key)
        query = f"encrypted=1&data={encrypted_hex}"
    else:
        query = f"encrypted=0&{command_query}"

    path = f"/http-write.json?{query}"
    resp_bytes = send_raw_http_get(device_ip, port, path, timeout_sec)
    return resp_bytes.decode("utf-8", errors="replace").strip()


# ---------------------------------------------------------------------------
# Appliance Telemetry Dissector & Schema Decoder
# ---------------------------------------------------------------------------

ROOT_KEYS_TO_FAMILY: dict[str, str] = {
    "statusLavatrice": "Washing Machine / Washer-Dryer",
    "statusWD": "Washer-Dryer Combo",
    "statusWM": "Washing Machine",
    "statusTD": "Tumble Dryer",
    "statusDWash": "Dishwasher",
    "statusForno": "Oven",
    "statusWCool": "Wine Cooler",
    "statusRefrigerator": "Refrigerator / Freezer",
    "StatusHood": "Kitchen Hood",
    "statusHob": "Induction / Gas Cooktop",
    "StatusVacuumCleaner": "Robot Vacuum Cleaner",
}


def convert_fahrenheit_to_celsius(f_temp: float) -> float:
    """Convert Fahrenheit temperature to Celsius."""
    return (f_temp - 32.0) * 5.0 / 9.0


def detect_appliance_family(json_data: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    """Identify root telemetry envelope and appliance family."""
    for root_key, family_name in ROOT_KEYS_TO_FAMILY.items():
        if root_key in json_data and isinstance(json_data[root_key], dict):
            return root_key, family_name, json_data[root_key]

    # Nested appliance wrapper fallback
    if "appliance" in json_data and isinstance(json_data["appliance"], dict):
        app = json_data["appliance"]
        if "current_status_parameters" in app and isinstance(app["current_status_parameters"], dict):
            return "appliance", "Appliance (Wrapped)", app["current_status_parameters"]

    return "unknown", "Unknown Appliance", json_data


def decode_registers(family_key: str, data: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Decode raw wire telemetry registers into structured (Key, RawValue, Description) tuples."""
    results: list[tuple[str, str, str]] = []

    # Washers & Washer-Dryers
    if family_key in ("statusLavatrice", "statusWD", "statusWM"):
        mach_mode_map = {
            "1": "Idle / Standby",
            "2": "Running",
            "3": "Paused",
            "4": "Delayed start selection",
            "5": "Delayed start programmed",
            "6": "Error",
            "7": "Finished",
            "8": "Finished",
        }
        phase_map = {
            "0": "Stopped",
            "1": "Pre-wash",
            "2": "Wash",
            "3": "Rinse",
            "4": "Last rinse",
            "5": "End",
            "6": "Drying",
            "7": "Error",
            "8": "Steam",
            "9": "Spin - Good night",
            "10": "Spin",
        }
        dry_target_map = {
            "0": "None",
            "1": "Extra Dry",
            "2": "Cupboard Dry",
            "3": "Iron Dry",
            "4": "Cooldown",
            "5": "120 min",
            "6": "90 min",
            "7": "60 min",
            "8": "30 min",
            "9": "Wool Dry",
        }

        for k, v in data.items():
            val = str(v)
            desc = ""
            if k == "MachMd":
                desc = mach_mode_map.get(val, "Unknown mode")
            elif k == "PrPh":
                desc = phase_map.get(val, "Unknown phase")
            elif k in ("Pr", "PrNm"):
                desc = f"Program selector index {val}"
            elif k == "PrCode":
                desc = f"Program firmware code {val}"
            elif k == "Temp":
                desc = f"{val} °C wash temperature" if val != "0" else "Cold wash (0 °C)"
            elif k == "SpinSp":
                try:
                    desc = f"{int(val) * 100} RPM spin speed" if val != "0" else "No spin (0 RPM)"
                except ValueError:
                    desc = f"{val} spin speed"
            elif k == "RemTime":
                try:
                    desc = f"{round(int(val) / 60)} minutes remaining"
                except ValueError:
                    desc = f"{val} remaining time"
            elif k == "DryT":
                desc = dry_target_map.get(val, f"{val} min / dryness level")
            elif k in ("WiFiStatus", "StatoWiFi", "RemCode"):
                desc = "Remote Control ENABLED" if is_truthy_value(val) else "Remote Control DISABLED"
            elif k == "DoorLock":
                desc = "Door locked" if is_truthy_value(val) else "Door unlocked"
            elif k == "FillR":
                desc = f"{val}% estimated load weight"
            elif k in ("Err", "CodiceErrore"):
                desc = "No fault" if val == "0" else f"Fault code {val}"
            elif k == "CheckUpState":
                desc = "Diagnostic check-up active" if is_truthy_value(val) else "Check-up idle"
            elif k in ("SLevel", "SLevTgt"):
                desc = f"Soil level {val} (" + {"1": "Light", "2": "Normal", "3": "Heavy"}.get(val, "Custom") + ")"
            elif k == "DelVal":
                desc = f"{val} min delayed start remaining"
            elif k == "NtcW":
                desc = f"{val} wash water temperature (ADC reading)"
            elif k == "NtcD":
                desc = f"{val} drying drum temperature (ADC reading)"
            elif k == "RecipeId":
                desc = f"Downloadable / NFC program '{val}'"
            elif k in ("OptMsk", "OptMsk1"):
                desc = f"Wash options bitmask {val}"
            elif k == "Stm":
                desc = "Steam option ACTIVE" if is_truthy_value(val) else "Steam off"
            elif k == "APSfreq":
                desc = f"{val} Hz motor inverter frequency"
            elif k == "motS":
                desc = f"Motor state code {val}"
            elif k == "unbF":
                desc = f"Unbalance fault count {val}"
            elif k == "unbC":
                desc = f"Unbalance event count {val}"
            elif k == "numF":
                desc = f"Total lifetime fault count {val}"
            elif k == "DisTestRes":
                desc = f"Check-up diagnostic result code {val}"

            results.append((k, val, desc))

    # Tumble Dryers
    elif family_key == "statusTD":
        td_mode_map = {
            "0": "Standby / Off",
            "1": "Selection / Idle",
            "2": "Running",
            "3": "Paused",
            "4": "Delayed start selection",
            "5": "Delayed start countdown",
            "6": "Test mode",
            "7": "Error mode",
            "8": "Finished / Completed",
        }
        td_phase_map = {
            "0": "Stopped",
            "1": "Pre-heating",
            "2": "Running (Active Drying)",
            "3": "Completed / End",
        }
        dry_lev_map = {
            "1": "Iron Dry",
            "2": "Hang Dry",
            "3": "Store / Cupboard Dry",
            "4": "Bone Dry",
        }

        for k, v in data.items():
            val = str(v)
            desc = ""
            if k == "StatoTD":
                desc = td_mode_map.get(val, "Unknown mode")
            elif k == "PrPh":
                desc = td_phase_map.get(val, "Unknown phase")
            elif k == "Pr":
                desc = f"Program ID {val}"
            elif k == "DryLev":
                desc = dry_lev_map.get(val, f"Dryness level {val}")
            elif k == "DryingManagerLevel":
                desc = dry_lev_map.get(val, f"Selected dryness target {val}")
            elif k == "RemTime":
                desc = f"{val} minutes remaining"
            elif k == "WaterTankFull":
                desc = "Water container FULL" if is_truthy_value(val) else "Water tank OK"
            elif k == "CleanFilter":
                desc = "Lint filter clean REQUIRED" if is_truthy_value(val) else "Filter clean OK"
            elif k == "DoorState":
                desc = "Door CLOSED" if is_truthy_value(val) else "Door OPEN"
            elif k in ("StatoWiFi", "RemCode"):
                desc = "Remote Control ENABLED" if is_truthy_value(val) else "Remote Control DISABLED"
            elif k == "DelVal":
                desc = f"{val} min delayed start remaining"
            elif k == "RecipeId":
                desc = f"Downloadable / NFC program '{val}'"
            elif k == "Rapido":
                desc = f"Timed / Rapid dry index {val}"
            elif k == "Time":
                desc = f"{val} min timed dry duration"
            elif k == "Refresh":
                desc = "Refresh / Anti-crease ACTIVE" if is_truthy_value(val) else "Refresh off"
            elif k in ("Err", "CodiceErrore"):
                desc = "No fault" if val in ("0", "E0") else f"Fault code {val}"
            elif k == "CheckUpState":
                desc = "Diagnostic check-up active" if is_truthy_value(val) else "Check-up idle"

            results.append((k, val, desc))

    # Dishwashers
    elif family_key == "statusDWash":
        dw_mode_map = {
            "0": "Idle / Ready",
            "1": "Pre-wash",
            "2": "Main Wash",
            "3": "Rinse",
            "4": "Drying",
            "5": "Cycle Finished",
        }

        for k, v in data.items():
            val = str(v)
            desc = ""
            if k == "StatoDWash":
                desc = dw_mode_map.get(val, "Unknown state")
            elif k == "Program":
                desc = f"Program {val}"
            elif k == "OpzProg":
                desc = "Option Plus (+)" if val == "p" else ("Option Minus (-)" if val == "m" else "Standard")
            elif k == "RemTime":
                desc = f"{val} minutes remaining"
            elif k == "OpenDoor":
                desc = "Door OPEN" if is_truthy_value(val) else "Door CLOSED"
            elif k == "OpenDoorOpt":
                desc = "Automatic door opening active" if is_truthy_value(val) else "Auto-door off"
            elif k == "MissSalt":
                desc = "Salt container EMPTY" if is_truthy_value(val) else "Salt level OK"
            elif k == "MissRinse":
                desc = "Rinse aid container EMPTY" if is_truthy_value(val) else "Rinse aid OK"
            elif k == "Eco":
                desc = "Eco cycle active" if is_truthy_value(val) else "Eco off"
            elif k == "MetaCarico":
                desc = "Half load active" if is_truthy_value(val) else "Standard load"
            elif k == "TreinUno":
                desc = "3-in-1 tablet active" if is_truthy_value(val) else "Standard detergent"
            elif k == "ExtraDry":
                desc = "Extra dry active" if is_truthy_value(val) else "Extra dry off"
            elif k == "DelayStart":
                desc = f"{val} hours delayed start countdown"
            elif k == "StatoWiFi":
                desc = "Remote Control ENABLED" if is_truthy_value(val) else "Remote Control DISABLED"
            elif k in ("Err", "CodiceErrore"):
                desc = "No fault" if val in ("0", "E0") else f"Fault code {val}"

            results.append((k, val, desc))

    # Ovens
    elif family_key == "statusForno":
        for k, v in data.items():
            val = str(v)
            desc = ""
            if k == "StartStop":
                desc = "Heating / Running" if is_truthy_value(val) else "Idle / Stopped"
            elif k == "Pausa":
                desc = "PAUSED" if is_truthy_value(val) else "Running / Ready"
            elif k == "Program":
                desc = f"Heating program {val}"
            elif k == "Selettore":
                desc = f"Selector position {val}"
            elif k == "TempRead":
                try:
                    f_val = float(val)
                    c_val = round(convert_fahrenheit_to_celsius(f_val))
                    desc = f"{c_val} °C ({f_val} °F) measured cavity temp"
                except ValueError:
                    desc = f"{val} temp reading"
            elif k == "TempSet":
                try:
                    desc = f"{int(val) // 10 if int(val) > 100 else int(val)} °C target temp"
                except ValueError:
                    desc = f"{val} target temp"
            elif k == "TempSetRaggiunta":
                desc = "Target temperature REACHED" if is_truthy_value(val) else "Preheating / Heating up"
            elif k == "DoorLock":
                desc = "Door locked" if is_truthy_value(val) else "Door unlocked"
            elif k == "SicurezzaBambini":
                desc = "Child lock active" if is_truthy_value(val) else "Child lock off"
            elif k == "TimeProgr":
                desc = f"{val} min programmed duration"
            elif k == "RecipeId":
                desc = f"Recipe '{val}'"
            elif k == "RecipeStep":
                desc = f"Recipe step {val}"
            elif k == "StatoWiFi":
                desc = "Remote Control ENABLED" if is_truthy_value(val) else "Remote Control DISABLED"

            results.append((k, val, desc))

    # Wine Coolers
    elif family_key == "statusWCool":
        wc_prog_map = {"1": "Red Wine", "2": "White Wine", "3": "Sparkling Wine"}
        for k, v in data.items():
            val = str(v)
            desc = ""
            if k == "r1":
                desc = "Remote Control ENABLED" if is_truthy_value(val) else "Remote Control DISABLED"
            elif k == "r2":
                desc = "Normal operation" if val == "E0" else f"Fault code {val}"
            elif k == "r3":
                desc = wc_prog_map.get(val, f"Zone 1 program {val}")
            elif k == "r4":
                desc = f"{val} °C Zone 1 set temp"
            elif k == "r5":
                desc = "Powered ON" if val == "2" else ("Powered OFF" if val == "0" else f"State {val}")
            elif k == "r6":
                desc = f"{val} °C Zone 1 measured temp"
            elif k == "r7":
                desc = wc_prog_map.get(val, f"Zone 2 program {val}")
            elif k == "r8":
                desc = f"{val} °C Zone 2 set temp"
            elif k == "r9":
                desc = f"{val} °C Zone 2 measured temp"
            elif k == "r10":
                desc = "Interior light ON" if is_truthy_value(val) else "Interior light OFF"
            elif k == "r11":
                desc = "Fahrenheit scale" if val == "1" else "Celsius scale"

            results.append((k, val, desc))

    # Refrigerators & Freezers
    elif family_key == "statusRefrigerator":
        for k, v in data.items():
            val = str(v)
            desc = ""
            if k == "FrSet":
                desc = f"{val} °C fridge compartment set temp"
            elif k == "FzSet":
                desc = f"-{val} °C freezer compartment set temp"
            elif k == "Door":
                desc = "Door OPEN" if is_truthy_value(val) else "Door CLOSED"
            elif k in ("DoorOpenCnt", "IncrDoorCnt"):
                desc = f"Door opened {val} times"
            elif k == "Cmp":
                desc = "Compressor RUNNING" if is_truthy_value(val) else "Compressor IDLE"
            elif k == "CmpFq":
                desc = f"{val} Hz compressor motor frequency"
            elif k == "Fan":
                desc = "Circulation fan RUNNING" if is_truthy_value(val) else "Fan off"
            elif k == "Heat":
                desc = "Defrost heater ACTIVE" if is_truthy_value(val) else "Defrost heater off"
            elif k == "Eco":
                desc = "Eco energy saving ACTIVE" if is_truthy_value(val) else "Eco off"
            elif k == "Spr":
                desc = "Super Freezing ACTIVE" if is_truthy_value(val) else "Super Freeze off"
            elif k == "SprC":
                desc = "Super Cooling ACTIVE" if is_truthy_value(val) else "Super Cool off"
            elif k == "Antib":
                desc = "Anti-bacterial sterilization ACTIVE" if is_truthy_value(val) else "Anti-bacterial off"
            elif k == "Ice":
                desc = "Ice maker ACTIVE" if is_truthy_value(val) else "Ice maker off"
            elif k == "NewIce":
                desc = f"{val} min drink chill countdown duration"
            elif k == "Lck":
                desc = "Child lock ACTIVE" if is_truthy_value(val) else "Child lock off"
            elif k == "PF":
                desc = "Power failure warning ACTIVE" if is_truthy_value(val) else "Power OK"
            elif k in ("WiFi", "WiFiStatus", "StatoWiFi"):
                desc = "Remote Control ENABLED" if is_truthy_value(val) else "Remote Control DISABLED"

            results.append((k, val, desc))

    # Kitchen Hoods
    elif family_key == "StatusHood":
        for k, v in data.items():
            val = str(v)
            desc = ""
            if k == "Fan":
                desc = "Intensive / Booster" if val == "4" else (f"Speed {val}" if val != "0" else "Fan OFF")
            elif k == "Light":
                desc = "Light ON" if val == "1" else ("Ambient light" if val == "2" else "Light OFF")
            elif k == "GreaseFilter":
                desc = "Grease filter saturation WARNING" if is_truthy_value(val) else "Grease filter OK"
            elif k == "CarbonFilter":
                desc = "Carbon filter replacement WARNING" if is_truthy_value(val) else "Carbon filter OK"
            elif k == "Timer":
                desc = "Auto-off timer ACTIVE" if is_truthy_value(val) else "Timer off"
            elif k == "TimerCnt":
                desc = f"{val} min remaining on auto-off timer"
            elif k == "BoostCnt":
                desc = f"{val} sec remaining on booster"
            elif k in ("WiFiStatus", "StatoWiFi"):
                desc = "Remote Control ENABLED" if is_truthy_value(val) else "Remote Control DISABLED"

            results.append((k, val, desc))

    # Cooktops & Hobs
    elif family_key == "statusHob":
        for k, v in data.items():
            val = str(v)
            desc = ""
            if k == "lock":
                desc = "Child lock ACTIVE" if is_truthy_value(val) else "Child lock off"
            elif k.endswith("status") and len(k) == 8:
                desc = "Zone ACTIVE" if is_truthy_value(val) else "Zone OFF"
            elif k.endswith("power") and len(k) == 7:
                desc = f"Power level {val}"
            elif k.endswith("hot") and len(k) == 5:
                desc = "Residual heat (HOT 'H')" if is_truthy_value(val) else "Safe / Cold"
            elif k.endswith("pan") and len(k) == 5:
                desc = "Cookware detected" if is_truthy_value(val) else "No cookware / unsuitable"
            elif k.endswith("combi") and len(k) == 7:
                desc = "Bridge / coupled zone" if is_truthy_value(val) else "Single zone"
            elif k.endswith("low") and len(k) == 5:
                desc = "Keep warm / melting active" if is_truthy_value(val) else "Standard mode"
            elif k in ("StatoWiFi", "WiFiStatus"):
                desc = "Remote Control ENABLED" if is_truthy_value(val) else "Remote Control DISABLED"

            results.append((k, val, desc))

    # Robot Vacuums
    elif family_key == "StatusVacuumCleaner":
        for k, v in data.items():
            val = str(v)
            desc = ""
            if k == "MachMd":
                desc = f"Operating mode {val}"
            elif k == "BaSt":
                desc = f"{val}% battery level"
            elif k == "LockSt":
                desc = "LOCKED" if is_truthy_value(val) else "UNLOCKED"
            elif k == "Tarea":
                desc = f"{val} m² total area cleaned"
            elif k == "TMin":
                desc = f"{val} minutes lifetime cleaning"
            elif k == "DBN":
                desc = "Dust bin missing/full ERROR" if is_truthy_value(val) else "Dust bin OK"
            elif k == "FiErr":
                desc = "Filter blockage ERROR" if is_truthy_value(val) else "Filter OK"
            elif k == "BMO":
                desc = "Brush motor fault ERROR" if is_truthy_value(val) else "Brush motor OK"
            elif k == "RMO":
                desc = "Wheel motor fault ERROR" if is_truthy_value(val) else "Wheel motor OK"

            results.append((k, val, desc))

    # Fallback for generic registers
    else:
        for k, v in data.items():
            val = str(v)
            desc = ""
            if k in ("WiFiStatus", "StatoWiFi", "RemCode", "WiFi"):
                desc = "Remote Control ENABLED" if is_truthy_value(val) else "Remote Control DISABLED"
            elif k in ("Err", "CodiceErrore"):
                desc = "No fault" if val in ("0", "E0") else f"Fault code {val}"
            results.append((k, val, desc))

    return results


def evaluate_remote_control(family_key: str, data: dict[str, Any]) -> dict[str, Any]:
    """Evaluate remote control prerequisites and identify write capabilities."""
    remote_flag = False
    for flag_key in ("WiFiStatus", "StatoWiFi", "RemCode", "WiFi", "r1"):
        if flag_key in data and is_truthy_value(data[flag_key]):
            remote_flag = True
            break

    supported_commands: list[str] = []
    dial_notes: str = ""

    if family_key in ("statusLavatrice", "statusWD", "statusWM"):
        dial_pos = data.get("Pr", data.get("PrNm", "unknown"))
        if str(dial_pos) == "15":
            dial_notes = "Physical dial knob is parked on Wi-Fi position (Hoover DualTech/One-Fi position 15)."
        else:
            dial_notes = f"Physical dial position is {dial_pos}. Must be set to Wi-Fi / Remote position to start."
        supported_commands = [
            "Start Cycle (Write=1&StSt=1&...)",
            "Pause Cycle (Write=1&Pa=1 or StSt=2)",
            "Resume Cycle (Write=1&Pa=0)",
            "Cancel Cycle (Write=1&StSt=0&...)",
            "Self Check-up (Write=1&CheckUpState=1)",
        ]

    elif family_key == "statusTD":
        supported_commands = [
            "Start Drying Cycle",
            "Pause Drying",
            "Cancel / Stop Drying",
        ]

    elif family_key == "statusDWash":
        door_open = is_truthy_value(data.get("OpenDoor", "0"))
        dial_notes = "Door is OPEN! Close door before sending start commands." if door_open else "Door is CLOSED."
        supported_commands = [
            "Start Wash (StartStop=1&Program=P<pos>&DelayStart=0&TreinUno=0&Eco=0&MetaCarico=0&ExtraDry=0&OpzProg=0)",
            "Reset / Cancel (Reset=1)",
            "Auto Door Pop (OpenDoorOpt=7)",
        ]

    elif family_key == "statusForno":
        supported_commands = [
            "Start Heating (Selettore=S<sel>&Program=P<prog>&TempSet=<C*10>&TimeProgr=<mins>&StartStop=1)",
            "Stop Heating (StartStop=0)",
            "Reset Oven (RecipeId=NULL&RecipeStep=0&Selettore=S0&Program=P1&TempSet=20&TimeProgr=60&StartStop=1)",
        ]

    elif family_key == "statusWCool":
        supported_commands = [
            "Toggle Light (w7=1 or w7=0)",
            "Set Zone 1 Temp (w2=<temp>)",
            "Set Zone 2 Temp (w5=<temp>)",
        ]

    elif family_key == "statusRefrigerator":
        supported_commands = [
            "Set Fridge Temp (Write=1&FrSet=<temp>&FzSet=<temp>&Eco=0&Spr=0&Ice=0&Lck=0)",
            "Set Freezer Temp",
            "Toggle Super Freeze (Spr=1)",
            "Toggle Super Cool (SprC=1)",
            "Toggle Eco Mode (Eco=1)",
            "Reset Power Fail Warning (ResetPF=1)",
        ]

    elif family_key == "StatusHood":
        supported_commands = [
            "Set Fan Speed (Fan=<0..4>)",
            "Set Light Mode (Light=<0..2>)",
            "Delayed Timer (Timer=1)",
        ]

    elif family_key == "StatusVacuumCleaner":
        supported_commands = [
            "Lock Cleaner (LockSt=1)",
            "Unlock Cleaner (LockSt=0)",
            "Sync System Clock (TimeSync=<date>)",
        ]

    return {
        "remote_control_enabled": remote_flag,
        "dial_notes": dial_notes,
        "supported_commands": supported_commands,
    }


def is_sensitive_key(key_name: str) -> str | None:
    """Return sensitive category ('mac', 'ip', or 'secret') if key holds sensitive info."""
    k = key_name.lower().strip()
    if k in ("mac", "macaddr", "mac_address", "bssid", "bssid_address"):
        return "mac"
    if k in ("ip", "ipaddr", "ip_address", "gateway", "subnet", "netmask", "dns", "dns1", "dns2"):
        return "ip"
    if k in ("ssid", "password", "passphrase", "pwd", "key", "encryption_key", "serial", "serial_number", "sn"):
        return "secret"

    parts = k.replace("-", "_").split("_")
    if any(p in ("mac", "bssid") for p in parts):
        return "mac"
    if any(p in ("ip", "gateway", "subnet", "netmask") for p in parts):
        return "ip"
    if any(p in ("ssid", "password", "passphrase", "serial") for p in parts):
        return "secret"

    if k.endswith("mac") or k.endswith("bssid"):
        return "mac"
    if k.endswith("ssid") or k.endswith("password") or k.endswith("passphrase"):
        return "secret"
    if k.endswith("serial"):
        return "secret"

    return None


def sanitize_value(key_name: str, val: Any) -> Any:
    """Sanitize individual value based on key sensitivity."""
    category = is_sensitive_key(key_name)
    if category is None:
        return val

    s = str(val).strip()
    if not s:
        return val

    if category == "mac":
        clean_s = s.replace("-", ":")
        if ":" in clean_s and len(clean_s) >= 8:
            parts = clean_s.split(":")
            if len(parts) == 6:
                return f"{parts[0]}:{parts[1]}:{parts[2]}:**:**:**"
            return clean_s[:8] + ":**:**:**"
        elif len(s) == 12:
            return s[:6] + "******"
        return "***REDACTED***"

    elif category == "ip":
        parts = s.split(".")
        if len(parts) == 4 and all(p.isdigit() for p in parts):
            return f"{parts[0]}.{parts[1]}.*.*"
        return "***REDACTED***"

    if category == "secret":
        if "serial" in key_name.lower() and len(s) >= 6:
            return s[:4] + "********"
        return "***REDACTED***"

    return "***REDACTED***"


def sanitize_data(raw_data: Any) -> Any:
    """Sanitize sensitive local network parameters from diagnostic data (dict or list)."""
    if isinstance(raw_data, dict):
        clean_dict: dict[str, Any] = {}
        for k, v in raw_data.items():
            if isinstance(v, (dict, list)):
                clean_dict[k] = sanitize_data(v)
            else:
                clean_dict[k] = sanitize_value(k, v)
        return clean_dict
    elif isinstance(raw_data, list):
        return [sanitize_data(item) for item in raw_data]
    return raw_data



# ---------------------------------------------------------------------------
# CLI Command Handlers
# ---------------------------------------------------------------------------


def print_header(out_stream: Any) -> None:
    """Print standard CLI banner."""
    print("=" * 78, file=out_stream)
    print(
        f"## Candy Simply-Fi Diagnostic & Telemetry Dissection Tool v{VERSION} ##",
        file=out_stream,
    )
    print(
        "Author: Home Assistant Candy Integration Team (@bigmoby and @auanasgheps). Original Python port by Melvin Groenendaal",
        file=out_stream,
    )
    print("=" * 78, file=out_stream)


def print_usage(out_stream: Any) -> None:
    """Print complete command line usage."""
    print_header(out_stream)
    print(
        """
Usage:
  simplyfi.py <ip> getkey
  simplyfi.py <ip> read    [key]
  simplyfi.py <ip> inspect [key]
  simplyfi.py <ip> remote  [key]
  simplyfi.py <ip> stats   [key]
  simplyfi.py <ip> config  [key]
  simplyfi.py <ip> diagnose [key] [--raw]
  simplyfi.py <ip> write   <key> <query_string>

Commands:
  getkey    Recover 16-character XOR key via known-plaintext attack against all appliance types
  read      Fetch and decrypt current telemetry JSON payload
  inspect   Dissect telemetry registers into a human-readable decoded terminal table
  remote    Check remote control preconditions, physical dial position, and command capabilities
  stats     Execute 2-step statistics handshake (prepareStatistics -> getStatistics)
  config    Fetch network module configuration and firmware details
  diagnose  Run complete diagnostic scan and generate sanitized Markdown report (use --raw for unredacted output)
  write     Send custom query command string to /http-write.json

Examples:
  simplyfi.py 192.168.1.50 getkey
  simplyfi.py 192.168.1.50 inspect
  simplyfi.py 192.168.1.50 diagnose
  simplyfi.py 192.168.1.50 diagnose --raw
  simplyfi.py 192.168.1.50 write 1234567890abcdef "Write=1&StSt=1&PrNm=11&..."
""",
        file=out_stream,
    )


def run_getkey(device_ip: str, port: int, timeout_sec: int) -> None:
    """Execute getkey command."""
    print_header(sys.stdout)
    print(f"Connecting to {device_ip}:{port} on /http-read.json?encrypted=1 ...")
    _, key, use_enc = fetch_or_discover_telemetry(device_ip, port, "", timeout_sec)
    if not key and not use_enc:
        print("-" * 78)
        print("Device is running UNENCRYPTED (plain JSON responses). No XOR key required.")
        print("-" * 78)
        return

    print("-" * 78)
    print(f"SUCCESS: Recovered 16-character XOR key: {key}")
    print("-" * 78)


def run_read(device_ip: str, port: int, key: str, timeout_sec: int) -> None:
    """Execute read command."""
    data, _, _ = fetch_or_discover_telemetry(device_ip, port, key, timeout_sec)
    print(json.dumps(data, indent=2))


def run_inspect(device_ip: str, port: int, key: str, timeout_sec: int) -> None:
    """Execute inspect command."""
    print_header(sys.stdout)
    data, resolved_key, use_enc = fetch_or_discover_telemetry(device_ip, port, key, timeout_sec)
    if use_enc and resolved_key:
        print(f"Using encryption key: {resolved_key}")

    root_key, family_name, appliance_dict = detect_appliance_family(data)
    print("-" * 78)
    print(f"APPLIANCE FAMILY : {family_name}")
    print(f"TELEMETRY ROOT   : '{root_key}'")
    print("-" * 78)

    registers = decode_registers(root_key, appliance_dict)
    print(f"{'Register':<18} | {'Raw Value':<12} | {'Decoded Meaning'}")
    print("-" * 78)
    for reg_key, raw_val, desc in registers:
        print(f"{reg_key:<18} | {raw_val:<12} | {desc}")

    print("-" * 78)


def run_remote_check(device_ip: str, port: int, key: str, timeout_sec: int) -> None:
    """Execute remote check command."""
    print_header(sys.stdout)
    data, _, _ = fetch_or_discover_telemetry(device_ip, port, key, timeout_sec)
    root_key, family_name, appliance_dict = detect_appliance_family(data)
    audit = evaluate_remote_control(root_key, appliance_dict)

    print(f"Appliance Family : {family_name}")
    print(f"Telemetry Root   : '{root_key}'")
    status_str = "ENABLED (Ready for commands)" if audit["remote_control_enabled"] else "DISABLED (Physical action required)"
    print(f"Remote Control   : {status_str}")
    if audit["dial_notes"]:
        print(f"Physical Status  : {audit['dial_notes']}")
    print("-" * 78)
    print("Supported Wire Command Grammars:")
    for cmd in audit["supported_commands"]:
        print(f"  * {cmd}")
    print("-" * 78)


def run_stats(device_ip: str, port: int, key: str, timeout_sec: int) -> None:
    """Execute statistics command."""
    print_header(sys.stdout)
    _, resolved_key, use_enc = fetch_or_discover_telemetry(device_ip, port, key, timeout_sec)
    time.sleep(1.0)
    print("Executing statistics handshake (prepareStatistics -> getStatistics)...")
    stats = fetch_statistics_json(device_ip, port, resolved_key, use_enc, timeout_sec)
    print(json.dumps(stats, indent=2))


def run_config(device_ip: str, port: int, key: str, timeout_sec: int) -> None:
    """Execute config command."""
    print_header(sys.stdout)
    _, resolved_key, use_enc = fetch_or_discover_telemetry(device_ip, port, key, timeout_sec)
    time.sleep(1.0)
    cfg = fetch_config_json(device_ip, port, resolved_key, use_enc, timeout_sec)
    print(json.dumps(cfg, indent=2))


def run_diagnose(device_ip: str, port: int, key: str, sanitize: bool, timeout_sec: int) -> None:
    """Execute diagnose command."""
    print_header(sys.stdout)
    print(f"Starting diagnostic scan against {device_ip}:{port} ...")

    # Step 1: Telemetry (Primary & Mandatory - single request)
    print("[1/3] Fetching appliance telemetry (/http-read.json)...")
    telemetry_dict, resolved_key, use_enc = fetch_or_discover_telemetry(
        device_ip, port, key, timeout_sec
    )
    root_key, family_name, appliance_dict = detect_appliance_family(telemetry_dict)
    print(f"      Identified: {family_name} ('{root_key}')")
    if resolved_key:
        key_display = "***REDACTED***" if sanitize else resolved_key
        print(f"      Recovered encryption key: {key_display}")

    # Step 2: Statistics (Only if supported by family)
    stats_dict: dict[str, Any] = {}
    if family_key_supports_statistics(root_key):
        print("[2/3] Probing cycle statistics...")
        time.sleep(1.0)
        try:
            stats_dict = fetch_statistics_json(device_ip, port, resolved_key, use_enc, 3)
        except Exception:
            stats_dict = {"status": "Statistics counters not available or not supported on this model"}
    else:
        stats_dict = {"status": "Not applicable for this appliance family"}

    # Step 3: Hardware Config (Optional probe with 2.0s timeout)
    print("[3/3] Probing hardware configuration (/http-config.json)...")
    time.sleep(1.0)
    config_dict: dict[str, Any] = {}
    try:
        config_dict = fetch_config_json(device_ip, port, resolved_key, use_enc, 2)
    except Exception:
        config_dict = {"status": "Config endpoint not exposed in normal operating mode"}

    # Step 4: Remote Control Audit & Formatting
    if sanitize:
        config_dict = sanitize_data(config_dict)
        telemetry_dict = sanitize_data(telemetry_dict)
        stats_dict = sanitize_data(stats_dict)
        appliance_dict = telemetry_dict.get(root_key, appliance_dict)

    rc_audit = evaluate_remote_control(root_key, appliance_dict)
    registers = decode_registers(root_key, appliance_dict)

    # Markdown Report Generation
    print("\n" + "=" * 78)
    print("### Candy Simply-Fi Diagnostic Report")
    print("=" * 78)
    print(f"**Appliance Family**: {family_name} (`{root_key}`)")
    print(f"**Encryption**: {'Encrypted (XOR)' if use_enc else 'Unencrypted (Cleartext)'}")
    if resolved_key:
        print(f"**Key**: `{'***REDACTED***' if sanitize else resolved_key}`")
    print(f"**Remote Control**: {'ENABLED' if rc_audit['remote_control_enabled'] else 'DISABLED'}")
    if rc_audit["dial_notes"]:
        print(f"**Dial / Physical State**: {rc_audit['dial_notes']}")

    print("\n#### Decoded Telemetry Registers")
    print("| Register | Value | Meaning |")
    print("| :--- | :--- | :--- |")
    for rk, rv, rd in registers:
        print(f"| `{rk}` | `{rv}` | {rd} |")

    print("\n#### Raw Telemetry Payload")
    print("```json")
    print(json.dumps(telemetry_dict, indent=2))
    print("```")

    if config_dict:
        print("\n#### Device Configuration")
        print("```json")
        print(json.dumps(config_dict, indent=2))
        print("```")

    if stats_dict:
        print("\n#### Appliance Statistics Counters")
        print("```json")
        print(json.dumps(stats_dict, indent=2))
        print("```")

    print("\n" + "=" * 78)
    print("Report complete. This output can be attached directly to Home Assistant Candy issues.")
    print("=" * 78)


def run_write(device_ip: str, port: int, key: str, query_string: str, timeout_sec: int) -> None:
    """Execute write command."""
    print_header(sys.stdout)
    if not query_string:
        raise CandyCommandError("No query string provided for write command.")

    use_enc = bool(key)
    print(f"Sending command to {device_ip}:{port}/http-write.json ...")
    print(f"Query string : {query_string}")
    resp = send_write_command_payload(device_ip, port, key, use_enc, query_string, timeout_sec)
    print("-" * 78)
    print(f"Appliance response: {resp}")
    print("-" * 78)


# ---------------------------------------------------------------------------
# Argument Parser & Entry Point
# ---------------------------------------------------------------------------


def main() -> None:
    """Main CLI entry point."""
    if len(sys.argv) < 2 or sys.argv[1].lower() in ("-h", "--help", "help"):
        print_usage(sys.stdout if len(sys.argv) >= 2 else sys.stderr)
        sys.exit(0 if len(sys.argv) >= 2 else 1)

    raw_ip = sys.argv[1]
    ip, port = parse_device_address(raw_ip)
    timeout = 10

    # Default to diagnose if no subcommand is provided
    if len(sys.argv) == 2:
        print_header(sys.stdout)
        print("Notice: No subcommand specified. Defaulting to 'diagnose' (sanitized)...")
        print("(Run with '--help' to see all available subcommands)\n")
        try:
            run_diagnose(ip, port, "", True, timeout)
            return
        except CandyKeyNotFoundError as err:
            print(f"Key Discovery Error: {err}", file=sys.stderr)
            sys.exit(2)
        except CandyCommunicationError as err:
            print(f"Network Communication Error: {err}", file=sys.stderr)
            sys.exit(3)
        except CandyProtocolError as err:
            print(f"Protocol / Data Error: {err}", file=sys.stderr)
            sys.exit(4)
        except CandyCommandError as err:
            print(f"Command Error: {err}", file=sys.stderr)
            sys.exit(5)
        except Exception as err:
            print(f"Unexpected Error: {err}", file=sys.stderr)
            sys.exit(99)

    cmd_or_key = sys.argv[2].lower()
    args = sys.argv[3:]

    # Direct flag shortcut: simplyfi.py <ip> --raw / -r
    if cmd_or_key in ("--raw", "-r"):
        try:
            run_diagnose(ip, port, "", False, timeout)
            return
        except CandyKeyNotFoundError as err:
            print(f"Key Discovery Error: {err}", file=sys.stderr)
            sys.exit(2)
        except CandyCommunicationError as err:
            print(f"Network Communication Error: {err}", file=sys.stderr)
            sys.exit(3)
        except CandyProtocolError as err:
            print(f"Protocol / Data Error: {err}", file=sys.stderr)
            sys.exit(4)
        except CandyCommandError as err:
            print(f"Command Error: {err}", file=sys.stderr)
            sys.exit(5)
        except Exception as err:
            print(f"Unexpected Error: {err}", file=sys.stderr)
            sys.exit(99)

    try:
        # Standard Subcommands
        if cmd_or_key == "getkey":
            run_getkey(ip, port, timeout)

        elif cmd_or_key == "read":
            key = args[0] if args else ""
            run_read(ip, port, key, timeout)

        elif cmd_or_key == "inspect":
            key = args[0] if args else ""
            run_inspect(ip, port, key, timeout)

        elif cmd_or_key == "remote":
            key = args[0] if args else ""
            run_remote_check(ip, port, key, timeout)

        elif cmd_or_key in ("stats", "getstatistics"):
            key = args[0] if args else ""
            run_stats(ip, port, key, timeout)

        elif cmd_or_key == "config":
            key = args[0] if args else ""
            run_config(ip, port, key, timeout)

        elif cmd_or_key == "diagnose":
            raw_mode = any(a in ("--raw", "-r") for a in args)
            key = next((a for a in args if a not in ("--raw", "-r")), "")
            run_diagnose(ip, port, key, not raw_mode, timeout)

        elif cmd_or_key == "write":
            if len(args) < 2:
                print("Error: write command requires <key> and <query_string>", file=sys.stderr)
                sys.exit(1)
            key = args[0]
            query = args[1]
            run_write(ip, port, key, query, timeout)

        # Legacy fallback compatibility:
        # simplyfi.py <ip> <key> <method: read, inspect, stats, config, diagnose, write>
        elif len(args) >= 1:
            key = sys.argv[2]
            subcmd = args[0].lower()
            if subcmd in ("read", "inspect"):
                run_inspect(ip, port, key, timeout)
            elif subcmd in ("stats", "getstatistics"):
                run_stats(ip, port, key, timeout)
            elif subcmd == "config":
                run_config(ip, port, key, timeout)
            elif subcmd == "remote":
                run_remote_check(ip, port, key, timeout)
            elif subcmd == "diagnose":
                raw_mode = any(a in ("--raw", "-r") for a in args[1:])
                run_diagnose(ip, port, key, not raw_mode, timeout)
            elif subcmd == "write":
                query = args[1] if len(args) > 1 else ""
                run_write(ip, port, key, query, timeout)
            else:
                print(f"Unknown command: {subcmd}", file=sys.stderr)
                sys.exit(1)
        else:
            print(f"Unknown command or invalid syntax: {cmd_or_key}", file=sys.stderr)
            print_usage(sys.stderr)
            sys.exit(1)

    except CandyKeyNotFoundError as err:
        print(f"Key Discovery Error: {err}", file=sys.stderr)
        sys.exit(2)
    except CandyCommunicationError as err:
        print(f"Network Communication Error: {err}", file=sys.stderr)
        sys.exit(3)
    except CandyProtocolError as err:
        print(f"Protocol / Data Error: {err}", file=sys.stderr)
        sys.exit(4)
    except CandyCommandError as err:
        print(f"Command Error: {err}", file=sys.stderr)
        sys.exit(5)
    except Exception as err:
        print(f"Unexpected Error: {err}", file=sys.stderr)
        sys.exit(99)



if __name__ == "__main__":
    main()
