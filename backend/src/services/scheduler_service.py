from datetime import datetime,timedelta,timezone
from ..models import DeliverySchedule,ReportRun
from .report_service import queue
from .attribution_service import freeze_version
from .audit_service import log
def schedule_due(db):
    now=datetime.now(timezone.utc)
    due=db.query(DeliverySchedule).filter(DeliverySchedule.active.is_(True),DeliverySchedule.next_run_at<=now.isoformat()).all()
    for schedule in due:
        # 定时交付与手工报表走同一版本冻结入口，计算期间改归属仍使用这版关系
        class _Scheduler:
            name="scheduler"
            email="scheduler"
        try:
            version_id,_=freeze_version(db,_Scheduler(),note=f"定时交付冻结：{schedule.name}")
        except Exception:
            db.rollback()
            raise
        row=ReportRun(name=schedule.name+" · 定时交付",dimensions=schedule.dimensions,owner="scheduler",schedule_id=schedule.id,attribution_version_id=version_id)
        db.add(row);db.flush()
        schedule.next_run_at=(now+timedelta(minutes=schedule.interval_minutes)).isoformat()
        log(db,"scheduler","schedule.due",schedule.id);db.commit()
        queue.rpush("metric:jobs",row.id)
