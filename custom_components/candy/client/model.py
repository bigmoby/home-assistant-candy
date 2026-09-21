from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path

_PROGRAM_NAMES: dict[str, dict[str, str]] = json.loads(
    (Path(__file__).parent / "program_names.json").read_text(encoding="utf-8")
)

_NFC_PROGRAMS_RAW: list[dict] = json.loads(
    (Path(__file__).parent / "nfc_programs.json").read_text(encoding="utf-8")
)

# Maps DUAL_WM_WD_PROGRAM_DOWNLOAD_NAME_* → {translations, category_translations, description_translations}
# Used by load_downloadable_programs to filter and translate the cloud catalog.
_DOWNLOADABLE_PROGRAM_TRANSLATIONS: dict[str, dict] = {
    e["name"].replace("NFC_PROGRAM_NAME_", "DUAL_WM_WD_PROGRAM_DOWNLOAD_NAME_"): {
        "translations": e["translations"],
        "category_translations": e["category_translations"],
        "description_translations": e.get("description_translations", {}),
    }
    for e in _NFC_PROGRAMS_RAW
}


class StatusCode(Enum):
    def __init__(self, code: int, label: str):
        self.code = code
        self.label = label

    def __str__(self):
        return self.label

    @classmethod
    def from_code(cls, code: int):
        for state in cls:
            if code == state.code:
                return state
        raise ValueError(f"Unrecognized code when parsing {cls}: {code}")


class MachineState(StatusCode):
    # Synthetic state: not returned by the device API, but used internally when the
    # device is unreachable and the last known state was Finished or Idle.
    # This allows sensors to display "Off" instead of "unavailable".
    OFF = (0, "Off")
    IDLE = (1, "Idle")
    RUNNING = (2, "Running")
    PAUSED = (3, "Paused")
    DELAYED_START_SELECTION = (4, "Delayed start selection")
    DELAYED_START_PROGRAMMED = (5, "Delayed start programmed")
    ERROR = (6, "Error")
    FINISHED1 = (7, "Finished")
    FINISHED2 = (8, "Finished")


class CheckUpResult(StatusCode):
    NOT_RUN = (0, "Not run")
    OK = (1, "OK")
    PROBLEM = (2, "Problem detected")


class WashProgramState(StatusCode):
    STOPPED = (0, "Stopped")
    PRE_WASH = (1, "Pre-wash")
    WASH = (2, "Wash")
    RINSE = (3, "Rinse")
    LAST_RINSE = (4, "Last rinse")
    END = (5, "End")
    DRYING = (6, "Drying")
    ERROR = (7, "Error")
    STEAM = (8, "Steam")
    GOOD_NIGHT = (9, "Spin - Good Night")  # TODO: GN pause?
    SPIN = (10, "Spin")


@dataclass
class WashingMachineStatus:
    machine_state: MachineState
    program_state: WashProgramState
    program: int
    program_code: int | None
    temp: int
    spin_speed: int
    remaining_minutes: int
    remote_control: bool
    fill_percent: int | None  # 0...100
    # Extended fields
    error: int | None  # Err — 0 means no error
    delay_value: int | None  # DelVal — delay start value in minutes
    ntc_water: int | None  # NtcW — water NTC sensor (raw ADC)
    ntc_drum: int | None  # NtcD — drum NTC sensor (raw ADC)
    motor_speed_freq: int | None  # APSfreq — motor frequency
    motor_state: int | None  # motS — motor state
    unbalance_fault: int | None  # unbF — unbalance fault count
    unbalance_count: int | None  # unbC — unbalance count
    fault_count: int | None  # numF — total fault count
    dis_test_res: CheckUpResult | None  # DisTestRes — result of last diagnostic
    soil_level: int | None  # SLevel — 0–4 soil level setting
    recipe_id: str | None  # RecipeId — downloadable program (e.g. "D_33")
    dry_type: int | None  # DryT — attached drying-phase option index, 0 if none

    @classmethod
    def from_json(cls, json):
        return cls(
            machine_state=MachineState.from_code(int(json["MachMd"])),
            program_state=WashProgramState.from_code(int(json["PrPh"])),
            program=int(json["Pr"]) if "Pr" in json else int(json["PrNm"]),
            program_code=int(json["PrCode"]) if "PrCode" in json else None,
            temp=int(json["Temp"]),
            spin_speed=int(json["SpinSp"]) * 100,
            remaining_minutes=round(int(json["RemTime"]) / 60),
            remote_control=json["WiFiStatus"] == "1",
            fill_percent=int(json["FillR"]) if "FillR" in json else None,
            error=int(json["Err"]) if "Err" in json else None,
            delay_value=int(json["DelVal"]) if "DelVal" in json else None,
            ntc_water=int(json["NtcW"]) if "NtcW" in json else None,
            ntc_drum=int(json["NtcD"]) if "NtcD" in json else None,
            motor_speed_freq=int(json["APSfreq"]) if "APSfreq" in json else None,
            motor_state=int(json["motS"]) if "motS" in json else None,
            unbalance_fault=int(json["unbF"]) if "unbF" in json else None,
            unbalance_count=int(json["unbC"]) if "unbC" in json else None,
            fault_count=int(json["numF"]) if "numF" in json else None,
            dis_test_res=CheckUpResult.from_code(int(json["DisTestRes"]))
            if "DisTestRes" in json
            else None,
            soil_level=int(json["SLevel"]) if "SLevel" in json else None,
            recipe_id=str(json["RecipeId"]).strip()
            if json.get("RecipeId") is not None
            else None,
            dry_type=int(json["DryT"]) if "DryT" in json else None,
        )


