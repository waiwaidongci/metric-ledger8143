"""端到端 API 验证（隔离依赖目录运行）：FastAPI TestClient + SQLite + 假 Redis。

运行：PYTHONPATH=/tmp/pysite DATABASE_URL=sqlite:////tmp/integ/ledger.db \
     python3 tests/test_api.py
覆盖：JWT 权限、归属关系校验拒绝、合法登记、入队冻结版本、worker 同版复算、
区域报表分摊依据与导出、并发成环只放行一份、查看者只读。
"""
import os
import pathlib
import threading

pathlib.Path("/tmp/integ").mkdir(exist_ok=True)
DB_PATH = "/tmp/integ/ledger.db"
if pathlib.Path(DB_PATH).exists():
    pathlib.Path(DB_PATH).unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["REDIS_URL"] = "redis://localhost:6399/0"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["SEED_DEMO"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from src.config.database import Base, engine, SessionLocal  # noqa: E402
from src import models  # noqa: E402
from src.models import User, Metric, SourceRow, AttributionNode, AttributionEdge, ReportRun  # noqa: E402
from src.services import report_service, attribution_service  # noqa: E402
from src.services.pivot_service import build_report  # noqa: E402
from src.services.attribution_service import load_snapshot  # noqa: E402
from src.utils.security import hash_password, make_token  # noqa: E402
from src.main import app  # noqa: E402

# 假 Redis：只记录入队的作业 id，不建立真实连接
class FakeQueue:
    def __init__(self):
        self.jobs = []
    def rpush(self, key, value):
        self.jobs.append(value)
    def ping(self):
        return True
    def blpop(self, key, timeout=0):
        return None

fake = FakeQueue()
report_service.queue = fake
import src.services.scheduler_service as scheduler_service  # noqa: E402
scheduler_service.queue = fake

Base.metadata.create_all(engine)

PASS, FAIL = 0, 0
def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1; print(f"  ✓ {name}")
    else:
        FAIL += 1; print(f"  ✗ {name} {detail}")

with SessionLocal() as db:
    admin = User(email="admin@t.demo", name="管理员", role="admin", password_hash=hash_password("pw123456"))
    viewer = User(email="v@t.demo", name="阅读者", role="viewer", password_hash=hash_password("pw123456"))
    db.add_all([admin, viewer]); db.flush()
    admin_token, viewer_token = make_token(admin), make_token(viewer)
    for key, expr in [("net_revenue", "revenue-refunds"), ("gross_profit", "net_revenue-cost"),
                      ("net_per_order", "net_revenue/orders")]:
        db.add(Metric(key=key, name=key, expression=expr, unit="元", description="集成测试口径不少于八个字", owner="管理员"))
    for node, kind in [("C1", "channel"), ("C2", "channel"), ("H1", "hub"), ("H2", "hub"),
                       ("华东", "region"), ("华北", "region"), ("华南", "region")]:
        db.add(AttributionNode(node=node, kind=kind, label=node))
    db.flush()
    # 合法图：C1 经两条路径，华东汇合；C2 不配置 → 回退旧区域
    for source, target, weight in [
        ("C1", "H1", 0.6), ("C1", "H2", 0.4),
        ("H1", "华东", 0.7), ("H1", "华北", 0.3), ("H2", "华东", 1.0)]:
        db.add(AttributionEdge(source=source, target=target, weight=weight,
                               start_date="2026-09-01", end_date=None, owner="管理员"))
    db.add_all([
        SourceRow(source_key="T-001", day="2026-09-10", channel="C1", region="华东",
                  revenue=1000.0, cost=400.0, refunds=100.0, orders=20, reference_net=900.0),
        SourceRow(source_key="T-002", day="2026-09-11", channel="C2", region="华南",
                  revenue=500.0, cost=200.0, refunds=50.0, orders=10, reference_net=450.0),
    ])
    db.commit()

client = TestClient(app)
H_ADMIN = {"Authorization": f"Bearer {admin_token}"}
H_VIEWER = {"Authorization": f"Bearer {viewer_token}"}

print("== 12. 鉴权与只读权限 ==")
check("未登录 401", client.get("/attribution/edges").status_code == 401)
check("查看者不能登记关系 403",
      client.post("/attribution/edges", headers=H_VIEWER,
                  json={"source": "C1", "target": "H1", "weight": 1.0, "start_date": "2026-09-01"}).status_code == 403)
check("管理员可读取节点", len(client.get("/attribution/nodes", headers=H_ADMIN).json()) == 7)

print("== 13. 归属关系登记校验 ==")
# 13a 破坏流出权重合计：H1 现有 0.7+0.3=1.0，再加 0.2
r = client.post("/attribution/edges", headers=H_ADMIN,
                json={"source": "H1", "target": "华南", "weight": 0.2, "start_date": "2026-09-01"})
check("权重合计破坏被 422 拒绝", r.status_code == 422 and "必须等于 1" in r.json()["detail"], str(r.json()))
# 13b 同一对关系有效期重叠
r = client.post("/attribution/edges", headers=H_ADMIN,
                json={"source": "C1", "target": "H1", "weight": 0.6, "start_date": "2026-09-15"})
check("同关系重叠有效期 422", r.status_code == 422 and "重叠有效期" in r.json()["detail"])
# 13c 自环与非法权重
r = client.post("/attribution/edges", headers=H_ADMIN,
                json={"source": "H1", "target": "H1", "weight": 1.0, "start_date": "2026-09-01"})
check("自环 422", r.status_code == 422 and "自环" in r.json()["detail"])
# 13d 区域不能作为流出起点 / 渠道不能作为流入目标
r = client.post("/attribution/edges", headers=H_ADMIN,
                json={"source": "华东", "target": "H1", "weight": 1.0, "start_date": "2026-09-01"})
check("区域作起点 422", r.status_code == 422, "终点" in r.json()["detail"])

# 13e 干净子图上的环路拒绝（经 update 重定向；环上节点均为中间节点，权重保持为 1，
# 因此只能靠环路检测拦截；渠道作流入目标、区域作流出起点已由节点类型规则单独拦截）
for node, kind in [("CC", "channel"), ("HA", "hub"), ("HB", "hub"), ("RZ", "region"), ("RZ2", "region")]:
    if not any(n["node"] == node for n in client.get("/attribution/nodes", headers=H_ADMIN).json()):
        client.post("/attribution/nodes", headers=H_ADMIN, json={"node": node, "kind": kind, "label": node})
for payload in [
    {"source": "CC", "target": "HA", "weight": 1.0, "start_date": "2028-03-01", "end_date": None},
    {"source": "HA", "target": "HB", "weight": 1.0, "start_date": "2028-03-01", "end_date": None},
    {"source": "HB", "target": "RZ", "weight": 1.0, "start_date": "2028-03-01", "end_date": None},
]:
    ok = client.post("/attribution/edges", headers=H_ADMIN, json=payload)
    check(f"合法链路登记 {payload['source']}→{payload['target']}", ok.status_code == 201, str(ok.json()))
hb_rz = next(e for e in client.get("/attribution/edges", headers=H_ADMIN).json()
             if e["source"] == "HB" and e["target"] == "RZ")
# 把 HB→RZ 重定向为 HB→HA，闭合 HA→HB→HA 环路，触发环路检测
r = client.patch(f"/attribution/edges/{hb_rz['id']}", headers=H_ADMIN, json={"target": "HA"})
check("重定向成环被 422 拒绝", r.status_code == 422 and "环路" in r.json()["detail"], str(r.json()))
unchanged = client.get("/attribution/edges", headers=H_ADMIN).json()
check("被拒重定向未污染原关系（仍指向 RZ）",
      any(e["id"] == hb_rz["id"] and e["target"] == "RZ" for e in unchanged))
# 合法重定向到另一终点区域
r = client.patch(f"/attribution/edges/{hb_rz['id']}", headers=H_ADMIN, json={"target": "RZ2"})
check("重定向为合法下游区域 200", r.status_code == 200 and r.json()["target"] == "RZ2", str(r.json()))

# 13f 日期不重叠的反向关系可用：3 月 PA→PB，4 月 PB→PA，两窗口不重叠故永不共存、无环
for node, kind in [("CA", "channel"), ("PA", "hub"), ("PB", "hub"), ("RY", "region")]:
    if not any(n["node"] == node for n in client.get("/attribution/nodes", headers=H_ADMIN).json()):
        client.post("/attribution/nodes", headers=H_ADMIN, json={"node": node, "kind": kind, "label": node})
reverse_payloads = [
    {"source": "CA", "target": "PA", "weight": 1.0, "start_date": "2029-03-01", "end_date": "2029-03-31"},
    {"source": "PA", "target": "PB", "weight": 1.0, "start_date": "2029-03-01", "end_date": "2029-03-31"},
    {"source": "PB", "target": "RY", "weight": 1.0, "start_date": "2029-03-01", "end_date": "2029-03-31"},
    {"source": "CA", "target": "PB", "weight": 1.0, "start_date": "2029-04-01", "end_date": None},
    {"source": "PB", "target": "PA", "weight": 1.0, "start_date": "2029-04-01", "end_date": None},
    {"source": "PA", "target": "RY", "weight": 1.0, "start_date": "2029-04-01", "end_date": None},
]
for payload in reverse_payloads:
    rr = client.post("/attribution/edges", headers=H_ADMIN, json=payload)
    check(f"不重叠反向关系 {payload['source']}→{payload['target']} 登记通过",
          rr.status_code == 201, str(rr.json()))
# 该子图每个窗口都能正常传播（3 月到 RY；4 月也到 RY，路径方向相反）
from src.services import graph_service
with SessionLocal() as db:
    sub = attribution_service.list_edges(db)
    terminals = attribution_service.region_terminals(db)
    mar = {x["region"]: x["region"] for x in graph_service.propagate("z", "CA", "2029-03-15", sub, 1.0, 1, terminals)}
    apr = {x["region"]: x["region"] for x in graph_service.propagate("z", "CA", "2029-04-15", sub, 1.0, 1, terminals)}
check("3 月经 PA→PB 到达 RY", "RY" in mar, str(mar))
check("4 月经反向 PB→PA 到达 RY", "RY" in apr, str(apr))

print("== 14. 入队冻结版本 + worker 同版复算 ==")
r = client.post("/reports", headers=H_ADMIN, json={"name": "区域分摊核对-API", "dimensions": ["region", "month"]})
check("报表 202 入队", r.status_code == 202, str(r.json()))
run_id = r.json()["id"]; version_id = r.json()["attribution_version_id"]
check("入队即带归属版本", isinstance(version_id, int))
check("作业进入队列", fake.jobs[-1] == run_id)
# 计算期间修改归属：新增一条不影响已冻结版本的关系（C2 开始配置）
client.post("/attribution/edges", headers=H_ADMIN,
            json={"source": "C2", "target": "华北", "weight": 1.0, "start_date": "2026-11-01"})
# 模拟 worker：始终加载冻结版本
with SessionLocal() as db:
    run = db.get(ReportRun, run_id)
    edges, terminals = load_snapshot(db, version_id)
    run.result = build_report(db.query(SourceRow).order_by(SourceRow.id).all(),
                              db.query(Metric).order_by(Metric.id).all(),
                              run.dimensions, edges=edges, terminals=terminals,
                              attribution_version_id=version_id)
    run.status = "completed"; db.commit()
    frozen = run.result
check("冻结版本不含计算期间新增的 C2 关系",
      all(e["source"] != "C2" for e in edges), "版本快照被污染")
check("跨区守恒标记为真", frozen["conservation"]["conserved"] is True, str(frozen["conservation"]))
check("分摊依据含两条来源", len({b["source_key"] for b in frozen["allocation_basis"]}) == 2)
basis = {(b["source_key"], b["region"]): b for b in frozen["allocation_basis"]}
# C1→华东 = 0.6*0.7+0.4 = 0.82；T-002 的 C2 未在冻结版中 → 回退华南
check("汇合区域权重 0.82", abs(basis[("T-001", "华东")]["weight"] - 0.82) < 1e-9)
check("未配置来源回退旧区域", basis[("T-002", "华南")]["fallback"] is True)

print("== 15. 页面与导出一致 ==")
shown = client.get(f"/reports/{run_id}", headers=H_ADMIN).json()
check("接口结果与 worker 落库一致", shown["result"]["allocation_basis"] == frozen["allocation_basis"])
csv_basis = client.get(f"/reports/{run_id}/basis-export", headers=H_ADMIN)
check("分摊依据 CSV 可导出", csv_basis.status_code == 200 and "T-001" in csv_basis.text and "归属版本分摊" in csv_basis.text)
csv_main = client.get(f"/reports/{run_id}/export", headers=H_ADMIN)
check("主报表 CSV 可导出", csv_main.status_code == 200 and "华北" in csv_main.text)
region_rec = client.get("/sources/region-reconciliation", headers=H_ADMIN).json()
check("区域核对接口守恒", region_rec["conservation"]["conserved"] is True)
legacy = client.get("/sources/reconciliation", headers=H_ADMIN).json()
check("渠道核对保持历史结构（无分摊字段）", "allocation_basis" not in legacy)
check("版本列表可查且标记在用",
      any(v["id"] == version_id and v["in_use"] for v in client.get("/attribution/versions", headers=H_ADMIN).json()))

print("== 16. 并发写串行化：竞争提交只放行一份；环路无法落库 ==")
# 16a. 并发登记同一条关系：锁串行化后先到生效（201），后到因有效期重叠被拒（422）
with SessionLocal() as db:
    base_count = db.query(AttributionEdge).count()
    if not db.query(AttributionNode).filter_by(node="M").first():
        db.add_all([AttributionNode(node="M", kind="hub", label="M"),
                    AttributionNode(node="N", kind="hub", label="N")]); db.commit()
# 先在 2027-04 窗口给 M 一条合法出口，保证节点本身可用；并发两笔落在另一窗口的同关系
client.post("/attribution/edges", headers=H_ADMIN,
            json={"source": "M", "target": "N", "weight": 1.0, "start_date": "2027-04-01", "end_date": "2027-04-30"})
client.post("/attribution/edges", headers=H_ADMIN,
            json={"source": "N", "target": "华南", "weight": 1.0, "start_date": "2027-04-01", "end_date": "2027-04-30"})
# 5 月 N 的出口预先备妥，使竞争关系只在“同关系重叠”这一点上冲突
client.post("/attribution/edges", headers=H_ADMIN,
            json={"source": "N", "target": "华南", "weight": 1.0, "start_date": "2027-05-01", "end_date": "2027-05-31"})
race_results = []
def concurrent_overlap_race():
    r = client.post("/attribution/edges", headers=H_ADMIN,
                    json={"source": "M", "target": "N", "weight": 1.0, "start_date": "2027-05-01",
                          "end_date": "2027-05-31"})
    race_results.append(r.status_code)
t1 = threading.Thread(target=concurrent_overlap_race)
t2 = threading.Thread(target=concurrent_overlap_race)
t1.start(); t2.start(); t1.join(); t2.join()
check("并发同关系写恰好一份生效（201+422）", sorted(race_results) == [201, 422], str(race_results))
with SessionLocal() as db:
    # 基线 + 3 条预备关系（4 月链路 + 5 月 N 出口）+ 竞争中仅一条 5 月 M→N = 基线 +4
    check("竞争后只多一条关系", db.query(AttributionEdge).count() == base_count + 4)
    graph_service.validate_edges(attribution_service.list_edges(db))
    check("竞争后图仍满足权重合计为一", True)

# 16b. 断头路只在版本冻结/计算时硬拦截：登记期允许分步搭建，冻结期拒绝不完整图
class _U:
    name = "冻结测试员"
    email = "freeze@t.demo"
for node in ("P", "Q"):
    if not any(n["node"] == node for n in client.get("/attribution/nodes", headers=H_ADMIN).json()):
        client.post("/attribution/nodes", headers=H_ADMIN, json={"node": node, "kind": "hub", "label": node})
r_m = client.post("/attribution/edges", headers=H_ADMIN,
                  json={"source": "P", "target": "Q", "weight": 1.0, "start_date": "2030-07-01"})
check("分步搭建：P→Q 登记期允许（201）", r_m.status_code == 201, str(r_m.json()))
with SessionLocal() as db:
    try:
        attribution_service.freeze_version(db, _U(), note="不完整图冻结应失败")
        check("断头路图冻结被拒绝", False, "冻结竟然成功")
    except Exception as exc:  # noqa: BLE001
        check("断头路图冻结被拒绝", "没有流出权重" in str(exc), str(exc))
# 补全 Q→华南 后整条链路合法，冻结成功
r_n = client.post("/attribution/edges", headers=H_ADMIN,
                  json={"source": "Q", "target": "华南", "weight": 1.0, "start_date": "2030-07-01"})
check("补全出口 Q→华南 登记成功", r_n.status_code == 201, str(r_n.json()))
with SessionLocal() as db:
    vid, snap = attribution_service.freeze_version(db, _U(), note="完整图冻结")
    check("完整链路冻结成功并返回版本", isinstance(vid, int) and len(snap) >= 2, str(vid))
# 试图闭合 Q→P 环：Q 在该窗口权重已满（Q→华南=1），必然 422，环无法落库
r = client.post("/attribution/edges", headers=H_ADMIN,
                json={"source": "Q", "target": "P", "weight": 1.0, "start_date": "2030-07-01"})
check("闭合环路的一笔被 422 拒绝", r.status_code == 422, str(r.status_code))
with SessionLocal() as db:
    # 全量边在所有关键日期仍然合法（锁内全量重校验的最终保证）
    from src.services import graph_service
    all_edges = attribution_service.list_edges(db)
    graph_service.validate_edges(all_edges)
    check("已落库归属图在全部生效日合法", True)

print(f"\n结果：{PASS} 通过 / {FAIL} 失败")
raise SystemExit(1 if FAIL else 0)
