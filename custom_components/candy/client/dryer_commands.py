"""Command builders for Candy and Hoover tumble dryers."""

from __future__ import annotations

from abc import ABC, abstractmethod


class DryerCommandBuilder(ABC):
    """Abstract interface for tumble dryer write command builders."""

    @abstractmethod
    def build_standard_start(
        self, selector_position: int, dry_level: int
    ) -> dict[str, str | int]:
        """Build parameters to start a standard drying cycle."""

    @abstractmethod
    def build_timed_start(
        self, selector_position: int, time_minutes: int
    ) -> dict[str, str | int]:
        """Build parameters to start a timed drying cycle."""

    @abstractmethod
    def build_rapid_start(
        self, selector_position: int, rapid_level: int
    ) -> dict[str, str | int]:
        """Build parameters to start a rapid drying cycle."""

    @abstractmethod
    def build_rapid_delay_start(
        self, selector_position: int, rapid_level: int, delay_minutes: int
    ) -> dict[str, str | int]:
        """Build parameters to schedule a delayed start for a rapid cycle."""

    @abstractmethod
    def build_delay_start(
        self, selector_position: int, dry_level: int, delay_minutes: int
    ) -> dict[str, str | int]:
        """Build parameters to schedule a delayed start for a standard cycle."""

    @abstractmethod
    def build_timed_delay_start(
        self, selector_position: int, time_minutes: int, delay_minutes: int
    ) -> dict[str, str | int]:
        """Build parameters to schedule a delayed start for a timed cycle."""

    @abstractmethod
    def build_stop(self, current_program: int) -> dict[str, str | int]:
        """Build parameters to stop or cancel the running cycle."""

    @abstractmethod
    def build_pause(self) -> dict[str, str | int]:
        """Build parameters to pause the active cycle."""

    @abstractmethod
    def build_resume(self) -> dict[str, str | int]:
        """Build parameters to resume a paused cycle."""

    @abstractmethod
    def build_cancel_anticrease(self) -> dict[str, str | int]:
        """Build parameters to cancel post-cycle anti-crease tumbling."""

    @abstractmethod
    def build_checkup_start(self) -> dict[str, str | int]:
        """Build parameters to start appliance diagnostic checkup."""

    @abstractmethod
    def build_checkup_reset(self) -> dict[str, str | int]:
        """Build parameters to reset appliance diagnostic checkup."""

    @abstractmethod
    def build_reset_warnings(self) -> dict[str, str | int]:
        """Build parameters to clear warning alerts on the appliance."""


class DualTechDryerCommandBuilder(DryerCommandBuilder):
    """Command builder for DualTech tumble dryers (TD_DIGIT_*, TD_LED_*)."""

    def build_standard_start(
        self, selector_position: int, dry_level: int
    ) -> dict[str, str | int]:
        return {
            "Write": 1,
            "Pa": 0,
            "Sel": 0,
            "PrNm": selector_position,
            "DryLev": dry_level,
            "StSt": 1,
        }

    def build_timed_start(
        self, selector_position: int, time_minutes: int
    ) -> dict[str, str | int]:
        return {
            "Write": 1,
            "Pa": 0,
            "Sel": 0,
            "PrNm": selector_position,
            "Time": time_minutes,
            "StSt": 1,
        }

    def build_rapid_start(
        self, selector_position: int, rapid_level: int
    ) -> dict[str, str | int]:
        return {
            "Write": 1,
            "Pa": 0,
            "Sel": 0,
            "PrNm": selector_position,
            "Rapido": rapid_level,
            "StSt": 1,
        }

    def build_rapid_delay_start(
        self, selector_position: int, rapid_level: int, delay_minutes: int
    ) -> dict[str, str | int]:
        return {
            "Write": 1,
            "Pa": 0,
            "Sel": 0,
            "PrNm": selector_position,
            "Rapido": rapid_level,
            "DelMd": 1,
            "DelVl": delay_minutes,
        }

    def build_delay_start(
        self, selector_position: int, dry_level: int, delay_minutes: int
    ) -> dict[str, str | int]:
        return {
            "Write": 1,
            "Pa": 0,
            "Sel": 0,
            "PrNm": selector_position,
            "DryLev": dry_level,
            "DelMd": 1,
            "DelVl": delay_minutes,
        }

    def build_timed_delay_start(
        self, selector_position: int, time_minutes: int, delay_minutes: int
    ) -> dict[str, str | int]:
        return {
            "Write": 1,
            "Pa": 0,
            "Sel": 0,
            "PrNm": selector_position,
            "Time": time_minutes,
            "DelMd": 1,
            "DelVl": delay_minutes,
        }

    def build_stop(self, current_program: int) -> dict[str, str | int]:
        return {
            "Write": 1,
            "StSt": 0,
            "DelMd": 0,
            "PrNm": current_program,
        }

    def build_pause(self) -> dict[str, str | int]:
        return {
            "Write": 1,
            "SetPauseDryMgr": 1,
        }

    def build_resume(self) -> dict[str, str | int]:
        return {
            "Write": 1,
            "SetRestartDryMgr": 1,
        }

    def build_cancel_anticrease(self) -> dict[str, str | int]:
        return {
            "Write": 1,
            "DontTumbling": 1,
        }

    def build_checkup_start(self) -> dict[str, str | int]:
        return {
            "Write": 1,
            "CheckUpState": 1,
        }

    def build_checkup_reset(self) -> dict[str, str | int]:
        return {
            "Write": 1,
            "CheckUpState": 0,
        }

    def build_reset_warnings(self) -> dict[str, str | int]:
        return {
            "Write": 1,
            "ResetWarnings": 1,
        }


def is_dualtech_dryer_interface(interface_type: str | None) -> bool:
    """Return True if interface_type corresponds to a DualTech tumble dryer."""
    if not interface_type:
        return False
    upper = interface_type.upper()
    return upper.startswith(("TD_DIGIT_", "TD_LED_")) or "DUAL" in upper


def get_dryer_command_builder(interface_type: str) -> DryerCommandBuilder:
    """Return command builder instance matching the tumble dryer interface type."""
    if is_dualtech_dryer_interface(interface_type):
        return DualTechDryerCommandBuilder()
    raise ValueError(f"Unsupported tumble dryer interface type: {interface_type}")
