"""Fast benchmark-report tests (no Java/game required).

Run: .venv/Scripts/python.exe -B -m unittest discover -s tests -p test_solver_bench.py -v
Real-dependency smoke runs use tools/solver_bench.py; they never replace these
schema/statistics checks. All test inputs below are synthetic nanoseconds.
"""
import contextlib
import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("solver_bench", ROOT / "tools/solver_bench.py")
bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)


def fixture(offset=0, idle=False):
    def run(value):
        return {"apiNs": [value] * 4, "inputUpdateNs": [10] * 4,
                "seedReadNs": [2] * 4, "checksumNs": [20] * 4,
                "prepareNs": 0 if idle else 100, "releaseNs": 0 if idle else 20,
                "fixtureNs": 0 if idle else 300, "apiCalls": 0 if idle else 4,
                "checksum": "0123456789abcdef", "releasedChecksum": "fedcba9876543210",
                "diagnostics": {"sumSolverIterations": 0 if idle else 50, "maxResidual": 0.0,
                    "gapTicks": 0, "obstructedTicks": 0, "unconvergedTicks": 0, "fallbackTicks": 0,
                    "nonzeroLoadTicks": 0 if idle else 3, "maxAbsLoad": 0.0 if idle else 10.0}}
    modes = []
    for api in (["no-call"] if idle else ["solve", "solvePersistent"]):
        modes.append({"api": api, "pairs": [
            {"replica": rep, "order": "AB" if (rep + offset) % 2 == 0 else "BA",
             "baseline": run(100 + rep * 100), "current": run(50 + rep * 50), "checksumsMatch": True}
            for rep in range(2)]})
    return {"schema": 2, "ticks": 4, "repeats": 2, "orderOffset": offset,
            "result": "pass", "bridgeDiagnostics": [] if idle else [
                {"index": 12, "api": api,
                 "baseline": {"bodyReadNs": [20] * 4, "bodyPublicationNs": [10] * 4, "checksum": "0123456789abcdef"},
                 "current": {"bodyReadNs": [20] * 4, "bodyPublicationNs": [10] * 4, "checksum": "0123456789abcdef"}}
                for api in ("solve", "solvePersistent")],
            "scenarios": [{"index": 17 if idle else 12,
                "name": "idle-no-call" if idle else "chain4", "groups": 0 if idle else 1,
                "bodiesPerGroup": 0 if idle else 4, "modes": modes}]}


class StatisticsTests(unittest.TestCase):
    def test_quantiles_and_even_median(self):
        stats = bench.describe(list(range(1, 21)))
        self.assertEqual(stats["median"], 10.5)
        self.assertEqual(stats["p95"], 19)
        self.assertEqual(stats["p99"], 20)
        self.assertEqual(stats["max"], 20)
        self.assertEqual(stats["range"], 19)
        self.assertGreater(stats["stdev"], 0)
        self.assertEqual(bench.describe([7])["stdev"], 0)
        with self.assertRaises(ValueError):
            bench.describe([])

    def test_paired_ratios_not_ratio_of_unpaired_minima(self):
        data = fixture()
        pair = data["scenarios"][0]["modes"][0]["pairs"][1]
        pair["current"]["apiNs"] = [400] * 4
        results = bench.aggregate([data, fixture(1)])
        first = results[0]
        self.assertEqual([r["paired_old_over_new"]["total"] for r in first["replicas"]], [2, .5, 2, 2])
        self.assertEqual(first["forks"][0]["paired_total_ratio"], 1.25)
        self.assertEqual(first["between_fork_spread"]["paired_total_ratio"]["n"], 2)
        self.assertEqual(first["between_fork_spread"]["baseline_median_ns"]["n"], 2)
        self.assertEqual(first["order_sensitivity"]["AB"]["n"], 2)
        self.assertEqual(first["order_sensitivity"]["BA"]["n"], 2)

    def test_zero_timer_denominator_is_not_infinite_speedup(self):
        data = fixture()
        for pair in data["scenarios"][0]["modes"][0]["pairs"]:
            pair["current"]["apiNs"] = [0] * 4
        result = bench.aggregate([data])[0]
        self.assertIsNone(result["replicas"][0]["paired_old_over_new"]["total"])
        self.assertIsNone(result["between_fork_spread"]["paired_total_ratio"])

    def test_idle_has_no_speedup_claim(self):
        data = fixture(idle=True)
        self.assertTrue(bench.validate_fork(data))
        row = bench.aggregate([data])[0]
        self.assertIsNone(row["replicas"][0]["paired_old_over_new"])
        self.assertIsNone(row["between_fork_spread"]["paired_total_ratio"])


