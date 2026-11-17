# Remote Control Guide

This guide explains how to use **Full Control mode** in Home Assistant to monitor, configure, and operate your Candy and Hoover connected appliances.

---

## Table of Contents

- [Quick Start: Enabling Remote Control](#quick-start-enabling-remote-control)
- [How Remote Control Works](#how-remote-control-works)
  - [Safety & Physical Dial Priority](#safety--physical-dial-priority)
- [Common Cycle Controls](#common-cycle-controls)
- [Appliance-Specific Controls](#appliance-specific-controls)
  - [Washing Machines](#washing-machines)
  - [Washer-Dryer Combos](#washer-dryer-combos)
  - [Tumble Dryers](#tumble-dryers)
- [Maintenance & Care](#maintenance--care)
  - [Washing Machines & Washer-Dryers](#washing-machines--washer-dryers)
  - [Tumble Dryers](#tumble-dryers-1)
- [Troubleshooting & Fault Alerts](#troubleshooting--fault-alerts)
- [Dashboards & Automations](#dashboards--automations)
  - [Ready-Made Dashboards](#ready-made-dashboards)
  - [Automations](#automations)
- [Frequently Asked Questions (FAQ)](#frequently-asked-questions-faq)

---

## Quick Start: Enabling Remote Control

To control your appliance from Home Assistant, remote operation must be activated on the physical machine:

1. **Prepare the machine:** Load your laundry, add detergent, and **ensure the door is firmly closed**.
2. **Turn on the machine.**
3. **Turn the physical dial/knob** to the dedicated **Wi-Fi** or **Remote** position (often labeled `Wi-Fi`, `Remote Control`, or `One Touch`).

Once activated:
- The **Remote Control** status turns **On** in Home Assistant.
- Control buttons, program selectors, and settings on your dashboard become active and ready for use.
- Select your desired program and options (temperature, spin speed, dry level), then tap **Start**!

---

## How Remote Control Works

### Safety & Physical Dial Priority

Candy and Hoover appliances prioritize hands-on safety: **the physical dial always takes priority over Home Assistant**.

- If anyone turns the dial away from the Wi-Fi position to a physical program, the appliance immediately switches to local manual control.
- In manual mode, Home Assistant continues displaying live sensor data (current status, cycle progress, remaining time), but control commands are safely locked out.
- When the appliance is turned off or remote control is not engaged, control entities appear as `unavailable` to prevent sending commands that the machine cannot accept.

---

## Common Cycle Controls

All appliances that support remote control share a consistent set of core controls:

| Control | Action | Description |
|---|---|---|
| **Start** | Run cycle | Starts the cycle with your currently selected program and options. |
| **Pause** | Pause cycle | Pauses an active cycle without losing remaining time or resetting settings. |
| **Resume** | Continue cycle | Resumes a paused cycle from where it left off. |
| **Stop** | Cancel cycle | Safely stops the active cycle and unlocks the door (running a drain sequence if needed). |
| **Delay Start** | Schedule start | Sets a delay timer before the cycle begins (ideal for running during off-peak energy hours). |

> [!TIP]
> **Pause & Resume Support:** Most modern appliances support remote Pause and Resume. If your specific machine model does not support remote pausing at the hardware level (such as Candy Bianca or older dial-only models), Home Assistant automatically hides the Pause and Resume buttons.

---

## Appliance-Specific Controls

Each appliance family provides tailored controls matching its capabilities:

### Washing Machines

- **Wash Programs:** Select from your machine's full list of localized cycles (e.g., *Cottons*, *Eco 40-60*, *Delicates*, *Rapid cycles*).
- **Wash Adjustments:** Customize temperature, spin speed, soil level, and wash options (such as Pre-wash, Extra Rinse, or Steam).
- **Dynamic Time Estimates:** Estimated finish times update dynamically as you adjust soil level or enable optional wash stages.

### Washer-Dryer Combos

Washer-dryers combine standard washing controls with dedicated drying management:

- **Program Type:** Easily switch between **Washing Only**, **Wash & Dry** (continuous cycle), or **Drying Only**.
- **Dry Settings:** Choose an automatic target dry level (*Iron dry*, *Cupboard dry*, *Extra dry*) or select a timed drying duration.
- **Built-in Safeguards:**
  - Selecting a delicate cycle that cannot be safely tumble-dried automatically switches drying off.
  - Starting a dry-only program automatically clears wash temperature and spin settings to ensure smooth operation.
  - Dry settings are locked while a cycle is running to prevent accidental mid-cycle changes.

### Tumble Dryers

- **Drying Programs:** Select from your dryer's full range of localized cycles.
- **Target Dry Level vs. Timed Drying:** Choose between sensor-based dryness targets (*Iron Dry*, *Hang Dry*, *Store Dry*, *Bone Dry*) or set a fixed timed drying duration (e.g., 30, 45, 60, 90, or 120 minutes).
- **Rapid Dry Option:** On programs that support rapid cycles (e.g. Whites, Mix & Dry, Synthetics), quickly select a rapid dry duration (30, 45, or 59 minutes).
- **Delay Start & Countdown Tracking:** Schedule delays in 1-hour increments (up to 24 hours) and monitor the active countdown in real time via the dedicated **Dryer delay start** sensor.
- **Anti-Crease Tumbling:** After drying completes, the dryer gently tumbles intermittently to prevent creases until unloaded. You can stop this at any time by pressing **Cancel Anti-Crease**.
- **Door Safety:** Cycles cannot be started while the door is open.

---

## Maintenance & Care

Regular maintenance keeps your appliance running efficiently and extends its lifespan. The integration provides proactive guidance tailored to each appliance type:

### Washing Machines & Washer-Dryers

Washing appliances track usage with cycle counters that mirror official maintenance routines:

- **Full Check-up:** Periodic self-test to verify all internal components. Start it with one tap; the reminder resets automatically once the test finishes.
- **Limescale Cleaning:** Descaling and drum-clean cycle. A notification provides preparation advice (such as adding descaler to an empty drum), and the reminder resets upon completion.
- **Filter Cleaning:** Reminds you when it is time to inspect and clean the debris filter. Once cleaned, tap the filter reset button on your dashboard to restart the counter.

### Tumble Dryers

Dryers use real-time hardware alerts rather than software cycle counters:

- **Lint Filter Alert:** Alerts you when the lint filter mesh needs to be cleaned to maintain optimal airflow.
- **Water Tank Alert:** Alerts you when the condensate collection drawer is full and needs emptying.
- **Clear Warnings:** After cleaning the filter or emptying the tank, tap **Reset Warnings** to clear the machine's warning indicator.
- **Electronic Self Check-up:** Tap the **Self Check-up** button to run an automated hardware diagnostic test on the dryer's internal components.

---

## Troubleshooting & Fault Alerts

If an appliance encounters an operational fault or hardware issue:

- **Plain-Language Guidance:** Instead of displaying an obscure code, Home Assistant displays a persistent notification with official, step-by-step troubleshooting instructions translated into your language (e.g., checking the water inlet tap, clearing a drain pump block, or balancing an uneven load).
- **Live Updates:** If the machine's status or diagnostic code changes, the notification automatically updates with the newest information.
- **Automatic Dismissal:** As soon as you resolve the problem and the appliance clears the fault, Home Assistant dismisses the notification automatically.

---

## Dashboards & Automations

### Ready-Made Dashboards

Pre-configured Lovelace dashboard cards using [Mushroom Cards](https://github.com/piitaya/lovelace-mushroom) are available in the [`dashboard/`](../dashboard/) directory:

<p float="left">
  <img src="images/dashboard_washing_machine.png" width="300" alt="Washing Machine Dashboard Card" />
  <img src="images/dashboard_maintenance.png" width="300" alt="Maintenance Dashboard Card" />
</p>

- **[Washing Machine Card](../dashboard/washing-machine.yaml):** Operational control panel for standard washing machines (program selection, spin/temp adjustments, start/pause/stop buttons, and time estimates).
- **[Washer-Dryer Card](../dashboard/washer-dryer.yaml):** All-in-one panel featuring wash-and-dry mode selection, drying settings, and live status icons.
- **[Tumble Dryer Card](../dashboard/tumble-dryer.yaml):** Complete dryer panel with dry level selectors, timed drying controls, filter and water alerts, and anti-crease management.
- **[Maintenance Card](../dashboard/maintenance.yaml):** Companion card strictly for **washing machines** and **washer-dryers** (tracks cycle-based countdowns for Full Check-up, Limescale cleaning, and Filter care). Not needed for tumble dryers, which already include live hardware alerts directly on their card.

#### Requirements & Setup

1. **Install Mushroom Cards:** Install [Mushroom Cards](https://github.com/piitaya/lovelace-mushroom) via **HACS > Frontend** (or manually). The cards require `custom:mushroom-template-card` and `custom:mushroom-chips-card`.
2. **Add Manual Card:** Edit your dashboard, click **Add Card**, and choose **Manual** at the bottom.
3. **Paste & Configure `<machine_name>`:** Copy the card YAML and replace every occurrence of `<machine_name>` with your device's entity prefix (e.g. `washing_machine` if your main status sensor is `sensor.washing_machine`).

For complete card details and setup instructions, see the [`dashboard/`](../dashboard/README.md) directory.

### Automations

The integration provides native Home Assistant device triggers for automations. You can set them up easily via the UI (**Settings > Devices & Services > Candy > your device > Automations (+)**) or in YAML:

- **Cycle Progress:** Trigger automations when cycles start or complete (e.g., `washing_completed`, `drying_completed`).
- **Maintenance Reminders:** Trigger alerts when a washing machine needs cleaning (`maintenance_limescale_due`, `clean_filter_needed`) or when a dryer's lint filter or water tank requires attention (`water_tank_full`).
- **Error Alerts:** Trigger urgent notifications if a machine reports an error (`error_reported`).

#### Example: Notify when laundry is complete

```yaml
alias: "Laundry: Notify when cycle is finished"
trigger:
  - domain: candy 
    device_id: <YOUR_CANDY_DEVICE_ID>
    type: washing_completed
    trigger: device   
action:
  - action: notify.<your_notify_target>
    data:
      title: "Washing Machine"
      message: "The laundry cycle has finished! 🧺"
```

---

## Frequently Asked Questions (FAQ)

#### Why are the controls greyed out or unavailable?
Controls are active only when the appliance is powered on, the door is closed, and the physical dial is set to the **Wi-Fi** or **Remote** position. If the machine is turned off or in manual mode, controls are disabled for safety.

#### Why does the dashboard briefly pause after I press Start or Stop?
After sending a command, Home Assistant temporarily pauses control updates for a few seconds. This gives the appliance time to process the command and update its internal state before fetching fresh data.

#### Can I control my appliance without internet access?
Yes! Once set up, all cycle monitoring and remote control commands communicate **100% locally** across your home Wi-Fi network. Internet access is only needed during initial setup to download your model's program catalog and translations.
