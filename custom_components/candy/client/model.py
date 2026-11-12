from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Any

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


class CheckUpState(StatusCode):
    IDLE = (0, "Idle")
    RUNNING = (1, "Running")
    COMPLETED = (2, "Completed")


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
    GOOD_NIGHT = (
        9,
        "Good Night rinse hold",
    )  # Rinse hold with water in drum; resume with Write=1&RestartGN=1
    SPIN = (10, "Spin")


# Confirmed via Simply-Fi APK CandyWasherDryerDualTech.dryWithValue (classes4.dex):
# 0 = none, 1 = extra, 2 = pronto armadio (cupboard), 3 = pronto stiro (iron), 4 = cool-down, 9 = wool dry
class WasherDryerDryTarget(StatusCode):
    NO_DRY = (0, "no_dry")
    EXTRA_DRY = (1, "extra_dry")
    CUPBOARD_DRY = (2, "cupboard_dry")
    IRON_DRY = (3, "iron_dry")
    COOLDOWN = (4, "cooldown")
    TIME_120 = (5, "120_minutes")
    TIME_90 = (6, "90_minutes")
    TIME_60 = (7, "60_minutes")
    TIME_30 = (8, "30_minutes")
    WOOL_DRY = (9, "wool_dry")

    @classmethod
    def from_raw(cls, raw: Any) -> WasherDryerDryTarget | None:
        """Parse a wire DryT register value safely.

        Returns the matching WasherDryerDryTarget if raw is a valid digit
        string or integer in 0..9; returns None for empty, non-digit, or
        unrecognized codes (e.g. unequipped standalone washer sentinels).
        """
        if raw is None:
            return None
        val_str = str(raw).strip()
        if not val_str.isdigit():
            return None
        code = int(val_str)
        for target in cls:
            if target.code == code:
                return target
        return None


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
    checkup_state: CheckUpState | None  # CheckUpState — diagnostic lifecycle
    soil_level: int | None  # SLevel — 0–4 soil level setting
    recipe_id: str | None  # RecipeId — downloadable program (e.g. "D_33")
    dry_target: WasherDryerDryTarget | None
    # Auto-dose fields (_ad models)
    detergent_on: bool | None
    softener_on: bool | None
    detergent_empty: bool | None
    softener_empty: bool | None
    detergent_reserve: bool | None
    softener_reserve: bool | None
    detergent_cycles_remaining: int | None
    softener_cycles_remaining: int | None
    water_hardness: int | None
    extra_dose_active: bool | None

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
            checkup_state=CheckUpState.from_code(int(json["CheckUpState"]))
            if "CheckUpState" in json
            else None,
            soil_level=int(json["SLevel"]) if "SLevel" in json else None,
            recipe_id=str(json["RecipeId"]).strip()
            if json.get("RecipeId") is not None
            else None,
            dry_target=WasherDryerDryTarget.from_raw(json.get("DryT")),
            detergent_on=json["Det"] == "1"
            if "Det" in json and json["Det"] != ""
            else None,
            softener_on=json["Soft"] == "1"
            if "Soft" in json and json["Soft"] != ""
            else None,
            detergent_empty=json["DetWarn"] == "1"
            if "DetWarn" in json and json["DetWarn"] != ""
            else None,
            softener_empty=json["SoftWarn"] == "1"
            if "SoftWarn" in json and json["SoftWarn"] != ""
            else None,
            detergent_reserve=json["DetPreW"] == "1"
            if "DetPreW" in json and json["DetPreW"] != ""
            else None,
            softener_reserve=json["SoftPreW"] == "1"
            if "SoftPreW" in json and json["SoftPreW"] != ""
            else None,
            detergent_cycles_remaining=int(json["DPrgCnt"])
            if "DPrgCnt" in json and str(json["DPrgCnt"]).isdigit()
            else None,
            softener_cycles_remaining=int(json["SPrgCnt"])
            if "SPrgCnt" in json and str(json["SPrgCnt"]).isdigit()
            else None,
            water_hardness=int(json["WaterHard"])
            if "WaterHard" in json and str(json["WaterHard"]).isdigit()
            else None,
            extra_dose_active=json["rED"] == "1"
            if "rED" in json and json["rED"] != ""
            else None,
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


