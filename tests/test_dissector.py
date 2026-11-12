"""Unit tests for telemetry dissector and register decoder."""

from typing import Any

import pytest

from custom_components.candy.dissector import (
    ROOT_KEYS_TO_FAMILY,
    decode_registers,
    detect_appliance_family,
    dissect_telemetry,
    evaluate_remote_control,
    is_truthy_value,
)


@pytest.mark.parametrize(
    ("val", "expected"),
    [
        (True, True),
        (False, False),
        ("1", True),
        ("true", True),
        ("TRUE", True),
        ("  yes  ", True),
        ("on", True),
        ("ON", True),
        ("locked", True),
        ("open", True),
        ("full", True),
        ("active", True),
        ("0", False),
        ("false", False),
        ("no", False),
        ("off", False),
        ("unlocked", False),
        ("closed", False),
        ("empty", False),
        ("random_string", False),
        ("", False),
        (None, False),
        (0, False),
        (123, False),
    ],
)
def test_is_truthy_value(val: Any, expected: bool) -> None:
    """Test truthy value evaluator handles booleans, strings, and other types."""
    assert is_truthy_value(val) is expected


def test_detect_appliance_family_all_standard_roots() -> None:
    """Test detection for all defined standard root envelope keys."""
    for root_key, expected_family in ROOT_KEYS_TO_FAMILY.items():
        payload = {root_key: {"dummy_reg": "1"}}
        key, family, data = detect_appliance_family(payload)
        assert key == root_key
        assert family == expected_family
        assert data == {"dummy_reg": "1"}


def test_detect_appliance_family_wrapped_envelope() -> None:
    """Test detection when appliance envelope is wrapped in current_status_parameters."""
    payload = {
        "appliance": {"current_status_parameters": {"MachMd": "1", "Temp": "40"}}
    }
    key, family, data = detect_appliance_family(payload)
    assert key == "appliance"
    assert family == "Appliance (Wrapped)"
    assert data == {"MachMd": "1", "Temp": "40"}


def test_detect_appliance_family_wrapped_envelope_invalid_parameters() -> None:
    """Test wrapped envelope when current_status_parameters is missing or invalid."""
    # current_status_parameters is not a dict
    payload1: dict[str, Any] = {
        "appliance": {"current_status_parameters": "not_a_dict"}
    }
    key, family, data = detect_appliance_family(payload1)
    assert key == "unknown"
    assert family == "Unknown Appliance"
    assert data == payload1

    # current_status_parameters missing
    payload2: dict[str, Any] = {"appliance": {"other_field": 123}}
    key, family, data = detect_appliance_family(payload2)
    assert key == "unknown"
    assert family == "Unknown Appliance"
    assert data == payload2


def test_detect_appliance_family_non_dict_values_fallback() -> None:
    """Test fallback when candidate root key is present but value is not a dict."""
    payload: dict[str, Any] = {"statusLavatrice": "string_value"}
    key, family, data = detect_appliance_family(payload)
    assert key == "unknown"
    assert family == "Unknown Appliance"
    assert data == payload


def test_detect_appliance_family_unknown_root() -> None:
    """Test fallback for unrecognized telemetry root payload."""
    payload: dict[str, Any] = {"unrecognizedEnvelope": {"val": 1}}
    key, family, data = detect_appliance_family(payload)
    assert key == "unknown"
    assert family == "Unknown Appliance"
    assert data == payload


# ---------------------------------------------------------------------------
# Washer & Washer-Dryer Register Decoding
# ---------------------------------------------------------------------------


def test_decode_registers_washer_modes_and_phases() -> None:
    """Test known and unknown operating modes and cycle phases for washing machines."""
    known_modes = {
        "1": "Idle / Standby",
        "2": "Running",
        "3": "Paused",
        "4": "Delayed start selection",
        "5": "Delayed start programmed",
        "6": "Error",
        "7": "Finished",
        "8": "Finished",
        "99": "Unknown mode",
    }
    for mode_val, expected_desc in known_modes.items():
        regs = decode_registers("statusLavatrice", {"MachMd": mode_val})
        assert regs[0]["meaning"] == expected_desc

    known_phases = {
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
        "99": "Unknown phase",
    }
    for phase_val, expected_desc in known_phases.items():
        regs = decode_registers("statusWD", {"PrPh": phase_val})
        assert regs[0]["meaning"] == expected_desc


def test_decode_registers_washer_temperatures_and_spins() -> None:
    """Test wash temperatures, spin speeds (including ValueError), and remaining time."""
    # Temp
    assert (
        decode_registers("statusWM", {"Temp": "0"})[0]["meaning"] == "Cold wash (0 °C)"
    )
    assert (
        decode_registers("statusWM", {"Temp": "60"})[0]["meaning"]
        == "60 °C wash temperature"
    )

    # Spin speed
    assert (
        decode_registers("statusWM", {"SpinSp": "0"})[0]["meaning"] == "No spin (0 RPM)"
    )
    assert (
        decode_registers("statusWM", {"SpinSp": "14"})[0]["meaning"]
        == "1400 RPM spin speed"
    )
    assert (
        decode_registers("statusWM", {"SpinSp": "invalid"})[0]["meaning"]
        == "invalid spin speed"
    )

    # Remaining time
    assert (
        decode_registers("statusWM", {"RemTime": "3600"})[0]["meaning"]
        == "60 minutes remaining"
    )
    assert (
        decode_registers("statusWM", {"RemTime": "invalid"})[0]["meaning"]
        == "invalid remaining time"
    )


