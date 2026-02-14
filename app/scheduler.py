import random
import time
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Facility, SnapshotExecution, FacilityMetric, HVACStatus


scheduler = AsyncIOScheduler()
JOB_ID = "snapshot_job"


# =====================================================
# CRON JOB LOGIC
# =====================================================

def generate_snapshot():
    start = time.time()
    db: Session = SessionLocal()

    try:
        snapshot = SnapshotExecution(
            execution_time=datetime.utcnow(),
            status="running"
        )
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)

        facilities = db.query(Facility).filter(Facility.is_active == True).all()
        statuses = db.query(HVACStatus).all()

        for f in facilities:
            occupancy = random.randint(
                int(0.4 * f.capacity),
                int(0.9 * f.capacity)
            )

            metric = FacilityMetric(
                snapshot_id=snapshot.id,
                facility_id=f.id,
                hvac_status_id=random.choice(statuses).id,
                occupancy=occupancy,
                energy_kwh=random.uniform(10000, 30000),
                water_liters=random.uniform(20000, 60000),
                open_tickets=random.randint(0, 20),
                recorded_at=datetime.utcnow()
            )
            db.add(metric)

        snapshot.status = "success"
        snapshot.execution_duration_ms = int((time.time() - start) * 1000)

        db.commit()
        retain_last_n(db, 50)

    except Exception:
        snapshot.status = "failed"
        db.commit()

    finally:
        db.close()


# =====================================================
# RETENTION
# =====================================================

def retain_last_n(db: Session, limit: int):
    executions = db.query(SnapshotExecution).order_by(
        SnapshotExecution.execution_time.desc()
    ).all()

    if len(executions) > limit:
        for old in executions[limit:]:
            db.query(FacilityMetric).filter(
                FacilityMetric.snapshot_id == old.id
            ).delete()
            db.delete(old)
        db.commit()


# =====================================================
# CONTROL FUNCTIONS
# =====================================================

def start_scheduler():
    if scheduler.get_job(JOB_ID):
        return "already_running"

    scheduler.add_job(
        generate_snapshot,
        "interval",
        seconds=2,
        id=JOB_ID,
        replace_existing=True
    )

    if not scheduler.running:
        scheduler.start()

    return "started"


def pause_scheduler():
    job = scheduler.get_job(JOB_ID)
    if not job:
        return "not_running"

    scheduler.pause_job(JOB_ID)
    return "paused"


def resume_scheduler():
    job = scheduler.get_job(JOB_ID)
    if not job:
        return "not_running"

    scheduler.resume_job(JOB_ID)
    return "resumed"


def stop_scheduler():
    job = scheduler.get_job(JOB_ID)
    if not job:
        return "not_running"

    scheduler.remove_job(JOB_ID)
    return "stopped"


def scheduler_status():
    job = scheduler.get_job(JOB_ID)

    return {
        "scheduler_running": scheduler.running,
        "job_exists": job is not None,
        "job_paused": job.next_run_time is None if job else None
    }