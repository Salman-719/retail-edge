"""Integration tests for the store onboarding flow.

Requires: EEP service running at localhost:8000
Run with: pytest tests/integration/ -v --tb=short
"""
import os
import pytest
import httpx

BASE = os.environ.get("EEP_URL", "http://localhost:8000")


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=30) as c:
        yield c


@pytest.fixture(scope="module")
def store(client):
    """Create a test store, yield it, then delete."""
    resp = client.post("/api/stores", json={"name": "Integration Test Store"})
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data
    # Cleanup
    client.delete(f"/api/stores/{data['id']}")


class TestStoreOnboardingFlow:
    """Full onboarding: store -> zones -> cameras -> employees."""

    def test_01_store_created(self, store):
        assert store["name"] == "Integration Test Store"
        assert "id" in store

    def test_02_create_zones(self, client, store):
        sid = store["id"]
        zone1 = client.post(f"/api/stores/{sid}/zones", json={
            "name": "Entrance", "type": "entrance",
            "points": [{"x": 0, "y": 0}, {"x": 10, "y": 0}, {"x": 10, "y": 10}, {"x": 0, "y": 10}],
        })
        assert zone1.status_code == 201
        assert zone1.json()["name"] == "Entrance"

        zone2 = client.post(f"/api/stores/{sid}/zones", json={
            "name": "Checkout", "type": "checkout",
            "points": [{"x": 20, "y": 0}, {"x": 30, "y": 0}, {"x": 30, "y": 10}, {"x": 20, "y": 10}],
        })
        assert zone2.status_code == 201

    def test_03_zone_overlap_rejected(self, client, store):
        sid = store["id"]
        # Overlaps with Entrance zone
        resp = client.post(f"/api/stores/{sid}/zones", json={
            "name": "Overlapping", "type": "general",
            "points": [{"x": 5, "y": 5}, {"x": 15, "y": 5}, {"x": 15, "y": 15}, {"x": 5, "y": 15}],
        })
        assert resp.status_code == 409

    def test_04_list_zones(self, client, store):
        sid = store["id"]
        resp = client.get(f"/api/stores/{sid}/zones")
        assert resp.status_code == 200
        zones = resp.json()
        assert len(zones) >= 2
        names = {z["name"] for z in zones}
        assert "Entrance" in names
        assert "Checkout" in names

    def test_05_create_camera(self, client, store):
        sid = store["id"]
        resp = client.post(f"/api/stores/{sid}/cameras", json={
            "name": "Camera 1",
            "position_x": 5.0,
            "position_y": 5.0,
            "height_meters": 3.0,
        })
        assert resp.status_code == 201
        assert resp.json()["name"] == "Camera 1"

    def test_06_create_employee(self, client, store):
        sid = store["id"]
        resp = client.post(f"/api/stores/{sid}/employees", json={
            "name": "John Doe",
            "role": "cashier",
        })
        assert resp.status_code == 201
        emp = resp.json()
        assert emp["name"] == "John Doe"
        assert emp["role"] == "cashier"

    def test_07_list_employees(self, client, store):
        sid = store["id"]
        resp = client.get(f"/api/stores/{sid}/employees")
        assert resp.status_code == 200
        emps = resp.json()
        assert len(emps) >= 1

    def test_08_create_shift(self, client, store):
        sid = store["id"]
        emps = client.get(f"/api/stores/{sid}/employees").json()
        emp_id = emps[0]["id"]

        resp = client.post(f"/api/stores/{sid}/employees/{emp_id}/shifts", json={
            "start_time": "2026-04-08T09:00:00",
            "end_time": "2026-04-08T17:00:00",
        })
        assert resp.status_code == 201

    def test_09_retrieve_all_entities(self, client, store):
        sid = store["id"]
        # Store
        resp = client.get(f"/api/stores/{sid}")
        assert resp.status_code == 200

        # Zones, cameras, employees all retrievable
        assert client.get(f"/api/stores/{sid}/zones").status_code == 200
        assert client.get(f"/api/stores/{sid}/cameras").status_code == 200
        assert client.get(f"/api/stores/{sid}/employees").status_code == 200

    def test_10_delete_store_cascades(self, client, store):
        sid = store["id"]
        resp = client.delete(f"/api/stores/{sid}")
        assert resp.status_code in (200, 204)

        # Zones should be gone
        resp = client.get(f"/api/stores/{sid}/zones")
        zones = resp.json()
        assert len(zones) == 0
