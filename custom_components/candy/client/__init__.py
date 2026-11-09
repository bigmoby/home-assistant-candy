import asyncio
import json
from json import JSONDecodeError
import logging
from pathlib import Path
from typing import Any

import aiohttp
from aiohttp import ClientSession
from aiolimiter import AsyncLimiter
import async_timeout
import backoff

from .decryption import Encryption, decrypt, find_key
from .dryer_commands import (
    DryerCommandBuilder as DryerCommandBuilder,
    DualTechDryerCommandBuilder as DualTechDryerCommandBuilder,
    get_dryer_command_builder as get_dryer_command_builder,
    is_dualtech_dryer_interface as is_dualtech_dryer_interface,
)
from .model import (
    DishwasherStatus,
    DownloadableProgram as DownloadableProgram,
    OvenStatus,
    TumbleDryerProgram as TumbleDryerProgram,
    TumbleDryerStatus,
    WasherDryerDryTarget as WasherDryerDryTarget,
    WashingMachineStatistics,
    WashingMachineStatus,
    WashingMachineWashProgram as WashingMachineWashProgram,
    WineCoolerStatus,
    load_downloadable_programs as load_downloadable_programs,
)

_LOGGER = logging.getLogger(__name__)

_raw_parent_map = json.loads(
    (Path(__file__).parent / "parent_to_program.json").read_text(encoding="utf-8")
)
_PARENT_TO_PROGRAM: dict[int, list[str]] = {}
for _entry in sorted(_raw_parent_map, key=lambda e: e["Priority"]):
    _PARENT_TO_PROGRAM.setdefault(_entry["Output"], []).append(_entry["Name"])
del _raw_parent_map, _entry


def parse_wash_programs(raw: list[dict]) -> list[WashingMachineWashProgram]:
    """Parse and filter the raw program list stored in a config entry."""
    programs = [WashingMachineWashProgram.from_dict(p) for p in raw]
    return [p for p in programs if p.position != 0]


def parse_dryer_programs(raw: list[dict]) -> list[TumbleDryerProgram]:
    """Parse and filter the raw dryer program list stored in a config entry."""
    programs = [TumbleDryerProgram.from_dict(p) for p in raw]
    return [p for p in programs if p.position != 0]


def resolve_downloadable_programs(
    programs: list[DownloadableProgram],
    standard_programs: list[WashingMachineWashProgram],
) -> list[tuple[DownloadableProgram, WashingMachineWashProgram]]:
    """Match each downloadable program to its base standard program via parentToProgram.json.

    parent is an Output index in parentToProgram.json, not a position. The app walks the
    priority-ordered list of program names for that output and picks the first one present
    in the device's own catalog. That program's pr_code and position go into the write command.
    """
    parent_map = _PARENT_TO_PROGRAM
    # Build lookup by full API name (parentToProgram.json uses full names with prefix)
    _PREFIXES = ("DUAL_WM_WD_PROGRAM_NAME_", "DUAL_WM_WD_")
    name_to_prog: dict[str, WashingMachineWashProgram] = {}
    for p in standard_programs:
        # p.name is already stripped; reconstruct the full name for each possible prefix
        for prefix in _PREFIXES:
            name_to_prog[prefix + p.name] = p

    result = []
    for dl in programs:
        candidates = parent_map.get(dl.parent, [])
        base = next((name_to_prog[n] for n in candidates if n in name_to_prog), None)
        if base is not None:
            result.append((dl, base))
        else:
            _LOGGER.warning(
                "Downloadable program %s (parent=%d) did not match any standard program",
                dl.name,
                dl.parent,
            )
    return result


# Some devices reportedly can't handle too frequent requests and respond with BAD_REQUEST
# This global limiter makes sure we don't call the API too fast
# https://github.com/ofalvai/home-assistant-candy/issues/61
_LIMITER = AsyncLimiter(max_rate=1, time_period=3)


