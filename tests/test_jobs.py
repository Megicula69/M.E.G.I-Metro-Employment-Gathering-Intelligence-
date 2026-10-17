from datetime import datetime, timedelta, timezone
from decimal import Decimal

from job_alert_bot.jobs import JobListing, Salary, SalaryPeriod, eligible, monthly_salary_lower, ranked_jobs


def job(identifier="one", salary=None, **changes):
    values = dict(source="test", source_id=identifier, title="Role", employer="Employer",
                  location="Makati City, NCR", ncr_workplace_or_base=True,
                  salary=salary if salary is not None else Salary(lower=Decimal("50000"), period=SalaryPeriod.MONTHLY), work_arrangement="Hybrid", employment_type="Full-time",
                  application_url=f"https://example.com/apply/{identifier}")
    values.update(changes)
    return JobListing(**values)


def test_ncr_url_and_open_job_filtering():
    now = datetime.now(timezone.utc)
    assert eligible(job())
    assert not eligible(job(ncr_workplace_or_base=False))
    assert not eligible(job(location=""))
    assert not eligible(job(application_url="javascript:alert(1)"))
    assert not eligible(job(application_url="https://"))
    assert not eligible(job(confirmed_closed=True))
    assert not eligible(job(expires_at=now - timedelta(seconds=1)), now)
    assert eligible(job(expires_at=now + timedelta(days=1)), now)


def test_salary_normalization_requires_explicit_work_time():
    assert monthly_salary_lower(job(salary=Salary(lower=Decimal("720000"), period=SalaryPeriod.ANNUAL))) == 60000
    assert monthly_salary_lower(job(salary=Salary(lower=Decimal("500"), period=SalaryPeriod.DAILY))) is None
    assert monthly_salary_lower(job(salary=Salary(lower=Decimal("500"), period=SalaryPeriod.DAILY,
                                                  days_per_month=Decimal("22")))) == 11000
    assert monthly_salary_lower(job(salary=Salary(lower=Decimal("250"), period=SalaryPeriod.HOURLY))) is None
    assert monthly_salary_lower(job(salary=Salary(lower=Decimal("250"), period=SalaryPeriod.HOURLY,
                                                  hours_per_day=Decimal("8"), days_per_month=Decimal("22")))) == 44000
    assert monthly_salary_lower(job(salary=Salary(currency="USD", lower=Decimal("1000"),
                                                  period=SalaryPeriod.MONTHLY))) is None


def test_ranking_uses_lower_base_and_puts_unknown_last():
    jobs = [job("unknown", Salary(lower=Decimal("70000"), period=None)), job("monthly", Salary(lower=Decimal("80000"), upper=Decimal("90000"),
                                                 period=SalaryPeriod.MONTHLY)),
            job("annual", Salary(lower=Decimal("1080000"), period=SalaryPeriod.ANNUAL)),
            job("excluded", Salary(lower=Decimal("200000"), period=SalaryPeriod.MONTHLY),
                ncr_workplace_or_base=False)]
    assert [item.source_id for item in ranked_jobs(jobs)] == ["annual", "monthly", "unknown"]
