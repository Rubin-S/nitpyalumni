"""Reject operational data from source control, including already tracked ignored files."""
import csv
import re
from pathlib import Path
import subprocess
import sys


def find_violations(root):
    tracked = subprocess.check_output(["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"])
    violations = []
    for raw in tracked.split(b"\0"):
        if not raw:
            continue
        name = raw.decode("utf-8")
        path = root / name
        if not path.is_file():  # Pending deletions in a local checkout.
            continue
        lower = path.name.lower()
        forbidden = (
            lower.endswith((".log", ".sqlite", ".sqlite3", ".db", ".sql", ".dump", ".pyc", ".pyo"))
            or "__pycache__" in path.relative_to(root).parts
            or lower in {".env", "cli.yaml"}
            or (lower.startswith(".env.") and lower != ".env.example")
            or "backups" in path.relative_to(root).parts
            or (lower.startswith("backup") and lower.endswith((".csv", ".tsv", ".json", ".zip", ".gz")))
        )
        if not forbidden and lower.endswith((".csv", ".tsv")):
            with path.open(encoding="utf-8-sig", errors="replace", newline="") as stream:
                header = {column.strip().lower() for column in next(csv.reader(stream, delimiter="\t" if lower.endswith(".tsv") else ","), [])}
            forbidden = bool(header & {"email", "email_id", "phone", "phone_number", "present_address", "password"})
        if not forbidden and lower.endswith((".py", ".js", ".html", ".yaml", ".yml")):
            source = path.read_text(encoding="utf-8", errors="replace")
            # Match the credential forms found in this repository's history.
            # Report filenames only; never print the credential itself.
            patterns = (
                r'mongodb(?:\+srv)?://[^\s"\'<>]*:[^\s"\'<>]*@',
                r'EMAIL_HOST_PASSWORD\s*=\s*["\'][^"\']+["\']',
                r'(?i)(?:api_token|CF_API_TOKEN)\s*=\s*["\'][A-Za-z0-9_-]{20,}["\']',
            )
            forbidden = any(re.search(pattern, source) for pattern in patterns)
        if forbidden:
            violations.append(name)
    return sorted(violations)


def main():
    violations = find_violations(Path.cwd())
    if violations:
        print("Operational or personal data must not be tracked:\n" + "\n".join(violations), file=sys.stderr)
        return 1
    print("Repository data guard passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
