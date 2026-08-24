"""Shared fixtures.

Tests run against the real dataset. That is deliberate: the point of this suite is to
catch a regression in how the platform reads *this* data, and a synthetic fixture
would not have caught the day-first timestamp trap or the all-zero state columns.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app

#: The site with the longest history and the only well-validated classifier.
PRIMARY_SITE = "House_4"
PRIMARY_APPLIANCE = "ac"

#: A site with power but no on/off state -- the degraded-capability path.
NO_STATE_SITE = "House1_Hyderabad"

#: The industrial site with sub-metered channels and critical loads.
INDUSTRIAL_SITE = "Singapore_2"


@pytest.fixture(scope="session")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def primary_date(client: TestClient) -> str:
    return client.get(f"/api/houses/{PRIMARY_SITE}").json()["latest_date"]
