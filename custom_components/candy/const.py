"""Constants for the Candy integration."""

DOMAIN = "candy"
PLATFORMS = ["sensor", "binary_sensor", "select", "number", "button", "switch", "light"]

DATA_KEY_COORDINATOR = "coordinator"
DATA_KEY_STATS_COORDINATOR = "stats_coordinator"
DATA_KEY_CLIENT = "client"
DATA_KEY_WRITE_PENDING = "write_pending"
DATA_KEY_MAINT_UNSUB = "maint_unsub"
DATA_KEY_CHECKUP_UNSUB = "checkup_unsub"
DATA_KEY_STATS_REFRESH_UNSUB = "stats_refresh_unsub"

CONF_INTEGRATION_TITLE = "Candy"
CONF_KEY_USE_ENCRYPTION = "use_encryption"

# Integration mode stored in config entry
CONF_KEY_MODE = "mode"
MODE_READ_ONLY = "read_only"
MODE_FULL_CONTROL = "full_control"

# Config entry fields populated from Simply-Fi cloud in Full Control mode
CONF_KEY_MAC_ADDRESS = "mac_address"
CONF_KEY_PROGRAMS = "simply_fi_programs"
CONF_KEY_DOWNLOADABLE_PROGRAMS = "simply_fi_downloadable_programs"
CONF_KEY_DEVICE_MODEL = "device_model"
CONF_KEY_SERIAL_NUMBER = "serial_number"
CONF_KEY_PURCHASE_DATE = "purchase_date"
CONF_KEY_PROGRAM_LANGUAGE = "program_language"

PROGRAM_LANGUAGES: dict[str, str] = {
    "bg": "Български",
    "cs": "Čeština",
    "de": "Deutsch",
    "el": "Ελληνικά",
    "en": "English",
    "es": "Español",
    "fr": "Français",
    "hr": "Hrvatski",
    "it": "Italiano",
    "nl": "Nederlands",
    "pl": "Polski",
    "pt": "Português",
    "ro": "Română",
    "ru": "Русский",
    "sk": "Slovenčina",
    "sl": "Slovenščina",
    "sr": "Српски",
    "tr": "Türkçe",
}

UNIQUE_ID_WASHING_MACHINE = "{0}-washing_machine"
UNIQUE_ID_WASH_PROGRAM = "{0}-wash_program"
UNIQUE_ID_WASH_CYCLE_STATUS = "{0}-wash_cycle_status"
UNIQUE_ID_WASH_REMAINING_TIME = "{0}-wash_remaining_time"
UNIQUE_ID_WASH_TEMPERATURE = "{0}-wash_temperature"
UNIQUE_ID_WASH_SPIN_SPEED = "{0}-wash_spin_speed"
UNIQUE_ID_WASH_FILL_PERCENT = "{0}-wash_fill_percent"
UNIQUE_ID_WASH_ERROR = "{0}-wash_error"
UNIQUE_ID_WASH_DELAY = "{0}-wash_delay"
UNIQUE_ID_WASH_NTC_WATER = "{0}-wash_ntc_water"
UNIQUE_ID_WASH_NTC_DRUM = "{0}-wash_ntc_drum"
UNIQUE_ID_WASH_MOTOR_FREQ = "{0}-wash_motor_freq"
UNIQUE_ID_WASH_TOTAL_CYCLES = "{0}-wash_total_cycles"
UNIQUE_ID_WASH_SOIL_LEVEL = "{0}-wash_soil_level"
UNIQUE_ID_WASH_DRY_PHASE = "{0}-wash_dry_phase"
UNIQUE_ID_WASH_CHECKUP_RESULT = "{0}-wash_checkup_result"
UNIQUE_ID_WASH_LAST_CHECKUP = "{0}-wash_last_checkup"
UNIQUE_ID_WASH_REMOTE_CONTROL = "{0}-wash_remote_control"

SOIL_LABELS: dict[int, str] = {1: "low", 2: "normal", 3: "high"}
SOIL_LABELS_REVERSE: dict[str, int] = {v: k for k, v in SOIL_LABELS.items()}

# Raw values for the "Dry"/"DryT" field; index 4 is intentionally absent (see PR description).
DRY_LABELS: dict[int, str] = {
    1: "extra_dry",
    2: "iron_dry",
    3: "cupboard_dry",
    5: "time_120",
    6: "time_90",
    7: "time_60",
    8: "time_30",
}
DRY_LABELS_REVERSE: dict[str, int] = {v: k for k, v in DRY_LABELS.items()}

