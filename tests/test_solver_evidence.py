"""Publication guardrails, using no private game dependencies."""
import gzip
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("export_solver_evidence", Path(__file__).resolve().parents[1] / "tools/export_solver_evidence.py")
E = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(E)


class SolverEvidenceTests(unittest.TestCase):
    def test_longest_path_wins_and_json_stays_valid(self):
        paths = {r"C:\Users\Dev": "<HOME>", r"C:\Users\Dev\repo": "<REPO>"}
        text = E.sanitize(r"C:\Users\Dev\repo file", paths)
        self.assertEqual(text, "<REPO> file")

    def test_json_unicode_and_jvm_uri_paths_are_redacted(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "мод каталог"
            paths = E.replacements(root)
            value = {"path": str(root / "classes")}
            cleaned = json.loads(E.sanitize(json.dumps(value), paths))
            self.assertEqual(cleaned["path"], "<REPO>" + str(root / "classes")[len(str(root)):])
            uri = E.sanitize(root.as_uri() + "/classes", paths)
            self.assertIn("<REPO>", uri)
            self.assertNotIn("%d0", uri.lower())

    def test_known_soft_wrapped_log_path_is_redacted(self):
        paths = {"E:/SteamLibrary/steamapps/common/ProjectZomboid": "<GAME>"}
        text = "file:/E:/SteamLibrary/st\neamapps/common/ProjectZomboid/file.jar"
        self.assertEqual(E.sanitize(text, paths, True), "file:/<GAME>/file.jar")
        self.assertEqual(E.sanitize(text, paths), text)

    def test_credentials_are_rejected(self):
        with self.assertRaises(ValueError):
            E.sanitize("ghp_" + "x" * 30, {})
        with self.assertRaises(ValueError):
            E.sanitize("-----BEGIN RSA PRIVATE KEY-----", {})

    def test_unknown_home_is_rejected(self):
        for text in (r"C:\Users\Other\cache", json.dumps({"path": r"C:\Users\Other\cache"}), "/home/other/cache"):
            with self.assertRaises(ValueError):
                E.sanitize(text, {})

    def test_compressed_json_preserves_all_numeric_samples(self):
        with tempfile.TemporaryDirectory() as d:
            source, target = Path(d) / "raw.json", Path(d) / "raw.json.gz"
            value = {"apiNs": [0, 1, 999999999, 1000000000], "checksum": "abcdef0000000000"}
            source.write_text(json.dumps(value), encoding="utf-8")
            first = E.export_file(source, target, {}, True)
            self.assertEqual(json.loads(gzip.decompress(target.read_bytes())), value)
            self.assertEqual(first, E.export_file(source, target, {}, True))

    def test_utf16_logs_are_readable(self):
        self.assertEqual(E.decode("тест".encode("utf-16")), "тест")

    def test_invalid_encoding_is_not_silently_corrupted(self):
        with self.assertRaises(UnicodeDecodeError):
            E.decode(b"\x81")

    def test_invalid_json_fails_before_output_creation(self):
        with tempfile.TemporaryDirectory() as d:
            source, output = Path(d) / "bad.json", Path(d) / "export"
            source.write_text("{bad", encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                E.main(["--log", str(source), "--output", str(output)])
            self.assertFalse(output.exists())

    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit):
                E.main(["--output", d])


if __name__ == "__main__":
    unittest.main()
