from homeassistant.helpers.aiohttp_client import async_get_clientsession
import pytest
from pytest_homeassistant_custom_component.common import load_fixture

from custom_components.candy.client import (
    CandyClient,
    Encryption,
    _xor_encrypt,
    detect_encryption,
    discover_devices,
)
from custom_components.candy.client.decryption import decrypt
from custom_components.candy.client.model import (
    DishwasherStatus,
    MachineState,
    WashingMachineStatus,
    WashProgramState,
    WineCoolerProgram,
    WineCoolerState,
    WineCoolerStatus,
)

from .common import (
    TEST_ENCRYPTED_HEX_RESPONSE,
    TEST_ENCRYPTION_KEY,
    TEST_ENCRYPTION_KEY_EMPTY,
    TEST_IP,
    TEST_UNENCRYPTED_HEX_RESPONSE,
)


@pytest.mark.parametrize("expected_lingering_tasks", [True])
async def test_idle(hass, aioclient_mock):
    """Test parsing the status when turning on the machine and selecting WiFi mode."""

    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json",
        text=load_fixture("washing_machine/idle.json"),
    )

    client = CandyClient(
        async_get_clientsession(hass),
        device_ip=TEST_IP,
        encryption_key=TEST_ENCRYPTION_KEY_EMPTY,
        use_encryption=False,
    )
    status = await client.status()

    assert isinstance(status, WashingMachineStatus)
    assert status.machine_state is MachineState.IDLE
    assert status.program_state is WashProgramState.STOPPED
    assert status.spin_speed == 800
    assert status.temp == 40
    assert status.recipe_id == "0"


async def test_delayed_start_wait(hass, aioclient_mock):
    """Test parsing the status when machine is waiting for a delayed start wash cycle."""
    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json",
        text=load_fixture("washing_machine/delayed_start_wait.json"),
    )

    client = CandyClient(
        async_get_clientsession(hass),
        device_ip=TEST_IP,
        encryption_key=TEST_ENCRYPTION_KEY_EMPTY,
        use_encryption=False,
    )
    status = await client.status()

    assert isinstance(status, WashingMachineStatus)
    assert status.machine_state is MachineState.DELAYED_START_PROGRAMMED
    assert status.program_state is WashProgramState.STOPPED
    assert status.remaining_minutes == 50


async def test_no_fillr_property(hass, aioclient_mock):
    """Test parsing the status when response doesn't contain the FillR property."""
    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json",
        text=load_fixture("washing_machine/no_fillr.json"),
    )

    client = CandyClient(
        async_get_clientsession(hass),
        device_ip=TEST_IP,
        encryption_key=TEST_ENCRYPTION_KEY_EMPTY,
        use_encryption=False,
    )
    status = await client.status()

    assert isinstance(status, WashingMachineStatus)
    assert status.machine_state is MachineState.IDLE
    assert status.fill_percent is None


async def test_detect_no_encryption(hass, aioclient_mock):
    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json?encrypted=0",
        text=load_fixture("washing_machine/idle.json"),
    )

    encryption_type, key = await detect_encryption(
        async_get_clientsession(hass), TEST_IP
    )

    assert encryption_type is Encryption.NO_ENCRYPTION
    assert key is None


async def test_detect_encryption_key(hass, aioclient_mock):
    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json?encrypted=0", json={"response": "BAD REQUEST"}
    )

    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json?encrypted=1", text=TEST_ENCRYPTED_HEX_RESPONSE
    )

    encryption_type, key = await detect_encryption(
        async_get_clientsession(hass), TEST_IP
    )

    assert encryption_type is Encryption.ENCRYPTION
    assert key == TEST_ENCRYPTION_KEY


