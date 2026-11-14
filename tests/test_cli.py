from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from ontorag.cli import main
from ontorag.index import build_index
from tests.fixtures import write_fixture


class CliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.abox, cls.overlay = write_fixture(cls.tmp.name)
        cls.index_path = Path(cls.tmp.name) / "tiny.sqlite"
        build_index(
            abox=cls.abox,
            overlay=cls.overlay,
            index=cls.index_path,
            verbose=False,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def run_cli(self, *args: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(list(args))
        return code, stdout.getvalue(), stderr.getvalue()

    def test_show_meta(self) -> None:
        code, out, err = self.run_cli("show-meta", "--index", str(self.index_path))
        self.assertEqual(code, 0, err)
        self.assertIn("occupations: 1", out)

    def test_extract_json(self) -> None:
        code, out, err = self.run_cli(
            "extract",
            "--index",
            str(self.index_path),
            "--overlay",
            str(self.overlay),
            "--text",
            "Saya lulusan S1 dan suka pemrograman.",
        )
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["education_level"], "S1")
        self.assertTrue(payload["elements"])

    def test_recommend_json(self) -> None:
        code, out, err = self.run_cli(
            "recommend",
            "--index",
            str(self.index_path),
            "--overlay",
            str(self.overlay),
            "--reasoner",
            "sql",
            "--text",
            "Saya suka data dan pemrograman. Saya lulusan S1 dan job zone 4.",
            "--format",
            "json",
        )
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["recommendations"][0]["tier"], "Eligible")
        self.assertEqual(payload["recommendations"][0]["title_en"], "Data Scientist")


if __name__ == "__main__":
    unittest.main()
