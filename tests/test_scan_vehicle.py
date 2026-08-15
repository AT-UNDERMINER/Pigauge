"""scan_vehicle against the fakes.

What this proves: bitmask walking, report rendering, and the CAN ID-scheme
probe. What it cannot prove is in test_scan_vehicle_pending() at the
bottom — that list needs the actual vehicle.
"""

import pytest
import yaml
from fake_ecu import FakeCanBus, FakeEcu, FakeMessage
from fake_elm327 import FakeELM327

from pigauge.core.config.models import CanProfileConfig, Elm327ProfileConfig, VehicleProfile
from pigauge.sources.can_socketcan import CanTransport
from pigauge.sources.elm327 import Elm327Transport
from pigauge.sources.obd_profile import build_poll_plan
from pigauge.sources.obd_transport import ObdTransportError
from pigauge.tools import scan_vehicle
from pigauge.tools.scan_vehicle import (
    GENERIC_PROFILE,
    ScanReport,
    detect_can_link,
    enumerate_supported,
    load_rates,
    main,
    scan_transport,
)

EXTENDED_REQUEST_ID = 0x18DB33F1
EXTENDED_RESPONSE_ID = 0x18DAF110


def can_transport(ecu=None, profile_can=None):
    transport = CanTransport(
        profile_can or CanProfileConfig(), bus=FakeCanBus(ecu), message_factory=FakeMessage
    )
    transport.connect()
    return transport


def elm_transport(adapter=None):
    transport = Elm327Transport(Elm327ProfileConfig(), serial_port=adapter or FakeELM327())
    transport.connect()
    return transport


class TestEnumeration:
    def test_walks_every_bank_over_can(self):
        supported = enumerate_supported(can_transport(), 0x01)
        assert 0x0C in supported  # first bank
        assert 0x2F not in supported  # second bank, not served
        assert 0x42 in supported  # third bank, reached via continuation bits

    def test_walks_every_bank_over_elm327(self):
        assert enumerate_supported(elm_transport(), 0x01) == enumerate_supported(
            can_transport(), 0x01
        )

    def test_query_pids_are_not_reported_as_data_pids(self):
        supported = enumerate_supported(can_transport(), 0x01)
        assert 0x00 not in supported and 0x20 not in supported and 0x40 not in supported

    def test_stops_when_a_bank_is_unanswered(self):
        ecu = FakeEcu(values={0x0C: b"\x1a\xf8"})  # first bank only, no continuation
        assert enumerate_supported(can_transport(ecu), 0x01) == [0x0C]

    def test_mode_09_enumerated(self):
        assert enumerate_supported(can_transport(), 0x09) == [0x02]

    def test_silent_ecu_yields_nothing(self):
        ecu = FakeEcu(values={})
        assert enumerate_supported(can_transport(ecu), 0x01) == []


class TestScanReport:
    def test_maps_supported_pids_to_channels(self):
        report = scan_transport(can_transport(), "can", "vcan0")
        assert report.decodable["engine.rpm"] == 0x0C
        assert report.decodable["electrical.battery_v"] == 0x42

    def test_elm327_records_the_negotiated_protocol(self):
        report = scan_transport(elm_transport(), "elm327", "/dev/ttyUSB0")
        assert "ISO 15765-4" in report.protocol

    def test_can_has_no_protocol_string(self):
        report = scan_transport(can_transport(), "can", "can0")
        assert "not reported" in report.render()

    def test_undecodable_pids_flagged_for_later(self):
        ecu = FakeEcu(values={0x0C: b"\x1a\xf8", 0x1F: b"\x00\x10"})  # 0x1F = run time
        report = scan_transport(can_transport(ecu), "can", "can0")
        assert report.undecodable == [0x1F]
        assert "Phase 9" in report.render()

    def test_silent_vehicle_gets_a_diagnostic_note(self):
        report = scan_transport(can_transport(FakeEcu(values={})), "can", "can0")
        assert any("ignition" in note for note in report.notes)

    def test_render_lists_channels_and_pids(self):
        rendered = scan_transport(can_transport(), "can", "can0").render()
        assert "engine.rpm" in rendered and "0x0C" in rendered

    def test_snippet_is_valid_yaml_shaped_and_marked_unfinished(self):
        report = scan_transport(can_transport(), "can", "can0")
        snippet = report.profile_snippet(rates={"engine.rpm": 10})
        assert "channels:" in snippet
        assert "engine.rpm:" in snippet and "pid: 0x0C" in snippet
        assert "NOT a finished profile" in snippet

    def test_snippet_flags_channels_without_a_known_rate(self):
        report = scan_transport(can_transport(), "can", "can0")
        assert "TODO: set rate_hz" in report.profile_snippet()

    def test_report_of_an_empty_scan_still_renders(self):
        assert "(none answered)" in ScanReport(transport="can", link="can0").render()

    def test_snippet_parses_as_yaml(self):
        report = scan_transport(can_transport(), "can", "can0")
        parsed = yaml.safe_load(report.profile_snippet(rates={"engine.rpm": 10}))
        assert parsed["channels"]["engine.rpm"] == {"pid": 0x0C, "rate_hz": 10}

    def test_snippet_channels_validate_against_the_profile_schema(self):
        report = scan_transport(can_transport(), "can", "can0")
        parsed = yaml.safe_load(report.profile_snippet(rates=load_rates(GENERIC_PROFILE)))
        profile = VehicleProfile(name="scanned", **parsed)
        assert build_poll_plan(profile)  # the snippet is directly usable

    def test_known_rates_replace_the_todo_marker(self):
        report = scan_transport(can_transport(), "can", "can0")
        snippet = report.profile_snippet(rates=load_rates(GENERIC_PROFILE))
        assert "rate_hz: 10" in snippet
        assert "TODO" not in snippet  # the generic profile covers every scanned channel


