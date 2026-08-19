import pytest
from pydantic import ValidationError

from app.models.schemas import TripRequest

USER_ID = "08ea6304-e03e-4f94-a0fc-5557709d9d7f"


def test_trip_request_rejects_invalid_start_date():
    with pytest.raises(ValidationError, match="start_date"):
        TripRequest(user_id=USER_ID, city="北京", days=3, start_date="2026-02-30")


def test_trip_request_requires_a_stable_user_id():
    with pytest.raises(ValidationError, match="user_id"):
        TripRequest(city="北京", days=3)


def test_trip_request_rejects_a_zero_budget_when_a_budget_is_supplied():
    with pytest.raises(ValidationError, match="budget_total"):
        TripRequest(user_id=USER_ID, city="北京", days=3, budget_total=0)
