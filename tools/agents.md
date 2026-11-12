# Candy Simply-Fi Diagnostic & Dissection Tool (`simplyfi.py` v2.0.0)

This documentation provides the technical and architectural reference for developers and LLM agents working with `tools/simplyfi.py`.

`simplyfi.py` is a standalone Python utility designed to recover device encryption keys, dissect real-time appliance telemetry across all Candy Simply-Fi and Hoover Wizard appliance families, audit remote control readiness, execute write commands, and produce sanitized diagnostic dumps for troubleshooting and onboarding new appliances.

---

## 1. Architectural Overview & Network Transport

Candy Simply-Fi and Hoover Wizard appliances expose a lightweight HTTP server on TCP port 80.
Because the onboard microcontrollers (Microchip PIC32 / Espressif ESP32/8266) feature fragile network stacks, `simplyfi.py` uses raw TCP sockets rather than high-level HTTP client libraries (like `requests` or `urllib3`):
* **Request Format**: Plain `GET /http-{endpoint}.json?{query} HTTP/1.1\r\nHost: {ip}\r\nConnection: close\r\n\r\n`
* **Response Separation**: Locates header terminator `\r\n\r\n` (or `\n\n`), isolates the payload body, strips carriage returns, newlines, and null terminators (`\x00`).
* **Format Detection**:
  * If body starts and ends with `{...}`, it is treated as plaintext JSON.
  * If body is hex-encoded ASCII (even or odd length padded with leading `0`), it is parsed via `bytes.fromhex()`.
* **Session Integrity**: Interleaving unencrypted and encrypted requests corrupts internal session state on some models. The tool cleanly separates probe requests.

---

## 2. Cryptographic Engine (Sliding-Window XOR Attack)

Candy appliances use a repeating 16-character ASCII key XOR cipher:
$$\text{ciphertext}[i] = \text{plaintext}[i] \oplus \text{key}[i \pmod{16}]$$

### Known-Plaintext Attack Workflow
1. **Sliding Window Search**: Iterates through the ciphertext byte-by-byte testing known plaintext signatures.
2. **Partial Key Derivation**: Extracts `partial_key[j] = ciphertext[pp + j] ^ search_bytes[j]`. Rejects immediately if any derived byte is outside printable ASCII (`0x20..0x7E`).
3. **16-Byte Fragment Recovery**:
   * If `len(search_bytes) >= 16`, takes the first 16 bytes.
   * If `len(search_bytes) == 15`, brute-forces the single missing byte across 95 printable ASCII values ($95 \times 16$ permutations, sub-millisecond).
4. **Permutation & Rotation**: Tests all 16 rotational alignments ($0 \le kp < 16$) to match byte offset 0 of the frame.
5. **JSON Validation Gate**: Decrypts the candidate buffer and validates using `json.loads()`. Candidate keys that decrypt into printable ASCII but fail JSON parsing are rejected as false positives.

---

## 3. Appliance Family Telemetry Schemas

`simplyfi.py` v2.0.0 automatically detects the root JSON envelope and decodes domain-specific registers across **all 9 appliance families**:

