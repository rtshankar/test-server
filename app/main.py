from datetime import datetime

from fastapi import FastAPI, Request, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from app.database import Base, engine, SessionLocal
from .models import (
    Facility,
    HVACStatus,
    SnapshotExecution,
    FacilityMetric
)
from app.config import SERVICE_NAME, FACILITY_SEED
from app.auth import authenticate
from scheduler import (
    start_scheduler,
    pause_scheduler,
    resume_scheduler,
    stop_scheduler,
    scheduler_status,
    scheduler
)

# =====================================================
# APP INIT
# =====================================================

app = FastAPI(title=SERVICE_NAME)

Base.metadata.create_all(bind=engine)


# =====================================================
# DB DEPENDENCY
# =====================================================

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =====================================================
# STARTUP (SEED MASTER DATA)
# =====================================================

@app.on_event("startup")
async def startup():
    db = SessionLocal()

    # Seed HVAC statuses
    if not db.query(HVACStatus).first():
        db.add_all([
            HVACStatus(code="healthy", description="Normal"),
            HVACStatus(code="warning", description="Attention required"),
            HVACStatus(code="critical", description="Immediate action"),
        ])

    # Seed Facilities
    if not db.query(Facility).first():
        for f in FACILITY_SEED:
            db.add(Facility(**f))

    db.commit()
    db.close()


# =====================================================
# SHUTDOWN (CLEAN SCHEDULER STOP)
# =====================================================

@app.on_event("shutdown")
async def shutdown():
    if scheduler.running:
        scheduler.shutdown(wait=False)


# =====================================================
# ---------------- PUBLIC ENDPOINT -------------------
# =====================================================

@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    try:
        # Check database connection
        db.execute(text("SELECT 1"))

        # Check scheduler state
        scheduler_running = scheduler.running

        return {
            "status": "healthy",
            "service": SERVICE_NAME,
            "database": "connected",
            "scheduler_running": scheduler_running,
            "timestamp": datetime.utcnow()
        }

    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "unhealthy",
                "error": str(e)
            }
        )

@app.get("/api/v1/public/summary")
async def public_summary(db: Session = Depends(get_db)):
    total_snapshots = db.query(SnapshotExecution).count()
    total_records = db.query(FacilityMetric).count()

    return {
        "service": SERVICE_NAME,
        "total_snapshots": total_snapshots,
        "total_records": total_records
    }


# =====================================================
# ---------------- V1 ENDPOINTS ----------------------
# =====================================================

@app.get("/api/v1/snapshots/count")
async def snapshot_count(request: Request, db: Session = Depends(get_db)):
    await authenticate(request, ["basic", "apikey"])
    count = db.query(SnapshotExecution).count()
    return {"total_executions": count}


@app.get("/api/v1/snapshots/latest")
async def latest_snapshot(request: Request, db: Session = Depends(get_db)):
    await authenticate(request, ["basic", "apikey"])

    snapshot = db.query(SnapshotExecution).order_by(
        SnapshotExecution.execution_time.desc()
    ).first()

    if not snapshot:
        raise HTTPException(status_code=404, detail="No data available")

    metrics = db.query(FacilityMetric).filter(
        FacilityMetric.snapshot_id == snapshot.id
    ).all()

    return {
        "version": "v1",
        "snapshot_id": snapshot.id,
        "execution_time": snapshot.execution_time,
        "status": snapshot.status,
        "facilities": [
            {
                "facility_id": m.facility_id,
                "occupancy": m.occupancy,
                "energy_kwh": m.energy_kwh,
                "water_liters": m.water_liters,
                "open_tickets": m.open_tickets,
                "recorded_at": m.recorded_at
            }
            for m in metrics
        ]
    }


@app.get("/api/v1/snapshots")
async def list_snapshots(request: Request, db: Session = Depends(get_db)):
    await authenticate(request, ["basic", "apikey"])

    snapshots = db.query(SnapshotExecution).order_by(
        SnapshotExecution.execution_time.desc()
    ).limit(20).all()

    return [
        {
            "snapshot_id": s.id,
            "execution_time": s.execution_time,
            "status": s.status,
            "duration_ms": s.execution_duration_ms
        }
        for s in snapshots
    ]


