from __future__ import annotations

import json
import tempfile
from pathlib import Path
from subprocess import CompletedProcess, run


def _run_command(command: list[str], cwd: str | None = None) -> CompletedProcess[str]:
    return run(command, capture_output=True, text=True, check=False, cwd=cwd)


def _looks_like_git_diff(code: str) -> bool:
    sample = code[:2000]
    return sample.startswith("diff --git") or "\ndiff --git " in sample or "\n@@ " in sample


def run_linter(code: str, language: str = "python") -> list[dict]:
    with tempfile.TemporaryDirectory() as tmp_dir:
        if language == "python":
            # Pylint expects valid Python source, not git patch format.
            if _looks_like_git_diff(code):
                return []
            src = Path(tmp_dir) / "snippet.py"
            src.write_text(code, encoding="utf-8")
            result = _run_command(["pylint", "--output-format=json", str(src)])
            if result.returncode not in (0, 16, 32):
                return [{"type": "tool", "message": result.stderr.strip() or result.stdout.strip()}]
            try:
                data = json.loads(result.stdout or "[]")
            except json.JSONDecodeError:
                return []
            return [
                {
                    "type": "style" if item.get("type") in {"convention", "refactor"} else "bug",
                    "line": item.get("line"),
                    "message": item.get("message", ""),
                    "symbol": item.get("symbol", ""),
                }
                for item in data
            ]

        if language == "javascript":
            src = Path(tmp_dir) / "snippet.js"
            src.write_text(code, encoding="utf-8")
            result = _run_command(["eslint", "--format", "json", str(src)])
            if result.returncode not in (0, 1):
                return [{"type": "tool", "message": result.stderr.strip() or result.stdout.strip()}]
            try:
                data = json.loads(result.stdout or "[]")
            except json.JSONDecodeError:
                return []
            messages = data[0].get("messages", []) if data else []
            return [
                {
                    "type": "style",
                    "line": item.get("line"),
                    "message": item.get("message", ""),
                    "rule_id": item.get("ruleId"),
                }
                for item in messages
            ]

    return []
