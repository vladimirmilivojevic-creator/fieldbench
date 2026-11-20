# Bench setup

## Virtual bench (what runs in CI and in the live demo)

```
                 python-can virtual bus "fieldbench-xxxx" (simulated time, 5 ms steps)
   ┌──────────────┬──────────────┬──────────────┬───────────────────┐
   │ ENGINE 0x00  │ TECU 0xF0    │ GNSS 0x1C    │ GUIDANCE 0x13     │  simulated nodes
   │ EEC1 20 ms   │ WBSD 100 ms  │ 129025 100ms │ GUIDANCE_STATUS   │
   │              │ RHS 100 ms   │ 129026 250ms │ DM1 1 s + on chg  │
   └──────▲───────┴──────▲───────┴──────▲───────┴─────────▲─────────┘
          │  fault injection node: drop / gnss_dropout /  │
          │  bus_off / bus_errors (error frame + retry)   │
          └───────────────────────┬───────────────────────┘
                                  │
                      recorder -> BLF + ASC -> decode (DBC) -> checks
```

- The plant model (`fieldbench/plant.py`) is the "vehicle": speed, engine
  speed, hitch and position as functions of time.
- Time is simulated, so a 14 s field pass takes a fraction of a second and
  every run gives the same frames (seeded jitter of +/- 0.8 ms).

## Moving to real hardware

The recorder and the analysis tools only use python-can, so the same code
works with a CAN interface. Not tested on real hardware in this project; the
configuration would be:

| Interface | python-can config | Notes |
|---|---|---|
| Vector VN1610 / VN1630 | `interface="vector", channel=0, bitrate=250000` | needs the Vector driver and an application channel set up in Vector Hardware Config |
| PEAK PCAN-USB | `interface="pcan", channel="PCAN_USBBUS1", bitrate=250000` | |
| Linux SocketCAN | `ip link set can0 up type can bitrate 250000`, then `interface="socketcan", channel="can0"` | |

```python
import can
from fieldbench.analysis import write_logs

with can.Bus(interface="vector", channel=0, bitrate=250000, app_name="CANalyzer") as bus:
    frames = [bus.recv(1.0) for _ in range(5000)]
write_logs([f for f in frames if f], "results/field_log")
```

Then run `fieldbench analyze results/field_log.blf --plot field.png`.

### ISOBUS bus checklist

- 250 kbit/s, 29-bit identifiers (J1939 / ISO 11783).
- Termination at both ends of the bus (ISOBUS uses active terminating bias
  circuits, a plain bench can use 120 ohm resistors).
- Check the bus load before adding a logger that transmits anything; a
  logger should be listen-only.

## GNSS receiver on serial

```
fieldbench guidance --serial COM5 --baud 38400 --max-lines 3000 --plot xte.png
```

The receiver must output GGA and RMC. RTK fixes (GGA quality 4) are judged
against the 2.5 cm class, DGPS against 0.30 m, plain GPS against 1.5 m
(`guidance.classes` in the spec).

## Running the campaign

```
pytest procedures --release 1.3.0 --results results     # or: fieldbench run --release 1.3.0
pytest procedures -k TP-GUI --release 1.4.0             # only the guidance procedures
```

Results: `results/report_<release>.html|xlsx`, `results/issues/FB-xxx.md`,
`results/logs/*.blf|asc`, `results/plots/*.png`, `results/issues.json`.