# Additive minutes when steam (steam=5) is enabled, keyed by program steam_type.
# Source: APK assets/assisted/full_remaining_time_value_v11.json, programType "Wash + Steam".
STEAM_DURATION_OFFSETS: dict[str, int] = {"C": 37, "S": 29, "R": 35}
UNIQUE_ID_WASH_ESTIMATED_DURATION = "{0}-wash_estimated_duration"
UNIQUE_ID_WASH_SCHEDULED_START = "{0}-wash_scheduled_start"
UNIQUE_ID_WASH_SCHEDULED_FINISH = "{0}-wash_scheduled_finish"
UNIQUE_ID_WASH_LIQUID_DETERGENT = "{0}-wash_liquid_detergent"
UNIQUE_ID_WASH_POWDER_DETERGENT = "{0}-wash_powder_detergent"
UNIQUE_ID_WASH_CYCLE_CAPACITY = "{0}-wash_cycle_capacity"
UNIQUE_ID_WASH_PURCHASE_DATE = "{0}-wash_purchase_date"

CONF_KEY_IS_WASHING_MACHINE = "is_washing_machine"
CONF_KEY_INTERFACE_TYPE = "interface_type"

CONF_KEY_MAINTENANCE_ENABLED = "maintenance_enabled"
CONF_KEY_MAINTENANCE_LIMESCALE_ENABLED = "maintenance_limescale_enabled"
CONF_KEY_MAINTENANCE_FILTER_ENABLED = "maintenance_filter_enabled"
CONF_KEY_WATER_HARDNESS = "water_hardness"
CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP = "maintenance_last_full_checkup"
CONF_KEY_MAINTENANCE_LAST_LIMESCALE = "maintenance_last_limescale"
CONF_KEY_MAINTENANCE_LAST_FILTER = "maintenance_last_filter"

CONF_KEY_CHECKUP_ENABLED = "checkup_enabled"
CONF_KEY_CHECKUP_SCHEDULE = "checkup_schedule"
CONF_KEY_CHECKUP_LAST_DATE = "checkup_last_date"
CONF_KEY_CHECKUP_LAST_RESULT = "checkup_last_result"

CHECKUP_SCHEDULE_EVERY_CYCLE = 0
CHECKUP_SCHEDULE_WEEKLY = 1
CHECKUP_SCHEDULE_MONTHLY = 2

MAINTENANCE_FULL_CHECKUP_THRESHOLD = 100
MAINTENANCE_FILTER_THRESHOLD = 100
MAINTENANCE_HARDNESS_THRESHOLDS: list[int] = [110, 105, 100, 95, 90, 85]
MAINTENANCE_HARDNESS_LABELS: list[str] = [
    "very_soft",
    "soft",
    "medium",
    "moderately_hard",
    "hard",
    "very_hard",
]

UNIQUE_ID_WASH_MAINT_FULL_CHECKUP = "{0}-wash_maint_full_checkup"
UNIQUE_ID_WASH_MAINT_LIMESCALE = "{0}-wash_maint_limescale"
UNIQUE_ID_WASH_MAINT_FILTER = "{0}-wash_maint_filter"
UNIQUE_ID_WASH_MAINT_FULL_CHECKUP_BUTTON = "{0}-wash_maint_full_checkup_reset"
UNIQUE_ID_WASH_MAINT_LIMESCALE_BUTTON = "{0}-wash_maint_limescale_reset"
UNIQUE_ID_WASH_MAINT_FILTER_BUTTON = "{0}-wash_maint_filter_reset"

NOTIF_ID_MAINT_FULL_CHECKUP = "candy_{0}_maint_full_checkup"
NOTIF_ID_MAINT_LIMESCALE = "candy_{0}_maint_limescale"
NOTIF_ID_MAINT_FILTER = "candy_{0}_maint_filter"

UNIQUE_ID_WASH_FULL_CHECKUP_BUTTON = "{0}-wash_full_checkup_button"
NOTIF_ID_FULL_CHECKUP = "candy_{0}_full_checkup"

UNIQUE_ID_WASH_LIMESCALE_BUTTON = "{0}-wash_limescale_button"
NOTIF_ID_LIMESCALE = "candy_{0}_limescale"

