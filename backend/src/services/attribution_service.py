"""归属关系维护与版本冻结。

并发规则：所有写操作与版本冻结都先取同一把事务锁（PostgreSQL 咨询锁，
SQLite/离线环境退化为进程内线程锁），再做全量环路与权重校验。
因此两个各自合法、合并后成环的并发修改只会有一份生效，后提交者拿到 422。
"""
import threading
from fastapi import HTTPException
from sqlalchemy import text
from ..models import AttributionEdge,AttributionNode,AttributionVersion,ReportRun
from ..utils.serialize import record
from . import graph_service
from .audit_service import log

ADVISORY_KEY = 7311001
_process_lock = threading.RLock()


class AttributionLock:
    def __init__(self, db):
        self.db = db
        self.thread_lock = None
        self.is_postgres = db.bind.dialect.name == "postgresql"

    def __enter__(self):
        if self.is_postgres:
            self.db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ADVISORY_KEY})
        else:
            self.thread_lock = _process_lock
            self.thread_lock.acquire()
        return self

    def __exit__(self, *exc):
        if self.thread_lock is not None:
            self.thread_lock.release()


def edge_dict(row):
    return {"id": row.id, "source": row.source, "target": row.target, "weight": row.weight,
            "start_date": row.start_date, "end_date": row.end_date}


def list_edges(db):
    return [edge_dict(x) for x in db.query(AttributionEdge).order_by(
        AttributionEdge.start_date, AttributionEdge.source, AttributionEdge.target).all()]


def list_nodes(db):
    return [record(x) for x in db.query(AttributionNode).order_by(AttributionNode.kind, AttributionNode.id).all()]


def region_terminals(db):
    return {x.node for x in db.query(AttributionNode).filter(AttributionNode.kind == "region").all()}


def list_versions(db):
    rows = db.query(AttributionVersion).order_by(AttributionVersion.id.desc()).limit(100).all()
    return [{"id": v.id, "note": v.note, "owner": v.owner, "created_at": v.created_at,
             "edge_count": len(v.snapshot), "in_use": bool(
                 db.query(ReportRun.id).filter(ReportRun.attribution_version_id == v.id).first())} for v in rows]


def _check_nodes(db, source, target):
    nodes = {x.node: x.kind for x in db.query(AttributionNode).all()}
    if source not in nodes:
        raise HTTPException(422, f"来源节点 {source} 未登记，请先维护节点")
    if target not in nodes:
        raise HTTPException(422, f"目标节点 {target} 未登记，请先维护节点")
    if nodes[source] == "region":
        raise HTTPException(422, "区域是归属终点，不能再向外流出")
    if nodes[target] == "channel":
        raise HTTPException(422, "渠道是归属起点，不能作为流入目标")


def _validate(db, candidate):
    # 登记期保证硬结构：权重合计为一、无重叠环路、无重叠有效期/自环。
    # 中间节点断头路属于"图尚未搭建完成"，留到版本冻结/计算时硬拦截，避免限制搭建顺序。
    existing = [edge_dict(x) for x in db.query(AttributionEdge).all()]
    try:
        graph_service.validate_prospective(existing, candidate)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


def create_edge(db, data, user):
    payload = data.model_dump()
    payload["start_date"] = payload["start_date"].isoformat()
    if payload.get("end_date"):
        payload["end_date"] = payload["end_date"].isoformat()
    with AttributionLock(db):
        _check_nodes(db, payload["source"], payload["target"])
        candidate = {k: payload[k] for k in ("source", "target", "weight", "start_date", "end_date")}
        _validate(db, candidate)
        row = AttributionEdge(**candidate, owner=user.name)
        db.add(row)
        db.flush()
        log(db, user.email, "attribution.edge.create", row.id)
        db.commit()
        return edge_dict(row)


def update_edge(db, edge_id, data, user):
    with AttributionLock(db):
        row = db.get(AttributionEdge, edge_id)
        if not row:
            raise HTTPException(404, "归属关系不存在")
        payload = data.model_dump(exclude_unset=True)
        if "start_date" in payload:
            payload["start_date"] = payload["start_date"].isoformat()
        if "end_date" in payload:
            payload["end_date"] = payload["end_date"].isoformat() if payload["end_date"] else None
        candidate = edge_dict(row) | payload
        _check_nodes(db, candidate["source"], candidate["target"])
        _validate(db, candidate)
        for key, value in payload.items():
            setattr(row, key, value)
        log(db, user.email, "attribution.edge.update", row.id)
        db.commit()
        return edge_dict(row)


def delete_edge(db, edge_id, user):
    with AttributionLock(db):
        row = db.get(AttributionEdge, edge_id)
        if not row:
            raise HTTPException(404, "归属关系不存在")
        remaining = [e for e in (edge_dict(x) for x in db.query(AttributionEdge).all()) if e["id"] != edge_id]
        try:
            graph_service.validate_edges(remaining)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        db.delete(row)
        log(db, user.email, "attribution.edge.delete", edge_id)
        db.commit()
        return {"deleted": edge_id}


def freeze_version(db, user, note=""):
    """入队计算前冻结当前全部生效关系；手工报表与定时交付走同一入口。"""
    with AttributionLock(db):
        snapshot = [edge_dict(x) for x in db.query(AttributionEdge).order_by(AttributionEdge.id).all()]
        try:
            graph_service.validate_edges(snapshot)
            terminals = region_terminals(db)
            # 从最早生效日起逐关键窗口校验传播完整性，覆盖长期开放边
            if snapshot:
                earliest = min(e["start_date"] for e in snapshot)
                for day in graph_service._key_days(snapshot, start=earliest):
                    graph_service.propagation_graph(snapshot, day, terminals)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        version = AttributionVersion(snapshot=snapshot, terminals=sorted(terminals), note=note, owner=user.name)
        db.add(version)
        db.flush()
        log(db, user.email, "attribution.version.freeze", version.id)
        db.commit()
        return version.id, snapshot


def load_snapshot(db, version_id):
    version = db.get(AttributionVersion, version_id)
    if not version:
        raise HTTPException(409, f"归属版本 {version_id} 不存在，无法复算")
    return version.snapshot, version.terminals
