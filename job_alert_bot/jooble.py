"""Philippine Jooble REST API adapter; live calls require separate API permission."""

import asyncio
import re
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from typing import Any
from urllib.parse import quote

import aiohttp
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .database import SourceRequestUsage
from .jobs import JobListing, Salary, SalaryPeriod
from .source_errors import AuthenticationFailure, QuotaExhausted, SourceFailure, TemporarySourceFailure


API_ROOT = "https://ph.jooble.org/api/"
_NCR = re.compile(
    r"\b(?:ncr|metro manila|national capital region|caloocan|las pi(?:ñ|n)as|makati|"
    r"malabon|mandaluyong|manila|marikina|muntinlupa|navotas|para(?:ñ|n)aque|"
    r"pasay|pasig|pateros|quezon city|taguig|valenzuela)\b",
    re.IGNORECASE,
)
_MONEY = re.compile(r"(?<!\w)\d[\d,]*(?:\.\d+)?")


SourceError = SourceFailure  # Backward compatible name for callers of the first adapter.


def retry_after_seconds(value: str | None) -> int | None:
    if not value:
        return None
    if value.isdecimal():
        return min(int(value), 86400)
    try:
        date = parsedate_to_datetime(value)
        if date.tzinfo is None:
            return None
        return max(0, min(int((date - datetime.now(timezone.utc)).total_seconds()), 86400))
    except (TypeError, ValueError, OverflowError):
        return None


def identified_ncr_location(location: str) -> bool:
    # A Philippines-wide or remote-only result has no identified NCR base.
    return bool(_NCR.search(location))


def parse_salary(value: Any) -> Salary:
    if not isinstance(value, str) or not value.strip():
        return Salary()
    raw = value.strip()
    compact = raw.lower()
    if "commission" in compact:
        return Salary(raw=raw)
    bonus = None
    if "bonus" in compact:
        # Only the explicit "plus bonus" form separates a base from a bonus.
        split = re.split(r"\bplus\s+bonus\b", raw, maxsplit=1, flags=re.IGNORECASE)
        if len(split) != 2:
            return Salary(raw=raw)
        raw_base = split[0].strip()
        bonus = "Bonus disclosed (amount not specified)"
    else:
        raw_base = raw
    if re.search(r"\d\s*(?:k|m|thousand|million)\b", raw_base, re.IGNORECASE):
        return Salary(raw=raw)
    currency = "PHP" if "php" in compact or "₱" in raw else ""
    period = None
    if re.search(r"\b(?:per\s+month|monthly|a\s+month|month|mo)\b", raw_base.lower()):
        period = SalaryPeriod.MONTHLY
    elif re.search(r"\b(?:per\s+year|annually|annual|yearly|year|yr)\b", raw_base.lower()):
        period = SalaryPeriod.ANNUAL
    elif re.search(r"\b(?:per\s+day|daily|day)\b", raw_base.lower()):
        period = SalaryPeriod.DAILY
    elif re.search(r"\b(?:per\s+hour|hourly|hour|hr)\b", raw_base.lower()):
        period = SalaryPeriod.HOURLY
    try:
        amounts = [Decimal(match.group().replace(",", "")) for match in _MONEY.finditer(raw_base)]
    except InvalidOperation:
        return Salary(raw=raw)
    if (not amounts or len(amounts) > 2 or amounts[0] <= 0
            or (len(amounts) > 1 and amounts[1] < amounts[0])):
        return Salary(raw=raw)
    return Salary(currency=currency, lower=amounts[0],
                  upper=amounts[1] if len(amounts) > 1 else None,
                  period=period, raw=raw_base, bonus=bonus)


def map_job(row: Any) -> JobListing | None:
    if not isinstance(row, dict):
        return None
    identifier = row.get("id")
    title = row.get("title")
    employer = row.get("company")
    location = row.get("location")
    link = row.get("link")
    if (not isinstance(identifier, (str, int)) or isinstance(identifier, bool)
            or not all(isinstance(x, str) and x.strip() for x in (title, employer, location, link))):
        return None
    return JobListing(
        source="Jooble PH", source_id=str(identifier), title=title.strip(), employer=employer.strip(),
        location=location.strip(), ncr_workplace_or_base=identified_ncr_location(location),
        salary=parse_salary(row.get("salary")), work_arrangement="",
        employment_type=str(row.get("type") or "Not specified"),
        application_url=link.strip(),
        # Jooble's documented result does not include expiry or closure state.
        expires_at=None, confirmed_closed=False,
    )


class JooblePhilippinesSource:
    def __init__(self, api_key: str, *, discord_approved: bool, keywords: str = "jobs",
                 usage_sessions: sessionmaker[Session] | None = None):
        if not discord_approved:
            raise ValueError("Jooble Discord-use approval is required before live collection")
        if not api_key or not re.fullmatch(r"[A-Za-z0-9_-]+", api_key):
            raise ValueError("A valid Philippine Jooble API key is required")
        if not keywords.strip():
            raise ValueError("Jooble search keywords cannot be empty")
        self._api_key = api_key
        self.keywords = keywords.strip()
        self._usage_sessions = usage_sessions

    def _reserve_request(self) -> None:
        if self._usage_sessions is None:
            return
        fingerprint = sha256(("jooble-ph:" + self._api_key).encode()).hexdigest()
        with self._usage_sessions.begin() as session:
            usage = session.scalar(select(SourceRequestUsage).where(
                SourceRequestUsage.source_key_hash == fingerprint).with_for_update())
            if usage is None:
                session.add(SourceRequestUsage(source_key_hash=fingerprint, requests_reserved=1))
            elif usage.requests_reserved >= 500:
                raise QuotaExhausted("This bot has reserved all 500 free Jooble requests for this key")
            else:
                usage.requests_reserved += 1

    async def fetch_jobs(self) -> list[JobListing]:
        # Reserve before the HTTP attempt: a failed attempt may still count upstream.
        self._reserve_request()
        url = API_ROOT + quote(self._api_key, safe="")
        payload = {"keywords": self.keywords, "location": "Metro Manila",
                   "page": 1, "ResultOnPage": 50}
        try:
            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload) as response:
                    if response.status in {401, 403, 429}:
                        body = (await response.text())[:1000].lower()
                        if any(term in body for term in ("quota exhausted", "quota exceeded", "lifetime limit", "request limit reached")):
                            raise QuotaExhausted("Jooble reports its API request quota is exhausted")
                        if response.status in {401, 403}:
                            raise AuthenticationFailure("Jooble rejected the Philippine API key or access (HTTP 401/403)")
                        raise TemporarySourceFailure(
                            "Jooble rate limited the request (HTTP 429)",
                            retry_after_seconds(response.headers.get("Retry-After")),
                        )
                    if response.status >= 500:
                        raise TemporarySourceFailure(f"Jooble returned HTTP {response.status}",
                                                     retry_after_seconds(response.headers.get("Retry-After")))
                    if response.status != 200:
                        raise SourceError(f"Jooble returned HTTP {response.status}")
                    data = await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise TemporarySourceFailure("Jooble request failed or timed out") from exc
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise SourceError("Jooble returned an unexpected response")
        return [job for row in data["jobs"] if (job := map_job(row)) is not None]
