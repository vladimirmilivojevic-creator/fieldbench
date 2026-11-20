from functools import reduce

import pytest
import serial

from fieldbench.nmea import checksum_ok, parse_sentence, read_fixes, read_nmea_file, serial_lines


def nmea(body: str) -> str:
    """Build a sentence with a correct checksum."""
    checksum = reduce(lambda acc, ch: acc ^ ord(ch), body, 0)
    return f"${body}*{checksum:02X}"


GGA = nmea("GPGGA,094737.00,5251.0093,N,00518.8170,E,4,12,0.6,1.2,M,45.0,M,,")
RMC = nmea("GPRMC,094737.00,A,5251.0093,N,00518.8170,E,5.6,230.5,200818,,,A")


def test_checksum():
    assert checksum_ok(GGA)
    assert not checksum_ok(GGA[:-2] + "00")
    assert not checksum_ok("GPGGA,no dollar")
    assert not checksum_ok("$GPGGA,bad*ZZ")


def test_parse_gga():
    kind, data = parse_sentence(GGA)
    assert kind == "GGA"
    assert data["lat"] == pytest.approx(52 + 51.0093 / 60)
    assert data["lon"] == pytest.approx(5 + 18.8170 / 60)
    assert data["quality"] == 4
    assert data["time_s"] == 9 * 3600 + 47 * 60 + 37


def test_parse_rmc_speed_in_mps():
    kind, data = parse_sentence(RMC)
    assert kind == "RMC"
    assert data["speed_mps"] == pytest.approx(5.6 * 0.514444)
    assert data["course_deg"] == 230.5


@pytest.mark.parametrize(
    "line",
    [
        nmea("GPGGA,094737.00,5251.0093,N,00518.8170,E,0,00,,,M,,M,,"),  # no fix
        nmea("GPRMC,094737.00,V,,,,,,,200818,,,N"),  # void
        nmea("GPGSV,3,1,12,01,40,083,46"),  # not parsed
        nmea("GPGGA,bad"),  # too short
        "garbage",
    ],
)
def test_ignored_sentences(line):
    assert parse_sentence(line) is None


def test_southern_and_western_hemisphere():
    _, data = parse_sentence(nmea("GNGGA,120000,4134.4979,S,09345.0343,W,1,08,1.0,0,M,0,M,,"))
    assert data["lat"] < 0 and data["lon"] < 0


def test_read_fixes_merges_gga_and_rmc():
    fixes = read_fixes([RMC, GGA, "", "# comment"])
    assert len(fixes) == 1
    assert fixes[0].quality == 4
    assert fixes[0].speed_mps == pytest.approx(2.88, abs=0.01)


def test_real_sample_logs(samples):
    boat = read_nmea_file(samples / "nmea" / "ijsselmeer_bg_zeus2.nmea")
    assert len(boat) > 140
    rtk = read_nmea_file(samples / "nmea" / "trimble_rtk_short.nmea")
    assert {f.quality for f in rtk} >= {2, 4}  # DGPS and RTK fixed


def test_serial_reader_with_loopback(monkeypatch):
    # loop:// is pyserial's built-in loopback port: what we write, we read back
    port = serial.serial_for_url("loop://", timeout=0.2)
    port.write(f"{GGA}\r\n{RMC}\r\n".encode())
    monkeypatch.setattr(serial, "serial_for_url", lambda *args, **kwargs: port)
    lines = list(serial_lines("loop://", max_lines=5))
    assert len(read_fixes(lines)) == 1
