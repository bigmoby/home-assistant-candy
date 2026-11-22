"""Command builders for Candy and Hoover dishwashers."""

from __future__ import annotations

from abc import ABC, abstractmethod


def is_open_door_supported(interface_type: str | None) -> bool:
    """Return True if interface_type ends with or contains _OD (motorized Auto-Open Door)."""
    if not interface_type:
        return False
    return "_OD" in interface_type.upper()


def is_legacy_dishwasher(interface_type: str | None) -> bool:
    """Return True if interface_type belongs to Family 1 legacy dishwashers."""
    if not interface_type:
        return False
    return any(
        term in interface_type
        for term in ("FSTouch", "BuiltIn", "NFC_DIGIT", "DishwasherInterfaceType")
    )


def is_modern_dishwasher(interface_type: str | None) -> bool:
    """Return True if the interface_type belongs to Family 2 (Brava) or Family 3 (AXI)."""
    if not interface_type or is_legacy_dishwasher(interface_type):
        return False
    up = interface_type.upper()
    if "_AD" in up or "RED_DEVIL" in up:
        return False
    return any(term in up for term in ("BRAVA", "DW_WIFI", "AXI", "SMOOTH"))


class DishwasherCommandBuilder(ABC):
    """Abstract interface for dishwasher write command builders."""

    @abstractmethod
    def build_start(
        self,
        program_code: str,
        position: int,
        delay_minutes: int,
        r15: int,
        three_in_one: bool,
        eco: bool,
        half_load: bool,
        extra_dry: bool,
        open_door: bool,
    ) -> dict[str, str | int]:
        """Build parameters to start a dishwasher cycle."""

    @abstractmethod
    def build_stop(self) -> dict[str, str | int]:
        """Build parameters to stop or reset the running cycle."""

    @abstractmethod
    def build_pause(self) -> dict[str, str | int]:
        """Build parameters to pause the active cycle."""

    @abstractmethod
    def build_resume(self) -> dict[str, str | int]:
        """Build parameters to resume a paused cycle."""

    @abstractmethod
    def build_open_door(self) -> dict[str, str | int]:
        """Build parameters to release motorized door."""

    @abstractmethod
    def build_checkup(self) -> dict[str, str | int]:
        """Build parameters to run diagnostic check-up."""

    @abstractmethod
    def build_checkup_reset(self) -> dict[str, str | int]:
        """Build parameters to reset/dismiss completed diagnostic check-up."""


class ModernDishwasherCommandBuilder(DishwasherCommandBuilder):
    """Command builder for modern Brava, Nautilus, and AXI dishwashers (Family 2 & 3)."""

    def __init__(self, open_door_supported: bool) -> None:
        self.open_door_supported = open_door_supported

    def build_start(
        self,
        program_code: str,
        position: int,
        delay_minutes: int,
        r15: int,
        three_in_one: bool,
        eco: bool,
        half_load: bool,
        extra_dry: bool,
        open_door: bool,
    ) -> dict[str, str | int]:
        delay_val: int
        if r15 > 0:
            delay_val = delay_minutes
        else:
            delay_val = delay_minutes // 60

        prog_str = program_code if program_code.startswith("P") else f"P{program_code}"
        # Bitmask confirmed via DishWasher.java:520 and Command.java:220:
        # Bit 0 (1): ExtraDry
        # Bit 1 (2): MetaCarico (Half Load)
        # Bit 2 (4): Eco
        # Bit 3 (8): TreinUno (3-in-1 tablets)
        # Bit 4 (16): OpenDoorOpt (Auto Door Open)
        opt_mask = (
            (int(extra_dry) * 1)
            | (int(half_load) * 2)
            | (int(eco) * 4)
            | (int(three_in_one) * 8)
            | (int(open_door) * 16 if self.open_door_supported else 0)
        )

        params: dict[str, str | int] = {
            "DelayStart": delay_val,
            "ExtraDry": int(extra_dry),
            "TreinUno": int(three_in_one),
            "Eco": int(eco),
            "Program": prog_str,
            "MetaCarico": int(half_load),
            "OpzProg": opt_mask,
            "w1": position,
            "StartStop": 1,
        }
        if self.open_door_supported:
            params["OpenDoorOpt"] = int(open_door)
        return params

    def build_stop(self) -> dict[str, str | int]:
        return {"Reset": 1}

    def build_pause(self) -> dict[str, str | int]:
        return {"Pa": 1}

    def build_resume(self) -> dict[str, str | int]:
        return {"Pa": 0}

    def build_open_door(self) -> dict[str, str | int]:
        return {"OpenDoorOpt": 7}

    def build_checkup(self) -> dict[str, str | int]:
        return {"StartCheckUp": 1}

    def build_checkup_reset(self) -> dict[str, str | int]:
        return {"Write": 1, "StartStop": 0, "Program": 11}


class LegacyTouchDishwasherCommandBuilder(DishwasherCommandBuilder):
    """Command builder for legacy Touch and Built-in dishwashers (Family 1)."""

    def __init__(self, open_door_supported: bool) -> None:
        self.open_door_supported = open_door_supported

    def build_start(
        self,
        program_code: str,
        position: int,
        delay_minutes: int,
        r15: int,
        three_in_one: bool,
        eco: bool,
        half_load: bool,
        extra_dry: bool,
        open_door: bool,
    ) -> dict[str, str | int]:
        delay_val: int
        if r15 > 0:
            delay_val = delay_minutes
        else:
            delay_val = delay_minutes // 60

        option = "0"
        if program_code.endswith("+"):
            option = "p"
        elif program_code.endswith("-"):
            option = "m"

        clean_prog = program_code.rstrip("+-")
        prog_str = clean_prog if clean_prog.startswith("P") else f"P{clean_prog}"

        params: dict[str, str | int] = {
            "DelayStart": delay_val,
            "ExtraDry": int(extra_dry),
            "TreinUno": int(three_in_one),
            "Eco": int(eco),
            "Program": prog_str,
            "MetaCarico": int(half_load),
            "OpzProg": option,
            "StartStop": 1,
        }
        if self.open_door_supported:
            params["OpenDoorOpt"] = int(open_door)
        return params

    def build_stop(self) -> dict[str, str | int]:
        return {"Reset": 1}

    def build_pause(self) -> dict[str, str | int]:
        return {"StartStop": 0}

    def build_resume(self) -> dict[str, str | int]:
        return {"StartStop": 1}

    def build_open_door(self) -> dict[str, str | int]:
        return {"OpenDoorOpt": 7}

    def build_checkup(self) -> dict[str, str | int]:
        return {"StartCheckUp": 1}

    def build_checkup_reset(self) -> dict[str, str | int]:
        return {"Write": 1, "StartStop": 0, "Program": 11}


def get_dishwasher_command_builder(
    interface_type: str | None,
) -> DishwasherCommandBuilder:
    """Return command builder instance matching the dishwasher interface type."""
    od_supported = is_open_door_supported(interface_type)
    if is_legacy_dishwasher(interface_type):
        return LegacyTouchDishwasherCommandBuilder(open_door_supported=od_supported)
    return ModernDishwasherCommandBuilder(open_door_supported=od_supported)