async def test_detect_encryption_without_key(hass, aioclient_mock):
    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json?encrypted=0", json={"response": "BAD REQUEST"}
    )

    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json?encrypted=1",
        text=TEST_UNENCRYPTED_HEX_RESPONSE,
    )

    encryption_type, key = await detect_encryption(
        async_get_clientsession(hass), TEST_IP
    )

    assert encryption_type is Encryption.ENCRYPTION_WITHOUT_KEY
    assert key is None


async def test_status_encryption_with_key(hass, aioclient_mock):
    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json",
        text="2F7C6B441B390C094C3C42093A023429764B1A403343714A6B3D503902342E073D535B6F086854653240386F2E0C23283714243F4B250A0D1A7313085D416B4C5E78686F6A3E191C570D662C1E0B657B76434361344071611A0454390C2026333D120E6F0368484A14443B44644114353503151E4D25084A026B016F416E4D485D53353F5C23163D562613774F53656D597B68441B0F1B071A73137D4F4F4A4B5D78431D4B251F1A592413774F337263787C6B4430683D104C3B50091F1A657B76414361344071611A0641280327282E263E11391B705A581A653C47646A6505311D00346A3E191A4C6B0B6F5D416B4C5E78686F6B2F153C5124546F5741767364534D403343714A7520423E3E022B35764B437C1B66756231401300041034133D1F12281B705A581A653C47646A650E24140F0956250A4A026B016F416E4D485D5333284A2F0C4A026B016F416E4D485D5322255C29133D486B0B6F5D416B4C5E78686F4B7B5A521A7B136160694E487603536F0368484A14443B4464413572764B437F1B6675623140133F59417D6365534D403343714A4A7C13774F53656D597B68441B384E4A026B016F416E4D485D53137A1B705A5B1A653C47646A65336C535B6F086854653240386F1F5A657B763F3401756854653240386F1F5272636E53506F3440711535434C",  # pylint: disable=line-too-long
    )

    client = CandyClient(
        async_get_clientsession(hass),
        device_ip=TEST_IP,
        encryption_key="TqaM9Jxh8I1MmcGA",
        use_encryption=True,
    )
    status = await client.status()

    assert isinstance(status, DishwasherStatus)


async def test_status_encryption_without_key(hass, aioclient_mock):
    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json",
        text="7B0D0A20202020227374617475734C6176617472696365223A7B0D0A2020202020202020202020202257694669537461747573223A2230222C0D0A20202020202020202020202022457272223A22323535222C0D0A202020202020202020202020224D6163684D64223A2232222C0D0A202020202020202020202020225072223A223133222C0D0A2020202020202020202020202250725068223A2235222C0D0A20202020202020202020202022534C6576656C223A22323535222C0D0A2020202020202020202020202254656D70223A2230222C0D0A202020202020202020202020225370696E5370223A2230222C0D0A202020202020202020202020224F707431223A2230222C0D0A202020202020202020202020224F707432223A2230222C0D0A202020202020202020202020224F707433223A2230222C0D0A202020202020202020202020224F707434223A2230222C0D0A202020202020202020202020224F707435223A2230222C0D0A202020202020202020202020224F707436223A2230222C0D0A202020202020202020202020224F707437223A2230222C0D0A202020202020202020202020224F707438223A2230222C0D0A20202020202020202020202022537465616D223A2230222C0D0A2020202020202020202020202244727954223A2230222C0D0A2020202020202020202020202244656C56616C223A22323535222C0D0A2020202020202020202020202252656D54696D65223A223130222C0D0A202020202020202020202020225265636970654964223A2230222C0D0A20202020202020202020202022436865636B55705374617465223A2230220D0A202020207D0D0A7D",  # pylint: disable=line-too-long
    )

    client = CandyClient(
        async_get_clientsession(hass),
        device_ip=TEST_IP,
        encryption_key="",
        use_encryption=True,
    )
    status = await client.status()

    assert isinstance(status, WashingMachineStatus)


