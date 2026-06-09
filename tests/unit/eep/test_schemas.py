"""EEP request-schema validation tests (pure Pydantic, no infra).

Covers the validators on the write-path request models — valid input plus the
null/edge/invalid cases the brief asks for. Imported via the eep conftest's
services/eep path shim; the schemas import only pydantic (+ email-validator).
"""
import pytest
from pydantic import ValidationError

from app.schemas.auth import RegisterRequest
from app.schemas.employees import CreateEmployeeRequest
from app.schemas.punch import PunchEventRequest
from app.schemas.store import CreateStoreRequest


# ── CreateStoreRequest ────────────────────────────────────────────────────────

def test_store_valid():
    s = CreateStoreRequest(name="Acme", slug="acme-01", address="1 Main St")
    assert s.slug == "acme-01"
    assert s.address == "1 Main St"


@pytest.mark.parametrize("bad_slug", ["Acme", "acme 01", "acme_01", "acmé", "ACME"])
def test_store_slug_must_be_lowercase_kebab(bad_slug):
    with pytest.raises(ValidationError):
        CreateStoreRequest(name="Acme", slug=bad_slug, address="1 Main St")


@pytest.mark.parametrize("bad_addr", ["", "   "])
def test_store_address_required(bad_addr):
    with pytest.raises(ValidationError):
        CreateStoreRequest(name="Acme", slug="acme", address=bad_addr)


def test_store_address_is_stripped():
    s = CreateStoreRequest(name="Acme", slug="acme", address="  1 Main St  ")
    assert s.address == "1 Main St"


# ── RegisterRequest ───────────────────────────────────────────────────────────

def test_register_valid():
    r = RegisterRequest(name="Jo", email="jo@example.com", password="longenough")
    assert r.email == "jo@example.com"


def test_register_password_too_short():
    with pytest.raises(ValidationError):
        RegisterRequest(name="Jo", email="jo@example.com", password="short")


@pytest.mark.parametrize("bad_email", ["not-an-email", "jo@", "@example.com", ""])
def test_register_invalid_email(bad_email):
    with pytest.raises(ValidationError):
        RegisterRequest(name="Jo", email=bad_email, password="longenough")


# ── CreateEmployeeRequest ─────────────────────────────────────────────────────

def test_employee_valid():
    e = CreateEmployeeRequest(name="Sam", role="cashier")
    assert e.role == "cashier"


def test_employee_name_required_nonempty():
    with pytest.raises(ValidationError):
        CreateEmployeeRequest(name="")


def test_employee_role_must_be_in_allowed_set():
    with pytest.raises(ValidationError):
        CreateEmployeeRequest(name="Sam", role="overlord")


def test_employee_role_optional():
    e = CreateEmployeeRequest(name="Sam")
    assert e.role is None


# ── PunchEventRequest (exactly-one-identifier) ────────────────────────────────

def test_punch_with_only_code_ok():
    p = PunchEventRequest(employee_code="BADGE-1")
    assert p.employee_code == "BADGE-1"


def test_punch_with_neither_identifier_rejected():
    with pytest.raises(ValidationError):
        PunchEventRequest()


def test_punch_with_both_identifiers_rejected():
    import uuid
    with pytest.raises(ValidationError):
        PunchEventRequest(employee_code="BADGE-1", employee_id=uuid.uuid4())
