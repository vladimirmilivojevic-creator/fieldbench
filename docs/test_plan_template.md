# Test plan template - precision-farming feature validation

A short test plan in the style of IEEE 829, filled in for the FieldBench
auto-guidance example. Copy it and replace the example rows for a new feature.

## 1. Identification

| Field | Example |
|---|---|
| Plan ID | TPL-GUI-2026-01 |
| Feature | Auto-guidance: engage / disengage logic and GNSS fault handling |
| Software release under test | 1.3.0 (release candidate), regression on 1.4.0 |
| Author / reviewer | test engineer / feature owner |
| Spec reference | `spec/system_spec.yaml` (requirements REQ-COM, REQ-SIG, REQ-GUI, REQ-BUS) |

## 2. Scope

**In scope:** CAN communication of the tractor ECU, GNSS receiver and guidance
controller (cycle times, timeouts, signal ranges); guidance engage / disengage
behaviour; reaction to lost messages, GNSS dropout, bus errors and bus-off.

**Out of scope:** steering control accuracy on the vehicle, implement control
(ISOBUS TC / TIM), terminal (VT) user interface, telematics upload.

## 3. Approach

| Level | Where | How |
|---|---|---|
| Bench, simulated (SIL) | FieldBench virtual CAN bus | pytest procedures from the YAML spec, every push in CI |
| Bench, hardware (HIL) | ECU on the bench, CAN interface, power supply | same procedures, bus via python-can `vector` / `pcan` / `socketcan` interface |
| Vehicle, field | test tractor, RTK correction | guidance pass on an AB line, NMEA + CAN logging, offline XTE check |

Fault injection is done on the bench: drop frames of one message, silence the
GNSS receiver, put one ECU bus-off, and inject error frames.

## 4. Entry and exit criteria

| Entry | Exit |
|---|---|
| Release notes and DBC for the release are available | All safety procedures pass |
| Bench passes the self test (nominal pass, no timeouts) | No open issue with severity "high" |
| Test procedures reviewed against the spec | Every requirement has at least one executed procedure |
| | Test report and issue list sent to the feature owner |

## 5. Traceability

| Requirement | Text | Safety | Procedure(s) |
|---|---|---|---|
| REQ-COM-001 | All messages are sent with their specified cycle time (+/- tolerance). |  | TP-COM-01 |
| REQ-COM-002 | No message is missing for longer than its timeout in normal operation. |  | TP-COM-02 |
| REQ-SIG-001 | All signals stay inside their specified physical range. |  | TP-SIG-01 |
| REQ-GUI-001 | Auto-steering engages only after an operator request while GNSS and wheel speed are valid. | yes | TP-GUI-01 |
| REQ-GUI-010 | Auto-steering disengages within 500 ms when the GNSS position is lost. | yes | TP-GUI-10 |
| REQ-GUI-011 | A GNSS loss raises DM1 SPN 584 FMI 9 (abnormal update rate) within 1 s. |  | TP-GUI-11 |
| REQ-GUI-012 | After a disengagement, steering re-engages only on a new operator request. | yes | TP-GUI-12 |
| REQ-GUI-020 | Auto-steering disengages within 500 ms when wheel-based speed is missing for more than 300 ms. | yes | TP-GUI-20, TP-BUS-02 |
| REQ-GUI-021 | A single lost wheel-speed frame does not disengage auto-steering. |  | TP-GUI-21 |
| REQ-BUS-001 | The system tolerates a burst of bus errors without losing any message for longer than its timeout. |  | TP-BUS-01 |

The unit test `test_every_requirement_has_a_procedure` fails when a
requirement in the spec has no procedure.

## 6. Test procedure format

Each procedure in the YAML spec has an ID, a title, the requirement it proves,
a driving scenario, optional faults and the checks:

```yaml
- id: TP-GUI-10
  title: GNSS dropout disengages steering
  requirement: REQ-GUI-010
  scenario: field_pass
  faults:
    - {type: gnss_dropout, at_s: 6.0, duration_s: 2.0}
  checks:
    - {type: reaction, signal: SteeringEngaged, equals: 0, after_s: 6.0, within_ms: 500}
```

## 7. Environment

| Item | Example |
|---|---|
| Bench | FieldBench 1.0, Python 3.12, python-can 4.x, cantools |
| Bus | ISOBUS / J1939, 250 kbit/s, 29-bit identifiers |
| GNSS | NMEA 0183 over serial, 1-10 Hz |
| Logging | Vector BLF + ASC for every procedure |

## 8. Risks

| Risk | Mitigation |
|---|---|
| Simulated ECUs differ from real ECU timing | Repeat the procedures on the HIL bench with the real ECU |
| GNSS conditions on the field are not repeatable | Record NMEA + CAN on every field pass and re-check offline |
| Spec changes without a test update | Traceability test in CI |

## 9. Deliverables

Excel and HTML test report per release, one defect report per failed check
(see [sample_defect_report.md](sample_defect_report.md)), BLF / ASC logs and
signal plots of every procedure.