def test_decode_registers_washer_dry_target() -> None:
    """Test drying targets in washer-dryers for standard map and custom times."""
    dry_map = {
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
    for dry_code, expected_label in dry_map.items():
        regs = decode_registers("statusWD", {"DryT": dry_code})
        assert regs[0]["meaning"] == expected_label

    regs_custom = decode_registers("statusWD", {"DryT": "45"})
    assert regs_custom[0]["meaning"] == "45 min / dryness level"


def test_decode_registers_washer_miscellaneous_registers() -> None:
    """Test all remaining registers for washing machines and washer-dryers."""
    data = {
        "Pr": "5",
        "PrNm": "11",
        "PrCode": "202",
        "WiFiStatus": "1",
        "StatoWiFi": "0",
        "RemCode": "true",
        "DoorLock": "1",
        "FillR": "85",
        "Err": "0",
        "CodiceErrore": "E03",
        "CheckUpState": "1",
        "SLevel": "2",
        "SLevTgt": "99",
        "DelVal": "45",
        "NtcW": "38",
        "NtcD": "52",
        "RecipeId": "nfc_program_1",
        "OptMsk": "128",
        "OptMsk1": "64",
        "Stm": "1",
        "APSfreq": "55",
        "motS": "3",
        "unbF": "1",
        "unbC": "4",
        "numF": "2",
        "DisTestRes": "0",
        "UnknownReg": "some_value",
    }
    regs = {
        r["register"]: r["meaning"] for r in decode_registers("statusLavatrice", data)
    }

    assert regs["Pr"] == "Program selector index 5"
    assert regs["PrNm"] == "Program selector index 11"
    assert regs["PrCode"] == "Program firmware code 202"
    assert regs["WiFiStatus"] == "Remote Control ENABLED"
    assert regs["StatoWiFi"] == "Remote Control DISABLED"
    assert regs["RemCode"] == "Remote Control ENABLED"
    assert regs["DoorLock"] == "Door locked"
    assert regs["FillR"] == "85% estimated load weight"
    assert regs["Err"] == "No fault"
    assert regs["CodiceErrore"] == "Fault code E03"
    assert regs["CheckUpState"] == "Diagnostic check-up active"
    assert regs["SLevel"] == "Soil level 2 (Normal)"
    assert regs["SLevTgt"] == "Soil level 99 (Custom)"
    assert regs["DelVal"] == "45 min delayed start remaining"
    assert regs["NtcW"] == "38 wash water temperature (ADC reading)"
    assert regs["NtcD"] == "52 drying drum temperature (ADC reading)"
    assert regs["RecipeId"] == "Downloadable / NFC program 'nfc_program_1'"
    assert regs["OptMsk"] == "Wash options bitmask 128"
    assert regs["OptMsk1"] == "Wash options bitmask 64"
    assert regs["Stm"] == "Steam option ACTIVE"
    assert regs["APSfreq"] == "55 Hz motor inverter frequency"
    assert regs["motS"] == "Motor state code 3"
    assert regs["unbF"] == "Unbalance fault count 1"
    assert regs["unbC"] == "Unbalance event count 4"
    assert regs["numF"] == "Total lifetime fault count 2"
    assert regs["DisTestRes"] == "Check-up diagnostic result code 0"
    assert regs["UnknownReg"] == ""

    # Check alternate state permutations
    alt_data = {
        "DoorLock": "0",
        "CheckUpState": "0",
        "Stm": "0",
        "SLevel": "1",
        "SLevTgt": "3",
    }
    alt_regs = {
        r["register"]: r["meaning"]
        for r in decode_registers("statusLavatrice", alt_data)
    }
    assert alt_regs["DoorLock"] == "Door unlocked"
    assert alt_regs["CheckUpState"] == "Check-up idle"
    assert alt_regs["Stm"] == "Steam off"
    assert alt_regs["SLevel"] == "Soil level 1 (Light)"
    assert alt_regs["SLevTgt"] == "Soil level 3 (Heavy)"


# ---------------------------------------------------------------------------
# Tumble Dryer Register Decoding
# ---------------------------------------------------------------------------


def test_decode_registers_tumble_dryer() -> None:
    """Test all register decodings and edge cases for tumble dryers."""
    td_modes = {
        "0": "Standby / Off",
        "1": "Selection / Idle",
        "2": "Running",
        "3": "Paused",
        "4": "Delayed start selection",
        "5": "Delayed start countdown",
        "6": "Test mode",
        "7": "Error mode",
        "8": "Finished / Completed",
        "99": "Unknown mode",
    }
    for mode_val, expected_desc in td_modes.items():
        regs = decode_registers("statusTD", {"StatoTD": mode_val})
        assert regs[0]["meaning"] == expected_desc

    td_phases = {
        "0": "Stopped",
        "1": "Pre-heating",
        "2": "Running (Active Drying)",
        "3": "Completed / End",
        "99": "Unknown phase",
    }
    for phase_val, expected_desc in td_phases.items():
        regs = decode_registers("statusTD", {"PrPh": phase_val})
        assert regs[0]["meaning"] == expected_desc

    data = {
        "Pr": "3",
        "DryLev": "2",
        "DryingManagerLevel": "4",
        "RemTime": "50",
        "WaterTankFull": "1",
        "CleanFilter": "1",
        "DoorState": "1",
        "StatoWiFi": "1",
        "RemCode": "0",
        "DelVal": "30",
        "RecipeId": "wool_recipe",
        "Rapido": "1",
        "Time": "45",
        "Refresh": "1",
        "Err": "0",
        "CodiceErrore": "E0",
        "CheckUpState": "1",
        "UnknownTD": "val",
    }
    regs = {r["register"]: r["meaning"] for r in decode_registers("statusTD", data)}
    assert regs["Pr"] == "Program ID 3"
    assert regs["DryLev"] == "Hang Dry"
    assert regs["DryingManagerLevel"] == "Bone Dry"
    assert regs["RemTime"] == "50 minutes remaining"
    assert regs["WaterTankFull"] == "Water container FULL"
    assert regs["CleanFilter"] == "Lint filter clean REQUIRED"
    assert regs["DoorState"] == "Door CLOSED"
    assert regs["StatoWiFi"] == "Remote Control ENABLED"
    assert regs["RemCode"] == "Remote Control DISABLED"
    assert regs["DelVal"] == "30 min delayed start remaining"
    assert regs["RecipeId"] == "Downloadable / NFC program 'wool_recipe'"
    assert regs["Rapido"] == "Timed / Rapid dry index 1"
    assert regs["Time"] == "45 min timed dry duration"
    assert regs["Refresh"] == "Refresh / Anti-crease ACTIVE"
    assert regs["Err"] == "No fault"
    assert regs["CodiceErrore"] == "No fault"
    assert regs["CheckUpState"] == "Diagnostic check-up active"
    assert regs["UnknownTD"] == ""

    # Falsy and custom branches
    alt_data = {
        "DryLev": "99",
        "DryingManagerLevel": "99",
        "WaterTankFull": "0",
        "CleanFilter": "0",
        "DoorState": "0",
        "Refresh": "0",
        "Err": "E04",
        "CodiceErrore": "18",
        "CheckUpState": "0",
    }
    alt_regs = {
        r["register"]: r["meaning"] for r in decode_registers("statusTD", alt_data)
    }
    assert alt_regs["DryLev"] == "Dryness level 99"
    assert alt_regs["DryingManagerLevel"] == "Selected dryness target 99"
    assert alt_regs["WaterTankFull"] == "Water tank OK"
    assert alt_regs["CleanFilter"] == "Filter clean OK"
    assert alt_regs["DoorState"] == "Door OPEN"
    assert alt_regs["Refresh"] == "Refresh off"
    assert alt_regs["Err"] == "Fault code E04"
    assert alt_regs["CodiceErrore"] == "Fault code 18"
    assert alt_regs["CheckUpState"] == "Check-up idle"


# ---------------------------------------------------------------------------
# Dishwasher Register Decoding
# ---------------------------------------------------------------------------


def test_decode_registers_dishwasher() -> None:
    """Test all register decodings and state options for dishwashers."""
    dw_states = {
        "0": "Idle / Ready",
        "1": "Pre-wash",
        "2": "Main Wash",
        "3": "Rinse",
        "4": "Drying",
        "5": "Cycle Finished",
        "99": "Unknown state",
    }
    for state_val, expected_desc in dw_states.items():
        regs = decode_registers("statusDWash", {"StatoDWash": state_val})
        assert regs[0]["meaning"] == expected_desc

    data = {
        "Program": "P3",
        "OpzProg": "p",
        "RemTime": "75",
        "OpenDoor": "1",
        "OpenDoorOpt": "1",
        "MissSalt": "1",
        "MissRinse": "1",
        "Eco": "1",
        "MetaCarico": "1",
        "TreinUno": "1",
        "ExtraDry": "1",
        "DelayStart": "3",
        "StatoWiFi": "1",
        "Err": "0",
        "CodiceErrore": "E0",
        "UnknownDW": "val",
    }
    regs = {r["register"]: r["meaning"] for r in decode_registers("statusDWash", data)}
    assert regs["Program"] == "Program P3"
    assert regs["OpzProg"] == "Option Plus (+)"
    assert regs["RemTime"] == "75 minutes remaining"
    assert regs["OpenDoor"] == "Door OPEN"
    assert regs["OpenDoorOpt"] == "Automatic door opening active"
    assert regs["MissSalt"] == "Salt container EMPTY"
    assert regs["MissRinse"] == "Rinse aid container EMPTY"
    assert regs["Eco"] == "Eco cycle active"
    assert regs["MetaCarico"] == "Half load active"
    assert regs["TreinUno"] == "3-in-1 tablet active"
    assert regs["ExtraDry"] == "Extra dry active"
    assert regs["DelayStart"] == "3 hours delayed start countdown"
    assert regs["StatoWiFi"] == "Remote Control ENABLED"
    assert regs["Err"] == "No fault"
    assert regs["CodiceErrore"] == "No fault"
    assert regs["UnknownDW"] == ""

    # Alternative branches (OpzProg m, standard, falsy values, faults)
    alt_data = {
        "OpzProg": "m",
        "OpenDoor": "0",
        "OpenDoorOpt": "0",
        "MissSalt": "0",
        "MissRinse": "0",
        "Eco": "0",
        "MetaCarico": "0",
        "TreinUno": "0",
        "ExtraDry": "0",
        "StatoWiFi": "0",
        "Err": "E02",
        "CodiceErrore": "E05",
    }
    alt_regs = {
        r["register"]: r["meaning"] for r in decode_registers("statusDWash", alt_data)
    }
    assert alt_regs["OpzProg"] == "Option Minus (-)"
    assert alt_regs["OpenDoor"] == "Door CLOSED"
    assert alt_regs["OpenDoorOpt"] == "Auto-door off"
    assert alt_regs["MissSalt"] == "Salt level OK"
    assert alt_regs["MissRinse"] == "Rinse aid OK"
    assert alt_regs["Eco"] == "Eco off"
    assert alt_regs["MetaCarico"] == "Standard load"
    assert alt_regs["TreinUno"] == "Standard detergent"
    assert alt_regs["ExtraDry"] == "Extra dry off"
    assert alt_regs["StatoWiFi"] == "Remote Control DISABLED"
    assert alt_regs["Err"] == "Fault code E02"
    assert alt_regs["CodiceErrore"] == "Fault code E05"

    regs_std_opz = decode_registers("statusDWash", {"OpzProg": "standard"})
    assert regs_std_opz[0]["meaning"] == "Standard"


# ---------------------------------------------------------------------------
# Oven Register Decoding
# ---------------------------------------------------------------------------


def test_decode_registers_oven() -> None:
    """Test all oven registers including Fahrenheit conversion and TempSet scaling."""
    data = {
        "StartStop": "1",
        "Pausa": "1",
        "Program": "P1",
        "Selettore": "S2",
        "TempRead": "356.0",  # (356 - 32) * 5/9 = 180 °C
        "TempSet": "1800",  # 1800 > 100 -> 180 °C
        "TempSetRaggiunta": "1",
        "DoorLock": "1",
        "SicurezzaBambini": "1",
        "TimeProgr": "60",
        "RecipeId": "roast_beef",
        "RecipeStep": "1",
        "StatoWiFi": "1",
        "UnknownOven": "val",
    }
    regs = {r["register"]: r["meaning"] for r in decode_registers("statusForno", data)}
    assert regs["StartStop"] == "Heating / Running"
    assert regs["Pausa"] == "PAUSED"
    assert regs["Program"] == "Heating program P1"
    assert regs["Selettore"] == "Selector position S2"
    assert "180 °C (356.0 °F) measured cavity temp" in regs["TempRead"]
    assert regs["TempSet"] == "180 °C target temp"
    assert regs["TempSetRaggiunta"] == "Target temperature REACHED"
    assert regs["DoorLock"] == "Door locked"
    assert regs["SicurezzaBambini"] == "Child lock active"
    assert regs["TimeProgr"] == "60 min programmed duration"
    assert regs["RecipeId"] == "Recipe 'roast_beef'"
    assert regs["RecipeStep"] == "Recipe step 1"
    assert regs["StatoWiFi"] == "Remote Control ENABLED"
    assert regs["UnknownOven"] == ""

    # Falsy, low TempSet (<= 100), and ValueError branches
    alt_data = {
        "StartStop": "0",
        "Pausa": "0",
        "TempRead": "invalid_temp",
        "TempSet": "50",  # <= 100 -> 50 °C
        "TempSetRaggiunta": "0",
        "DoorLock": "0",
        "SicurezzaBambini": "0",
        "StatoWiFi": "0",
    }
    alt_regs = {
        r["register"]: r["meaning"] for r in decode_registers("statusForno", alt_data)
    }
    assert alt_regs["StartStop"] == "Idle / Stopped"
    assert alt_regs["Pausa"] == "Running / Ready"
    assert alt_regs["TempRead"] == "invalid_temp temp reading"
    assert alt_regs["TempSet"] == "50 °C target temp"
    assert alt_regs["TempSetRaggiunta"] == "Preheating / Heating up"
    assert alt_regs["DoorLock"] == "Door unlocked"
    assert alt_regs["SicurezzaBambini"] == "Child lock off"
    assert alt_regs["StatoWiFi"] == "Remote Control DISABLED"

    # TempSet ValueError branch
    bad_temp_set = decode_registers("statusForno", {"TempSet": "not_an_int"})
    assert bad_temp_set[0]["meaning"] == "not_an_int target temp"


# ---------------------------------------------------------------------------
# Wine Cooler Register Decoding
# ---------------------------------------------------------------------------


def test_decode_registers_wine_cooler() -> None:
    """Test all wine cooler r1..r11 register interpretations."""
    data = {
        "r1": "1",
        "r2": "E0",
        "r3": "1",
        "r4": "14",
        "r5": "2",
        "r6": "13",
        "r7": "2",
        "r8": "10",
        "r9": "9",
        "r10": "1",
        "r11": "1",
        "unknown_wc": "val",
    }
    regs = {r["register"]: r["meaning"] for r in decode_registers("statusWCool", data)}
    assert regs["r1"] == "Remote Control ENABLED"
    assert regs["r2"] == "Normal operation"
    assert regs["r3"] == "Red Wine"
    assert regs["r4"] == "14 °C Zone 1 set temp"
    assert regs["r5"] == "Powered ON"
    assert regs["r6"] == "13 °C Zone 1 measured temp"
    assert regs["r7"] == "White Wine"
    assert regs["r8"] == "10 °C Zone 2 set temp"
    assert regs["r9"] == "9 °C Zone 2 measured temp"
    assert regs["r10"] == "Interior light ON"
    assert regs["r11"] == "Fahrenheit scale"
    assert regs["unknown_wc"] == ""

    # Alternative branches (r3/r7 Sparkling or custom, r5 OFF or intermediate, r11 Celsius)
    alt_data = {
        "r1": "0",
        "r2": "E1",
        "r3": "3",
        "r5": "0",
        "r7": "99",
        "r10": "0",
        "r11": "0",
    }
    alt_regs = {
        r["register"]: r["meaning"] for r in decode_registers("statusWCool", alt_data)
    }
    assert alt_regs["r1"] == "Remote Control DISABLED"
    assert alt_regs["r2"] == "Fault code E1"
    assert alt_regs["r3"] == "Sparkling Wine"
    assert alt_regs["r5"] == "Powered OFF"
    assert alt_regs["r7"] == "Zone 2 program 99"
    assert alt_regs["r10"] == "Interior light OFF"
    assert alt_regs["r11"] == "Celsius scale"

    # r5 other state and r3 custom
    custom_regs = {
        r["register"]: r["meaning"]
        for r in decode_registers("statusWCool", {"r5": "1", "r3": "99"})
    }
    assert custom_regs["r5"] == "State 1"
    assert custom_regs["r3"] == "Zone 1 program 99"


# ---------------------------------------------------------------------------
# Refrigerator & Freezer Register Decoding
# ---------------------------------------------------------------------------


def test_decode_registers_refrigerator() -> None:
    """Test all refrigerator and freezer registers and truthy toggles."""
    data = {
        "FrSet": "4",
        "FzSet": "18",
        "Door": "1",
        "DoorOpenCnt": "12",
        "IncrDoorCnt": "15",
        "Cmp": "1",
        "CmpFq": "50",
        "Fan": "1",
        "Heat": "1",
        "Eco": "1",
        "Spr": "1",
        "SprC": "1",
        "Antib": "1",
        "Ice": "1",
        "NewIce": "25",
        "Lck": "1",
        "PF": "1",
        "WiFi": "1",
        "WiFiStatus": "0",
        "StatoWiFi": "1",
        "unknown_fr": "val",
    }
    regs = {
        r["register"]: r["meaning"]
        for r in decode_registers("statusRefrigerator", data)
    }
    assert regs["FrSet"] == "4 °C fridge compartment set temp"
    assert regs["FzSet"] == "-18 °C freezer compartment set temp"
    assert regs["Door"] == "Door OPEN"
    assert regs["DoorOpenCnt"] == "Door opened 12 times"
    assert regs["IncrDoorCnt"] == "Door opened 15 times"
    assert regs["Cmp"] == "Compressor RUNNING"
    assert regs["CmpFq"] == "50 Hz compressor motor frequency"
    assert regs["Fan"] == "Circulation fan RUNNING"
    assert regs["Heat"] == "Defrost heater ACTIVE"
    assert regs["Eco"] == "Eco energy saving ACTIVE"
    assert regs["Spr"] == "Super Freezing ACTIVE"
    assert regs["SprC"] == "Super Cooling ACTIVE"
    assert regs["Antib"] == "Anti-bacterial sterilization ACTIVE"
    assert regs["Ice"] == "Ice maker ACTIVE"
    assert regs["NewIce"] == "25 min drink chill countdown duration"
    assert regs["Lck"] == "Child lock ACTIVE"
    assert regs["PF"] == "Power failure warning ACTIVE"
    assert regs["WiFi"] == "Remote Control ENABLED"
    assert regs["WiFiStatus"] == "Remote Control DISABLED"
    assert regs["StatoWiFi"] == "Remote Control ENABLED"
    assert regs["unknown_fr"] == ""

    # Falsy branches
    alt_data = {
        "Door": "0",
        "Cmp": "0",
        "Fan": "0",
        "Heat": "0",
        "Eco": "0",
        "Spr": "0",
        "SprC": "0",
        "Antib": "0",
        "Ice": "0",
        "Lck": "0",
        "PF": "0",
    }
    alt_regs = {
        r["register"]: r["meaning"]
        for r in decode_registers("statusRefrigerator", alt_data)
    }
    assert alt_regs["Door"] == "Door CLOSED"
    assert alt_regs["Cmp"] == "Compressor IDLE"
    assert alt_regs["Fan"] == "Fan off"
    assert alt_regs["Heat"] == "Defrost heater off"
    assert alt_regs["Eco"] == "Eco off"
    assert alt_regs["Spr"] == "Super Freeze off"
    assert alt_regs["SprC"] == "Super Cool off"
    assert alt_regs["Antib"] == "Anti-bacterial off"
    assert alt_regs["Ice"] == "Ice maker off"
    assert alt_regs["Lck"] == "Child lock off"
    assert alt_regs["PF"] == "Power OK"


# ---------------------------------------------------------------------------
# Kitchen Hood Register Decoding
# ---------------------------------------------------------------------------


def test_decode_registers_kitchen_hood() -> None:
    """Test all kitchen hood speeds, lights, timers, and filters."""
    # Speeds: 4 (booster), 1..3, 0 (off)
    assert (
        decode_registers("StatusHood", {"Fan": "4"})[0]["meaning"]
        == "Intensive / Booster"
    )
    assert decode_registers("StatusHood", {"Fan": "2"})[0]["meaning"] == "Speed 2"
    assert decode_registers("StatusHood", {"Fan": "0"})[0]["meaning"] == "Fan OFF"

    # Lights: 1 (on), 2 (ambient), 0 (off)
    assert decode_registers("StatusHood", {"Light": "1"})[0]["meaning"] == "Light ON"
    assert (
        decode_registers("StatusHood", {"Light": "2"})[0]["meaning"] == "Ambient light"
    )
    assert decode_registers("StatusHood", {"Light": "0"})[0]["meaning"] == "Light OFF"

    data = {
        "GreaseFilter": "1",
        "CarbonFilter": "1",
        "Timer": "1",
        "TimerCnt": "10",
        "BoostCnt": "180",
        "WiFiStatus": "1",
        "StatoWiFi": "0",
        "unknown_hood": "val",
    }
    regs = {r["register"]: r["meaning"] for r in decode_registers("StatusHood", data)}
    assert regs["GreaseFilter"] == "Grease filter saturation WARNING"
    assert regs["CarbonFilter"] == "Carbon filter replacement WARNING"
    assert regs["Timer"] == "Auto-off timer ACTIVE"
    assert regs["TimerCnt"] == "10 min remaining on auto-off timer"
    assert regs["BoostCnt"] == "180 sec remaining on booster"
    assert regs["WiFiStatus"] == "Remote Control ENABLED"
    assert regs["StatoWiFi"] == "Remote Control DISABLED"
    assert regs["unknown_hood"] == ""

    # Falsy filters and timer
    alt_data = {
        "GreaseFilter": "0",
        "CarbonFilter": "0",
        "Timer": "0",
    }
    alt_regs = {
        r["register"]: r["meaning"] for r in decode_registers("StatusHood", alt_data)
    }
    assert alt_regs["GreaseFilter"] == "Grease filter OK"
    assert alt_regs["CarbonFilter"] == "Carbon filter OK"
    assert alt_regs["Timer"] == "Timer off"


# ---------------------------------------------------------------------------
# Cooktop & Hob Register Decoding
# ---------------------------------------------------------------------------


def test_decode_registers_hob() -> None:
    """Test dynamic zone matching for cooktops and hobs."""
    data = {
        "lock": "1",
        "z1status": "1",
        "z1power": "9",
        "z1hot": "1",
        "z1pan": "1",
        "z1combi": "1",
        "z1low": "1",
        "StatoWiFi": "1",
        "WiFiStatus": "0",
        "unknown_hob": "val",
        # Registers that end with keyword but fail length requirement:
        "zone1status": "1",  # len == 11 != 8
        "z1powers": "9",  # does not end with 'power'
    }
    regs = {r["register"]: r["meaning"] for r in decode_registers("statusHob", data)}
    assert regs["lock"] == "Child lock ACTIVE"
    assert regs["z1status"] == "Zone ACTIVE"
    assert regs["z1power"] == "Power level 9"
    assert regs["z1hot"] == "Residual heat (HOT 'H')"
    assert regs["z1pan"] == "Cookware detected"
    assert regs["z1combi"] == "Bridge / coupled zone"
    assert regs["z1low"] == "Keep warm / melting active"
    assert regs["StatoWiFi"] == "Remote Control ENABLED"
    assert regs["WiFiStatus"] == "Remote Control DISABLED"
    assert regs["unknown_hob"] == ""
    assert regs["zone1status"] == ""
    assert regs["z1powers"] == ""

    # Falsy dynamic states
    alt_data = {
        "lock": "0",
        "z1status": "0",
        "z1hot": "0",
        "z1pan": "0",
        "z1combi": "0",
        "z1low": "0",
    }
    alt_regs = {
        r["register"]: r["meaning"] for r in decode_registers("statusHob", alt_data)
    }
    assert alt_regs["lock"] == "Child lock off"
    assert alt_regs["z1status"] == "Zone OFF"
    assert alt_regs["z1hot"] == "Safe / Cold"
    assert alt_regs["z1pan"] == "No cookware / unsuitable"
    assert alt_regs["z1combi"] == "Single zone"
    assert alt_regs["z1low"] == "Standard mode"


# ---------------------------------------------------------------------------
# Robot Vacuum Cleaner Register Decoding
# ---------------------------------------------------------------------------


def test_decode_registers_vacuum_cleaner() -> None:
    """Test all robot vacuum cleaner telemetry registers."""
    data = {
        "MachMd": "2",
        "BaSt": "95",
        "LockSt": "1",
        "Tarea": "64",
        "TMin": "180",
        "DBN": "1",
        "FiErr": "1",
        "BMO": "1",
        "RMO": "1",
        "unknown_vac": "val",
    }
    regs = {
        r["register"]: r["meaning"]
        for r in decode_registers("StatusVacuumCleaner", data)
    }
    assert regs["MachMd"] == "Operating mode 2"
    assert regs["BaSt"] == "95% battery level"
    assert regs["LockSt"] == "LOCKED"
    assert regs["Tarea"] == "64 m² total area cleaned"
    assert regs["TMin"] == "180 minutes lifetime cleaning"
    assert regs["DBN"] == "Dust bin missing/full ERROR"
    assert regs["FiErr"] == "Filter blockage ERROR"
    assert regs["BMO"] == "Brush motor fault ERROR"
    assert regs["RMO"] == "Wheel motor fault ERROR"
    assert regs["unknown_vac"] == ""

    # Falsy states
    alt_data = {
        "LockSt": "0",
        "DBN": "0",
        "FiErr": "0",
        "BMO": "0",
        "RMO": "0",
    }
    alt_regs = {
        r["register"]: r["meaning"]
        for r in decode_registers("StatusVacuumCleaner", alt_data)
    }
    assert alt_regs["LockSt"] == "UNLOCKED"
    assert alt_regs["DBN"] == "Dust bin OK"
    assert alt_regs["FiErr"] == "Filter OK"
    assert alt_regs["BMO"] == "Brush motor OK"
    assert alt_regs["RMO"] == "Wheel motor OK"


# ---------------------------------------------------------------------------
# Fallback / Generic Register Decoding
# ---------------------------------------------------------------------------


def test_decode_registers_fallback() -> None:
    """Test generic fallback decoder for unrecognized appliance families."""
    data = {
        "WiFiStatus": "1",
        "StatoWiFi": "0",
        "RemCode": "1",
        "WiFi": "0",
        "Err": "0",
        "CodiceErrore": "E99",
        "unknown_generic": "val",
    }
    regs = {
        r["register"]: r["meaning"] for r in decode_registers("unknown_family", data)
    }
    assert regs["WiFiStatus"] == "Remote Control ENABLED"
    assert regs["StatoWiFi"] == "Remote Control DISABLED"
    assert regs["RemCode"] == "Remote Control ENABLED"
    assert regs["WiFi"] == "Remote Control DISABLED"
    assert regs["Err"] == "No fault"
    assert regs["CodiceErrore"] == "Fault code E99"
    assert regs["unknown_generic"] == ""

    # Err == "E0" is also No fault in generic fallback
    err_zero = decode_registers("unknown_family", {"Err": "E0"})
    assert err_zero[0]["meaning"] == "No fault"


# ---------------------------------------------------------------------------
# Remote Control Evaluation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("flag_key", "flag_val"),
    [
        ("WiFiStatus", "1"),
        ("StatoWiFi", "true"),
        ("RemCode", "on"),
        ("WiFi", "yes"),
        ("r1", "1"),
    ],
)
def test_evaluate_remote_control_flags_truthy(flag_key: str, flag_val: str) -> None:
    """Test remote control flag is recognized across all 5 Wi-Fi key identifiers."""
    res = evaluate_remote_control("statusTD", {flag_key: flag_val})
    assert res["remote_control_enabled"] is True