async def test_status_unknown_device_type(hass, aioclient_mock):
    """status() raises when JSON has no known root key."""
    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json",
        json={"unknownKey": {"WiFiStatus": "1"}},
    )
    client = CandyClient(
        async_get_clientsession(hass),
        device_ip=TEST_IP,
        encryption_key=TEST_ENCRYPTION_KEY_EMPTY,
        use_encryption=False,
    )
    with pytest.raises(Exception, match="Unable to detect machine type"):
        await client.status()


async def test_send_command_encrypted(hass, aioclient_mock):
    """send_command uses the encrypted URL path when key is set."""
    aioclient_mock.get(f"http://{TEST_IP}/http-write.json", status=200, text="")
    client = CandyClient(
        async_get_clientsession(hass),
        device_ip=TEST_IP,
        encryption_key=TEST_ENCRYPTION_KEY,
        use_encryption=True,
    )
    await client.send_command("Write=1&StSt=0")


async def test_send_command_error_response(hass, aioclient_mock):
    """send_command raises ValueError when device returns non-200."""
    aioclient_mock.get(
        f"http://{TEST_IP}/http-write.json", status=400, text="BAD REQUEST"
    )
    client = CandyClient(
        async_get_clientsession(hass),
        device_ip=TEST_IP,
        encryption_key=TEST_ENCRYPTION_KEY_EMPTY,
        use_encryption=False,
    )
    with pytest.raises(ValueError, match="Write command failed"):
        await client.send_command("Write=1")


async def test_fetch_statistics_encrypted_empty_key(hass, aioclient_mock):
    """fetch_statistics handles encrypted=1 response with empty key (hex-only)."""
    stats_hex = b'{"statusCounters": {"Temp0to30": "318", "Temp40": "70", "Temp60to90": "0"}}'.hex()
    aioclient_mock.get(
        f"http://{TEST_IP}/http-prepareStatistics.json", text='{"response":"OK"}'
    )
    aioclient_mock.get(f"http://{TEST_IP}/http-getStatistics.json", text=stats_hex)
    client = CandyClient(
        async_get_clientsession(hass),
        device_ip=TEST_IP,
        encryption_key=TEST_ENCRYPTION_KEY_EMPTY,
        use_encryption=True,
    )
    stats = await client.fetch_statistics()
    assert stats.total_cycles == 388


async def test_fetch_statistics_encrypted_with_key(hass, aioclient_mock):
    """fetch_statistics decrypts the response when a key is set."""
    stats_json = (
        b'{"statusCounters": {"Temp0to30": "318", "Temp40": "70", "Temp60to90": "0"}}'
    )
    key = TEST_ENCRYPTION_KEY.encode()
    encrypted_hex = decrypt(key, stats_json).hex()
    aioclient_mock.get(
        f"http://{TEST_IP}/http-prepareStatistics.json", text='{"response":"OK"}'
    )
    aioclient_mock.get(f"http://{TEST_IP}/http-getStatistics.json", text=encrypted_hex)
    client = CandyClient(
        async_get_clientsession(hass),
        device_ip=TEST_IP,
        encryption_key=TEST_ENCRYPTION_KEY,
        use_encryption=True,
    )
    stats = await client.fetch_statistics()
    assert stats.total_cycles == 388


async def test_fetch_statistics_missing_status_counters(hass, aioclient_mock):
    """fetch_statistics raises when statusCounters key is absent in response."""
    aioclient_mock.get(
        f"http://{TEST_IP}/http-prepareStatistics.json", text='{"response":"OK"}'
    )
    aioclient_mock.get(
        f"http://{TEST_IP}/http-getStatistics.json",
        json={"someOtherKey": {}},
    )
    client = CandyClient(
        async_get_clientsession(hass),
        device_ip=TEST_IP,
        encryption_key=TEST_ENCRYPTION_KEY_EMPTY,
        use_encryption=False,
    )
    with pytest.raises(Exception, match="Unable to parse statistics"):
        await client.fetch_statistics()


