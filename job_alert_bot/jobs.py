"""Source-independent job data, eligibility, and salary ordering."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class SalaryPeriod(str, Enum):
    HOURLY = "hourly"
    DAILY = "daily"
    MONTHLY = "monthly"
    ANNUAL = "annual"


@dataclass(frozen=True)
class Salary:
    currency: str = "PHP"
    lower: Decimal | None = None
    upper: Decimal | None = None
    period: SalaryPeriod | None = None
    hours_per_day: Decimal | None = None
    days_per_month: Decimal | None = None
    hours_per_month: Decimal | None = None
    bonus: str | None = None
    raw: str | None = None


@dataclass(frozen=True)
class JobListing:
    source: str
    source_id: str
    title: str
    employer: str
    location: str
    ncr_workplace_or_base: bool
    salary: Salary
    work_arrangement: str
    employment_type: str
    application_url: str
    expires_at: datetime | None = None
    confirmed_closed: bool = False

    @property
    def key(self) -> str:
        return f"{self.source}:{self.source_id}"


def usable_application_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
        return (
            parts.scheme.lower() in {"http", "https"}
            and bool(parts.hostname)
            and not parts.username
            and not parts.password
            and not any(char.isspace() for char in url)
            and len(url) <= 512
        )
    except ValueError:
        return False


def canonical_url_hash(url: str) -> str | None:
    """Match identical listing URLs while removing only known tracking parameters."""
    if not usable_application_url(url):
        return None
    parts = urlsplit(url)
    query = sorted((key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
                   if not key.lower().startswith("utm_") and key.lower() not in
                   {"fbclid", "gclid", "msclkid"})
    canonical = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/",
                            urlencode(query), ""))
    return sha256(canonical.encode("utf-8")).hexdigest()


def eligible(job: JobListing, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if not job.ncr_workplace_or_base or not job.location.strip():
        return False
    if not usable_application_url(job.application_url) or job.confirmed_closed:
        return False
    if job.expires_at is not None:
        if job.expires_at.tzinfo is None:
            raise ValueError("expires_at must include a timezone")
        if job.expires_at <= now:
            return False
    return True


def monthly_salary_lower(job: JobListing) -> Decimal | None:
    salary = job.salary
    if salary.currency.upper() != "PHP" or salary.lower is None or salary.lower <= 0:
        return None
    if salary.period == SalaryPeriod.MONTHLY:
        return salary.lower
    if salary.period == SalaryPeriod.ANNUAL:
        return salary.lower / Decimal(12)
    if salary.period == SalaryPeriod.DAILY and salary.days_per_month is not None and salary.days_per_month > 0:
        return salary.lower * salary.days_per_month
    if salary.period == SalaryPeriod.HOURLY:
        if salary.hours_per_month is not None and salary.hours_per_month > 0:
            return salary.lower * salary.hours_per_month
        if (salary.hours_per_day is not None and salary.hours_per_day > 0
                and salary.days_per_month is not None and salary.days_per_month > 0):
            return salary.lower * salary.hours_per_day * salary.days_per_month
    return None


def ranked_jobs(jobs: list[JobListing], now: datetime | None = None) -> list[JobListing]:
    # Preserve adapter order for equal or undisclosed salaries.
    candidates = [job for job in jobs if eligible(job, now)]
    return sorted(candidates, key=lambda job: (
        monthly_salary_lower(job) is None,
        -(monthly_salary_lower(job) or Decimal(0)),
    ))