def test_evaluate_remote_control_flag_disabled() -> None:
    """Test remote control is disabled when all flag keys are absent or falsy."""
    res1 = evaluate_remote_control("statusTD", {"WiFiStatus": "0"})
    assert res1["remote_control_enabled"] is False

    res2 = evaluate_remote_control("statusTD", {})
    assert res2["remote_control_enabled"] is False


def test_evaluate_remote_control_washers() -> None:
    """Test washing machine dial position notes and supported commands."""
    # Dial parked on 15
    res_parked = evaluate_remote_control("statusLavatrice", {"Pr": "15"})
    assert "parked on Wi-Fi position" in res_parked["dial_notes"]
    assert len(res_parked["supported_commands"]) == 5

    # Dial parked on 15 via PrNm fallback
    res_prnm_parked = evaluate_remote_control("statusWD", {"PrNm": "15"})
    assert "parked on Wi-Fi position" in res_prnm_parked["dial_notes"]

    # Dial on position other than 15
    res_other = evaluate_remote_control("statusWM", {"Pr": "2"})
    assert "Physical dial position is 2" in res_other["dial_notes"]

    # Dial position unknown when both Pr and PrNm missing
    res_unknown = evaluate_remote_control("statusLavatrice", {})
    assert "Physical dial position is unknown" in res_unknown["dial_notes"]


