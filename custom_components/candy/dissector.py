"""Telemetry dissector and register decoder for Candy Simply-Fi appliances."""

from __future__ import annotations

from typing import Any

from .client.model import fahrenheit_to_celsius

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


def is_truthy_value(val: Any) -> bool:
    """Return True if val represents an active or truthy hardware state."""
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    return s in ("1", "true", "yes", "on", "locked", "open", "full", "active")


def detect_appliance_family(
    json_data: dict[str, Any],
) -> tuple[str, str, dict[str, Any]]:
    """Identify root telemetry envelope and appliance family."""
    for root_key, family_name in ROOT_KEYS_TO_FAMILY.items():
        if root_key in json_data and isinstance(json_data[root_key], dict):
            return root_key, family_name, json_data[root_key]

    if "appliance" in json_data and isinstance(json_data["appliance"], dict):
        app = json_data["appliance"]
        if "current_status_parameters" in app and isinstance(
            app["current_status_parameters"], dict
        ):
            return "appliance", "Appliance (Wrapped)", app["current_status_parameters"]

    return "unknown", "Unknown Appliance", json_data


def decode_registers(
    family_key: str,
    data: dict[str, Any],
) -> list[dict[str, str]]:
    """Decode raw wire telemetry registers into structured dictionaries."""
    results: list[dict[str, str]] = []

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
                desc = (
                    f"{val} °C wash temperature" if val != "0" else "Cold wash (0 °C)"
                )
            elif k == "SpinSp":
                try:
                    desc = (
                        f"{int(val) * 100} RPM spin speed"
                        if val != "0"
                        else "No spin (0 RPM)"
                    )
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
                desc = (
                    "Remote Control ENABLED"
                    if is_truthy_value(val)
                    else "Remote Control DISABLED"
                )
            elif k == "DoorLock":
                desc = "Door locked" if is_truthy_value(val) else "Door unlocked"
            elif k == "FillR":
                desc = f"{val}% estimated load weight"
            elif k in ("Err", "CodiceErrore"):
                desc = "No fault" if val == "0" else f"Fault code {val}"
            elif k == "CheckUpState":
                desc = (
                    "Diagnostic check-up active"
                    if is_truthy_value(val)
                    else "Check-up idle"
                )
            elif k in ("SLevel", "SLevTgt"):
                soil_labels = {"1": "Light", "2": "Normal", "3": "Heavy"}
                desc = f"Soil level {val} ({soil_labels.get(val, 'Custom')})"
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

            results.append({"register": k, "value": val, "meaning": desc})

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
                desc = (
                    "Water container FULL" if is_truthy_value(val) else "Water tank OK"
                )
            elif k == "CleanFilter":
                desc = (
                    "Lint filter clean REQUIRED"
                    if is_truthy_value(val)
                    else "Filter clean OK"
                )
            elif k == "DoorState":
                desc = "Door CLOSED" if is_truthy_value(val) else "Door OPEN"
            elif k in ("StatoWiFi", "RemCode"):
                desc = (
                    "Remote Control ENABLED"
                    if is_truthy_value(val)
                    else "Remote Control DISABLED"
                )
            elif k == "DelVal":
                desc = f"{val} min delayed start remaining"
            elif k == "RecipeId":
                desc = f"Downloadable / NFC program '{val}'"
            elif k == "Rapido":
                desc = f"Timed / Rapid dry index {val}"
            elif k == "Time":
                desc = f"{val} min timed dry duration"
            elif k == "Refresh":
                desc = (
                    "Refresh / Anti-crease ACTIVE"
                    if is_truthy_value(val)
                    else "Refresh off"
                )
            elif k in ("Err", "CodiceErrore"):
                desc = "No fault" if val in ("0", "E0") else f"Fault code {val}"
            elif k == "CheckUpState":
                desc = (
                    "Diagnostic check-up active"
                    if is_truthy_value(val)
                    else "Check-up idle"
                )

            results.append({"register": k, "value": val, "meaning": desc})

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
                desc = (
                    "Option Plus (+)"
                    if val == "p"
                    else ("Option Minus (-)" if val == "m" else "Standard")
                )
            elif k == "RemTime":
                desc = f"{val} minutes remaining"
            elif k == "OpenDoor":
                desc = "Door OPEN" if is_truthy_value(val) else "Door CLOSED"
            elif k == "OpenDoorOpt":
                desc = (
                    "Automatic door opening active"
                    if is_truthy_value(val)
                    else "Auto-door off"
                )
            elif k == "MissSalt":
                desc = (
                    "Salt container EMPTY" if is_truthy_value(val) else "Salt level OK"
                )
            elif k == "MissRinse":
                desc = (
                    "Rinse aid container EMPTY"
                    if is_truthy_value(val)
                    else "Rinse aid OK"
                )
            elif k == "Eco":
                desc = "Eco cycle active" if is_truthy_value(val) else "Eco off"
            elif k == "MetaCarico":
                desc = "Half load active" if is_truthy_value(val) else "Standard load"
            elif k == "TreinUno":
                desc = (
                    "3-in-1 tablet active"
                    if is_truthy_value(val)
                    else "Standard detergent"
                )
            elif k == "ExtraDry":
                desc = "Extra dry active" if is_truthy_value(val) else "Extra dry off"
            elif k == "DelayStart":
                desc = f"{val} hours delayed start countdown"
            elif k == "StatoWiFi":
                desc = (
                    "Remote Control ENABLED"
                    if is_truthy_value(val)
                    else "Remote Control DISABLED"
                )
            elif k in ("Err", "CodiceErrore"):
                desc = "No fault" if val in ("0", "E0") else f"Fault code {val}"

            results.append({"register": k, "value": val, "meaning": desc})

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
                    c_val = round(fahrenheit_to_celsius(f_val))
                    desc = f"{c_val} °C ({f_val} °F) measured cavity temp"
                except ValueError:
                    desc = f"{val} temp reading"
            elif k == "TempSet":
                try:
                    desc = f"{int(val) // 10 if int(val) > 100 else int(val)} °C target temp"
                except ValueError:
                    desc = f"{val} target temp"
            elif k == "TempSetRaggiunta":
                desc = (
                    "Target temperature REACHED"
                    if is_truthy_value(val)
                    else "Preheating / Heating up"
                )
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
                desc = (
                    "Remote Control ENABLED"
                    if is_truthy_value(val)
                    else "Remote Control DISABLED"
                )

            results.append({"register": k, "value": val, "meaning": desc})

    # Wine Coolers
    elif family_key == "statusWCool":
        wc_prog_map = {"1": "Red Wine", "2": "White Wine", "3": "Sparkling Wine"}
        for k, v in data.items():
            val = str(v)
            desc = ""
            if k == "r1":
                desc = (
                    "Remote Control ENABLED"
                    if is_truthy_value(val)
                    else "Remote Control DISABLED"
                )
            elif k == "r2":
                desc = "Normal operation" if val == "E0" else f"Fault code {val}"
            elif k == "r3":
                desc = wc_prog_map.get(val, f"Zone 1 program {val}")
            elif k == "r4":
                desc = f"{val} °C Zone 1 set temp"
            elif k == "r5":
                desc = (
                    "Powered ON"
                    if val == "2"
                    else ("Powered OFF" if val == "0" else f"State {val}")
                )
            elif k == "r6":
                desc = f"{val} °C Zone 1 measured temp"
            elif k == "r7":
                desc = wc_prog_map.get(val, f"Zone 2 program {val}")
            elif k == "r8":
                desc = f"{val} °C Zone 2 set temp"
            elif k == "r9":
                desc = f"{val} °C Zone 2 measured temp"
            elif k == "r10":
                desc = (
                    "Interior light ON"
                    if is_truthy_value(val)
                    else "Interior light OFF"
                )
            elif k == "r11":
                desc = "Fahrenheit scale" if val == "1" else "Celsius scale"

            results.append({"register": k, "value": val, "meaning": desc})

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
                desc = (
                    "Compressor RUNNING" if is_truthy_value(val) else "Compressor IDLE"
                )
            elif k == "CmpFq":
                desc = f"{val} Hz compressor motor frequency"
            elif k == "Fan":
                desc = "Circulation fan RUNNING" if is_truthy_value(val) else "Fan off"
            elif k == "Heat":
                desc = (
                    "Defrost heater ACTIVE"
                    if is_truthy_value(val)
                    else "Defrost heater off"
                )
            elif k == "Eco":
                desc = "Eco energy saving ACTIVE" if is_truthy_value(val) else "Eco off"
            elif k == "Spr":
                desc = (
                    "Super Freezing ACTIVE"
                    if is_truthy_value(val)
                    else "Super Freeze off"
                )
            elif k == "SprC":
                desc = (
                    "Super Cooling ACTIVE" if is_truthy_value(val) else "Super Cool off"
                )
            elif k == "Antib":
                desc = (
                    "Anti-bacterial sterilization ACTIVE"
                    if is_truthy_value(val)
                    else "Anti-bacterial off"
                )
            elif k == "Ice":
                desc = "Ice maker ACTIVE" if is_truthy_value(val) else "Ice maker off"
            elif k == "NewIce":
                desc = f"{val} min drink chill countdown duration"
            elif k == "Lck":
                desc = "Child lock ACTIVE" if is_truthy_value(val) else "Child lock off"
            elif k == "PF":
                desc = (
                    "Power failure warning ACTIVE"
                    if is_truthy_value(val)
                    else "Power OK"
                )
            elif k in ("WiFi", "WiFiStatus", "StatoWiFi"):
                desc = (
                    "Remote Control ENABLED"
                    if is_truthy_value(val)
                    else "Remote Control DISABLED"
                )

            results.append({"register": k, "value": val, "meaning": desc})

    # Kitchen Hoods
    elif family_key == "StatusHood":
        for k, v in data.items():
            val = str(v)
            desc = ""
            if k == "Fan":
                desc = (
                    "Intensive / Booster"
                    if val == "4"
                    else (f"Speed {val}" if val != "0" else "Fan OFF")
                )
            elif k == "Light":
                desc = (
                    "Light ON"
                    if val == "1"
                    else ("Ambient light" if val == "2" else "Light OFF")
                )
            elif k == "GreaseFilter":
                desc = (
                    "Grease filter saturation WARNING"
                    if is_truthy_value(val)
                    else "Grease filter OK"
                )
            elif k == "CarbonFilter":
                desc = (
                    "Carbon filter replacement WARNING"
                    if is_truthy_value(val)
                    else "Carbon filter OK"
                )
            elif k == "Timer":
                desc = "Auto-off timer ACTIVE" if is_truthy_value(val) else "Timer off"
            elif k == "TimerCnt":
                desc = f"{val} min remaining on auto-off timer"
            elif k == "BoostCnt":
                desc = f"{val} sec remaining on booster"
            elif k in ("WiFiStatus", "StatoWiFi"):
                desc = (
                    "Remote Control ENABLED"
                    if is_truthy_value(val)
                    else "Remote Control DISABLED"
                )

            results.append({"register": k, "value": val, "meaning": desc})

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
                desc = (
                    "Residual heat (HOT 'H')" if is_truthy_value(val) else "Safe / Cold"
                )
            elif k.endswith("pan") and len(k) == 5:
                desc = (
                    "Cookware detected"
                    if is_truthy_value(val)
                    else "No cookware / unsuitable"
                )
            elif k.endswith("combi") and len(k) == 7:
                desc = (
                    "Bridge / coupled zone" if is_truthy_value(val) else "Single zone"
                )
            elif k.endswith("low") and len(k) == 5:
                desc = (
                    "Keep warm / melting active"
                    if is_truthy_value(val)
                    else "Standard mode"
                )
            elif k in ("StatoWiFi", "WiFiStatus"):
                desc = (
                    "Remote Control ENABLED"
                    if is_truthy_value(val)
                    else "Remote Control DISABLED"
                )

            results.append({"register": k, "value": val, "meaning": desc})

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
                desc = (
                    "Dust bin missing/full ERROR"
                    if is_truthy_value(val)
                    else "Dust bin OK"
                )
            elif k == "FiErr":
                desc = "Filter blockage ERROR" if is_truthy_value(val) else "Filter OK"
            elif k == "BMO":
                desc = (
                    "Brush motor fault ERROR"
                    if is_truthy_value(val)
                    else "Brush motor OK"
                )
            elif k == "RMO":
                desc = (
                    "Wheel motor fault ERROR"
                    if is_truthy_value(val)
                    else "Wheel motor OK"
                )

            results.append({"register": k, "value": val, "meaning": desc})

    # Fallback for generic registers
    else:
        for k, v in data.items():
            val = str(v)
            desc = ""
            if k in ("WiFiStatus", "StatoWiFi", "RemCode", "WiFi"):
                desc = (
                    "Remote Control ENABLED"
                    if is_truthy_value(val)
                    else "Remote Control DISABLED"
                )
            elif k in ("Err", "CodiceErrore"):
                desc = "No fault" if val in ("0", "E0") else f"Fault code {val}"
            results.append({"register": k, "value": val, "meaning": desc})

    return results


def evaluate_remote_control(
    family_key: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate remote control prerequisites and identify write capabilities."""
    remote_flag = False
    for flag_key in ("WiFiStatus", "StatoWiFi", "RemCode", "WiFi", "r1"):
        if flag_key in data and is_truthy_value(data[flag_key]):
            remote_flag = True
            break

    supported_commands: list[str] = []
    dial_notes = ""

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
        dial_notes = (
            "Door is OPEN! Close door before sending start commands."
            if door_open
            else "Door is CLOSED."
        )
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


def dissect_telemetry(
    telemetry_data: dict[str, Any],
) -> dict[str, Any]:
    """Perform full dissection of telemetry payload."""
    root_key, family_name, appliance_dict = detect_appliance_family(telemetry_data)
    decoded = decode_registers(root_key, appliance_dict)
    rc_info = evaluate_remote_control(root_key, appliance_dict)
    return {
        "appliance_family": family_name,
        "root_key": root_key,
        "remote_control": rc_info,
        "decoded_registers": decoded,
    }
