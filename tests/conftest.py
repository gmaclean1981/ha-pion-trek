"""Enable the custom component in the official HA pytest harness."""

import pytest


@pytest.fixture(autouse=True)
def enable_custom(enable_custom_integrations, monkeypatch):
    monkeypatch.setattr("custom_components.pion_trek.client.SESSION_SETTLE_SECONDS", 0)


@pytest.fixture(autouse=True)
def prevent_real_bluetooth(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("Tests must never connect to real Bluetooth devices")

    monkeypatch.setattr("custom_components.pion_trek.coordinator.establish_connection", forbidden)
