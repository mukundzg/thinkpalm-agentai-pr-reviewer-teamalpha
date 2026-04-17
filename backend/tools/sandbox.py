from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from subprocess import CompletedProcess
from subprocess import run

from backend.models import TestOutput


def _has_npm_test_script(package_json_path: Path) -> bool:
    try:
        raw = package_json_path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        scripts = parsed.get("scripts", {})
        return isinstance(scripts, dict) and isinstance(scripts.get("test"), str)
    except Exception:
        return False


def _collect_test_commands(repo_path: str) -> list[str]:
    root = Path(repo_path)
    commands: list[str] = []

    has_pytest = shutil.which("pytest") is not None
    has_npm = shutil.which("npm") is not None

    if has_pytest and (root / "backend").exists():
        commands.append("python -m pytest -q backend")
    elif has_pytest and ((root / "pytest.ini").exists() or (root / "pyproject.toml").exists()):
        commands.append("python -m pytest -q")

    frontend_package = root / "frontend" / "package.json"
    root_package = root / "package.json"
    if has_npm and frontend_package.exists() and _has_npm_test_script(frontend_package):
        commands.append("npm --prefix frontend run test -- --runInBand")
    elif has_npm and root_package.exists() and _has_npm_test_script(root_package):
        commands.append("npm run test -- --runInBand")

    return commands


def run_tests_in_sandbox(repo_path: str = ".") -> TestOutput:
    use_docker = os.getenv("TEST_RUNNER_MODE", "local").strip().lower() == "docker"
    if use_docker and shutil.which("docker"):
        command = (
            "docker run --rm --network none "
            "--memory=512m --cpus=1 "
            f"-v {repo_path}:/workspace -w /workspace python:3.11-slim "
            "bash -lc 'pytest -q || npm test -- --runInBand'"
        )
        result = run(command, shell=True, capture_output=True, text=True, check=False)
        errors = []
        if result.returncode != 0:
            errors = [line for line in result.stderr.splitlines() if line.strip()] or [
                "Tests failed in sandbox."
            ]
        return TestOutput(status="pass" if result.returncode == 0 else "fail", errors=errors, command=command)

    commands = _collect_test_commands(repo_path)
    if not commands:
        return TestOutput(
            status="pass",
            errors=[],
            command="No runnable tests detected (pytest/npm test unavailable or not configured).",
        )

    attempts: list[tuple[str, CompletedProcess[str]]] = []

    for command in commands:
        result = run(command, shell=True, capture_output=True, text=True, check=False, cwd=repo_path)
        attempts.append((command, result))
        if result.returncode == 0:
            return TestOutput(status="pass", errors=[], command=command)

    used = " || ".join(cmd for cmd, _ in attempts)
    errors: list[str] = []
    for command, result in attempts:
        stderr_lines = [line for line in result.stderr.splitlines() if line.strip()]
        if stderr_lines:
            errors.extend(stderr_lines[:8])
        elif result.stdout.strip():
            errors.extend([line for line in result.stdout.splitlines() if line.strip()][:8])
        else:
            errors.append(f"Command failed with exit code {result.returncode}: {command}")

    return TestOutput(status="fail", errors=errors[:20], command=used)
