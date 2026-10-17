"""Source contract and clearly fictional demonstration listings."""

from decimal import Decimal
from typing import Protocol

from .jobs import JobListing, Salary, SalaryPeriod


class JobSource(Protocol):
    async def fetch_jobs(self) -> list[JobListing]: ...


class SampleDataSource:
    async def fetch_jobs(self) -> list[JobListing]:
        # example.com links are placeholders for the local demo, not real openings.
        return [
            JobListing("sample", "backend", "[SAMPLE] Backend Engineer", "Sample Company A",
                       "Makati City, NCR", True,
                       Salary(lower=Decimal("85000"), upper=Decimal("110000"),
                              period=SalaryPeriod.MONTHLY, bonus="Possible annual bonus (sample)"),
                       "Hybrid", "Full-time", "https://example.com/jobs/backend"),
            JobListing("sample", "analyst", "[SAMPLE] Data Analyst", "Sample Company B",
                       "Quezon City, NCR", True,
                       Salary(lower=Decimal("900000"), period=SalaryPeriod.ANNUAL),
                       "On-site", "Full-time", "https://example.com/jobs/analyst"),
            JobListing("sample", "support", "[SAMPLE] Support Specialist", "Sample Company C",
                       "Pasig City, NCR", True,
                       Salary(lower=Decimal("35000"), period=SalaryPeriod.MONTHLY),
                       "On-site", "Full-time", "https://example.com/jobs/support"),
            JobListing("sample", "designer", "[SAMPLE] Product Designer", "Sample Company D",
                       "Taguig City, NCR", True, Salary(),
                       "Hybrid", "Contract", "https://example.com/jobs/designer"),
        ]
