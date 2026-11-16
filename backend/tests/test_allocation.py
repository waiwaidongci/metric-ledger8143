"""端到端分摊验证：用桩模块隔离第三方依赖，直接驱动真实的 pivot_service。

校验：区域报表先分摊金额与单数再算指标、跨区合计守恒、分摊依据合并、
无归属时旧区域兼容，以及同版关系下重复计算结果稳定（版本快照语义）。
"""
import importlib.util
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1] / "src"


def install_stubs():
    for package in ("src", "src.services", "src.constants", "src.config",
                    "src.models", "src.utils", "src.routes", "src.controllers",
                    "src.middlewares", "src.schemas"):
        sys.modules.setdefault(package, types.ModuleType(package))
    dimensions = types.ModuleType("src.constants.dimensions")
    from enum import StrEnum

    class Dimension(StrEnum):
        CHANNEL = "channel"
        MONTH = "month"
        REGION = "region"
    dimensions.Dimension = Dimension
    dimensions.BASE_FIELDS = {"revenue", "cost", "refunds", "orders"}
    sys.modules["src.constants.dimensions"] = dimensions
    return dimensions


def load(module_name, relative_path):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


install_stubs()
expression = load("src.services.expression_service", "services/expression_service.py")
graph = load("src.services.graph_service", "services/graph_service.py")
pivot = load("src.services.pivot_service", "services/pivot_service.py")

PASS, FAIL = 0, 0


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} {detail}")


class Row:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class Metric:
    def __init__(self, key, name, expression, unit="元"):
        self.key, self.name, self.expression, self.unit = key, name, expression, unit


metrics = [
    Metric("net_revenue", "净收入", "revenue-refunds"),
    Metric("gross_profit", "贡献毛利", "net_revenue-cost"),
    Metric("net_per_order", "每单净收入", "net_revenue/orders", "元/单"),
]
# 三条来源：两条属于已配置渠道 C，一条未配置（兼容旧区域）
rows = [
    Row(source_key="S1", day="2026-09-10", channel="C", region="华东",
        revenue=1000.0, cost=400.0, refunds=100.0, orders=20, reference_net=900.0),
    Row(source_key="S2", day="2026-09-11", channel="C", region="华北",
        revenue=500.0, cost=200.0, refunds=50.0, orders=10, reference_net=450.0),
    Row(source_key="S3", day="2026-09-12", channel="未拆并渠道", region="华南",
        revenue=300.0, cost=120.0, refunds=30.0, orders=6, reference_net=270.0),
]
edges = [
    {"source": "C", "target": "H1", "weight": 0.6, "start_date": "2026-09-01", "end_date": None},
    {"source": "C", "target": "H2", "weight": 0.4, "start_date": "2026-09-01", "end_date": None},
    {"source": "H1", "target": "华东", "weight": 0.7, "start_date": "2026-09-01", "end_date": None},
    {"source": "H1", "target": "华北", "weight": 0.3, "start_date": "2026-09-01", "end_date": None},
    {"source": "H2", "target": "华东", "weight": 1.0, "start_date": "2026-09-01", "end_date": None},
]
terminals = ["华东", "华北", "华南"]
result = pivot.build_report(rows, metrics, ["region", "month"], edges=edges,
                            attribution_version_id=3, terminals=terminals)

print("== 8. 区域报表：先分摊再算指标 ==")
cells = {c["dimensions"]["region"]: c for c in result["cells"]}
# C 的终点权重：华东 = 0.6*0.7 + 0.4 = 0.82；华北 = 0.6*0.3 = 0.18
# 华东收入 = (1000+500)*0.82 = 1230；华北 = 270；华南（兼容行）= 300
# 退款：华东 = (100+50)*0.82 = 123 → 净收入 1230-123 = 1107；成本 600*0.82 = 492
check("华东净收入按汇合权重分摊", abs(cells["华东"]["values"]["net_revenue"] - 1107.0) < 1e-6, str(cells["华东"]["values"]))
check("华北净收入按 0.18 分摊", abs(cells["华北"]["values"]["net_revenue"] - 243.0) < 1e-6, str(cells["华北"]["values"]))
check("未配置来源沿用旧区域华南", abs(cells["华南"]["values"]["net_revenue"] - 270.0) < 1e-6)
# 毛利 = 净收入 - 分摊后成本
check("毛利基于分摊后成本重算",
      abs(cells["华东"]["values"]["gross_profit"] - (1107.0 - 492.0)) < 1e-6, str(cells["华东"]["values"]["gross_profit"]))
