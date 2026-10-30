import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from cofa_kit.__main__ import main
from cofa_kit.core import KitError
from cofa_kit.semiconductor import spc_summary, yield_summary


class SemiconductorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, text, encoding="utf-8"):
        file = self.root / "input.csv"
        file.write_text(text, encoding=encoding)
        return file

    def yield_for(self, records, **kwargs):
        return yield_summary(self.write("lot_id,wafer_id,tool_id,tested,passed\n" + records), group_by=["tool_id"], key=["lot_id", "wafer_id"], **kwargs)

    def series_for(self, values, **kwargs):
        records = "timestamp,tool_id,value\n" + "".join(f"2026-01-01T00:{i:02}:00+09:00,A,{value}\n" for i, value in enumerate(values))
        return spc_summary(self.write(records), value_col="value", time_col="timestamp", baseline_count=3, **kwargs)

    def test_weighted_yield_not_mean_of_percentages(self):
        result = self.yield_for("L1,W1,A,100,99\nL1,W2,A,2,1\n")
        self.assertEqual(result["totals"]["tested"], 102)
        self.assertEqual(result["totals"]["passed"], 100)
        self.assertAlmostEqual(result["totals"]["pass_rate_pct"], 10000 / 102)
        self.assertNotAlmostEqual(result["totals"]["pass_rate_pct"], 74.5)

    def test_zero_denominator_and_no_data_are_unknown(self):
        result = self.yield_for("L1,W1,A,0,0\n")
        self.assertIsNone(result["totals"]["pass_rate"])
        self.assertIsNone(result["groups"][0]["pass_rate_pct"])
        self.assertIsNone(self.yield_for("")["totals"]["pass_rate"])

    def test_duplicate_keys_and_invalid_counts_fail(self):
        records = ["L1,W1,A,100,99\nL1,W1,B,100,100\n", "L1,W1,A,1,2\n", "L1,W1,A,-1,0\n", "L1,W1,A,1.0,1\n", "L1,W1,A,,1\n", "L1,,A,1,1\n", "L1,W1,,1,1\n"]
        for value in records:
            with self.subTest(value=value), self.assertRaises(KitError):
                self.yield_for(value)

    def test_group_and_key_multiple_columns(self):
        file = self.write("lot,wafer,tool,product,n,good\nL,W1,A,P,10,8\nL,W2,A,Q,5,5\n")
        result = yield_summary(file, group_by=["tool", "product"], key=["lot", "wafer"], tested_col="n", passed_col="good")
        self.assertEqual(len(result["groups"]), 2)
        self.assertEqual(result["totals"]["passed"], 13)

    def test_limit_rejects_partial_analysis(self):
        with self.assertRaisesRegex(KitError, "no partial"):
            self.yield_for("L1,W1,A,1,1\nL1,W2,A,1,1\n", max_rows=1)
        with self.assertRaisesRegex(KitError, "no partial"):
            self.series_for([10, 11, 10, 14], max_rows=3)

    def test_spc_hand_calculation_and_boundary_transition(self):
        result = self.series_for([10, 11, 10, 14])
        baseline = result["baseline"]
        self.assertAlmostEqual(baseline["mean"], 31 / 3)
        self.assertEqual(baseline["mr_bar"], 1)
        self.assertAlmostEqual(baseline["i_ucl"], 31 / 3 + 3 / 1.128)
        self.assertAlmostEqual(baseline["mr_ucl"], 3.267)
        point = result["evaluation"][0]
        self.assertEqual(point["moving_range"], 4)
        self.assertTrue(point["i_signal"])
        self.assertTrue(point["mr_signal"])

    def test_future_points_do_not_change_baseline(self):
        first = self.series_for([10, 11, 10, 14])["baseline"]
        second = self.series_for([10, 11, 10, 1000, -1000])["baseline"]
        self.assertEqual(first, second)

    def test_zero_moving_range_is_indeterminate(self):
        result = self.series_for([10, 10, 10, 10, 20])
        self.assertEqual(result["status"], "indeterminate")
        self.assertIsNone(result["baseline"]["i_ucl"])
        for point in result["evaluation"]:
            self.assertIsNone(point["i_signal"])
            self.assertIsNone(point["mr_signal"])

    def test_unsorted_tied_and_mixed_zone_timestamps_fail(self):
        for times in (["00:01:00Z", "00:00:00Z", "00:02:00Z"], ["00:00:00Z", "00:00:00Z", "00:01:00Z"], ["00:00:00", "00:01:00Z", "00:02:00Z"], ["00:00:00+09:00", "00:01:00+00:00", "00:02:00+00:00"]):
            with self.subTest(times=times), self.assertRaises(KitError):
                file = self.write("timestamp,value\n" + "".join(f"2026-01-01T{t},10\n" for t in times))
                spc_summary(file, value_col="value", time_col="timestamp", baseline_count=3)

    def test_nonfinite_missing_and_mixed_series_fail(self):
        for values in ([10, "nan", 10], [10, "inf", 10], [10, "", 10]):
            with self.subTest(values=values), self.assertRaises(KitError):
                self.series_for(values)
        file = self.write("timestamp,tool_id,value\n2026-01-01T00:00:00Z,A,10\n2026-01-01T00:01:00Z,B,11\n2026-01-01T00:02:00Z,A,10\n")
        with self.assertRaisesRegex(KitError, "mixed series"):
            spc_summary(file, value_col="value", time_col="timestamp", baseline_count=3)

    def test_explicit_identity_missing_and_small_baseline_fail(self):
        file = self.write("timestamp,value\n2026-01-01T00:00:00Z,10\n")
        with self.assertRaisesRegex(KitError, "Missing columns"):
            spc_summary(file, value_col="value", time_col="timestamp", baseline_count=3, series_cols=["batch"])
        with self.assertRaises(KitError):
            spc_summary(file, value_col="value", time_col="timestamp", baseline_count=2)

    def test_synthetic_fixture_matches_independent_expected_values(self):
        fixtures = Path(__file__).resolve().parents[1] / "examples" / "semiconductor"
        expected = json.loads((fixtures / "expected.json").read_text())
        result = yield_summary(fixtures / "yield_clean.csv", group_by=["tool_id"], key=["lot_id", "wafer_id"])
        self.assertAlmostEqual(result["totals"]["pass_rate_pct"], expected["yield_clean"]["totals"]["pass_rate_pct"])
        result = spc_summary(fixtures / "measurements.csv", value_col="value", time_col="timestamp", baseline_count=25)
        baseline = expected["measurements_baseline_25"]
        for name in ("mean", "mr_bar", "i_lcl", "i_ucl", "mr_ucl"):
            self.assertAlmostEqual(result["baseline"][name], baseline[name])
        for actual, target in zip(result["evaluation"], baseline["evaluation"]):
            self.assertTrue(all(actual[key] == value for key, value in target.items()))

    def test_cli_cp949_output_and_no_overwrite(self):
        file = self.write("lot,tool,tested,passed\n묶음,장비,10,9\n", "cp949")
        output = self.root / "result.json"
        argv = ["semi", "yield", str(file), "--group-by", "tool", "--key", "lot", "--encoding", "cp949", "--output", str(output)]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(argv), 0)
            before = output.read_bytes()
            self.assertEqual(main(argv), 2)
            self.assertEqual(output.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
