# NMEA samples

Real receiver recordings from the [gpsd](https://gpsd.io) regression test corpus
(BSD-2-Clause, see the header comments in each file). They are kept unchanged;
the NMEA reader skips the `#` comment lines.

| File | Receiver | What it is used for |
|---|---|---|
| `ijsselmeer_bg_zeus2.nmea` | B&G Zeus2 chartplotter, IJsselmeer (NL), 2018 | A straight 146 s pass at about 3 m/s with 1 Hz GPS fixes: the guidance (cross-track error) demo |
| `trimble_rtk_short.nmea` | Trimble receiver with RTK, 2020 | Parser test for `GN` talker ids and fix quality 2 (DGPS) / 4 (RTK fixed) |

The IJsselmeer track is from a boat, not a tractor: it was the best public
straight-line recording with a clear licence. Any NMEA log or a live serial
GNSS receiver can be checked the same way:

```
fieldbench guidance --nmea my_field_pass.nmea --plot xte.png
fieldbench guidance --serial COM5 --baud 38400
```