| Appliance Family | Root Key | Authoritative Class (`classes4.dex`) | Primary Telemetry Registers |
| :--- | :--- | :--- | :--- |
| **Washing Machine / Washer-Dryer** | `statusLavatrice` (or `statusWD`/`statusWM`) | `CandyWasherStatus.java` | `MachMd`, `PrPh`, `Pr`, `PrCode`, `Temp`, `SpinSp`, `RemTime`, `DryT`, `FillR`, `DoorLock`, `WiFiStatus` |
| **Tumble Dryer** | `statusTD` | `CandyTumbleDryerDTStatus.java` | `StatoTD`, `PrPh`, `Pr`, `DryLev`, `RemTime`, `CleanFilter`, `WaterTankFull`, `StatoWiFi` |
| **Dishwasher** | `statusDWash` | `CandyDishwasherStatus.java` | `StatoDWash`, `Program`, `OpzProg`, `RemTime`, `DelayStart`, `OpenDoor`, `MissSalt`, `MissRinse`, `Eco`, `MetaCarico`, `TreinUno`, `StatoWiFi` |
| **Oven** | `statusForno` | `CandyOvenStatus.java` | `StartStop`, `Pausa`, `Program`, `Selettore`, `TempRead` (converted from °F to °C), `TempSet`, `TempSetRaggiunta`, `TimeProgr`, `DoorLock`, `SicurezzaBambini`, `StatoWiFi` |
| **Wine Cooler** | `statusWCool` | `CandyApplianceStatus.java` | `r1` (Remote), `r2` (Error), `r3`/`r4` (Zone 1 Prog & Temp), `r5` (Power), `r7`/`r8` (Zone 2 Prog & Temp), `r10` (Light) |
| **Refrigerator / Freezer** | `statusRefrigerator` | `CandyFridgeStatus.java` | `FrSet`, `FzSet`, `Door`, `DoorOpenCnt`, `Cmp` (Compressor), `CmpFq` (Hz), `Fan`, `Heat`, `Eco`, `Spr` (Super Freeze), `SprC` (Super Cool), `Antib` (Sterilization), `Ice`, `NewIce`, `Lck`, `PF`, `WiFi` |
| **Kitchen Hood** | `StatusHood` | `CandyHoodStatus.java` | `Fan` (Speed 0..4), `Light` (0=Off, 1=On, 2=Ambient), `GreaseFilter`, `CarbonFilter`, `Timer`, `TimerCnt`, `BoostCnt`, `WiFiStatus` |
| **Cooktop / Hob** | `statusHob` | `CandyCookStatus.java` | Zones 1..4: `Z<n>status`, `Z<n>power`, `Z<n>hot` (Residual heat "H"), `Z<n>pan`, `Z<n>combi`, `Z<n>low`, `Z<n>timeh`, `Z<n>timem`, `lock`, `StatoWiFi` |
| **Robot Vacuum** | `StatusVacuumCleaner` | `CandyVacuumCleanerStatus.java` | `MachMd`, `BaSt` (Battery %), `LockSt`, `Tarea` ($m^2$), `TMin`, `DBN` (Dust bin), `FiErr` (Filter), `BMO` (Brush motor), `RMO` (Wheel motor) |

---

## 4. Endpoints & Command Handshakes

### 4.1 Telemetry Read
* **Endpoint**: `GET /http-read.json?encrypted=1` (or `encrypted=0`)
* **Response**: Root JSON object wrapping the appliance telemetry.

### 4.2 Statistics Handshake
For washing machines and tumble dryers, flash counters require a two-step sequence:
1. `GET /http-prepareStatistics.json?encrypted={0|1}`: Signals the MCU to dump internal cycle counters into memory buffer.
2. `GET /http-getStatistics.json?encrypted={0|1}`: Returns `{"statusCounters": {"Program1": "10", ...}}`.

### 4.3 Command Execution (Write)
* **Endpoint**: `GET /http-write.json?encrypted=1&data=<HEX_ENCRYPTED_QUERY>`
* **Pre-conditions**: Appliance must report remote control enabled (`WiFiStatus=1`, `StatoWiFi=1`, `RemCode=1`, or `r1=1`).

---

## 5. CLI Usage & Command Reference

```bash
# 1. Recover 16-character XOR key automatically
python tools/simplyfi.py 192.168.1.50 getkey

# 2. Inspect real-time telemetry (human-readable decoded terminal table)
python tools/simplyfi.py 192.168.1.50 inspect

# 3. Audit remote control prerequisites & physical dial knob status
python tools/simplyfi.py 192.168.1.50 remote

# 4. Fetch cycle statistics via two-step handshake
python tools/simplyfi.py 192.168.1.50 stats

# 5. Fetch network module configuration & firmware details
python tools/simplyfi.py 192.168.1.50 config

# 6. Run full diagnostic scan and generate sanitized GitHub issue report (use --raw for unredacted)
python tools/simplyfi.py 192.168.1.50 diagnose

# 7. Send write command
python tools/simplyfi.py 192.168.1.50 write 1234567890abcdef "Write=1&StSt=1&PrNm=11&..."

# Legacy syntax compatibility:
python tools/simplyfi.py 192.168.1.50 read
python tools/simplyfi.py 192.168.1.50 1234567890abcdef read
```