def test_evaluate_remote_control_tumble_dryer() -> None:
    """Test tumble dryer commands and empty dial notes."""
    res = evaluate_remote_control("statusTD", {"StatoWiFi": "1"})
    assert res["dial_notes"] == ""
    assert res["supported_commands"] == [
        "Start Drying Cycle",
        "Pause Drying",
        "Cancel / Stop Drying",
    ]


def test_evaluate_remote_control_dishwasher() -> None:
    """Test dishwasher door status notes and supported commands."""
    # Door open
    res_open = evaluate_remote_control("statusDWash", {"OpenDoor": "1"})
    assert (
        res_open["dial_notes"]
        == "Door is OPEN! Close door before sending start commands."
    )
    assert len(res_open["supported_commands"]) == 3

    # Door closed
    res_closed = evaluate_remote_control("statusDWash", {"OpenDoor": "0"})
    assert res_closed["dial_notes"] == "Door is CLOSED."

    # OpenDoor key omitted (defaults to closed)
    res_default = evaluate_remote_control("statusDWash", {})
    assert res_default["dial_notes"] == "Door is CLOSED."


def test_evaluate_remote_control_oven() -> None:
    """Test oven supported commands."""
    res = evaluate_remote_control("statusForno", {})
    assert res["dial_notes"] == ""
    assert len(res["supported_commands"]) == 3
    assert any("Start Heating" in cmd for cmd in res["supported_commands"])


