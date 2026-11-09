# Candy Home Assistant Component

[![Run tests](https://github.com/bigmoby/home-assistant-candy/actions/workflows/lint.yml/badge.svg)](https://github.com/bigmoby/home-assistant-candy/actions/workflows/lint.yml)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

[![Donate](https://img.shields.io/badge/donate-BuyMeCoffee-yellow.svg)](https://www.buymeacoffee.com/bigmoby)

A highly optimized custom component for [Home Assistant](https://homeassistant.io) that effortlessly integrates Candy, Haier, and Simply-Fi connected home appliances.

Fully compliant with strictly-typed Home Assistant (>= 2024.x) development standards, it features **Zero-Configuration Automatic Decryption**—making setup purely plug-and-play.

---

## ✨ Features

- **Supported appliances**:
  - 🧺 Washing Machine — with optional **Full Remote Control** (see below)
  - 🔄 Washer Dryer combo — with optional **Full Remote Control** (see below)
  - 🌫️ Tumble Dryer - with optional **Full Remote Control** (see below)
  - 🔪 Dishwasher
  - 🍳 Oven
  - 🍷 Wine Cooler / Cellar
- **Full Remote Control:** Complete interactive control panel for **washing machines**, **washer-dryer combos** and **tumble dryers** (see the [compatibility matrix](#compatibility-note) for supported and tested models). Select localized programs, adjust wash & dry parameters (temp, spin speed, soil level, drying mode), start/pause/stop cycles, and track remote status.
- **Zero-Config Decryption:** Say goodbye to manually extracting encryption keys. This integration boasts a natively built-in *sliding-window/known-plaintext* algorithm that unlocks your device seamlessly in fractions of a second during setup.
- **Strict HA Compatibility:** Follows the rigorous MyPy styling standards enforced by Home Assistant 2025.
- Uses the local device API for real-time responsiveness. 
- Creates dedicated, native semantic sensors (e.g., remaining time, current status, machine cycle) and exposes granular information cleanly as sensor attributes.
- **Intelligent Fault Notifications & Error Handling:** Intercepts appliance error codes and shows persistent Home Assistant notifications with authentic vendor troubleshooting steps
- **Automated Maintenance Notifications:** Show reminders when check-up, descaling, or filter cleaning are due, provides preparation advice on cycle start, and automatically resets baselines upon completion.

---

## 🎛️ Full Control Features

Full Control mode turns the integration into an interactive remote panel for **washing machines**, **washer-dryer combos** and **tumble dryers**, matching and enhancing the official Simply-Fi mobile app experience directly within Home Assistant.

*Washing Machine Example*
<p float="left">
  <img src="docs/images/dashboard_washing_machine.png" width="300" />
  <img src="docs/images/dashboard_maintenance.png" width="300" /> 
</p>

### What it provides

- **Complete Cycle Control:** Select official localized programs, adjust temperature, spin speed, soil level, or drying targets (dryness level, timed drying), and trigger Start, Pause, Resume, Stop, or Cancel Anti-Crease.
- **Proactive Maintenance & Diagnostics:** Cycle-based reminders for washing machines (Full Check-up, Limescale cleaning, Filter care), live hardware alerts for tumble dryers (lint filter and water tank full), and electronic self check-up.
- **Vendor Troubleshooting:** Automatic Home Assistant notifications with authentic step-by-step guidance when the appliance encounters a fault.
- **Ready-to-Use Dashboards:** Pre-built Lovelace cards using [Mushroom Cards](https://github.com/piitaya/lovelace-mushroom) ready to control your appliance (see [`dashboard/`](dashboard/README.md)).
- **Smart Safety Gating:** Automatically disables controls when manual or local operation takes precedence.

📖 **For detailed instructions, appliance workflows, and safety rules, see the [Remote Control Guide](docs/remote-control.md).**


### Key Improvements Over the Official App

- **Direct Dashboard Control:** Monitor and run cycles directly from Home Assistant without opening the mobile app.
- **Faster Responsiveness:** Fast 20-second wake-up detection when the machine turns on, plus immediate state refresh (~5s) after sending commands.
- **Persistent Error Guidance:** Troubleshooting instructions appear right in Home Assistant and clear automatically once the machine fault is resolved.
- **Accurate Cycle Tracking:** Fixes the vendor app's 8-bit counter overflow bug (which resets total wash counts after 256 cycles) and provides precise finish time estimates.

### Compatibility Note

The remote control functionality has been implemented for several physical appliances. See the table below.

| Appliance | Interface / Family | Tested | Notes |
|---|---|---|---|
| Washing Machine | Candy RapidÓ (`RAPIDO`, `RAPIDO_4DIG_STM_NEL`) | Yes | Reference hardware (`RO41274DWMSE/1-S`).|
| Washing Machine / Washer Dryer | Hoover AXI (`red_devil_axi*`, `hwash700`) | Yes | Reference hardware (`AWMPD 410LH8/1-S` and `AWDPD4138LHR/1`). |
| Tumble Dryer | DualTech (`TD_DIGIT_*`, `TD_LED_*`, `3D_DUAL`) | Yes | Reference hardware (`GVS H9A2TCE-80`). |
| Washing Machine / Washer Dryer | DualTech (`3D_DUAL`, `4D_DUAL`, `DUALTECH`) | Yes | Tested on `3D_DUAL` hardware. Remote pause and stats counters are unsupported by hardware. |
| Washer Dryer | Candy RapidÓ (`ROW` series) | No | Shares RapidÓ protocol with generic washer-dryer engine. |
| Washing Machine / Washer Dryer | Candy Bianca (`BIANCA`, `BWD` series) | No | Implemented from cloud catalog and protocol specifications. Remote pause/resume is unsupported by Bianca hardware. |
| Washing Machine | Candy Smart Pro / Hoover H-WASH 300 / X-Care (`SMARTPRO`, `HWASH300`, `XCARE`) | No | Implemented from protocol specifications. |

Other appliance series may not behave correctly. If you encounter issues or unexpected behaviour, please open an [Issue](https://github.com/bigmoby/home-assistant-candy/issues) and attach the output of the `simplyfi.py`  tool. Feedback is very welcome.

---

## 🛠️ Installation

### Method 1: HACS (Recommended)
1. Install [HACS](https://hacs.xyz/).
2. Go to the HACS integrations page, search for `Candy Simply-Fi` and download it.
3. Restart Home Assistant.
4. Go to **Settings > Devices & Services**, click **Add integration** and search for `Candy`.
5. Enter the **IP Address** of your appliance.
6. If available, you can choose to enable Full Control of your appliance.
    - **One-Time Cloud Sign-In:** Enter your Simply-Fi credentials once to download your device's program catalog and encryption key. Credentials are discarded immediately and never stored.
    - **Customize:** Choose your preferred display language for program names and descriptions (10 languages available), and optionally configure maintenance thresholds.
6. The integration will automatically authenticate, decrypt if necessary, and assign the appliance to your dashboard!

### Method 2: Manual
1. Copy the `custom_components/candy` folder into your Home Assistant's `custom_components` directory.
2. Restart Home Assistant and add `Candy` via the UI.

---

## 🚀 Built-in Debugging Tool (`simplyfi.py` v2.0.0)

Want to troubleshoot network reachability, verify your 16-character encryption key, test remote control readiness, or inspect raw and decoded telemetry from your appliance? We've got you covered:

Inside the `tools/` folder, you'll find the standalone `simplyfi.py` diagnostic suite. It runs from any terminal independently from Home Assistant:

```bash
# 1. Recover your 16-character XOR key automatically
python3 tools/simplyfi.py <YOUR_APPLIANCE_IP> getkey

# 2. Inspect real-time decoded telemetry in a human-readable table
python3 tools/simplyfi.py <YOUR_APPLIANCE_IP> inspect

# 3. Audit remote control prerequisites and physical dial knob position
python3 tools/simplyfi.py <YOUR_APPLIANCE_IP> remote

# 4. Fetch cycle statistics via the 2-step handshake (prepare + fetch)
python3 tools/simplyfi.py <YOUR_APPLIANCE_IP> stats

# 5. Generate a complete, sanitized diagnostic report for GitHub issues
python3 tools/simplyfi.py <YOUR_APPLIANCE_IP> diagnose
```

Supports all 10 appliance families: Washing Machines, Washer-Dryers, Tumble Dryers, Dishwashers, Ovens, Wine Coolers, Refrigerators/Freezers, Kitchen Hoods, Induction/Gas Cooktops, and Robot Vacuums. For full details and command grammar, see [`tools/agents.md`](tools/agents.md).

---

## 🔍 Finding Your Appliance on the Network

Not sure what IP address your Candy appliance has? Run this one-liner from any terminal on the **same local network** as your device.

> **Prerequisite:** replace `192.168.1` with your actual subnet if different (check your router settings).

```bash
# Scan the entire subnet for Candy Simply-Fi appliances
for i in $(seq 1 254); do
  result=$(curl -s --max-time 1 "http://192.168.1.$i/http-read.json?encrypted=0" 2>/dev/null)
  [ -n "$result" ] && echo "192.168.1.$i: $result"
done
```

The script probes every host on the subnet for the Candy local API endpoint. Any appliance that responds will print its IP address alongside its raw JSON status — for example:

```
192.168.1.79: { "statusLavatrice": { "WiFiStatus": "1", ... } }
```

Use that IP when configuring the integration in Home Assistant.

---

## 🙋 My device isn't supported. Can you help?

Absolutely! If you have an appliance that is not supported yet (e.g. Refrigerator, Hood, Cooktop, or a new Dishwasher/Oven variant), or you notice odd readings, please open a new [Issue](https://github.com/bigmoby/home-assistant-candy/issues) with the following information:

1. Run the diagnostic tool (sanitized by default; use `--raw` if unredacted output is needed):
   ```bash
   python3 tools/simplyfi.py <YOUR_APPLIANCE_IP> diagnose
   ```
2. Paste the generated Markdown output directly into your issue. It automatically includes sanitized device configuration, decoded telemetry registers, raw JSON payloads, and cycle counters while redacting sensitive Wi-Fi credentials, MAC addresses, and encryption keys.

---

## 👨‍💻 Develop

If you want to contribute, test features or build new integrations, the environment is fully automated.

### Quick Start
Setup the development environment using our rapid bash scripts:
```bash
make setup
```

### Available Commands
Use the `Makefile` for all standard operations:
```bash
make setup         # Setup development environment and venv
make check         # Run all checks (lint + test)
make lint          # Run ruff spacing and mypy static type checking
make format        # Format python code to meet standard
make test          # Run tests with coverage
make clean         # Deep clean cache folders
```

### Development Tools (Pre-Commit)
We rely on Github rigorous standards to maintain 100% Home Assistant compliance.
You can install our native pre-commit hooks that format and protect every single push:
```bash
make pre-commit-install
```

---

## Sponsor

Please, if You want support this kind of projects:

<a href="https://www.buymeacoffee.com/bigmoby" target="_blank"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" alt="Buy Me A Coffee" style="height: 41px !important;width: 174px !important;box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;-webkit-box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;" ></a>

Many Thanks,

Fabio Mauro
