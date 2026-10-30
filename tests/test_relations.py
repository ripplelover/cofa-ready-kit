import contextlib
import csv
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

from cofa_kit.__main__ import main
from cofa_kit.core import KitError
from cofa_kit.relations import join_audit

ROOT = Path(__file__).resolve().parents[1]


class JoinAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, text, encoding="utf-8"):
        path = self.root / name
        path.write_text(text, encoding=encoding)
        return path

    def audit(self, left, right, relationship="many_to_one", **kwargs):
        return join_audit(self.write("left.csv", left), self.write("right.csv", right),
                          left_key=["id"], right_key=["id"], relationship=relationship, **kwargs)

    def test_normal_many_to_one_preserves_left_rows(self):
        result = self.audit("id,value\na,3\na,4\nb,8\n", "id,label\na,A\nb,B\n")
        self.assertTrue(result["ok"])
        self.assertEqual(result["left"], dict(rows=3, distinct_keys=2, duplicate_keys=1, matched_rows=3, unmatched_rows=0))
        self.assertEqual(result["predicted_rows"], dict(inner=3, left=3, right=3, full=3))
        self.assertEqual(result["left_join_expansion_factor"], 1)

    def test_two_by_three_expansion_and_explicit_many_to_many(self):
        result = self.audit("id\nsecret-key\nsecret-key\n", "id\nsecret-key\nsecret-key\nsecret-key\n", "many_to_many")
        self.assertTrue(result["ok"])
        self.assertEqual(result["predicted_rows"]["inner"], 6)
        self.assertEqual(result["left_join_expansion_factor"], 3)
        self.assertGreaterEqual(len(result["warnings"]), 2)
        self.assertNotIn("secret-key", json.dumps(result))

    def test_expected_uniqueness_checks_unmatched_duplicates_too(self):
        result = self.audit("id\na\n", "id\na\nz\nz\n")
        self.assertFalse(result["ok"])
        self.assertEqual(result["issues"][0]["side"], "right")
        self.assertEqual(result["predicted_rows"]["left"], 1)
        result = self.audit("id\na\na\n", "id\na\n", "one_to_many")
        self.assertFalse(result["ok"])
        result = self.audit("id\na\na\n", "id\na\na\n", "one_to_one")
        self.assertEqual({issue["side"] for issue in result["issues"]}, {"left", "right"})

    def test_unmatched_rows_inner_left_right_and_full(self):
        result = self.audit("id\na\na\nb\n", "id\na\nc\n")
        self.assertEqual(result["left"]["unmatched_rows"], 1)
        self.assertEqual(result["right"]["unmatched_rows"], 1)
        self.assertEqual(result["predicted_rows"], dict(inner=2, left=3, right=3, full=4))

    def test_composite_keys_distinguish_reused_wafer_ids(self):
        left = self.write("left.csv", "lot,wafer\nL1,W1\nL2,W1\n")
        right = self.write("right.csv", "batch,item\nL1,W1\nL2,W1\n")
        result = join_audit(left, right, left_key=["lot", "wafer"], right_key=["batch", "item"], relationship="one_to_one")
        self.assertTrue(result["ok"])
        self.assertEqual(result["shared_keys"], 2)
        self.assertEqual(result["predicted_rows"]["inner"], 2)

    def test_keys_preserve_leading_zero_case_and_whitespace(self):
        result = self.audit("id\n001\n1\n a\na\nA\n", "id\n001\na\n", "one_to_one")
        self.assertEqual(result["left"]["distinct_keys"], 5)
        self.assertEqual(result["shared_keys"], 2)
        self.assertEqual(result["left"]["unmatched_rows"], 3)

    def test_missing_keys_schema_and_malformed_rows_rejected(self):
        for text in ("id\n \n", "id\n\n", "id,other\na\n", "other\na\n", "id,id\na,b\n", 'id\n"unfinished\n'):
            with self.subTest(text=text), self.assertRaises((KitError, csv.Error)):
                self.audit(text, "id\na\n")

    def test_full_scan_limit_and_empty_files(self):
        with self.assertRaisesRegex(KitError, "no partial"):
            self.audit("id\na\nb\n", "id\na\n", max_rows=1)
        with self.assertRaisesRegex(KitError, "no partial"):
            self.audit("id\na\n", "id\na\nb\n", max_rows=1)
        result = self.audit("id\n", "id\na\n", "one_to_one")
        self.assertIsNone(result["left_join_expansion_factor"])
        self.assertEqual(result["predicted_rows"], dict(inner=0, left=0, right=1, full=1))

    def test_invalid_options_and_key_lengths(self):
        left, right = self.write("left.csv", "id\na\n"), self.write("right.csv", "id\na\n")
        for kwargs in ({"left_key": []}, {"right_key": ["id", "id2"]}, {"relationship": "auto"},
                       {"max_rows": True}, {"max_rows": 100001}, {"encoding": "latin-1"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(KitError):
                join_audit(left, right, **dict({"left_key": ["id"], "right_key": ["id"], "relationship": "many_to_one"}, **kwargs))

    def test_cli_exit_codes_cp949_output_and_source_preservation(self):
        left = self.write("left.csv", "id\n장비\n", "cp949")
        right = self.write("right.csv", "id\n장비\n장비\n", "cp949")
        before = (left.read_bytes(), right.read_bytes())
        output = self.root / "result.json"
        args = ["data", "join-check", str(left), str(right), "--left-key", "id", "--right-key", "id",
                "--relationship", "many_to_one", "--encoding", "cp949", "--output", str(output)]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(args), 1)
            recorded = output.read_bytes()
            self.assertFalse(json.loads(recorded)["ok"])
            self.assertEqual(main(args), 2)
            self.assertEqual(output.read_bytes(), recorded)
            self.assertEqual(main(args[:-2] + ["--max-rows", "1"]), 2)
        self.assertEqual((left.read_bytes(), right.read_bytes()), before)


class JoinMCPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("join_mcp_server", ROOT / "scripts" / "mcp_server.py")
        cls.server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.server)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.parent = Path(self.temp.name).resolve()
        self.root = self.parent / "workspace"
        self.root.mkdir()
        (self.root / "left.csv").write_text("id\na\na\n", encoding="utf-8")
        (self.root / "right.csv").write_text("id\na\n", encoding="utf-8")
        self.args = {"left_path": "left.csv", "right_path": "right.csv", "left_key": ["id"], "right_key": ["id"], "relationship": "many_to_one"}

    def tearDown(self):
        self.temp.cleanup()

    def test_actual_tool_normal_and_contract_failure_return_diagnostics(self):
        reply = self.server.call_tool(self.root, "csv_join_audit", self.args)
        self.assertFalse(reply["isError"], reply)
        self.assertEqual(json.loads(reply["content"][0]["text"])["predicted_rows"]["left"], 2)
        (self.root / "right.csv").write_text("id\na\na\na\n", encoding="utf-8")
        reply = self.server.call_tool(self.root, "csv_join_audit", self.args)
        self.assertTrue(reply["isError"])
        data = json.loads(reply["content"][0]["text"])
        self.assertEqual(data["predicted_rows"]["inner"], 6)
        self.assertEqual(data["issues"][0]["side"], "right")

    def test_external_paths_and_invalid_arguments_are_rejected(self):
        outside = self.parent / "outside.csv"
        outside.write_text("id\na\n", encoding="utf-8")
        cases = ({"left_path": "../outside.csv"}, {"right_path": str(outside)}, {"left_key": "id"},
                 {"right_key": []}, {"right_key": ["id", "other"]}, {"relationship": []},
                 {"relationship": None}, {"max_rows": True}, {"max_rows": 10001},
                 {"encoding": "latin-1"}, {"output": "unexpected.json"})
        for patch in cases:
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                self.server.call_tool(self.root, "csv_join_audit", {**self.args, **patch})
        self.assertFalse((self.root / "unexpected.json").exists())


if __name__ == "__main__":
    unittest.main()
