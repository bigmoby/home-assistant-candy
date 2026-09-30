# Remote Control — Washing Machine

This page documents the `binary_sensor.remote_control` entity, maintenance
counters, notifications, error code handling, and the polling behaviour behind Full Control mode.

## Remote Control status

The washing machine reports whether it currently accepts remote commands via
the `WiFiStatus` field in its local status JSON. This is exposed as:

- `binary_sensor.<machine>_remote_control` (diagnostic, `mdi:remote`)
- the `remote_control` attribute on the main status sensor

`WiFiStatus` can be `0` even while the machine is otherwise online and
reporting status normally. This happens when the machine is being operated
**physically from its own panel**: it stays connected to WiFi and keeps
reporting its state, but rejects commands sent remotely until the user
switches control back to the app/network side (or the cycle finishes).

### What gets disabled when Remote Control is off

Every entity that writes to the machine becomes `unavailable`:

- Start / Pause / Stop buttons
- Program, temperature, spin speed, and soil level selects
- Option switches (Prewash, Hygiene, Steam, Anti-crease, Good Night, Extra
  Rinse, AquaPlus, NFC)
- Delay start number
- Full Check-up and Limescale Cleaning buttons

The maintenance **reset** buttons are the one exception — they only update
config-entry data (the counter baseline), never write to the device, so they
stay available regardless of Remote Control status.

When the machine is fully off/unreachable, the integration reports a
synthetic offline status with `remote_control=False`, so the same gating
also covers "machine off" — there's no separate code path to reason about.

## Maintenance counters

Three counters mirror the Simply-Fi app's built-in reminders. All three are
driven by the same **cumulative total wash cycle count** reported by the
device's statistics endpoint — not by elapsed time.

| Counter | Threshold | Cycle to run | Auto-reset? |
|---|---|---|---|
| Check-up | 100 cycles (fixed) | Full Check-up button | Yes — automatic on completion (manual button fallback) |
| Limescale | 85–110 cycles, depends on configured water hardness | Limescale Cleaning button | Yes — automatic on completion (manual button fallback) |
| Filter | 100 cycles (fixed) | none — physical cleaning | No — manual |

### Maintenance resets and lifecycle

- **Full Check-up**: Resets its counter automatically when the cycle completes successfully (`CheckUpState == 2`). Home Assistant posts a completion notification matching the Simply-Fi app, clears any active check-up reminder, commits the updated `total_cycles` baseline, and resets the appliance diagnostic register. A manual reset button is also available as a fallback.
- **Limescale Cleaning**: Resets its counter automatically when the `AUTOCLEAN` cycle completes successfully (`MachMd` reaches `FINISHED1` or `FINISHED2` without errors). Home Assistant dismisses any active limescale reminder, posts a cycle completion notification (matching the Simply-Fi app), commits the updated `total_cycles` baseline, and refreshes statistics. A manual reset button is also available as a fallback.
- **Filter**: Requires manual reset. Cleaning the pump filter is a physical task without machine feedback; after cleaning, press the matching **Filter maintenance reset** button.

Each reset button writes the current `total_cycles` value (from the stats
coordinator) into the config entry as the new baseline
(`CONF_KEY_MAINTENANCE_LAST_FULL_CHECKUP` / `_LIMESCALE` / `_FILTER`). The
remaining-cycles sensor is a clamp, not a countdown that wraps: once a
counter reaches 0 it stays at 0 (and keeps re-firing its notification) on
every subsequent wash until reset, rather than silently restarting.

The Filter counter never has an associated start button — cleaning the pump
filter is a manual, physical task, so its only actionable entity is the
reset button.

### Maintenance notifications

The integration actively manages the notification lifecycle for maintenance tasks:

- **Due reminders**: When any maintenance counter reaches 0 remaining cycles (Check-up, Limescale, or Filter), Home Assistant posts a persistent notification prompting you to perform the required maintenance. The messages are fully localized in your chosen language.
- **Start instructions**: When starting a Full Check-up or Limescale Cleaning cycle from Home Assistant, a notification is posted with official preparation instructions (e.g. running the drum empty, adding descaling solution).
- **Completion notices & auto-dismissal**: When a Full Check-up or Limescale Cleaning cycle finishes successfully without errors, Home Assistant posts a completion notification and automatically dismisses the active maintenance due reminder.

## Fault & Error Code Handling

When the washing machine reports an operational fault or hardware issue (`Err` code in telemetry), Home Assistant automatically captures the error and displays a persistent notification:

- **Official troubleshooting steps**: Instead of showing just a raw error code, the notification provides the authentic vendor troubleshooting steps extracted directly from the Simply-Fi app (e.g. checking water pressure and inlet tap, cleaning pump filter, checking drain hose, or balancing load).
- **Localized guidance**: Troubleshooting instructions match your configured appliance language (or Home Assistant language).
- **Dynamic updates**: If the machine's reported error code changes while a fault is active, the persistent notification updates in-place.
- **Automatic dismissal**: Once the issue is resolved on the appliance and the error code clears (`Err` returns to 0), Home Assistant automatically clears and dismisses the error notification without requiring manual action.
- **Universal availability**: Error notifications run for all washing machine setups, both in Read-Only and Full Control modes.

## Polling behaviour

The coordinator adapts its polling interval based on device reachability,
and additionally reacts to write commands:

| Situation | Interval |
|---|---|
| Machine reachable (normal polling) | 60 s |
| Machine unreachable / reports Off | 20 s — faster wake-up detection |
| Immediately after a write command | ~5 s |

### Normal and resting intervals

`coordinator.update_interval` is mutated inside the polling closure itself:
60 seconds while the last successful fetch succeeded, dropping to 20 seconds
once the device is inferred to be off (connection failures are treated as
"powered off" rather than errors, using a synthetic offline status). The
shorter resting interval exists purely so Home Assistant notices a wake-up
quickly, without needing a manual refresh button.

### Post-command refresh

Write commands (Start/Pause/Stop, Full Check-up, Limescale Cleaning, and any
control entity `set_value`/`select_option` call) don't wait for the next
scheduled poll to reflect their effect:

1. A `write_pending` counter is incremented and coordinator listeners are
   notified immediately — every gated control goes `unavailable` for the
   duration.
2. The command is sent to the device.
3. The integration sleeps 5 seconds, giving the machine time to actually
   process the command (immediately re-polling on success or failure was
   tried and caused false "unavailable"/"Off" reports — the machine isn't
   always done processing yet).
4. The counter is decremented; once it reaches zero, a coordinator refresh
   is requested, pulling the now-updated state.

Overlapping commands share the same counter, so a second command doesn't
prematurely unlock the controls while the first is still settling.
