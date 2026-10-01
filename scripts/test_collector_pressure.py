"""Check pressure and I/O counter parsing without a running stack."""

import importlib.util
import tempfile
import unittest
from pathlib import Path


spec = importlib.util.spec_from_file_location(
    "collector", Path(__file__).with_name("collect-debug-report.py"))
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


class PressureCountersTest(unittest.TestCase):
    def test_pressure_and_io_counters(self):
        with tempfile.TemporaryDirectory() as folder:
            pressure = Path(folder, "pressure")
            pressure.write_text(
                "some avg10=0.00 avg60=0.00 avg300=0.00 total=123\n"
                "full avg10=0.00 avg60=0.00 avg300=0.00 total=8\n")
            self.assertEqual(collector._read_pressure_totals(pressure),
                             {"some": 123, "full": 8})
            io = Path(folder, "io.stat")
            io.write_text("8:0 rbytes=12 wbytes=20 rios=1 wios=2\n"
                          "8:1 rbytes=4 wbytes=7 rios=3 wios=4\n")
            self.assertEqual(collector._read_io_totals(io),
                             {"rbytes": 16, "wbytes": 27, "rios": 4, "wios": 6})
            self.assertEqual(collector._read_pressure_totals(Path(folder, "absent")), {})

    def test_generation_change_invalidates_delta(self):
        def sample(generation, value):
            return {"containers": {"scanner": {
                "cgroup_generation": generation,
                "io": {"rbytes": value}}}}

        self.assertEqual(collector.nested_counter_delta(
            [sample(3, 12), sample(3, 21)], "scanner", "io", "rbytes"), 9)
        self.assertIsNone(collector.nested_counter_delta(
            [sample(3, 12), sample(4, 21)], "scanner", "io", "rbytes"))
        self.assertIsNone(collector.nested_counter_delta(
            [sample(3, 12), sample(3, 2)], "scanner", "io", "rbytes"))


if __name__ == "__main__":
    unittest.main()
