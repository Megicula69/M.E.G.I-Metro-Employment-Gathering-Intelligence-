"""PostgreSQL storage for per-server settings and successful deliveries."""

from datetime import date, datetime, timezone

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


class ServerConfig(Base):
    __tablename__ = "server_configs"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    alert_channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)


class JobDelivery(Base):
    __tablename__ = "job_deliveries"
    __table_args__ = (UniqueConstraint("guild_id", "job_key"),
                      Index("uq_delivery_guild_canonical", "guild_id", "canonical_url_hash", unique=True))

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("server_configs.guild_id"), nullable=False)
    job_key: Mapped[str] = mapped_column(String(512), nullable=False)
    canonical_url_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    delivered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    server: Mapped[ServerConfig] = relationship()


class SourceRequestUsage(Base):
    """Local request count keyed by a hash of the provider key, never the secret."""

    __tablename__ = "source_request_usage"

    source_key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    requests_reserved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CollectionCycle(Base):
    """A daily reservation prevents a second provider fetch after a restart."""

    __tablename__ = "collection_cycles"

    manila_date: Mapped[date] = mapped_column(Date, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=lambda: datetime.now(timezone.utc))
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, default="started")


class DailyBatch(Base):
    """One real batch per server per Philippine date."""

    __tablename__ = "daily_batches"

    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("server_configs.guild_id"), primary_key=True)
    manila_date: Mapped[date] = mapped_column(Date, primary_key=True)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                default=lambda: datetime.now(timezone.utc))


def make_session_factory(database_url: str):
    if not database_url.startswith(("postgresql+psycopg://", "postgresql://")):
        raise ValueError("DATABASE_URL must point to PostgreSQL")
    engine = create_engine(database_url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    # create_all does not add columns to databases from the first milestone.
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE job_deliveries ADD COLUMN IF NOT EXISTS canonical_url_hash VARCHAR(64)"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_delivery_guild_canonical "
                                "ON job_deliveries (guild_id, canonical_url_hash)"))
    return sessionmaker(engine, expire_on_commit=False)
