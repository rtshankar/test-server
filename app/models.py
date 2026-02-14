from sqlalchemy import (
    Column, Integer, String, Float,
    DateTime, Boolean, ForeignKey,
    Index, func
)
from app.database import Base


class Facility(Base):
    __tablename__ = "facilities"

    id = Column(String(20), primary_key=True)
    name = Column(String(255), nullable=False)
    city = Column(String(100), nullable=False)
    capacity = Column(Integer, nullable=False)

    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class SnapshotExecution(Base):
    __tablename__ = "snapshot_executions"

    id = Column(Integer, primary_key=True)
    execution_time = Column(DateTime(timezone=True), nullable=False, index=True)
    status = Column(String(50), default="running")
    execution_duration_ms = Column(Integer)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class HVACStatus(Base):
    __tablename__ = "hvac_statuses"

    id = Column(Integer, primary_key=True)
    code = Column(String(50), unique=True, nullable=False)
    description = Column(String(255))


class FacilityMetric(Base):
    __tablename__ = "facility_metrics"

    id = Column(Integer, primary_key=True)

    snapshot_id = Column(Integer, ForeignKey("snapshot_executions.id"))
    facility_id = Column(String(20), ForeignKey("facilities.id"))
    hvac_status_id = Column(Integer, ForeignKey("hvac_statuses.id"))

    occupancy = Column(Integer, nullable=False)
    energy_kwh = Column(Float, nullable=False)
    water_liters = Column(Float, nullable=False)
    open_tickets = Column(Integer, nullable=False)

    recorded_at = Column(DateTime(timezone=True), index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_facility_snapshot", "facility_id", "snapshot_id"),
        Index("idx_facility_recorded", "facility_id", "recorded_at"),
    )