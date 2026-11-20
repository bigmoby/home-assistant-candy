# Lovelace Dashboard Cards

Pre-configured, interactive Lovelace dashboard cards for Candy, Hoover, and Haier appliances with Full Control support.

<p float="left">
  <img src="../docs/images/dashboard_washing_machine.png" width="300" alt="Washing Machine Card" />
  <img src="../docs/images/dashboard_maintenance.png" width="300" alt="Maintenance Card" />
</p>

## Requirements

These dashboard cards require [Mushroom Cards](https://github.com/piitaya/lovelace-mushroom) (`custom:mushroom-template-card` and `custom:mushroom-chips-card`).

You can install it via [HACS](https://hacs.xyz/):
1. Navigate to **HACS** > **Frontend**.
2. Search for **Mushroom**.
3. Click **Download**, then reload your browser when prompted.

---

## Setup Instructions

1. **Choose your card(s):**
   - **Main Appliance Cards (choose one):**
     - [`washing-machine.yaml`](washing-machine.yaml): Operational panel for standard washing machines (program selection, spin/temp adjustments, start/pause/stop, progress display).
     - [`washer-dryer.yaml`](washer-dryer.yaml): All-in-one panel for washer-dryer combos with both wash and dry options.
     - [`tumble-dryer.yaml`](tumble-dryer.yaml): All-in-one panel for standalone tumble dryers with dry level, timed drying, anti-crease, live filter/water alerts, and self check-up.
     - [`dishwasher.yaml`](dishwasher.yaml): Operational panel for dishwashers with cycle selection, wash options (Eco, Half Load, Extra Dry, 3-in-1, Auto Open Door), delay start, progress telemetry, and start/pause/resume/stop/open door controls.
   - **Companion Maintenance Cards:**
     - [`maintenance.yaml`](maintenance.yaml): Companion card for **Washing Machines** and **Washer-Dryer combos** (tracks cycle-based maintenance countdowns for Full Check-up, Limescale Autoclean, Debris Filter and provides one-click cleaning triggers).
     - [`dishwasher-maintenance.yaml`](dishwasher-maintenance.yaml): Companion card for **Dishwashers** (monitors salt and rinse aid reservoirs, tub auto-clean warnings, lifetime cycles, water hardness, and provides electronic diagnostic self-tests).

   > [!NOTE]
   > **When are maintenance cards needed?**
   > - **Washing Machines & Washer-Dryers:** Use [`maintenance.yaml`](maintenance.yaml).
   > - **Dishwashers:** Use [`dishwasher-maintenance.yaml`](dishwasher-maintenance.yaml).
   > - **Tumble Dryers:** Not needed; standalone dryers use live hardware alerts (lint filter & water tank) built directly into [`tumble-dryer.yaml`](tumble-dryer.yaml).
   > - **Ovens & Wine Coolers:** These appliances are read-only sensor integrations and do not use control or maintenance cards.
2. **Add to your dashboard:**
   - Open your Home Assistant dashboard and click the pencil icon (**Edit Dashboard**) in the top right.
   - Click **Add Card**, scroll down to the bottom, and select **Manual** (or Edit as YAML).
   - Copy the entire YAML content from the chosen card file and paste it into the card editor.
3. **Configure `<machine_name>`:**
   - Replace every occurrence of `<machine_name>` with your device's entity prefix.
   - **How to find your prefix:** Check the entity ID of your appliance's main status sensor under **Settings** > **Devices & Services** > **Candy** > your device.
     - For example, if your sensor is `sensor.washing_machine`, replace `<machine_name>` with `washing_machine`.
     - If your sensor is `sensor.dishwasher`, replace `<machine_name>` with `dishwasher`.
     - If your sensor is `sensor.my_candy_dryer`, replace `<machine_name>` with `my_candy_dryer`.
4. Click **Save**.
