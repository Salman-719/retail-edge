#!/usr/bin/env python3
"""Verify that .env.example documents every required (Field(...)) Settings variable.

Usage (from repo root, inside any service container with workspace mounted):
    python scripts/check_env_example.py

Exits 0 if all required fields are covered, 1 if any are missing.

What counts as "required": any pydantic field annotated as `Field(...)` (the ellipsis
literal as first positional argument means no default — pydantic will raise at startup
if the env var is absent).
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).parent.parent


def _env_keys(path: pathlib.Path) -> set[str]:
    keys: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            keys.add(line.split("=", 1)[0].strip())
    return keys


def _required_fields(settings_file: pathlib.Path) -> list[tuple[str, str]]:
    """Return (service_label, ENV_VAR_NAME) for each Field(...) with no default."""
    # Service label: second-to-last component of the path before the filename
    # e.g. services/eep/app/core/config.py → "eep"
    #      services/iep3_reconciliation/app/settings.py → "iep3_reconciliation"
    parts = settings_file.parts
    try:
        svc_idx = parts.index("services") + 1
        service = parts[svc_idx]
    except (ValueError, IndexError):
        service = settings_file.parent.name

    src = settings_file.read_text(encoding="utf-8")
    results = []
    # Match:  field_name: SomeType = Field(...)
    # Field(...) — ellipsis as first positional arg = required field, no default.
    for m in re.finditer(r"(\w+)\s*:\s*[\w\[\], |]+\s*=\s*Field\(\.\.\.", src):
        field = m.group(1).upper()
        results.append((service, field))
    return results


example_path = ROOT / ".env.example"
if not example_path.exists():
    print(f"ERROR: .env.example not found at {example_path}")
    sys.exit(1)

example_keys = _env_keys(example_path)

settings_files = (
    list((ROOT / "services").glob("*/app/settings.py"))
    + list((ROOT / "services").glob("*/app/core/config.py"))
)

if not settings_files:
    print("ERROR: no settings files found under services/")
    sys.exit(1)

missing: list[tuple[str, str, pathlib.Path]] = []
found: list[tuple[str, str]] = []

for sf in settings_files:
    for service, field in _required_fields(sf):
        if field in example_keys:
            found.append((service, field))
        else:
            missing.append((service, field, sf.relative_to(ROOT)))

if missing:
    print(f"FAIL: {len(missing)} required field(s) missing from .env.example:")
    for service, field, src in missing:
        print(f"  - {field!r}  (service={service}, defined in {src})")
    sys.exit(1)

print(
    f"PASS: all {len(found)} required fields across {len(settings_files)} "
    f"settings files are present in .env.example"
)
sys.exit(0)
