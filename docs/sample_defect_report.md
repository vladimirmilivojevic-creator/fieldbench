# FB-003: No automatic re-engage after the GNSS signal returns: SteeringEngaged == 0 from 6.5 to 14 s

| Field | Value |
|---|---|
| Status | open |
| Severity | high (safety) |
| Procedure | TP-GUI-12 |
| Requirement | REQ-GUI-012 - After a disengagement, steering re-engages only on a new operator request. |
| Found in release | 1.3.0 |
| Occurrences | 1 |
| First seen | 2026-11-20 13:24 UTC |


## Steps to reproduce
1. Flash software release 1.3.0 on the bench ECUs.
2. Start scenario 'field_pass': 9 km/h, 1900 rpm, heading 72 deg, operator engages auto-steering at 2 s.
3. Inject fault 'gnss_dropout' at 6 s for 2 s.
4. Run `pytest procedures -k TP-GUI-12 --release 1.3.0` and check the result.

## Expected
0

## Actual
1 at 8.10 s

## Log excerpt (ASC, decoded)
```
   7.960454 1  CF00400x  Rx   d 8 00 00 A0 53 3B 00 00 00  // EEC1 ActualEnginePercentTorque=35 EngineSpeed=1898.375
   7.980730 1  CF00400x  Rx   d 8 00 00 A0 46 3B 00 00 00  // EEC1 ActualEnginePercentTorque=35 EngineSpeed=1896.75
   7.999368 1  CFE48F0x  Rx   d 8 C4 09 98 3A 00 00 00 01  // WBSD WheelBasedSpeed=2.5 WheelBasedDistance=15 MachineDirection=1
   7.999918 1  9F8011Cx  Rx   d 8 E9 8B B6 1C 2C 47 A6 08  // GNSS_POSITION Latitude=48.173 Longitude=14.511
   8.000135 1  CF00400x  Rx   d 8 00 00 A0 3A 3B 00 00 00  // EEC1 ActualEnginePercentTorque=35 EngineSpeed=1895.25
   8.000244 1  CFE45F0x  Rx   d 8 32 01 00 00 00 00 00 00  // RHS RearHitchPosition=20 RearHitchInWork=1
   8.000351 1  18FECA13x  Rx   d 8 04 00 48 02 09 00 01 00  // DM1 ProtectLamp=0 AmberWarningLamp=1 RedStopLamp=0 MalfunctionLamp=0 SpnLow=584 Fmi=9 SpnHigh=0 OccurrenceCount=1
   8.000781 1  CADFF13x  Rx   d 8 00 02 DC FF 00 00 00 00  // GUIDANCE_STATUS SteeringEngaged=0 SteeringReadiness=0 ExitReason=2 CrossTrackError=-0.036
   8.005536 1  18FECA13x  Rx   d 8 00 00 00 00 00 00 00 00  // DM1 ProtectLamp=0 AmberWarningLamp=0 RedStopLamp=0 MalfunctionLamp=0 SpnLow=0 Fmi=0 SpnHigh=0 OccurrenceCount=0
   8.020322 1  CF00400x  Rx   d 8 00 00 A0 30 3B 00 00 00  // EEC1 ActualEnginePercentTorque=35 EngineSpeed=1894
   8.040057 1  CF00400x  Rx   d 8 00 00 A0 28 3B 00 00 00  // EEC1 ActualEnginePercentTorque=35 EngineSpeed=1893
   8.060635 1  CF00400x  Rx   d 8 00 00 A0 23 3B 00 00 00  // EEC1 ActualEnginePercentTorque=35 EngineSpeed=1892.375
   8.080531 1  CF00400x  Rx   d 8 00 00 A0 20 3B 00 00 00  // EEC1 ActualEnginePercentTorque=35 EngineSpeed=1892
   8.099356 1  CADFF13x  Rx   d 8 05 00 FF FF 00 00 00 00  // GUIDANCE_STATUS SteeringEngaged=1 SteeringReadiness=1 ExitReason=0 CrossTrackError=-0.001
   8.099451 1  CFE48F0x  Rx   d 8 C4 09 92 3B 00 00 00 01  // WBSD WheelBasedSpeed=2.5 WheelBasedDistance=15.25 MachineDirection=1
   8.099666 1  CF00400x  Rx   d 8 00 00 A0 21 3B 00 00 00  // EEC1 ActualEnginePercentTorque=35 EngineSpeed=1892.125
   8.099793 1  CFE45F0x  Rx   d 8 32 01 00 00 00 00 00 00  // RHS RearHitchPosition=20 RearHitchInWork=1
   8.100034 1  9F8011Cx  Rx   d 8 F0 8B B6 1C 4C 47 A6 08  // GNSS_POSITION Latitude=48.173 Longitude=14.511
   8.119753 1  CF00400x  Rx   d 8 00 00 A0 24 3B 00 00 00  // EEC1 ActualEnginePercentTorque=35 EngineSpeed=1892.5
   8.120120 1  9F8021Cx  Rx   d 8 1E 00 16 31 FA 00 00 00  // GNSS_COG_SOG SID=30 CogReference=0 CourseOverGround=1.257 SpeedOverGround=2.5
   8.139270 1  CF00400x  Rx   d 8 00 00 A0 2A 3B 00 00 00  // EEC1 ActualEnginePercentTorque=35 EngineSpeed=1893.25
   8.160504 1  CF00400x  Rx   d 8 00 00 A0 32 3B 00 00 00  // EEC1 ActualEnginePercentTorque=35 EngineSpeed=1894.25
   8.180242 1  CF00400x  Rx   d 8 00 00 A0 3C 3B 00 00 00  // EEC1 ActualEnginePercentTorque=35 EngineSpeed=1895.5
   8.199677 1  CFE48F0x  Rx   d 8 C4 09 8C 3C 00 00 00 01  // WBSD WheelBasedSpeed=2.5 WheelBasedDistance=15.5 MachineDirection=1
   8.199702 1  CF00400x  Rx   d 8 00 00 A0 48 3B 00 00 00  // EEC1 ActualEnginePercentTorque=35 EngineSpeed=1897
   8.199720 1  9F8011Cx  Rx   d 8 F6 8B B6 1C 6C 47 A6 08  // GNSS_POSITION Latitude=48.173 Longitude=14.511
   8.199764 1  CFE45F0x  Rx   d 8 32 01 00 00 00 00 00 00  // RHS RearHitchPosition=20 RearHitchInWork=1
   8.200398 1  CADFF13x  Rx   d 8 05 00 FE FF 00 00 00 00  // GUIDANCE_STATUS SteeringEngaged=1 SteeringReadiness=1 ExitReason=0 CrossTrackError=-0.002
   8.220002 1  CF00400x  Rx   d 8 00 00 A0 56 3B 00 00 00  // EEC1 ActualEnginePercentTorque=35 EngineSpeed=1898.75
   8.240042 1  CF00400x  Rx   d 8 00 00 A0 63 3B 00 00 00  // EEC1 ActualEnginePercentTorque=35 EngineSpeed=1900.375
```

## Attachments
- `TP-GUI-12_1.3.0.blf`
- `TP-GUI-12_1.3.0.asc`
- `TP-GUI-12_1.3.0.png`
