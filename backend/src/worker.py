import json,time,traceback
from pathlib import Path
from .config.database import SessionLocal,engine,Base
from .models import ReportRun,SourceRow,Metric,Delivery
from .services.report_service import queue
from .services.pivot_service import build_report
from .services.attribution_service import load_snapshot
from .services.scheduler_service import schedule_due
from .services.audit_service import log
from .constants.status import RunStatus
Base.metadata.create_all(engine);Path("/artifacts").mkdir(exist_ok=True)
while True:
    Path("/artifacts/heartbeat").write_text(str(time.time()))
    try:
        with SessionLocal() as db:schedule_due(db)
        job=queue.blpop("metric:jobs",timeout=2)
        if not job:continue
        with SessionLocal() as db:
            run=db.get(ReportRun,int(job[1]))
            if not run or run.status!=RunStatus.QUEUED:continue
            run.status=RunStatus.RUNNING;db.commit()
            try:
                # 始终使用入队时冻结的同版归属关系，计算期间维护新关系不影响本运行
                if run.attribution_version_id:
                    edges,terminals=load_snapshot(db,run.attribution_version_id)
                else:
                    edges,terminals=None,None
                run.result=build_report(db.query(SourceRow).order_by(SourceRow.id).all(),db.query(Metric).order_by(Metric.id).all(),run.dimensions,edges=edges,attribution_version_id=run.attribution_version_id,terminals=terminals)
                run.status=RunStatus.COMPLETED
                Path(f"/artifacts/report-{run.id}.json").write_text(json.dumps(run.result,ensure_ascii=False))
                if run.schedule_id:db.add(Delivery(schedule_id=run.schedule_id,run_id=run.id,title=run.name))
                log(db,"worker","report.delivered" if run.schedule_id else "report.completed",run.id)
            except Exception as e:run.status=RunStatus.FAILED;run.error=str(e);traceback.print_exc()
            db.commit()
    except Exception:traceback.print_exc();time.sleep(2)