class SchemaTests(unittest.TestCase):
    def test_canonical_hash_and_byte_hash_are_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.txt"
            path.write_bytes(b"\xef\xbb\xbfa\r\nb\r\n")
            self.assertEqual(bench.canonical_sha256(path), hashlib.sha256(b"a\nb\n").hexdigest())
            self.assertNotEqual(bench.sha256_file(path), bench.canonical_sha256(path))

    def test_checksums_repeat_across_forks_and_replicas(self):
        data = fixture()
        self.assertTrue(bench.checksums_reproducible([data, fixture(1)]))
        pair = data["scenarios"][0]["modes"][0]["pairs"][1]
        for side in ("baseline", "current"):
            pair[side]["checksum"] = "0000000000000000"
        self.assertTrue(bench.validate_fork(data))  # old/new still equal
        self.assertFalse(bench.checksums_reproducible([data]))  # but sequence not reproducible

    def test_both_apis_and_balanced_order(self):
        self.assertTrue(bench.validate_fork(fixture()))
        self.assertTrue(bench.validate_fork(fixture(1)))

    def test_reject_truncated_negative_and_fractional_ticks(self):
        for values in ([1], [1, 2, 3, -1], [1, 2, 3, 1.5]):
            data = fixture()
            data["scenarios"][0]["modes"][0]["pairs"][0]["baseline"]["apiNs"] = values
            with self.assertRaises(ValueError):
                bench.validate_fork(data)

    def test_missing_mode_and_wrong_order_rejected(self):
        data = fixture()
        data["scenarios"][0]["modes"].pop()
        with self.assertRaises(ValueError):
            bench.validate_fork(data)
        data = fixture()
        data["scenarios"][0]["modes"][0]["pairs"][1]["order"] = "AB"
        with self.assertRaises(ValueError):
            bench.validate_fork(data)

    def test_checksum_mismatch_and_flag_tamper(self):
        data = fixture()
        pair = data["scenarios"][0]["modes"][0]["pairs"][0]
        pair["current"]["releasedChecksum"] = "0000000000000000"
        with self.assertRaises(ValueError):
            bench.validate_fork(data)
        pair["checksumsMatch"] = False
        self.assertFalse(bench.validate_fork(data))

    def test_bridge_is_separate_and_both_apis_required(self):
        data = fixture()
        rows = bench.aggregate_bridges([data, fixture(1)])
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["baseline"]["bodyPublicationNs"]["median"], 10)
        data["bridgeDiagnostics"].pop()
        with self.assertRaises(ValueError):
            bench.validate_fork(data)
        data = fixture()
        data["bridgeDiagnostics"][0]["current"]["bodyReadNs"] = [1]
        with self.assertRaises(ValueError):
            bench.validate_fork(data)

    def test_bridge_checksum_mismatch_fails_result(self):
        data = fixture()
        data["bridgeDiagnostics"][0]["current"]["checksum"] = "0000000000000000"
        self.assertFalse(bench.validate_fork(data))
        data["bridgeDiagnostics"][0]["current"]["checksum"] = "invalid"
        with self.assertRaises(ValueError):
            bench.validate_fork(data)

    def test_diagnostics_cannot_claim_work_in_idle(self):
        data = fixture(idle=True)
        data["scenarios"][0]["modes"][0]["pairs"][0]["current"]["diagnostics"]["sumSolverIterations"] = 1
        with self.assertRaises(ValueError):
            bench.validate_fork(data)

    def test_call_count_and_lifecycle_control(self):
        data = fixture(idle=True)
        data["scenarios"][0]["modes"][0]["pairs"][0]["current"]["apiCalls"] = 4
        with self.assertRaises(ValueError):
            bench.validate_fork(data)
        data = fixture(idle=True)
        data["scenarios"][0]["modes"][0]["pairs"][0]["current"]["prepareNs"] = 1
        with self.assertRaises(ValueError):
            bench.validate_fork(data)

    def test_fork_layout_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            bench.aggregate([fixture(), fixture(idle=True)])

    def test_cli_defaults_and_filters(self):
        args = bench.parse_args([])
        self.assertEqual(args.forks, 4)
        self.assertEqual(args.repeats, 4)
        self.assertGreaterEqual(args.ticks, 900)
        self.assertEqual(bench.parse_args(["--scenarios", "17, 0,12"]).scenarios, "0,12,17")
        for args in (["--ticks", "0"], ["--forks", "0"], ["--warmup", "-1"],
                     ["--scenarios", "18"], ["--scenarios", "1,1"], ["--scenarios", ""]):
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                bench.parse_args(args)


if __name__ == "__main__":
    unittest.main()
