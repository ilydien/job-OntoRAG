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

    def test_requirements_json(self) -> None:
        code, out, err = self.run_cli(
            "requirements",
            "--index",
            str(self.index_path),
            "--occupation",
            "https://example.org/occupation/data-scientist",
            "--format",
            "json",
        )
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["occupation"]["title"], "Data Scientist")
        self.assertEqual(payload["education"]["local"], "S1")
        self.assertEqual(payload["job_zone"]["value"], 4)
        knowledge = next(
            item
            for item in payload["requirements"]
            if item["rating_type"] == "KnowledgeRating"
        )
        self.assertEqual(knowledge["items"][0]["label"], "Programming")

    def test_requirements_unknown_occupation(self) -> None:
        code, _out, err = self.run_cli(
            "requirements",
            "--index",
            str(self.index_path),
            "--occupation",
            "urn:missing",
        )
        self.assertEqual(code, 2)
        self.assertIn("unknown occupation", err)

    def test_extract_declared_skill(self) -> None:
        code, out, err = self.run_cli(
            "extract",
            "--index",
            str(self.index_path),
            "--overlay",
            str(self.overlay),
            "--text",
            "Saya suka data.",
            "--skill",
            "Programming=4",
        )
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["skill_levels"], {"https://example.org/element/programming": 4.0})

    def test_profile_json(self) -> None:
        code, out, err = self.run_cli(
            "profile",
            "--index",
            str(self.index_path),
            "--occupation",
            "https://example.org/occupation/data-scientist",
            "--format",
            "json",
        )
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["occupation"]["title_en"], "Data Scientist")
        self.assertEqual(payload["tasks"][0]["task"], "Build data models")

    def test_recommend_json(self) -> None:
        code, out, err = self.run_cli(
            "recommend",
            "--index",
            str(self.index_path),
            "--overlay",
            str(self.overlay),
            "--reasoner",
            "sql",
            "--retrieval",
            "lexical",
            "--text",
            "Saya suka data dan pemrograman. Saya lulusan S1 dan job zone 4.",
            "--format",
            "json",
        )
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["recommendations"][0]["tier"], "Eligible")
        self.assertEqual(payload["recommendations"][0]["title_en"], "Data Scientist")
        self.assertIn("description", payload["recommendations"][0])
        self.assertTrue(payload["recommendations"][0]["description"])


if __name__ == "__main__":
    unittest.main()