class DryerProgramState(StatusCode):
    STOPPED = (0, "Stopped")
    PRE_HEATING = (1, "Pre-heating")
    RUNNING = (2, "Running")
    END = (3, "End")


class DryerCycleState(StatusCode):
    LEVEL_NONE = (0, "No Dry")
    LEVEL_IRON = (1, "Iron Dry")
    LEVEL_HANG = (2, "Hang Dry")
    LEVEL_STORE = (3, "Store Dry")
    LEVEL_BONE = (4, "Bone Dry")


@dataclass
class TumbleDryerStatus:
    machine_state: MachineState
    program_state: DryerProgramState
    cycle_state: DryerCycleState
    program: int
    remaining_minutes: int
    remote_control: bool
    dry_level: int
    dry_level_selected: int
    refresh: bool
    need_clean_filter: bool
    water_tank_full: bool
    door_closed: bool

    @classmethod
    def from_json(cls, json):
        return cls(
            machine_state=MachineState.from_code(int(json["StatoTD"])),
            program_state=DryerProgramState.from_code(int(json["PrPh"])),
            cycle_state=DryerCycleState.from_code(int(json["DryLev"])),
            program=int(json["Pr"]),
            remaining_minutes=int(json["RemTime"]),
            remote_control=json["StatoWiFi"] == "1",
            dry_level=int(json["DryLev"]),
            dry_level_selected=int(json["DryingManagerLevel"]),
            refresh=json["Refresh"] == "1",
            need_clean_filter=json["CleanFilter"] == "1",
            water_tank_full=json["WaterTankFull"] == "1",
            door_closed=json["DoorState"] == "1",
        )


class DishwasherState(StatusCode):
    """Dishwashers have a single state combining the machine state and program state."""

    IDLE = (0, "Idle")
    PRE_WASH = (1, "Pre-wash")
    WASH = (2, "Wash")
    RINSE = (3, "Rinse")
    DRYING = (4, "Drying")
    FINISHED = (5, "Finished")


@dataclass
class DishwasherStatus:
    machine_state: DishwasherState
    program: str
    remaining_minutes: int
    delayed_start_hours: int | None
    door_open: bool
    door_open_allowed: bool | None
    eco_mode: bool
    remote_control: bool
    salt_empty: bool
    rinse_aid_empty: bool

    @classmethod
    def from_json(cls, json):
        return cls(
            machine_state=DishwasherState.from_code(int(json["StatoDWash"])),
            program=DishwasherStatus.parse_program(json),
            remaining_minutes=int(json["RemTime"]),
            delayed_start_hours=int(json["DelayStart"])
            if json["DelayStart"] != "0"
            else None,
            door_open=json["OpenDoor"] != "0",
            door_open_allowed=json["OpenDoorOpt"] == "1"
            if "OpenDoorOpt" in json
            else None,
            eco_mode=json["Eco"] != "0",
            remote_control=json["StatoWiFi"] == "1",
            salt_empty=json["MissSalt"] == "1",
            rinse_aid_empty=json["MissRinse"] == "1",
        )

    @staticmethod
    def parse_program(json) -> str:
        """Parse final program label, like P1, P1+, P1-."""
        program = json["Program"]
        # Some dishwashers don't include the OpzProg field
        option = json.get("OpzProg")
        if option == "p":
            return program + "+"
        if option == "m":
            return program + "-"
        # Third OpzProg value is 0
        return program


class OvenState(StatusCode):
    IDLE = (0, "Idle")
    HEATING = (1, "Heating")


