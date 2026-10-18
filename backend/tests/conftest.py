from __future__ import annotations

import pytest

from app.config import DATA_DIR
from app.data import Floor, Menu
from app.events import EventLog
from app.tasks import TaskBook
from tests.test_api import client  # noqa: F401 - shared FastAPI TestClient fixture


@pytest.fixture(scope="session")
def menu() -> Menu:
    return Menu.load(DATA_DIR / "menu.json")


@pytest.fixture(scope="session")
def floor() -> Floor:
    return Floor.load(DATA_DIR / "floor.json")


@pytest.fixture
def book(floor: Floor) -> TaskBook:
    return TaskBook(floor, EventLog(), escalation_sec=30)
