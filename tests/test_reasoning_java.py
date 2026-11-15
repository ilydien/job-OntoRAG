from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ontorag import config
from ontorag import reasoning
from ontorag.reasoning import (
    JAVA_ENV,
    configure_java_environment,
    resolve_java_executable,
)


def _write_java(home: Path) -> Path:
    binary = home / "bin" / "java"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o755)
    return binary


class JavaResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.java_a = _write_java(self.root / "a")
        self.java_b = _write_java(self.root / "b")
        self.java_c = _write_java(self.root / "c")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _resolve(self, env: dict, bundled: Path | None = None) -> Path | None:
        bundled = bundled or (self.root / "missing-jre")
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(
            config, "BUNDLED_JRE", bundled
        ), mock.patch.object(config, "PROJECT_ROOT", self.root), mock.patch.object(
            reasoning.shutil, "which", return_value=None
        ):
            return resolve_java_executable()

    def test_explicit_env_wins_over_java_home(self) -> None:
        resolved = self._resolve(
            {JAVA_ENV: str(self.java_a), "JAVA_HOME": str(self.java_b.parent.parent)}
        )
        self.assertEqual(resolved, self.java_a.resolve())

    def test_explicit_env_accepts_home_directory(self) -> None:
        resolved = self._resolve({JAVA_ENV: str(self.java_a.parent.parent)})
        self.assertEqual(resolved, self.java_a.resolve())

    def test_java_home_is_used_without_explicit_env(self) -> None:
        resolved = self._resolve({"JAVA_HOME": str(self.java_b.parent.parent)})
        self.assertEqual(resolved, self.java_b.resolve())

    def test_bundled_jre_is_used_as_fallback(self) -> None:
        resolved = self._resolve({}, bundled=self.java_c.parent.parent)
        self.assertEqual(resolved, self.java_c.resolve())

    def test_missing_runtime_returns_none(self) -> None:
        self.assertIsNone(self._resolve({}))

    def test_non_executable_candidate_is_ignored(self) -> None:
        binary = self.root / "plain" / "bin" / "java"
        binary.parent.mkdir(parents=True)
        binary.write_text("not executable", encoding="utf-8")
        binary.chmod(0o644)
        self.assertIsNone(self._resolve({JAVA_ENV: str(binary)}))

    def test_configure_sets_java_home_and_path(self) -> None:
        env = {"PATH": "/usr/bin", JAVA_ENV: str(self.java_a)}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(
            config, "BUNDLED_JRE", self.root / "missing-jre"
        ), mock.patch.object(config, "PROJECT_ROOT", self.root), mock.patch.object(
            reasoning.shutil, "which", return_value=None
        ):
            java = configure_java_environment()
            self.assertEqual(java, self.java_a.resolve())
            self.assertEqual(os.environ["JAVA_HOME"], str(self.java_a.parent.parent))
            self.assertEqual(
                os.environ["PATH"], str(self.java_a.parent) + os.pathsep + "/usr/bin"
            )

    def test_repository_bundled_jre_is_detected(self) -> None:
        binary = config.BUNDLED_JRE / "bin" / "java"
        if not binary.exists():
            self.skipTest("no bundled JRE in this copy of the project")
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
            reasoning.shutil, "which", return_value=None
        ):
            self.assertEqual(resolve_java_executable(), binary.resolve())


if __name__ == "__main__":
    unittest.main()
