"""Verify immutable baseline artifacts; does not write into design directories."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]


def main():
    baseline = json.loads((ROOT / "integration-audit/before.json").read_text())
    failures = []
    count = 0
    for group in ("protected", "main_protected"):
        for relative, expected in baseline[group].items():
            path = ROOT / relative
            content = path.read_bytes() if path.is_file() else None
            actual = hashlib.sha256(content).hexdigest() if content is not None else None
            # Git's Windows checkout may expand LF to CRLF. Existing local files
            # are checked byte-for-byte; main's Git blobs allow only that EOL conversion.
            if group == "main_protected" and actual != expected and content is not None:
                actual = hashlib.sha256(content.replace(b"\r\n", b"\n")).hexdigest()
            count += 1
            if actual != expected:
                failures.append(relative)
    for relative in baseline["directories"]:
        if not (ROOT / relative).is_dir():
            failures.append(relative + "/")
    if failures:
        raise SystemExit("Changed or missing protected paths: " + ", ".join(failures))
    print(f"PASS: {count} baseline checks; all original top-level folders remain.")


if __name__ == "__main__":
    main()
