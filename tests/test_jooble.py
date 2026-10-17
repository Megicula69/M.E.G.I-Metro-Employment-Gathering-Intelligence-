import asyncio
from decimal import Decimal
from hashlib import sha256

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from job_alert_bot import jooble
from job_alert_bot.database import Base, SourceRequestUsage
from job_alert_bot.jobs import SalaryPeriod, monthly_salary_lower, ranked_jobs
from job_alert_bot.source_errors import AuthenticationFailure, QuotaExhausted, TemporarySourceFailure


def row(identifier, location, salary, link=None):
    return {"id": identifier, "title": f"Role {identifier}", "company": "Example Employer",
            "location": location, "salary": salary, "type": "Full-time",
            "link": link or f"https://ph.jooble.org/jdp/{identifier}"}


def test_jooble_mapping_filters_ncr_and_keeps_uncomparable_pay_last():
    jobs = [jooble.map_job(item) for item in [
        row(1, "Quezon City, Metro Manila", "PHP 50,000 - 70,000 per month"),
        row(2, "Cebu City", "PHP 200,000 per month"),
        row(3, "Makati City, NCR", "₱1,200,000 per year"),
        row(4, "Remote - Philippines", "PHP 150,000 per month"),
        row(5, "Taguig City", "PHP 500 per hour"),
        row(6, "Pasig City", "Negotiable"),
        row(7, "Manila", "PHP 90,000 per month", "javascript:bad"),
    ]]
    assert [item.source_id for item in ranked_jobs(jobs)] == ["3", "1", "5"]
    assert monthly_salary_lower(jobs[2]) == Decimal("100000")
    assert monthly_salary_lower(jobs[4]) is None
    assert jobs[0].application_url == "https://ph.jooble.org/jdp/1"
    assert jooble.map_job(row(8, "Makati", "PHP 50,000 per month") | {"company": ""}) is None


def test_approval_gate_and_live_request_shape(monkeypatch):
    with pytest.raises(ValueError, match="approval"):
        jooble.JooblePhilippinesSource("example-key", discord_approved=False)

    calls = []

    class FakeResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def json(self):
            return {"jobs": [row(42, "Makati City", "PHP 75,000 monthly")]}

    class FakeSession:
        def __init__(self, *, timeout):
            assert timeout.total == 20

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def post(self, url, *, json):
            calls.append((url, json))
            return FakeResponse()

    monkeypatch.setattr(jooble.aiohttp, "ClientSession", FakeSession)
    source = jooble.JooblePhilippinesSource("example-key", discord_approved=True, keywords="engineer")
    fetched = asyncio.run(source.fetch_jobs())
    assert len(fetched) == 1
    assert fetched[0].source_id == "42"
    assert calls == [("https://ph.jooble.org/api/example-key",
                      {"keywords": "engineer", "location": "Metro Manila", "page": 1, "ResultOnPage": 50})]


def test_unknown_salary_and_bonus_are_not_ranked_as_base():
    no_period = jooble.parse_salary("PHP 80,000 - 100,000")
    bonus = jooble.parse_salary("PHP 80,000 per month plus bonus")
    assert no_period.lower == 80000 and no_period.period is None
    assert bonus.lower == 80000 and bonus.bonus is not None
    assert jooble.parse_salary("PHP 800 per day").period == SalaryPeriod.DAILY
    assert jooble.parse_salary("PHP 80k monthly").lower is None
    assert jooble.parse_salary("Commission only").lower is None
    assert jooble.map_job(row(9, "Makati", "PHP 80,000 monthly")).work_arrangement == ""


@pytest.mark.parametrize("status,body,headers,error", [
    (403, "API quota exceeded", {}, QuotaExhausted),
    (403, "Access denied", {}, AuthenticationFailure),
    (429, "Slow down", {"Retry-After": "120"}, TemporarySourceFailure),
])
def test_provider_error_classification_does_not_leak_key(monkeypatch, status, body, headers, error):
    class Response:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def text(self):
            return body

    response = Response()
    response.status = status
    response.headers = headers

    class Session:
        def __init__(self, *, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def post(self, url, *, json):
            return response

    monkeypatch.setattr(jooble.aiohttp, "ClientSession", Session)
    source = jooble.JooblePhilippinesSource("very-secret-key", discord_approved=True)
    with pytest.raises(error) as info:
        asyncio.run(source.fetch_jobs())
    assert "very-secret-key" not in str(info.value)
    if status == 429:
        assert info.value.retry_after_seconds == 120


def test_local_jooble_request_budget_stops_before_network(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'budget.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    fingerprint = sha256(b"jooble-ph:example-key").hexdigest()
    with sessions.begin() as session:
        session.add(SourceRequestUsage(source_key_hash=fingerprint, requests_reserved=500))
    monkeypatch.setattr(jooble.aiohttp, "ClientSession",
                        lambda **kwargs: pytest.fail("Network must not be called after 500 reservations"))
    source = jooble.JooblePhilippinesSource("example-key", discord_approved=True,
                                           usage_sessions=sessions)
    with pytest.raises(QuotaExhausted):
        asyncio.run(source.fetch_jobs())
