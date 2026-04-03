#!/usr/bin/env python3
"""
gather_diff.py — Android Review skill helper

Collects the files and diff to be reviewed, runs ktlint if available,
and outputs a structured JSON manifest for the SKILL.md to consume.

Usage:
  python3 gather_diff.py --branch feature-branch main
  python3 gather_diff.py --file path/to/File.kt
  python3 gather_diff.py --staged          # review staged changes
  python3 gather_diff.py --unstaged        # review unstaged working tree changes
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


# ── Helpers ──────────────────────────────────────────────────────────────────

def run(cmd: list[str], cwd: str | None = None) -> tuple[int, str, str]:
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def find_git_root() -> Path | None:
    code, out, _ = run(["git", "rev-parse", "--show-toplevel"])
    return Path(out) if code == 0 else None


def is_kotlin_file(path: str) -> bool:
    return path.endswith(".kt") or path.endswith(".kts")


def is_reviewable(path: str) -> bool:
    """Exclude generated files, build outputs, and non-code assets."""
    skip_prefixes = ("build/", ".gradle/", "generated/", ".idea/")
    skip_suffixes = (".xml", ".json", ".png", ".webp", ".svg", ".md", ".toml")
    p = path.lower()
    if any(p.startswith(s) for s in skip_prefixes):
        return False
    if any(p.endswith(s) for s in skip_suffixes):
        return False
    return is_kotlin_file(path)


def get_file_content(git_root: Path, filepath: str) -> str:
    full = git_root / filepath
    try:
        return full.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def get_diff_for_file(git_root: Path, filepath: str, ref_a: str, ref_b: str) -> str:
    code, out, _ = run(
        ["git", "diff", f"{ref_a}...{ref_b}", "--", filepath],
        cwd=str(git_root),
    )
    return out if code == 0 else ""


def get_changed_files_branch(git_root: Path, feature: str, base: str) -> list[dict]:
    """Return changed Kotlin files between two branches with their diff."""
    code, out, err = run(
        ["git", "diff", "--name-status", f"{base}...{feature}"],
        cwd=str(git_root),
    )
    if code != 0:
        print(f"[gather_diff] git diff failed: {err}", file=sys.stderr)
        sys.exit(1)

    files = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        if len(parts) < 2:
            continue
        status, filepath = parts[0][0], parts[1]  # first char of status (A/M/D/R)
        if not is_reviewable(filepath):
            continue

        content = get_file_content(git_root, filepath) if status != "D" else ""
        diff = get_diff_for_file(git_root, filepath, base, feature)
        changed_lines = extract_changed_line_ranges(diff)

        files.append({
            "path": filepath,
            "status": {"A": "added", "M": "modified", "D": "deleted", "R": "renamed"}.get(status, "modified"),
            "changed_line_ranges": changed_lines,
            "diff": diff,
            "full_content": content,
        })
    return files


def get_single_file(git_root: Path, filepath: str) -> list[dict]:
    """Return a single file for review."""
    full = git_root / filepath
    if not full.exists():
        print(f"[gather_diff] File not found: {filepath}", file=sys.stderr)
        sys.exit(1)
    if not is_kotlin_file(filepath):
        print(f"[gather_diff] Not a Kotlin file: {filepath}", file=sys.stderr)
        sys.exit(1)

    content = full.read_text(encoding="utf-8", errors="replace")
    return [{
        "path": filepath,
        "status": "review",
        "changed_line_ranges": [],
        "diff": "",
        "full_content": content,
    }]


def get_staged_files(git_root: Path) -> list[dict]:
    code, out, _ = run(["git", "diff", "--cached", "--name-status"], cwd=str(git_root))
    if code != 0:
        return []
    return _parse_name_status(git_root, out, staged=True)


def get_unstaged_files(git_root: Path) -> list[dict]:
    code, out, _ = run(["git", "diff", "--name-status"], cwd=str(git_root))
    if code != 0:
        return []
    return _parse_name_status(git_root, out, staged=False)


def _parse_name_status(git_root: Path, output: str, staged: bool) -> list[dict]:
    files = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        if len(parts) < 2:
            continue
        status, filepath = parts[0][0], parts[1]
        if not is_reviewable(filepath):
            continue
        diff_args = ["git", "diff", "--cached" if staged else "", "--", filepath]
        diff_args = [a for a in diff_args if a]  # strip empty string
        _, diff, _ = run(diff_args, cwd=str(git_root))
        content = get_file_content(git_root, filepath) if status != "D" else ""
        files.append({
            "path": filepath,
            "status": "staged" if staged else "unstaged",
            "changed_line_ranges": extract_changed_line_ranges(diff),
            "diff": diff,
            "full_content": content,
        })
    return files


def extract_changed_line_ranges(diff: str) -> list[dict]:
    """Parse @@ -a,b +c,d @@ hunk headers to get new-file line ranges."""
    import re
    ranges = []
    for match in re.finditer(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", diff):
        start = int(match.group(1))
        count = int(match.group(2)) if match.group(2) is not None else 1
        if count > 0:
            ranges.append({"start": start, "end": start + count - 1})
    return ranges


# ── ktlint ────────────────────────────────────────────────────────────────────

def run_ktlint(git_root: Path, filepaths: list[str]) -> list[dict]:
    """Run ktlint if available and return a list of lint findings."""
    code, ktlint_path, _ = run(["which", "ktlint"])
    if code != 0:
        # Try common local paths
        local = git_root / "ktlint"
        if not local.exists():
            return []
        ktlint_path = str(local)

    relative_paths = [str(git_root / p) for p in filepaths]
    code, out, _ = run(
        [ktlint_path, "--reporter=json"] + relative_paths,
        cwd=str(git_root),
    )
    findings = []
    try:
        raw = json.loads(out)
        for file_result in raw:
            for error in file_result.get("errors", []):
                findings.append({
                    "file": file_result.get("file", ""),
                    "line": error.get("line", 0),
                    "column": error.get("column", 0),
                    "rule": error.get("rule", ""),
                    "message": error.get("message", ""),
                })
    except (json.JSONDecodeError, TypeError):
        pass
    return findings


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Gather Android files for review")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--branch", nargs=2, metavar=("FEATURE", "BASE"),
                      help="Review diff between feature and base branch")
    mode.add_argument("--file", metavar="PATH",
                      help="Review a single file")
    mode.add_argument("--staged", action="store_true",
                      help="Review staged (index) changes")
    mode.add_argument("--unstaged", action="store_true",
                      help="Review unstaged working tree changes")

    parser.add_argument("--no-ktlint", action="store_true",
                        help="Skip ktlint even if available")
    parser.add_argument("--depth", choices=["quick", "full"], default="full",
                        help="quick=blocking issues only, full=complete review")
    parser.add_argument("--focus", metavar="CATEGORY",
                        help="Restrict to one category: memory|compose|coroutines|arch|kotlin|security|lifecycle|threading|testing")

    args = parser.parse_args()

    git_root = find_git_root()
    if not git_root:
        print(json.dumps({"error": "Not inside a git repository"}))
        sys.exit(1)

    # Collect files
    if args.branch:
        feature, base = args.branch
        files = get_changed_files_branch(git_root, feature, base)
    elif args.file:
        files = get_single_file(git_root, args.file)
    elif args.staged:
        files = get_staged_files(git_root)
    else:
        files = get_unstaged_files(git_root)

    if not files:
        print(json.dumps({
            "error": "No reviewable Kotlin files found.",
            "hint": "Only .kt/.kts files outside build/ and generated/ are reviewed.",
        }))
        sys.exit(0)

    # ktlint pass
    ktlint_findings = []
    if not args.no_ktlint:
        reviewable_paths = [f["path"] for f in files if f["status"] != "deleted"]
        ktlint_findings = run_ktlint(git_root, reviewable_paths)

    manifest = {
        "git_root": str(git_root),
        "depth": args.depth,
        "focus": args.focus,
        "file_count": len(files),
        "files": files,
        "ktlint_findings": ktlint_findings,
        "ktlint_available": len(ktlint_findings) > 0 or not args.no_ktlint,
    }

    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
