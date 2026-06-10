"""Consistency guardrails (CI). See specs/robustness-qa/consistency/REGISTER.md.

These read source files only (no service imports), so they are immune to the
cross-service `app` package-name collision and need no service deps. They FAIL
when a known consistency invariant is broken, preventing the drift class from
recurring.

  G1 — embedding dim/byte parity (CONS-001)
  G5 — no reintroduction of the removed `section_id` (CONS-003)
"""
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8", errors="replace")


def _int_after(pattern: str, text: str) -> int:
    m = re.search(pattern, text)
    assert m, f"pattern not found: {pattern!r}"
    return int(m.group(1))


# ── G1: embedding dimension / byte-length parity ──────────────────────────────

def test_embedding_dim_parity_across_services():
    reid = _int_after(r"EMBEDDING_DIM\s*=\s*(\d+)", _read("services/reid_service/service.py"))
    iep2 = _int_after(r"EMBEDDING_DIM\s*=\s*(\d+)", _read("services/iep2_vision/reid/reid.py"))
    iep3 = _int_after(r"embedding_dim:\s*int\s*=\s*Field\(default=(\d+)",
                      _read("services/iep3_reconciliation/app/settings.py"))
    assert reid == iep2 == iep3, (
        f"embedding dim disagrees: reid={reid} iep2={iep2} iep3={iep3} — "
        "update all sites together (CONS-001)"
    )


def test_embedding_byte_constraint_matches_dim():
    reid = _int_after(r"EMBEDDING_DIM\s*=\s*(\d+)", _read("services/reid_service/service.py"))
    new_bytes = _int_after(r"_NEW_BYTES\s*=\s*(\d+)",
                           _read("services/eep/alembic/versions/0005_embedding_dim_2048.py"))
    assert new_bytes == reid * 4, (
        f"schema centroid byte constraint ({new_bytes}) != dim*4 ({reid * 4}) — "
        "a model dim change must update the DB CHECK too (CONS-001)"
    )


# ── G5: the removed `section_id` concept must not return ──────────────────────

def test_no_section_id_in_models_or_routers():
    scan_dirs = [
        _ROOT / "services" / "eep" / "app" / "models",
        _ROOT / "services" / "eep" / "app" / "api" / "routers",
        _ROOT / "services" / "eep" / "app" / "schemas",
    ]
    offenders = []
    for d in scan_dirs:
        for py in d.rglob("*.py"):
            text = py.read_text(encoding="utf-8", errors="replace")
            if re.search(r"\bsection_ids?\b", text):
                offenders.append(str(py.relative_to(_ROOT)))
    assert not offenders, (
        f"`section_id`/`section_ids` reintroduced (removed in SPEC-00A): {offenders} (CONS-003)"
    )