def test_evaluate_remote_control_wine_cooler() -> None:
    """Test wine cooler supported commands."""
    res = evaluate_remote_control("statusWCool", {})
    assert res["dial_notes"] == ""
    assert res["supported_commands"] == [
        "Toggle Light (w7=1 or w7=0)",
        "Set Zone 1 Temp (w2=<temp>)",
        "Set Zone 2 Temp (w5=<temp>)",
    ]


def test_evaluate_remote_control_refrigerator() -> None:
    """Test refrigerator supported commands."""
    res = evaluate_remote_control("statusRefrigerator", {})
    assert res["dial_notes"] == ""
    assert len(res["supported_commands"]) == 6
    assert any("Set Fridge Temp" in cmd for cmd in res["supported_commands"])


def test_evaluate_remote_control_kitchen_hood() -> None:
    """Test kitchen hood supported commands."""
    res = evaluate_remote_control("StatusHood", {})
    assert res["dial_notes"] == ""
    assert len(res["supported_commands"]) == 3
    assert any("Set Fan Speed" in cmd for cmd in res["supported_commands"])


def test_evaluate_remote_control_robot_vacuum() -> None:
    """Test robot vacuum supported commands."""
    res = evaluate_remote_control("StatusVacuumCleaner", {})
    assert res["dial_notes"] == ""
    assert len(res["supported_commands"]) == 3
    assert any("Lock Cleaner" in cmd for cmd in res["supported_commands"])


