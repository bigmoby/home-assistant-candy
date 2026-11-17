"""Decryption utilities for Candy Simply-Fi devices.

Algorithm ported from simplyfi.py (tools/simplyfi.py) — known-plaintext
sliding window attack to recover the XOR key from the encrypted response.
"""

from enum import Enum
import json
import logging

_LOGGER = logging.getLogger(__name__)

# Known plaintext fragments present in Candy device JSON responses.
# Each string must be <= 17 bytes (16 bytes are used as the XOR search window).
# Both top-level ({"WiFiStatus":) and nested (\t\t"StatoWiFi":) variants are
# listed to cover all known response formats.
KNOWN_PLAINTEXTS = [
    '{"WiFiStatus":"0"',
    '{"WiFiStatus":"1"',
    '{"StatoWiFi":"0"',
    '{"StatoWiFi":"1"',
    '"WiFiStatus":"0"',
    '"WiFiStatus":"1"',
    '"StatoWiFi":"0",',
    '"StatoWiFi":"1",',
    '"CodiceErrore":"',
    '"CheckUpState":"',
    '{\r\n\t"statusWCool',
    '{\r\n\t"statusLavat',
    '{\r\n\t"statusTD":{',
    '{\r\n\t"statusForno',
    '{\r\n\t"statusDWash',
    '{\r\n  "statusWCool',
    '{\r\n  "statusLavat',
    '{\r\n  "statusTD":{',
    '{\r\n  "statusForno',
    '{\r\n  "statusDWash',
    '{\n\t"statusWCool"',
    '{\n\t"statusLavatri',
    '{\n\t"statusForno":',
    '{\n\t"statusDWash":',
    '{\n  "statusWCool":',
    '{\n  "statusLavatri',
    '{\n  "statusForno":',
    '{\n  "statusDWash":',
    '{"statusWCool":{',
    '{"statusLavatrice',
    '{"statusTD":{',
    '{"statusForno":{',
    '{"statusDWash":{',
    '"statusWCool":{',
    '"statusWCool": {',
]


class Encryption(Enum):
    NO_ENCRYPTION = 1  # Use `encrypted=0` in request, response is plaintext JSON
    ENCRYPTION = (
        2  # Use `encrypted=1` in request, response is encrypted bytes in hex encoding
    )

    # Use `encrypted=1` in request, response is unencrypted hex bytes
    # https://github.com/ofalvai/home-assistant-candy/issues/35#issuecomment-965557116)
    ENCRYPTION_WITHOUT_KEY = 3


def is_printable(text: bytearray) -> bool:
    for ch in text:
        if ch != 0xFF and ch not in (ord("\r"), ord("\n"), ord("\t")):
            if not (0x20 <= ch <= 0x7E):
                return False
    return True


def find_xor_key(data: bytes, known_plaintext: str) -> str:
    known_bytes = known_plaintext.encode("utf-8")
    if len(known_bytes) > 17:
        _LOGGER.error("The length of the known plaintext is greater than 16!")
        return ""

    search_bytes = known_bytes[:16] if len(known_bytes) == 17 else known_bytes

    for pp in range(len(data) - len(search_bytes) + 1):
        partial_key = bytearray()
        for j in range(len(search_bytes)):
            partial_key.append(data[pp + j] ^ search_bytes[j])

        if is_printable(partial_key):
            for kl in range(len(partial_key), 17):
                for kp in range(kl):
                    expanded_key = bytearray(partial_key)
                    expanded_key.extend([0xFF] * (kl - len(partial_key)))
                    expanded_key = expanded_key[kp:] + expanded_key[:kp]

                    decrypted_text = bytearray()
                    for x in range(len(data)):
                        k_byte = expanded_key[x % len(expanded_key)]
                        if k_byte == 0xFF:
                            decrypted_text.append(0xFF)
                        else:
                            decrypted_text.append(data[x] ^ k_byte)

                    if is_printable(decrypted_text):
                        if known_bytes in decrypted_text:
                            if _is_valid_json(bytes(decrypted_text)):
                                key_str = "".join(
                                    chr(c) for c in expanded_key if c != 0xFF
                                )
                                return key_str[:16]
    return ""


def find_key(encrypted_response: bytes) -> str | None:
    for kp in KNOWN_PLAINTEXTS:
        key = find_xor_key(encrypted_response, kp)
        if key:
            _LOGGER.debug("Potential encryption key found")
            return key

    return None


def decrypt(key: bytes, encrypted_response: bytes) -> bytes:
    key_len = len(key)
    decrypted: list[int] = []
    for i, byte in enumerate(encrypted_response):
        decrypted.append(byte ^ key[i % key_len])
    return bytes(decrypted)


def _is_valid_json(decrypted: bytes) -> bool:
    try:
        json.loads(decrypted)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return False
    return True