@dataclass
class OvenStatus:
    machine_state: OvenState
    program: int
    selection: int
    temp: float
    temp_reached: bool
    program_length_minutes: int | None
    remote_control: bool

    @classmethod
    def from_json(cls, json):
        return cls(
            machine_state=OvenState.from_code(int(json["StartStop"])),
            program=int(json["Program"]),
            selection=int(json["Selettore"]),
            temp=round(fahrenheit_to_celsius(int(json["TempRead"]))),
            temp_reached=json["TempSetRaggiunta"] == "1",
            program_length_minutes=int(json["TimeProgr"])
            if "TimeProgr" in json
            else None,
            remote_control=json["StatoWiFi"] == "1",
        )


@dataclass
class WashingMachineWashProgram:
    position: int
    selector_position: int
    name: str
    pr_code: int
    max_temperature: int
    default_temperature: int
    max_spin_speed: int
    default_spin_speed: int
    min_soil_level: int
    max_soil_level: int
    default_soil_level: int
    steam: bool
    steam_type: str
    default_duration: int
    duration_soil_max: int
    duration_soil_medium: int
    duration_soil_min: int
    liquid_detergent_dose: int | None  # 1–4 dose level, or None if not applicable
    powder_detergent_dose: int | None  # 1–4 dose level, or None if not applicable
    max_cycle_capacity: int | None  # kg
    available_options: int  # OptMsk1 bitmask of valid options for this program
    selector_position_dry: int | None  # program accepts an attached drying phase if set

    @classmethod
    def from_dict(cls, program_dict: dict) -> "WashingMachineWashProgram":
        """Parse a program entry from the Simply-Fi appliances JSON."""
        p = program_dict["program"]
        params = {
            cp["command_parameter"]["name"]: cp["command_parameter"]["validation"]
            for cp in p["command_parameters"]
        }

        def _int(key: str, fallback: int = 0) -> int:
            val = params.get(key, "")
            try:
                return int(val)
            except (ValueError, TypeError):
                return fallback

        def _int_or_none(key: str) -> int | None:
            val = params.get(key, "")
            try:
                result = int(val)
            except (ValueError, TypeError):
                return None
            else:
                return result if result > 0 else None

        raw_name: str = p.get("name", "")
        for prefix in ("DUAL_WM_WD_PROGRAM_NAME_", "DUAL_WM_WD_"):
            if raw_name.startswith(prefix):
                raw_name = raw_name[len(prefix) :]
                break

        return cls(
            position=int(p["position"]),
            selector_position=_int("selector_position"),
            name=raw_name,
            pr_code=_int("pr_code"),
            max_temperature=_int("maximum_temperature"),
            default_temperature=_int("default_temperature"),
            max_spin_speed=_int("maximum_spin_speed"),
            default_spin_speed=_int("default_spin_speed"),
            min_soil_level=_int("minimum_soil_level"),
            max_soil_level=_int("maximum_soil_level"),
            default_soil_level=_int("default_soil_level"),
            steam=_int("steam") != 0,
            steam_type=params.get("steam_type", ""),
            default_duration=_int("default_duration"),
            duration_soil_max=_int("remaining_time_soil_max"),
            duration_soil_medium=_int("remaining_time_soil_medium"),
            duration_soil_min=_int("remaining_time_soil_min"),
            liquid_detergent_dose=_int_or_none("liquid_detergent_dose"),
            powder_detergent_dose=_int_or_none("powder_detergent_dose"),
            max_cycle_capacity=_int_or_none("max_cycle_capacity"),
            available_options=_int("available_options"),
            selector_position_dry=_int_or_none("selector_position_dry"),
        )

    @property
    def display_name(self) -> str:
        return self.localized_name("en")

    def localized_name(self, language: str) -> str:
        """Return the program name in the given BCP-47 language code.

        Falls back to English, then to title-casing the raw key.
        """
        translations = _PROGRAM_NAMES.get(self.name, {})
        return (
            translations.get(language)
            or translations.get("en")
            or self.name.replace("_", " ").title()
        )

    def localized_description(self, language: str) -> str | None:
        """Return the program description in the given BCP-47 language code, or None."""
        translations = _PROGRAM_NAMES.get(self.name + "_DESCRIPTION", {})
        return translations.get(language) or translations.get("en") or None


@dataclass
class DownloadableProgram:
    """A special/downloadable program fetched from the Simply-Fi cloud catalog.

    Write-command parameters come from cloud wm_wd_programs; display translations
    come from nfc_programs.json (APK-sourced, explicit per-language strings).
    """

    position: int
    name: str
    parent: int  # Output index into parentToProgram.json; resolved to base program via priority walk
    temperature: int
    spin_speed: int | None  # RPM; None means "MAX" → use base.max_spin_speed
    soil_level: int
    options: int
    steam: int
    translations: dict[str, str]
    category_translations: dict[str, str]
    description_translations: dict[str, str]

    @property
    def recipe_id(self) -> str:
        return f"D_{self.position}"

    def display_name(self, lang: str) -> str:
        return self.translations.get(lang) or self.translations.get("en", self.name)

    def category_name(self, lang: str) -> str:
        return self.category_translations.get(lang) or self.category_translations.get(
            "en", ""
        )

    def category_prefixed(self, lang: str) -> str:
        return f"{self.category_name(lang)} - {self.display_name(lang)}"

    def description(self, lang: str) -> str:
        return self.description_translations.get(
            lang
        ) or self.description_translations.get("en", "")


