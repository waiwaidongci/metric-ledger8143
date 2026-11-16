from fastapi import HTTPException
from ..models import SourceRow,Metric
from ..utils.serialize import record
from .pivot_service import build_report
from .attribution_service import list_edges,region_terminals
def source_preview(db):
    return [record(x) for x in db.query(SourceRow).order_by(SourceRow.id).limit(100)]
def reconciliation(db):
    try:return build_report(db.query(SourceRow).order_by(SourceRow.id).all(),db.query(Metric).order_by(Metric.id).all(),["channel","month"])
    except ValueError as e:raise HTTPException(422,str(e))
def region_reconciliation(db):
    # 区域核对按当前归属关系分摊；已归档报表仍使用各自冻结版本，历史结果不变
    try:return build_report(db.query(SourceRow).order_by(SourceRow.id).all(),db.query(Metric).order_by(Metric.id).all(),["region","month"],edges=list_edges(db),terminals=region_terminals(db))
    except ValueError as e:raise HTTPException(422,str(e))
