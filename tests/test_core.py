import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from cofa_kit.__main__ import main
from cofa_kit.core import (KitError, append_log, check_workspace, contained_path,
                           init_workspace, profile_file, report_workspace, run_check)


class ToolkitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, text, encoding="utf-8"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding=encoding)
        return path

    def manifest(self, status="verified", evidence=None, required=None, priority="must"):
        value = {"required_files": required if required is not None else ["answer.txt"], "criteria": [
            {"id": "R1", "requirement": "Return correct totals", "priority": priority,
             "status": status, "evidence": evidence if evidence is not None else ["checks.txt"]}]}
        self.write("requirements.json", json.dumps(value))
        return value

    def test_init_does_not_overwrite_or_partially_write(self):
        self.write("decision-log.jsonl", "keep me")
        with self.assertRaises(KitError):
            init_workspace(self.root)
        self.assertFalse((self.root / "requirements.json").exists())
        self.assertEqual((self.root / "decision-log.jsonl").read_text(), "keep me")

    def test_initialized_work_is_not_reported_complete(self):
        init_workspace(self.root)
        result = check_workspace(self.root)
        self.assertFalse(result["ok"])
        report = report_workspace(self.root)
        self.assertIn("GAPS FOUND", report)
        self.assertIn("No decisions or test outcomes", report)

    def test_csv_profile_missing_duplicate_numeric(self):
        file = self.write("data.csv", "name,value\na,2\na,2\nb,\nc,text\n")
        result = profile_file(file)
        self.assertEqual(result["rows_sampled"], 4)
        self.assertEqual(result["total_rows"], 4)
        self.assertEqual(result["duplicate_rows_in_sample"], 1)
        column = result["columns"][1]
        self.assertEqual(column["missing"], 1)
        self.assertEqual(column["numeric"]["mean"], 2)
        self.assertEqual(column["non_numeric_non_missing"], 1)

    def test_csv_bound_does_not_claim_full_scan(self):
        file = self.write("data.csv", "value\n1\n2\n3\n4\n")
        result = profile_file(file, max_rows=2)
        self.assertEqual(result["rows_sampled"], 2)
        self.assertIsNone(result["total_rows"])
        self.assertTrue(result["truncated"])
        self.assertEqual(result["columns"][0]["numeric"]["max"], 2)

    def test_csv_bad_shape_and_duplicate_headers(self):
        for text in ("a,a\n1,2\n", "a,b\n1,2,3\n", 'a,b\n"unfinished,2\n'):
            with self.subTest(text=text), self.assertRaises((KitError, __import__('csv').Error)):
                profile_file(self.write("bad.csv", text))

    def test_cp949_and_utf8_bom(self):
        for encoding in ("cp949", "utf-8-sig"):
            file = self.write("data.csv", "항목,수량\n검사,3\n", encoding)
            result = profile_file(file, encoding=encoding)
            self.assertEqual(result["columns"][0]["name"], "항목")

    def test_json_sample_missing_nested_and_boolean(self):
        file = self.write("data.json", json.dumps([{"n": 1, "flag": True}, {"n": None}, {"n": 99}]))
        result = profile_file(file, max_rows=2)
        self.assertEqual(result["total_rows"], 3)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["columns"][0]["missing"], 1)
        self.assertIsNone(result["columns"][1]["numeric"])

    def test_json_rejects_duplicate_keys_and_nan(self):
        for text in ('[{"x": 1, "x": 2}]', '[{"x": NaN}]', '[3]'):
            with self.subTest(text=text), self.assertRaises(KitError):
                profile_file(self.write("bad.json", text))

    def test_invalid_limit(self):
        file = self.write("data.csv", "a\n1\n")
        for value in (0, -1, 100001, True):
            with self.subTest(value=value), self.assertRaises(KitError):
                profile_file(file, max_rows=value)

    def test_manifest_success_and_file_gaps(self):
        self.manifest()
        self.write("answer.txt", "result")
        self.write("checks.txt", "checked actual totals")
        self.assertTrue(check_workspace(self.root)["ok"])
        self.write("answer.txt", "")
        self.assertFalse(check_workspace(self.root)["ok"])
        (self.root / "checks.txt").unlink()
        self.assertTrue(any(i["type"] == "evidence" for i in check_workspace(self.root)["issues"]))

    def test_verified_needs_evidence_and_must_needs_verified(self):
        self.manifest(evidence=[], required=[])
        self.assertFalse(check_workspace(self.root)["ok"])
        self.manifest(status="in_progress", evidence=[], required=[])
        self.assertFalse(check_workspace(self.root)["ok"])
        self.manifest(status="blocked", evidence=[], required=[], priority="could")
        result = check_workspace(self.root)
        self.assertTrue(result["ok"])
        self.assertTrue(result["warnings"])

    def test_empty_criteria_not_success(self):
        self.write("requirements.json", '{"required_files": [], "criteria": []}')
        self.assertFalse(check_workspace(self.root)["ok"])

    def test_traversal_rejected_portably(self):
        for path in ("../outside.txt", "a/../../outside.txt", "..\\outside.txt", "C:\\data.txt", "/etc/passwd"):
            with self.subTest(path=path), self.assertRaises(KitError):
                contained_path(self.root, path)

    def test_symlink_escape_rejected(self):
        with tempfile.TemporaryDirectory() as other:
            target = Path(other) / "outside.txt"
            target.write_text("private")
            link = self.root / "link.txt"
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("This OS account cannot create symlinks")
            with self.assertRaises(KitError):
                contained_path(self.root, "link.txt")

    def test_log_and_report_preserve_observed_failure(self):
        init_workspace(self.root)
        self.write("failure.txt", "expected 7, found 8")
        append_log(self.root, "test", "FAILED: wrong total", ["failure.txt"])
        report = report_workspace(self.root)
        self.assertIn("FAILED: wrong total", report)
        self.assertIn("failure.txt", report)
        with self.assertRaises(KitError):
            append_log(self.root, "test", "not run", ["missing.txt"])

    def test_manifest_shape_and_duplicate_id_rejected(self):
        self.write("requirements.json", '{"required_files": "x", "criteria": []}')
        with self.assertRaises(KitError):
            check_workspace(self.root)
        value = self.manifest()
        value["criteria"].append(dict(value["criteria"][0]))
        self.write("requirements.json", json.dumps(value))
        with self.assertRaises(KitError):
            check_workspace(self.root)

    def test_cli_exit_codes_and_output_no_overwrite(self):
        init_workspace(self.root)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["check", "--workspace", str(self.root)]), 1)
            self.assertEqual(main(["check", "--workspace", str(self.root), "--manifest", "absent.json"]), 2)
            file = self.write("sample.csv", "x\n1\n")
            output = self.write("keep.json", "original")
            self.assertEqual(main(["profile", str(file), "--output", str(output)]), 2)
            self.assertEqual(output.read_text(), "original")

    def test_run_records_real_failure_without_updating_status(self):
        init_workspace(self.root)
        result = run_check(self.root, "R1", [sys.executable, "-c", "import sys; print('observed failure'); sys.exit(7)"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["exit_code"], 7)
        evidence = self.root / result["evidence_directory"]
        self.assertIn("observed failure", (evidence / "stdout.txt").read_text())
        self.assertFalse(check_workspace(self.root)["ok"])
        self.assertEqual(json.loads((self.root / "requirements.json").read_text())["criteria"][0]["status"], "todo")

    def test_run_timeout_and_bounded_output(self):
        init_workspace(self.root)
        result = run_check(self.root, "R1", [sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.1)
        self.assertFalse(result["ok"])
        self.assertTrue(result["timed_out"])
        result = run_check(self.root, "R1", [sys.executable, "-c", "print('x' * 100000)"], max_output_bytes=1024)
        self.assertTrue(result["ok"])
        self.assertTrue(result["output_truncated"]["stdout"])
        self.assertEqual(result["captured_bytes"]["stdout"], 1024)
        self.assertLessEqual((self.root / result["evidence_directory"] / "stdout.txt").stat().st_size, 1024)

    def test_run_no_tests_or_all_skipped_is_not_success(self):
        init_workspace(self.root)
        for output in ("Ran 0 tests in 0.000s\nOK", "Ran 2 tests in 0.000s\nOK (skipped=2)", "1 skipped in 0.01s"):
            with self.subTest(output=output):
                result = run_check(self.root, "R1", [sys.executable, "-c", f"print({output!r})"])
                self.assertEqual(result["exit_code"], 0)
                self.assertFalse(result["ok"])

    def test_run_preserves_binary_output_bound_and_reported_failures(self):
        init_workspace(self.root)
        result = run_check(self.root, "R1", [sys.executable, "-c", "import sys; sys.stdout.buffer.write(bytes([255]) * 5000)"], max_output_bytes=1024)
        self.assertEqual((self.root / result["evidence_directory"] / "stdout.txt").stat().st_size, 1024)
        result = run_check(self.root, "R1", [sys.executable, "-c", "print('1 failed, 2 passed in 0.01s')"])
        self.assertEqual(result["exit_code"], 0)
        self.assertFalse(result["ok"])

    def test_run_normal_test_and_unknown_criterion(self):
        init_workspace(self.root)
        result = run_check(self.root, "R1", [sys.executable, "-c", "print('Ran 2 tests in 0.001s\\nOK')"])
        self.assertTrue(result["ok"])
        with self.assertRaises(KitError):
            run_check(self.root, "missing", [sys.executable, "--version"])


if __name__ == "__main__":
    unittest.main()