UNIQUE_ID_WASH_PROGRAM_SELECT = "{0}-wash_program_select"
UNIQUE_ID_WASH_PROGRAM_DESCRIPTION = "{0}-wash_program_description"
UNIQUE_ID_WASH_TEMP_SELECT = "{0}-wash_temp_select"
UNIQUE_ID_WASH_SPIN_SELECT = "{0}-wash_spin_select"
UNIQUE_ID_WASH_SOIL_SELECT = "{0}-wash_soil_select"
UNIQUE_ID_WASH_DRY_SELECT = "{0}-wash_dry_select"
UNIQUE_ID_WASH_DELAY_NUMBER = "{0}-wash_delay_number"
UNIQUE_ID_WASH_START_BUTTON = "{0}-wash_start_button"
UNIQUE_ID_WASH_PAUSE_BUTTON = "{0}-wash_pause_button"
UNIQUE_ID_WASH_STOP_BUTTON = "{0}-wash_stop_button"
UNIQUE_ID_WASH_STEAM_SWITCH = "{0}-wash_steam_switch"
UNIQUE_ID_WASH_NFC_SWITCH = "{0}-wash_nfc_switch"
UNIQUE_ID_WASH_OPTION_PREWASH = "{0}-wash_option_prewash"
UNIQUE_ID_WASH_OPTION_HYGIENE = "{0}-wash_option_hygiene"
UNIQUE_ID_WASH_OPTION_ANTICREASE = "{0}-wash_option_anticrease"
UNIQUE_ID_WASH_OPTION_GOODNIGHT = "{0}-wash_option_goodnight"
UNIQUE_ID_WASH_OPTION_RINSE_1 = "{0}-wash_option_rinse_1"
UNIQUE_ID_WASH_OPTION_RINSE_2 = "{0}-wash_option_rinse_2"
UNIQUE_ID_WASH_OPTION_RINSE_3 = "{0}-wash_option_rinse_3"
UNIQUE_ID_WASH_OPTION_ACQUAPLUS = "{0}-wash_option_acquaplus"

# (bitmask, translation_key, unique_id_suffix, english_name)
WASH_OPTIONS: list[tuple[int, str, str, str]] = [
    (1, "wash_option_prewash", "wash_option_prewash", "Prewash"),
    (2, "wash_option_hygiene", "wash_option_hygiene", "Hygiene"),
    (4, "wash_option_anticrease", "wash_option_anticrease", "Anti-crease"),
    (8, "wash_option_goodnight", "wash_option_goodnight", "Good Night"),
    (16, "wash_option_rinse_1", "wash_option_rinse_1", "Extra rinse +1"),
    (32, "wash_option_rinse_2", "wash_option_rinse_2", "Extra rinse +2"),
    (64, "wash_option_rinse_3", "wash_option_rinse_3", "Extra rinse +3"),
    (128, "wash_option_acquaplus", "wash_option_acquaplus", "AquaPlus"),
]

UNIQUE_ID_TUMBLE_DRYER = "{0}-tumble_dryer"
UNIQUE_ID_TUMBLE_PROGRAM = "{0}-tumble_program"
UNIQUE_ID_TUMBLE_CYCLE_STATUS = "{0}-tumble_cycle_status"
UNIQUE_ID_TUMBLE_REMAINING_TIME = "{0}-tumble_remaining_time"

UNIQUE_ID_OVEN = "{0}-oven"
UNIQUE_ID_OVEN_PROGRAM = "{0}-oven_program"
UNIQUE_ID_OVEN_TEMP = "{0}-oven-temp"
UNIQUE_ID_DISHWASHER = "{0}-dishwasher"
UNIQUE_ID_DISHWASHER_PROGRAM = "{0}-dishwasher_program"
UNIQUE_ID_DISHWASHER_REMAINING_TIME = "{0}-dishwasher_remaining_time"

UNIQUE_ID_WINE_COOLER = "{0}-wine_cooler"
UNIQUE_ID_WINE_COOLER_PROGRAM = "{0}-wine_cooler_program"
UNIQUE_ID_WINE_COOLER_TEMP = "{0}-wine_cooler_temp"
UNIQUE_ID_WINE_COOLER_LIGHT = "{0}-wine_cooler_light"
UNIQUE_ID_WINE_COOLER_LIGHT_ENTITY = "{0}-wine_cooler_light_control"
UNIQUE_ID_WINE_COOLER_ERROR = "{0}-wine_cooler_error"
UNIQUE_ID_WINE_COOLER_TEMP_DOWN = "{0}-wine_cooler_temp_down"
UNIQUE_ID_WINE_COOLER_PROGRAM_DOWN = "{0}-wine_cooler_program_down"

DEVICE_NAME_WASHING_MACHINE = "Washing machine"
DEVICE_NAME_TUMBLE_DRYER = "Tumble dryer"
DEVICE_NAME_OVEN = "Oven"
DEVICE_NAME_DISHWASHER = "Dishwasher"
DEVICE_NAME_WINE_COOLER = "Wine cooler"

SUGGESTED_AREA_BATHROOM = "Bathroom"
SUGGESTED_AREA_KITCHEN = "Kitchen"
SUGGESTED_AREA_CELLAR = "Cellar"