def _parse_json_safe(text: str | bytes) -> dict[str, Any]:
    """Safely decode and parse JSON, stripping leading/trailing whitespace and null bytes."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="ignore")
    text = text.strip().strip("\x00").strip()
    return json.loads(text)


class CandyClient:
    def __init__(
        self,
        session: ClientSession,
        device_ip: str,
        encryption_key: str,
        use_encryption: bool,
    ):
        self.session = (
            session  # Session is the default HA session, shouldn't be cleaned up
        )
        self.device_ip = device_ip
        self.encryption_key = encryption_key
        self.use_encryption = use_encryption

    @backoff.on_exception(
        backoff.expo, aiohttp.ClientError, max_tries=3, logger=__name__
    )
    @backoff.on_exception(backoff.expo, TimeoutError, max_tries=3, logger=__name__)
    async def status_with_retry(
        self,
    ) -> (
        WashingMachineStatus
        | TumbleDryerStatus
        | DishwasherStatus
        | OvenStatus
        | WineCoolerStatus
    ):
        return await self.status()

    async def _fetch_and_decode_endpoint(self, url: str) -> dict[str, Any]:
        """Fetch an endpoint URL, decrypt if needed, and parse JSON payload."""
        async with _LIMITER, self.session.get(url) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise ValueError(
                    f"HTTP GET {url} failed with status {resp.status}: {text[:200]}"
                )
            if self.use_encryption:
                resp_text = await resp.text()
                resp_text = resp_text.strip().strip("\x00").strip()
                if resp_text.startswith("{") and resp_text.endswith("}"):
                    return _parse_json_safe(resp_text)
                if self.encryption_key != "":
                    decrypted_text = decrypt(
                        self.encryption_key.encode(), bytes.fromhex(resp_text)
                    )
                else:
                    decrypted_text = bytes.fromhex(resp_text)
                return _parse_json_safe(decrypted_text)

            text = await resp.text()
            return _parse_json_safe(text)

    async def fetch_raw_status(self) -> dict[str, Any]:
        """Fetch raw JSON telemetry payload from /http-read.json."""
        url = _status_url(self.device_ip, self.use_encryption)
        return await self._fetch_and_decode_endpoint(url)

    async def fetch_raw_statistics(self) -> dict[str, Any]:
        """Fetch statistics counters handshake (prepareStatistics -> getStatistics)."""
        prepare_url = _prepare_statistics_url(self.device_ip, self.use_encryption)
        try:
            async with _LIMITER, self.session.get(prepare_url) as resp:
                await resp.read()
        except Exception as err:
            _LOGGER.debug(
                "prepareStatistics handshake failed or not supported: %s", err
            )

        url = _statistics_url(self.device_ip, self.use_encryption)
        return await self._fetch_and_decode_endpoint(url)

    async def fetch_all_endpoints(self) -> dict[str, Any]:
        """Fetch all supported device endpoints with timeout and error handling."""
        endpoints: dict[str, Any] = {}

        # 1. Telemetry status (/http-read.json)
        try:
            async with async_timeout.timeout(7):
                telemetry = await self.fetch_raw_status()
                endpoints["http-read.json"] = telemetry
        except Exception as err:
            endpoints["http-read.json"] = {
                "error": f"Error fetching /http-read.json: {err!r}"
            }
            endpoints["http-getStatistics.json"] = {
                "status": "Skipped: device is unreachable"
            }
            return endpoints

        # 2. Statistics counters (/http-getStatistics.json)
        has_stats_support = any(
            k in telemetry
            for k in ("statusLavatrice", "statusWD", "statusWM", "statusTD")
        )
        if has_stats_support:
            try:
                async with async_timeout.timeout(7):
                    stats_data = await self.fetch_raw_statistics()
                    endpoints["http-getStatistics.json"] = stats_data
            except Exception as err:
                endpoints["http-getStatistics.json"] = {
                    "error": f"Error fetching statistics: {err!r}"
                }
        else:
            endpoints["http-getStatistics.json"] = {
                "status": "Statistics counters not supported for this appliance family"
            }

        return endpoints

    async def status(
        self,
    ) -> (
        WashingMachineStatus
        | TumbleDryerStatus
        | DishwasherStatus
        | OvenStatus
        | WineCoolerStatus
    ):
        resp_json = await self.fetch_raw_status()
        _LOGGER.debug(resp_json)

        if "statusTD" in resp_json:
            status = TumbleDryerStatus.from_json(resp_json["statusTD"])
        elif "statusLavatrice" in resp_json:
            status = WashingMachineStatus.from_json(resp_json["statusLavatrice"])
        elif "statusForno" in resp_json:
            status = OvenStatus.from_json(resp_json["statusForno"])
        elif "statusDWash" in resp_json:
            status = DishwasherStatus.from_json(resp_json["statusDWash"])
        elif "statusWCool" in resp_json:
            status = WineCoolerStatus.from_json(resp_json["statusWCool"])
        else:
            raise Exception(
                "Unable to detect machine type from API response", resp_json
            )

        return status

    async def send_command(self, query_string: str) -> None:
        """Send a write command to the device.

        query_string is a URL-encoded parameter string, e.g.
        'Write=1&StSt=1&PrNm=11&...'
        """
        if self.use_encryption and self.encryption_key:
            hex_data = _xor_encrypt(query_string, self.encryption_key)
            url = _write_url(self.device_ip, use_encryption=True, data=hex_data)
        else:
            url = _write_url(self.device_ip, use_encryption=False, data=query_string)

        async with async_timeout.timeout(5), self.session.get(url) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise ValueError(
                    f"Write command failed (HTTP {resp.status}): {text[:200]}"
                )

    async def set_autodose(self, detergent_on: bool, softener_on: bool) -> None:
        """Send command to configure auto-dose for detergent and softener."""
        det_val = 1 if detergent_on else 0
        soft_val = 1 if softener_on else 0
        await self.send_command(f"Write=1&SetDet={det_val}&SetSoft={soft_val}")

    async def set_water_hardness(self, hardness: int) -> None:
        """Send command to configure water hardness level (1..3)."""
        if hardness not in (1, 2, 3):
            raise ValueError(
                f"Invalid water hardness level: {hardness}. Must be 1 (Soft), 2 (Medium), or 3 (Hard)."
            )
        await self.send_command(f"SetHard={hardness}")

    async def resume_good_night(self) -> None:
        """Send command to release Good Night rinse hold and finish with spin."""
        await self.send_command("Write=1&RestartGN=1")

    @backoff.on_exception(
        backoff.expo, aiohttp.ClientError, max_tries=3, logger=__name__
    )
    @backoff.on_exception(backoff.expo, TimeoutError, max_tries=3, logger=__name__)
    @backoff.on_exception(backoff.expo, JSONDecodeError, max_tries=3, logger=__name__)
    async def statistics_with_retry(self) -> WashingMachineStatistics:
        return await self.fetch_statistics()

    async def fetch_statistics(self) -> WashingMachineStatistics:
        resp_json = await self.fetch_raw_statistics()
        _LOGGER.debug(resp_json)

        if "statusCounters" not in resp_json:
            raise Exception(
                "Unable to parse statistics response: missing statusCounters key",
                resp_json,
            )

        return WashingMachineStatistics.from_json(resp_json["statusCounters"])

    async def set_wine_cooler_light(
        self, turn_on: bool, current_status: WineCoolerStatus
    ) -> None:
        """Control wine cooler light state."""
        params: dict[str, str] = {
            "Write": "1",
            "w1": str(current_status.program.code),
            "w2": str(current_status.temp),
        }
        if current_status.program_down is not None:
            params["w4"] = str(current_status.program_down.code)
        if current_status.temp_down is not None:
            params["w5"] = str(current_status.temp_down)
        params["w7"] = "1" if turn_on else "0"

        encoded_query = "&".join(f"{k}={v}" for k, v in params.items())

        if self.use_encryption and self.encryption_key != "":
            encrypted_data = _xor_encrypt(encoded_query, self.encryption_key)
            url = f"http://{self.device_ip}/http-write.json?encrypted=1&data={encrypted_data}"
        else:
            url = f"http://{self.device_ip}/http-write.json?encrypted=0&{encoded_query}"

        async with _LIMITER, self.session.get(url) as resp:
            resp.raise_for_status()


def _xor_encrypt(plaintext: str, key: str) -> str:
    """Encrypt plaintext string using sliding XOR key and return uppercase hex string."""
    pt_bytes = plaintext.encode("utf-8")
    k_bytes = key.encode("utf-8")
    encrypted = bytes(
        [pt_bytes[i] ^ k_bytes[i % len(k_bytes)] for i in range(len(pt_bytes))]
    )
    return encrypted.hex().upper()


async def detect_encryption(
    session: aiohttp.ClientSession, device_ip: str
) -> tuple[Encryption, str | None]:
    # noinspection PyBroadException
    try:
        _LOGGER.info("Trying to get a response without encryption (encrypted=0)...")
        url = _status_url(device_ip, use_encryption=False)
        async with _LIMITER, session.get(url) as resp:
            text = await resp.text()
            resp_json = _parse_json_safe(text)
            assert resp_json.get("response") != "BAD REQUEST"
            _LOGGER.info(
                "Received unencrypted JSON response, no need to use key for decryption"
            )
            return Encryption.NO_ENCRYPTION, None
    except Exception as err:  # pylint: disable=broad-except
        _LOGGER.debug(err)
        _LOGGER.info(
            "Failed to get a valid response without encryption, let's try with encrypted=1..."
        )
        url = _status_url(device_ip, use_encryption=True)
        async with _LIMITER, session.get(url) as resp:
            resp_hex = await resp.text()  # Response is hex encoded encrypted data
            resp_hex = resp_hex.strip().strip("\x00").strip()
            try:
                unhexed = bytes.fromhex(resp_hex)
                _parse_json_safe(unhexed)
            except Exception as json_err:
                _LOGGER.info(
                    "Brute force decryption key from the encrypted response..."
                )
                _LOGGER.debug("Response: %s", resp_hex)
                key = find_key(bytes.fromhex(resp_hex))
                if key is None:
                    raise ValueError("Couldn't brute force key") from json_err

                _LOGGER.info("Using key with encrypted=1 for future requests")
                return Encryption.ENCRYPTION, key
            else:
                _LOGGER.info(
                    "Response is not encrypted (despite encryption=1 in request), no need to brute force "
                    "the key"
                )
                return Encryption.ENCRYPTION_WITHOUT_KEY, None


def _status_url(device_ip: str, use_encryption: bool) -> str:
    return f"http://{device_ip}/http-read.json?encrypted={1 if use_encryption else 0}"


def _write_url(device_ip: str, use_encryption: bool, data: str) -> str:
    if use_encryption:
        return f"http://{device_ip}/http-write.json?encrypted=1&data={data}"
    return f"http://{device_ip}/http-write.json?encrypted=0&{data}"


def _statistics_url(device_ip: str, use_encryption: bool) -> str:
    return f"http://{device_ip}/http-getStatistics.json?encrypted={1 if use_encryption else 0}"


def _prepare_statistics_url(device_ip: str, use_encryption: bool) -> str:
    return f"http://{device_ip}/http-prepareStatistics.json?encrypted={1 if use_encryption else 0}"


# Maps JSON root keys to human-readable device type labels
_DEVICE_TYPE_LABELS: dict[str, str] = {
    "statusLavatrice": "Washing Machine",
    "statusTD": "Tumble Dryer",
    "statusDWash": "Dishwasher",
    "statusForno": "Oven",
    "statusWCool": "Wine Cooler",
}


async def discover_devices(
    session: aiohttp.ClientSession, subnet: str, timeout: float = 1.0
) -> dict[str, str]:
    """Scan a /24 subnet for Candy Simply-Fi devices.

    Returns a dict mapping IP address -> device type label for each device found.
    """

    async def _probe(ip: str) -> tuple[str, str] | None:
        url = f"http://{ip}/http-read.json?encrypted=0"
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=timeout)
            ) as resp:
                if resp.status != 200:
                    return None
                text = await resp.text()
                data = _parse_json_safe(text)
                for key, label in _DEVICE_TYPE_LABELS.items():
                    if key in data:
                        return ip, label
        except Exception:  # pylint: disable=broad-except
            pass
        return None

    base = ".".join(subnet.split(".")[:3])
    tasks = [_probe(f"{base}.{i}") for i in range(1, 255)]
    results = await asyncio.gather(*tasks)

    return {
        ip: label
        for result in results
        if result and (ip := result[0]) and (label := result[1])
    }