_STATO_TD_MAP: dict[int, MachineState] = {
    0: MachineState.IDLE,
    1: MachineState.IDLE,
    2: MachineState.RUNNING,
    3: MachineState.PAUSED,
    4: MachineState.DELAYED_START_SELECTION,
    5: MachineState.DELAYED_START_PROGRAMMED,
    6: MachineState.RUNNING,
    7: MachineState.ERROR,
    8: MachineState.FINISHED1,
}


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
    error: str | None
    delay_value: int | None
    checkup_state: CheckUpState | None
    recipe_id: str | None
    time: int | None
    rapido: int | None

    @classmethod
    def from_json(cls, json):
        err = json.get("CodiceErrore")
        error_val = (
            str(err).strip()
            if err is not None and str(err).strip() not in ("0", "E0", "")
            else None
        )
        raw_stato = int(json["StatoTD"])
        machine_state = _STATO_TD_MAP.get(raw_stato)
        if machine_state is None:
            raise ValueError(f"Unrecognized StatoTD code: {raw_stato}")
        return cls(
            machine_state=machine_state,
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
            error=error_val,
            delay_value=int(json["DelVal"])
            if "DelVal" in json and str(json["DelVal"]).isdigit()
            else None,
            checkup_state=CheckUpState.from_code(int(json["CheckUpState"]))
            if "CheckUpState" in json and str(json["CheckUpState"]).isdigit()
            else None,
            recipe_id=str(json["RecipeId"]).strip()
            if json.get("RecipeId") not in (None, "NULL", "")
            else None,
            time=int(json["Time"])
            if "Time" in json and str(json["Time"]).isdigit()
            else None,
            rapido=int(json["Rapido"])
            if "Rapido" in json and str(json["Rapido"]).isdigit()
            else None,
        )

    @property
    def error_code(self) -> int | None:
        """Integer error code (0 if clear, e.g. 3 for E03)."""
        if self.error is None or self.error in ("0", "E0", ""):
            return 0
        raw = self.error.upper().lstrip("E")
        return int(raw) if raw.isdigit() else None


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
    program_type: str
    selector_position_dry: int | None
    dry_supported: bool
    dry: int

    @classmethod
    def from_dict(cls, program_dict: dict) -> WashingMachineWashProgram:
        """Parse a program entry from the Simply-Fi appliances JSON."""
        p = program_dict.get("program", program_dict)
        raw_params = p.get("command_parameters") or p.get("parameters") or []
        params: dict[str, str] = {}
        if isinstance(raw_params, dict):
            params = {k: str(v) for k, v in raw_params.items()}
        elif isinstance(raw_params, list):
            for cp in raw_params:
                if "command_parameter" in cp:
                    params[cp["command_parameter"]["name"]] = str(
                        cp["command_parameter"]["validation"]
                    )
                elif "name" in cp:
                    params[cp["name"]] = str(cp["validation"])

        def _int(key: str, fallback: int) -> int:
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
        for prefix in (
            "DUAL_WM_WD_PROGRAM_NAME_",
            "DUAL_WM_WD_",
            "NFC_PROGRAM_NAME_1D_",
            "NFC_PROGRAM_NAME_2D_",
            "NFC_PROGRAM_NAME_",
            "WA_PROG_",
            "NFC_CARE_",
        ):
            if raw_name.startswith(prefix):
                raw_name = raw_name[len(prefix) :]
                break
        if raw_name == "AUTO_CLEAN":
            raw_name = "AUTOCLEAN"

        raw_program_type: str = params.get("program_type", "").upper()
        if "WASH_AND_DRY" in raw_name.upper() or "WASH_DRY" in raw_name.upper():
            raw_program_type = "WD"
        elif not raw_program_type:
            if "_DRY" in raw_name.upper() or "DRY_" in raw_name.upper():
                raw_program_type = "D"
            else:
                raw_program_type = "W"

        selector_position_dry = _int_or_none("selector_position_dry")
        dry_val = _int("dry", 0)
        dry_supported = (selector_position_dry is not None) or (dry_val > 0)

        return cls(
            position=int(p["position"]),
            selector_position=_int("selector_position", 0),
            name=raw_name,
            pr_code=_int("pr_code", 0),
            max_temperature=_int("maximum_temperature", 0),
            default_temperature=_int("default_temperature", 0),
            max_spin_speed=_int("maximum_spin_speed", 0),
            default_spin_speed=_int("default_spin_speed", 0),
            min_soil_level=_int("minimum_soil_level", 0),
            max_soil_level=_int("maximum_soil_level", 0),
            default_soil_level=_int("default_soil_level", 0),
            steam=_int("steam", 0) != 0,
            steam_type=params.get("steam_type", ""),
            default_duration=_int("default_duration", 0),
            duration_soil_max=_int("remaining_time_soil_max", 0),
            duration_soil_medium=_int("remaining_time_soil_medium", 0),
            duration_soil_min=_int("remaining_time_soil_min", 0),
            liquid_detergent_dose=_int_or_none("liquid_detergent_dose"),
            powder_detergent_dose=_int_or_none("powder_detergent_dose"),
            max_cycle_capacity=_int_or_none("max_cycle_capacity"),
            available_options=_int("available_options", 0),
            program_type=raw_program_type,
            selector_position_dry=selector_position_dry,
            dry_supported=dry_supported,
            dry=dry_val,
        )

    @property
    def is_dry(self) -> bool:
        """Return True if this program is a standalone drying cycle.

        Note: Describes individual cycle type for program selectors and options,
        not physical appliance hardware identity.
        """
        if self.program_type:
            return self.program_type == "D"
        name_upper = self.name.upper()
        return (
            name_upper.endswith("_DRY")
            or "_DRY_" in name_upper
            or name_upper.startswith("DRY_")
        )

    @property
    def is_wash(self) -> bool:
        """Return True if this program includes a wash phase."""
        if self.program_type:
            return self.program_type in ("W", "WD")
        return not self.is_dry

    @property
    def is_wash_and_dry(self) -> bool:
        """Return True if this program supports combined wash and dry."""
        return (
            (self.program_type == "WD")
            or (self.is_wash and self.dry_supported)
            or ("WASH_AND_DRY" in self.name.upper())
            or ("WASH_DRY" in self.name.upper())
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

    def duration_for_soil(self, soil: int) -> int:
        """Return duration in minutes for the given soil level."""
        if self.min_soil_level < self.max_soil_level:
            if soil <= 1:
                return self.duration_soil_min or self.default_duration
            if soil == 2:
                return self.duration_soil_medium or self.default_duration
            return self.duration_soil_max or self.default_duration
        return self.default_duration


@dataclass
class TumbleDryerProgram:
    position: int
    selector_position: int
    name: str
    default_drying_level: int
    max_time_level: int
    default_time_level: int
    set_dry_level: bool
    set_time_level: bool
    set_rapido: bool
    duration: int
    mask1: int
    mask2: int

    @classmethod
    def from_dict(cls, program_dict: dict) -> TumbleDryerProgram:
        """Parse a program entry from the Simply-Fi tumble dryer appliance JSON."""
        p = program_dict.get("program", program_dict)
        raw_params = p.get("command_parameters") or p.get("parameters") or []
        params: dict[str, str] = {}
        if isinstance(raw_params, dict):
            params = {k: str(v) for k, v in raw_params.items()}
        elif isinstance(raw_params, list):
            for cp in raw_params:
                if "command_parameter" in cp:
                    params[cp["command_parameter"]["name"]] = str(
                        cp["command_parameter"]["validation"]
                    )
                elif "name" in cp:
                    params[cp["name"]] = str(cp["validation"])

        def _int(key: str, fallback: int) -> int:
            val = params[key] if key in params else p.get(key, "")
            try:
                return int(val)
            except (ValueError, TypeError):
                return fallback

        raw_name: str = p.get("name", "")
        for prefix in (
            "__HOOVER__NFC_TD_PROGRAM_NAME_",
            "__HOOVER__DUAL_TD_PROGRAM_DOWNLOAD_",
            "NFC_TD_PROGRAM_NAME_",
            "TD_PROGRAM_NAME_",
            "NFC_TD_",
            "DUAL_TD_PROGRAM_DOWNLOAD_",
            "DUAL_WM_PROGRAM_DOWNLOAD_",
        ):
            if raw_name.startswith(prefix):
                raw_name = raw_name[len(prefix) :]
                break

        return cls(
            position=int(p.get("position", 0)),
            selector_position=_int("selector_position", 0),
            name=raw_name,
            default_drying_level=_int("default_drying_level", 0),
            max_time_level=_int("max_time_level", 0),
            default_time_level=_int("default_time_level", 0),
            set_dry_level=_int("set_dry_level", 0) != 0,
            set_time_level=_int("set_time_level", 0) != 0,
            set_rapido=_int("set_rapido", 0) != 0,
            duration=_int("duration", 0),
            mask1=_int("mask1", 0),
            mask2=_int("mask2", 0),
        )

    @property
    def display_name(self) -> str:
        return self.localized_name("en")

    def localized_name(self, language: str) -> str:
        """Return the program name in the given BCP-47 language code."""
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

    def resolve_soil_target(self, base: WashingMachineWashProgram) -> int:
        """Resolve effective soil level against a base program's constraints."""
        if base.min_soil_level <= self.soil_level <= base.max_soil_level and (
            self.soil_level > 0 or base.min_soil_level == 0
        ):
            return self.soil_level
        if base.min_soil_level <= base.default_soil_level <= base.max_soil_level:
            return base.default_soil_level
        return base.min_soil_level


def _safe_int(val: object, fallback: int) -> int:
    if isinstance(val, (int, str, float, bytes)):
        try:
            return int(val)
        except ValueError:
            return fallback
    return fallback


def load_downloadable_programs(cloud_raw: list[dict]) -> list[DownloadableProgram]:
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
                parent=_safe_int(entry.get("parent"), 0),
                temperature=_safe_int(entry.get("temperature"), 0),
                spin_speed=spin,
                soil_level=_safe_int(entry.get("soil_level"), 0),
                options=_safe_int(entry.get("options"), 0),
                steam=_safe_int(entry.get("steam"), 0),
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