def test_evaluate_remote_control_unsupported_family() -> None:
    """Test appliance family without custom remote commands (e.g. hobs or unknown)."""
    res = evaluate_remote_control("statusHob", {"WiFiStatus": "1"})
    assert res["remote_control_enabled"] is True
    assert res["dial_notes"] == ""
    assert res["supported_commands"] == []


# ---------------------------------------------------------------------------
# End-to-End Dissection Integration
# ---------------------------------------------------------------------------


def test_dissect_telemetry_standard_payload() -> None:
    """Test dissect_telemetry end-to-end integration for standard payload."""
    payload = {
        "statusLavatrice": {
            "MachMd": "2",
            "PrPh": "3",
            "Pr": "15",
            "Temp": "40",
            "SpinSp": "10",
            "WiFiStatus": "1",
        }
    }
    result = dissect_telemetry(payload)
    assert result["appliance_family"] == "Washing Machine / Washer-Dryer"
    assert result["root_key"] == "statusLavatrice"
    assert result["remote_control"]["remote_control_enabled"] is True
    assert "parked on Wi-Fi position" in result["remote_control"]["dial_notes"]
    assert len(result["decoded_registers"]) == 6


def test_dissect_telemetry_wrapped_payload() -> None:
    """Test dissect_telemetry end-to-end integration for wrapped envelope payload."""
    payload = {
        "appliance": {
            "current_status_parameters": {
                "StatoTD": "2",
                "PrPh": "2",
                "RemTime": "30",
                "StatoWiFi": "1",
            }
        }
    }
    result = dissect_telemetry(payload)
    assert result["appliance_family"] == "Appliance (Wrapped)"
    assert result["root_key"] == "appliance"
    assert result["remote_control"]["remote_control_enabled"] is True
    assert len(result["decoded_registers"]) == 4


def test_dissect_telemetry_unknown_payload() -> None:
    """Test dissect_telemetry end-to-end integration for unknown payload."""
    payload: dict[str, Any] = {"unknown": {"foo": "bar"}}
    result = dissect_telemetry(payload)
    assert result["appliance_family"] == "Unknown Appliance"
    assert result["root_key"] == "unknown"
    assert result["remote_control"]["remote_control_enabled"] is False
    assert result["decoded_registers"] == [
        {"register": "unknown", "value": "{'foo': 'bar'}", "meaning": ""}
    ]

    empty_result = dissect_telemetry({})
    assert empty_result["decoded_registers"] == []