def load_downloadable_programs(cloud_raw: list[dict]) -> list["DownloadableProgram"]:
    """Build DownloadableProgram list from cloud wm_wd_programs response.

    Only programs present in nfc_programs.json (APK allowlist) are included,
    since those are the only ones with user-visible translated display names.
    Dry-only programs are skipped via the nfc_programs.json allowlist (they have no translations).
    """
    result = []
    for entry in cloud_raw:
        position_str = entry.get("position", "")
        try:
            position = int(position_str)
        except (ValueError, TypeError):
            continue
        name = entry.get("name", "")
        trans = _DOWNLOADABLE_PROGRAM_TRANSLATIONS.get(name)
        if trans is None:
            continue
        spin_raw = entry.get("spin_speed", "0")
        spin: int | None
        if str(spin_raw).upper() == "MAX":
            spin = None
        else:
            try:
                spin = int(spin_raw)
            except (ValueError, TypeError):
                spin = None
        result.append(
            DownloadableProgram(
                position=position,
                name=name,
                parent=int(entry.get("parent", 0)),
                temperature=int(entry.get("temperature", 0)),
                spin_speed=spin,
                soil_level=int(entry.get("soil_level", 0)),
                options=int(entry.get("options", 0)),
                steam=int(entry.get("steam", 0)),
                translations=trans["translations"],
                category_translations=trans["category_translations"],
                description_translations=trans["description_translations"],
            )
        )
    return result


@dataclass
class WashingMachineStatistics:
    total_cycles: int

    @classmethod
    def from_json(cls, json):
        # Program1..21 are 8-bit device counters that wrap at 256, which would
        # periodically collapse total_cycles by 256. Temp0to30/Temp40/Temp60to90
        # are wider counters tracking the same events (confirmed equal to the
        # program sum in captures), so they're used instead. Programs that never
        # heat may not increment any temperature bucket, causing a small
        # under-count — an accepted trade-off versus the wraparound.
        total = sum(
            int(v)
            for k, v in json.items()
            if k in ("Temp0to30", "Temp40", "Temp60to90") and v.isdigit()
        )
        return cls(total_cycles=total)


class WineCoolerState(StatusCode):
    OFF = (0, "Off")
    ON = (2, "On")
    ERROR = (3, "Error")


class WineCoolerProgram(StatusCode):
    RED_WINE = (1, "Red wine")
    WHITE_WINE = (2, "White wine")
    SPARKLING = (3, "Sparkling")

    @property
    def default_temp(self) -> int:
        if self == WineCoolerProgram.RED_WINE:
            return 16
        if self == WineCoolerProgram.WHITE_WINE:
            return 12
        if self == WineCoolerProgram.SPARKLING:
            return 8
        return 12


@dataclass
class WineCoolerStatus:
    machine_state: WineCoolerState
    program: WineCoolerProgram
    temp: int
    light: bool
    error: str | None
    remote_control: bool
    program_down: WineCoolerProgram | None = None
    temp_down: int | None = None

    @classmethod
    def from_json(cls, json):
        wc_state_code = int(json["r5"]) if "r5" in json else 2
        error_val = json.get("r2")
        program = WineCoolerProgram.from_code(int(json["r3"]))
        raw_temp = int(json["r4"]) if "r4" in json and str(json["r4"]).isdigit() else 0
        temp = raw_temp if raw_temp > 0 else program.default_temp

        program_down = None
        if "r7" in json and json["r7"] not in ("0", ""):
            try:
                program_down = WineCoolerProgram.from_code(int(json["r7"]))
            except ValueError:
                program_down = None

        raw_temp_down = (
            int(json["r8"])
            if "r8" in json and str(json["r8"]).isdigit() and json["r8"] != "0"
            else None
        )
        temp_down = (
            raw_temp_down
            if (raw_temp_down is not None and raw_temp_down > 0)
            else (program_down.default_temp if program_down else None)
        )

        return cls(
            machine_state=WineCoolerState.from_code(wc_state_code),
            program=program,
            temp=temp,
            light=json.get("r10") == "1",
            error=error_val if error_val and error_val != "E0" else None,
            remote_control=json.get("r1") == "1",
            program_down=program_down,
            temp_down=temp_down,
        )


def fahrenheit_to_celsius(fahrenheit: float) -> float:
    return (fahrenheit - 32) * 5.0 / 9.0
