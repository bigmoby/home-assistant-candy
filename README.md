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
  - 🌫️ Tumble Dryer
  - 🔪 Dishwasher
  - 🍳 Oven
  - 🍷 Wine Cooler / Cellar
- **Zero-Config Decryption:** Say goodbye to manually extracting encryption keys. This integration boasts a natively built-in *sliding-window/known-plaintext* algorithm that unlocks your device seamlessly in fractions of a second during setup.
- **Strict HA Compatibility:** Follows the rigorous MyPy styling standards enforced by Home Assistant 2025.
- Uses the local device API for real-time responsiveness. 
- Creates dedicated, native semantic sensors (e.g., remaining time, current status, machine cycle) and exposes granular information cleanly as sensor attributes.
- **Intelligent Fault Notifications & Error Handling:** Intercepts appliance error codes and shows persistent Home Assistant notifications with authentic vendor troubleshooting steps
- **Automated Maintenance Notifications:** Show reminders when check-up, descaling, or filter cleaning are due, provides preparation advice on cycle start, and automatically resets baselines upon completion.

---

## 🧺 Washing Machine — Full Control

Full Control mode turns the integration into a complete remote panel, going beyond status monitoring to let you program, start, and track your washing machine from Home Assistant. The protocol was reverse-engineered from the official Candy/Simply-Fi app, and the feature set matches everything the mobile app offers.

<p float="left">
  <img src="docs//images/dashboard_washing_machine.png" width="300" />
  <img src="docs//images/dashboard_maintenance.png" width="300" /> 
</p>

### How it works

At setup, you choose between **Read-Only** (sensors only) and **Full Control**. Full Control prompts for your Simply-Fi cloud credentials once — they are used to download the program catalog, encryption key, and device metadata, then immediately discarded and never stored. Program names, descriptions, and option labels come directly from the official app, available in 17 languages, and default to your Home Assistant language.

### Setup flow

1. Device is discovered automatically on the local network (or enter the IP manually).
2. Choose mode: **Read-Only** or **Full Control**.
3. *(Full Control)* Enter your Simply-Fi email and password — programs and device info are downloaded, credentials are discarded.
4. Select the display language for program names and description, pick your favourite language indipendently the Home Assistant language.
5. Optionally enable maintenance cycle counters (check-up, limescale, filter) and set water hardness.
6. Optionally enable automatic self-diagnostic scheduling (every cycle / weekly / monthly).

### What you get

**Control entities:** program selector (with localized program names and descriptions), temperature, spin speed, soil level, delay start, extra switches (Prewash, Hygiene, Steam and so on), and Start / Pause / Stop buttons.

**Maintenance & diagnostics:** mirrors the Candy app's built-in reminders. 
Check-up, limescale, and filter counters with configurable water hardness thresholds; self-diagnostic result sensor and last check-up timestamp. When counters reach their thresholds, persistent notifications prompt you to perform maintenance. Starting a diagnostic or limescale routine posts preparation instructions, and completing the cycle automatically resets its counter baseline and dismisses the reminder (manual reset buttons are also available as fallback; the filter counter is cleaned manually and reset via button).

**Proactive error handling:** monitors washing machine fault codes in real time and posts persistent Home Assistant notifications with localized vendor troubleshooting instructions (such as checking water taps, unblocking the pump filter, or adjusting laundry load balance). Notifications update dynamically if codes change and dismiss automatically when the appliance clears the error.

**Remote Control status:** a dedicated sensor tracks whether the machine currently accepts remote commands, and disables every control entity while it doesn't. See [`docs/remote-control.md`](docs/remote-control.md) for details.

### Improvements over the official app

- **Proactive troubleshooting & reminders:** Home Assistant immediately presents vendor troubleshooting guidance on errors and clears alerts when resolved, plus manages the full maintenance notification lifecycle without opening the Simply-Fi app.

- **Faster feedback:** every write command locks the controls, waits for the machine to process it, then forces an immediate refresh — so the dashboard reflects the new state in a few seconds instead of waiting for the next 60-second poll.
- **Faster wake-up:** while the machine is off, Home Assistant polls every 20 seconds instead of 60, so it notices when the machine turns back on much sooner.
- **Accurate end-time calculation:** The integration computes an accurate scheduled finish timestamp, accounting for all variables.
- **Always-on visibility:** Machine state and controls are available on your dashboard without opening the app.
- **Correct lifetime cycle count:** the official app derives total wash cycles from per-program
  counters that are 8-bit and silently wrap at 256 — after enough washes on one program its
  total jumps *backwards* by 256. This integration reads the wide temperature counters instead,
  so the total keeps climbing correctly.

### Dashboard cards

Ready-made Lovelace cards are included in the [`dashboard/`](dashboard/) folder. 

[Mushroom](https://github.com/piitaya/lovelace-mushroom) custom card is required.

- [`washing-machine.yaml`](dashboard/washing-machine.yaml) — main control card: status, running info, program selector, options, start/pause/stop buttons, and scheduled start/finish times.
- [`maintenance.yaml`](dashboard/maintenance.yaml) — maintenance card: check-up, limescale, and filter counters with reset buttons and check-up result.

To use them, copy the card YAML into a new manual card in your Lovelace dashboard and replace every occurrence of `<machine_name>` with your own machine's entity ID prefix (e.g. `my_washing_machine`).

### Compatibility Note

Full functionality has been tested on the **RAPIDO** series. Other washing machine series may behave differently. If you encounter issues or unexpected behaviour, please share your findings in the [Discussions](https://github.com/bigmoby/home-assistant-candy/discussions/categories/device-support-improvements) section or open an Issue — feedback is very welcome.

---

## 🛠️ Installation

### Method 1: HACS (Recommended)
1. Install [HACS](https://hacs.xyz/).
2. Go to the HACS integrations page, search for `Candy Simply-Fi` and download it.
3. Restart Home Assistant.
4. Go to **Settings > Devices & Services**, click **Add integration** and search for `Candy`.
5. Enter the **IP Address** of your appliance.
6. The integration will automatically authenticate, decrypt if necessary, and assign the appliance to your dashboard!

### Method 2: Manual
1. Copy the `custom_components/candy` folder into your Home Assistant's `custom_components` directory.
2. Restart Home Assistant and add `Candy` via the UI.

---

## 🚀 Built-in Debugging Tool

Are you a developer, or do you want to inspect what raw JSON your specific appliance is throwing over your network? We've got you covered:

Inside the `tools/` folder of this repository, you'll find the standalone `simplyfi.py` script. You can run it effortlessly from any terminal independent from Home Assistant!

```bash
python3 tools/simplyfi.py <YOUR_APPLIANCE_IP_ADDRESS>
```

This is incredibly useful for validating your appliance network reachability or diagnosing new payloads.

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

Absolutely! If you have an appliance that is not supported yet (or you notice odd readings), head over to the [Discussions section](https://github.com/bigmoby/home-assistant-candy/discussions/categories/device-support-improvements). Open a new thread or comment to an existing one with the following information:

1. The raw status API response of your device (Please use the provided `tools/simplyfi.py` inside this repo to query your IP and get the full JSON).
2. A brief, intuitive explanation of what you think each field correlates to based on the machine's state (e.g., _The `SpinSp` field reads "8", meaning Spin speed 800 RPM in my model_).

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