async def test_detect_encryption_brute_force_fails(hass, aioclient_mock):
    """detect_encryption raises when brute-force key search finds nothing."""
    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json?encrypted=0", json={"response": "BAD REQUEST"}
    )
    # 32 bytes of 'a' (0x61): valid UTF-8, triggers JSONDecodeError, not decodable by find_key
    aioclient_mock.get(f"http://{TEST_IP}/http-read.json?encrypted=1", text="61" * 32)
    with pytest.raises(ValueError, match="Couldn't brute force key"):
        await detect_encryption(async_get_clientsession(hass), TEST_IP)


@pytest.mark.parametrize("expected_lingering_tasks", [True])
async def test_discover_devices_finds_washing_machine(hass, aioclient_mock):
    """discover_devices returns matched IPs with device-type labels."""
    aioclient_mock.get(
        "http://192.168.0.1/http-read.json",
        json={"statusLavatrice": {"WiFiStatus": "1"}},
    )
    result = await discover_devices(async_get_clientsession(hass), "192.168.0.0")
    assert "192.168.0.1" in result
    assert result["192.168.0.1"] == "Washing Machine"


async def test_status_wine_cooler(hass, aioclient_mock):
    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json",
        text='{"statusWCool":{"r1":"1","r2":"E0","r3":"1","r4":"16","r5":"2","r6":"0","r7":"0","r8":"0","r9":"0","r10":"1"}}',
    )

    client = CandyClient(
        async_get_clientsession(hass),
        device_ip=TEST_IP,
        encryption_key="",
        use_encryption=False,
    )
    status = await client.status()

    assert isinstance(status, WineCoolerStatus)
    assert status.machine_state == WineCoolerState.ON
    assert status.program == WineCoolerProgram.RED_WINE
    assert status.temp == 16
    assert status.light is True
    assert status.remote_control is True
    assert status.error is None


async def test_detect_encryption_with_trailing_null_bytes(hass, aioclient_mock):
    """Test detect_encryption when device appends trailing null bytes."""
    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json?encrypted=0",
        text='{"statusWCool":{"r1":"1","r2":"E0","r3":"1","r4":"16","r5":"2","r6":"0","r7":"0","r8":"0","r9":"0","r10":"0"}}\x00',
    )

    encryption_type, key = await detect_encryption(
        async_get_clientsession(hass), device_ip=TEST_IP
    )
    assert encryption_type is Encryption.NO_ENCRYPTION
    assert key is None


async def test_set_wine_cooler_light_encrypted(hass, aioclient_mock):
    """Test sending encrypted light control command."""
    key = "NHCm1edvvWJdVMIb"
    query = "Write=1&w1=1&w2=16&w7=1"
    encrypted_data = _xor_encrypt(query, key)

    aioclient_mock.get(
        f"http://{TEST_IP}/http-write.json?encrypted=1&data={encrypted_data}",
        text='{"response":"OK"}',
    )

    client = CandyClient(
        async_get_clientsession(hass),
        device_ip=TEST_IP,
        encryption_key=key,
        use_encryption=True,
    )

    status = WineCoolerStatus(
        machine_state=WineCoolerState.ON,
        program=WineCoolerProgram.RED_WINE,
        temp=16,
        light=False,
        error=None,
        remote_control=True,
    )

    await client.set_wine_cooler_light(True, status)
    assert aioclient_mock.call_count == 1


async def test_special_program_recipe_id(hass, aioclient_mock):
    """Test parsing RecipeId for a special/downloadable program."""
    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json",
        text=load_fixture("washing_machine/idle.json").replace(
            '"RecipeId": "0"', '"RecipeId": "D_33"'
        ),
    )
    client = CandyClient(
        async_get_clientsession(hass),
        device_ip=TEST_IP,
        encryption_key=TEST_ENCRYPTION_KEY_EMPTY,
        use_encryption=False,
    )
    status = await client.status()
    assert isinstance(status, WashingMachineStatus)
    assert status.recipe_id == "D_33"
