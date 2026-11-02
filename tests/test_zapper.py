import contextlib
import csv
import io
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from zapper import ChangeDetector, main, read_value


class ChangeDetectorTests(unittest.TestCase):
    def test_increase_threshold_is_strict_and_event_is_not_repeated(self):
        detector = ChangeDetector()
        self.assertEqual(detector.update(1000000).status, "baseline")
        self.assertEqual(detector.update(1100000).status, "sample")
        self.assertEqual(detector.update(1200001).status, "candidate")
        self.assertEqual(detector.update(1200001).status, "sample")
        self.assertEqual(detector.update(900000).status, "sample")

    def test_decrease_mode(self):
        detector = ChangeDetector(threshold=10, direction="decrease")
        detector.update(100)
        self.assertEqual(detector.update(80).status, "candidate")
        self.assertEqual(detector.update(100).status, "sample")

    def test_unavailable_readings_clear_baseline(self):
        for value in (0, -1, float("nan"), float("inf")):
            with self.subTest(value=value):
                detector = ChangeDetector(threshold=10)
                detector.update(100)
                self.assertEqual(detector.update(value).status, "reset")
                self.assertEqual(detector.update(1000).status, "baseline")

    def test_invalid_configuration(self):
        for threshold in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                ChangeDetector(threshold=threshold)
        with self.assertRaises(ValueError):
            ChangeDetector(direction="unknown")


class MemoryTests(unittest.TestCase):
    def test_pointer_chain_for_both_widths(self):
        for bits, method in ((32, "read_uint"), (64, "read_ulonglong")):
            with self.subTest(bits=bits):
                memory = Mock()
                pointer = getattr(memory, method)
                pointer.side_effect = [0x80000000, 0x90000000, 0xA0000000]
                memory.read_int.return_value = 123
                self.assertEqual(read_value(memory, 0x100, (0x10, 0x20, 0x30), bits), 123)
                self.assertEqual([call.args[0] for call in pointer.call_args_list],
                                 [0x100, 0x80000010, 0x90000020])
                memory.read_int.assert_called_once_with(0xA0000030)

    def test_float_value(self):
        memory = Mock()
        memory.read_uint.return_value = 0x1000
        memory.read_float.return_value = 0.75
        self.assertEqual(read_value(memory, 0x100, (0x30,), value_type="float"), 0.75)
        memory.read_float.assert_called_once_with(0x1030)

    def test_null_pointers_do_not_read_value(self):
        for pointers in ([0], [0x1000, 0]):
            memory = Mock()
            memory.read_uint.side_effect = pointers
            with self.assertRaises(ValueError):
                read_value(memory, 0x100, (0x10, 0x20))
            memory.read_int.assert_not_called()

    def test_read_failure_is_not_converted_to_a_health_value(self):
        memory = Mock()
        memory.read_uint.side_effect = OSError("Memory unavailable")
        with self.assertRaises(OSError):
            read_value(memory, 0x100, (0x10,))


class CommandTests(unittest.TestCase):
    def test_live_failures_and_interrupt_close_the_process(self):
        for failure in (OSError("Memory unavailable"), KeyboardInterrupt()):
            with self.subTest(failure=type(failure).__name__):
                memory = Mock()
                package = types.ModuleType("pymem")
                package.Pymem = Mock(return_value=memory)
                package.process = types.ModuleType("pymem.process")
                package.process.module_from_name = Mock(return_value=Mock(lpBaseOfDll=0x1000))
                with patch.dict("sys.modules", {"pymem": package, "pymem.process": package.process}), \
                     patch("zapper.read_value", side_effect=failure), \
                     contextlib.redirect_stdout(io.StringIO()), \
                     contextlib.redirect_stderr(io.StringIO()):
                    result = main([])
                self.assertEqual(result, 0 if isinstance(failure, KeyboardInterrupt) else 1)
                memory.close_process.assert_called_once_with()

    @patch("zapper.time.sleep")
    def test_demo_records_values_and_does_not_overwrite_logs(self, sleep):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "samples.csv"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--demo", "--csv", str(path)]), 0)
            original = path.read_bytes()
            with path.open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 8)
            self.assertEqual(sum(row["status"] == "candidate" for row in rows), 1)
            self.assertTrue(all(row["source"] == "demo" for row in rows))
            self.assertEqual(rows[6]["status"], "baseline")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--demo", "--csv", str(path)]), 1)
            self.assertEqual(path.read_bytes(), original)

    def test_invalid_polling_interval(self):
        for interval in ("0", "-1", "nan", "inf"):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(["--demo", "--interval", interval])
            self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