@app.get("/api/v1/facilities/{facility_id}/history")
async def facility_history(facility_id: str, request: Request, db: Session = Depends(get_db)):
    await authenticate(request, ["basic", "apikey"])

    records = db.query(FacilityMetric).filter(
        FacilityMetric.facility_id == facility_id
    ).order_by(FacilityMetric.recorded_at.desc()).limit(50).all()

    return {
        "facility_id": facility_id,
        "records": [
            {
                "snapshot_id": r.snapshot_id,
                "occupancy": r.occupancy,
                "energy_kwh": r.energy_kwh,
                "water_liters": r.water_liters,
                "open_tickets": r.open_tickets,
                "recorded_at": r.recorded_at
            }
            for r in records
        ]
    }

@app.get("/api/v1/facilities/{facility_id}/aggregate")
async def facility_aggregate(
    facility_id: str,
    request: Request,
    db: Session = Depends(get_db),
    from_time: str = Query(...),
    to_time: str = Query(...)
):
    await authenticate(request, ["basic", "apikey", "bearer"])

    try:
        from_dt = datetime.fromisoformat(from_time)
        to_dt = datetime.fromisoformat(to_time)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid datetime format.")

    result = db.query(
        func.avg(FacilityMetric.occupancy),
        func.avg(FacilityMetric.energy_kwh),
        func.avg(FacilityMetric.water_liters),
        func.avg(FacilityMetric.open_tickets)
    ).filter(
        FacilityMetric.facility_id == facility_id,
        FacilityMetric.recorded_at >= from_dt,
        FacilityMetric.recorded_at <= to_dt
    ).first()

    return {
        "facility_id": facility_id,
        "from_time": from_dt,
        "to_time": to_dt,
        "averages": {
            "avg_occupancy": round(result[0] or 0, 2),
            "avg_energy_kwh": round(result[1] or 0, 2),
            "avg_water_liters": round(result[2] or 0, 2),
            "avg_open_tickets": round(result[3] or 0, 2)
        }
    }

# =====================================================
# ---------------- V2 ENHANCED -----------------------
# =====================================================

@app.get("/api/v2/facilities/{facility_id}/metrics")
async def facility_metrics_v2(facility_id: str, request: Request, db: Session = Depends(get_db)):
    await authenticate(request, ["basic", "apikey", "bearer"])

    snapshot = db.query(SnapshotExecution).order_by(
        SnapshotExecution.execution_time.desc()
    ).first()

    if not snapshot:
        raise HTTPException(status_code=404, detail="No data available")

    metric = db.query(FacilityMetric).filter(
        FacilityMetric.snapshot_id == snapshot.id,
        FacilityMetric.facility_id == facility_id
    ).first()

    if not metric:
        raise HTTPException(status_code=404, detail="Facility not found")

    energy_per_person = round(metric.energy_kwh / metric.occupancy, 2)

    return {
        "version": "v2",
        "metadata": {
            "snapshot_id": snapshot.id,
            "execution_time": snapshot.execution_time
        },
        "operational": {
            "occupancy": metric.occupancy,
            "open_tickets": metric.open_tickets
        },
        "utilities": {
            "energy_kwh": metric.energy_kwh,
            "water_liters": metric.water_liters,
            "energy_per_person": energy_per_person
        }
    }


# =====================================================
# ---------------- CRON CONTROL ----------------------
# =====================================================

@app.post("/admin/cron/start")
async def cron_start():
    return {"status": start_scheduler()}


@app.post("/admin/cron/pause")
async def cron_pause():
    return {"status": pause_scheduler()}


@app.post("/admin/cron/resume")
async def cron_resume():
    return {"status": resume_scheduler()}


@app.post("/admin/cron/stop")
async def cron_stop():
    return {"status": stop_scheduler()}


@app.get("/admin/cron/status")
async def cron_status():
    return scheduler_status()