# 单数：华东 = 30*0.82 = 24.6；华北 = 5.4；华南 = 6
check("每单净收入为重算比率而非比率平均",
      abs(cells["华东"]["values"]["net_per_order"] - 1107.0 / 24.6) < 1e-6, str(cells["华东"]["values"]["net_per_order"]))
check("分摊单元记录区域权重（两条来源各 0.82）", cells["华东"]["allocation_weight"] == 1.64, str(cells["华东"]["allocation_weight"]))

print("== 9. 跨区合计守恒 ==")
cons = result["conservation"]
check("金额分摊前后守恒", cons["conserved"] and cons["revenue_before"] == cons["revenue_after"], str(cons))
check("单数分摊前后守恒", cons["orders_before"] == cons["orders_after"], str(cons))
# 总净收入（canonical_net）= 全部来源 revenue-refunds，区域合计与来源合计一致
check("区域合计净收入等于来源合计",
      abs(result["total"]["canonical_net"] - sum(r.revenue - r.refunds for r in rows)) < 1e-6,
      str(result["total"]["canonical_net"]))
# 每单净收入 = 总净收入 / 总单数，间接验证总单数仍为 36
check("总单数守恒（经每单净收入反推）",
      abs(result["total"]["values"]["net_per_order"] - result["total"]["canonical_net"] / 36.0) < 1e-6)
check("明细去重计数守恒（3 条来源）", result["total"]["source_count"] == 3, str(result["total"]["source_count"]))
check("区域单元记录分摊权重", all("allocation_weight" in c for c in result["cells"]))
check("结果冻结版本号", result["attribution_version_id"] == 3)

print("== 10. 分摊依据：来源到区域、多路径合并 ==")
basis = {(b["source_key"], b["region"]): b for b in result["allocation_basis"]}
check("依据覆盖来源 × 终点组合", len(basis) == 5, str(len(basis)))  # S1/S2 各 2 区 + S3 一区
s1_east = basis[("S1", "华东")]
check("同来源多路径在依据中合并为一条", s1_east["weight"] == 0.82, str(s1_east))
check("依据保留合并前的两条路径", len(s1_east["paths"]) == 2, str(s1_east["paths"]))
check("依据金额与权重一致", abs(s1_east["revenue"] - 820.0) < 1e-6, str(s1_east["revenue"]))
check("兼容行标记为旧区域取数", basis[("S3", "华南")]["fallback"] is True)
check("分摊行标记为版本取数", s1_east["fallback"] is False)

print("== 11. 同版关系重复计算稳定 & 无归属时历史口径不变 ==")
again = pivot.build_report(rows, metrics, ["region", "month"], edges=edges,
                           attribution_version_id=3, terminals=terminals)
check("同版快照两次计算完全一致", again["cells"] == result["cells"])
legacy = pivot.build_report(rows, metrics, ["region", "month"])
legacy_cells = {c["dimensions"]["region"]: c for c in legacy["cells"]}
check("无归属时分摊字段缺省（历史报表结构不变）", "allocation_basis" not in legacy)
check("无归属时按来源行旧区域统计",
      abs(legacy_cells["华东"]["values"]["net_revenue"] - 900.0) < 1e-6, str(legacy_cells["华东"]["values"]))
channel_report = pivot.build_report(rows, metrics, ["channel", "month"], edges=edges)
check("渠道维度报表不触发分摊", "allocation_basis" not in channel_report)

print(f"\n结果：{PASS} 通过 / {FAIL} 失败")
sys.exit(1 if FAIL else 0)