class TestCanLinkDetection:
    def test_eleven_bit_scheme_detected_first(self):
        transport, link = detect_can_link(
            "vcan0", bus=FakeCanBus(), message_factory=FakeMessage
        )
        assert "11-bit" in link
        transport.close()

    def test_falls_back_to_the_extended_scheme(self):
        class ExtendedOnlyBus(FakeCanBus):
            """Answers only 29-bit requests, as an extended-ID vehicle would."""

            def send(self, message, timeout=None):
                if message.arbitration_id != EXTENDED_REQUEST_ID:
                    self.sent.append(message)
                    return
                payload = bytes(message.data)
                response = self.ecu.respond_to_frame(payload[1 : 1 + payload[0]])
                if response is not None:
                    self._inbox.append(
                        FakeMessage(EXTENDED_RESPONSE_ID, bytes([len(response)]) + response)
                    )

        transport, link = detect_can_link(
            "vcan0", bus=ExtendedOnlyBus(), message_factory=FakeMessage
        )
        assert "29-bit" in link
        transport.close()

    def test_no_answer_raises_with_the_bitrate_hint(self):
        class SilentBus(FakeCanBus):
            """A bus where nothing answers — wrong bitrate, or ignition off."""

            def send(self, message, timeout=None):
                self.sent.append(message)

        with pytest.raises(ObdTransportError, match="bitrate"):
            detect_can_link("vcan0", bus=SilentBus(), message_factory=FakeMessage)


class TestCli:
    def test_elm327_scan_prints_a_report(self, monkeypatch, capsys):
        monkeypatch.setattr(
            scan_vehicle, "Elm327Transport",
            lambda *args, **kwargs: Elm327Transport(
                Elm327ProfileConfig(), serial_port=FakeELM327()
            ),
        )
        assert main(["--transport", "elm327", "--port", "/dev/ttyUSB0"]) == 0
        output = capsys.readouterr().out
        assert "PiGauge vehicle scan" in output
        assert "engine.rpm" in output

    def test_report_written_to_file(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(
            scan_vehicle, "Elm327Transport",
            lambda *args, **kwargs: Elm327Transport(
                Elm327ProfileConfig(), serial_port=FakeELM327()
            ),
        )
        out = tmp_path / "scan.txt"
        assert main(["--transport", "elm327", "--out", str(out)]) == 0
        assert "Mode 01 PIDs supported" in out.read_text(encoding="utf-8")

    def test_unreachable_vehicle_exits_nonzero(self, monkeypatch, capsys):
        def refuse(*args, **kwargs):
            raise ObdTransportError("adapter could not reach the ECU")

        monkeypatch.setattr(scan_vehicle, "detect_can_link", refuse)
        assert main(["--transport", "can", "--interface", "can0"]) == 1
        assert "scan failed" in capsys.readouterr().err

    def test_transport_argument_is_required(self):
        with pytest.raises(SystemExit):
            main([])


def test_scan_vehicle_pending_on_the_patrol():
    """Documents what the fakes cannot answer (Phase 4 hardware acceptance).

    The fake ECU answers whatever it is told to answer, so a green suite
    here says the scanner works — not that the Patrol behaves this way.
    Still unknown until the tool is run on the vehicle:

    - which transport the GU ZD30 diagnostic port actually speaks
      (CAN vs K-line; docs/PROTOCOLS.md flags earlier ZD30s as Consult-II
      era K-line)
    - the real supported-PID list, and whether MAP (0x0B) is among it
    - the poll rates the vehicle sustains, which no scan can measure
    - therefore config/vehicles/patrol_zd30_gu.yaml stays a stub
    """
    assert True
