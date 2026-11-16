"""归属分摊离线验证：仅依赖标准库，动态加载 src 下的纯逻辑模块。

覆盖需求点：
1. 交错有效期：同一渠道在不同日期切换权重；
2. 汇合路径：同一来源经多条路径到同一区域时合并；
3. 环路拒绝：有效期重叠的成环边拒绝，日期不重叠的反向关系可用；
4. 权重守恒：各节点每日流出权重合计为一、跨区分摊金额与单数守恒；
5. 并发成环：各自合法的两份修改合并后成环，只允许一份生效（进程锁模拟）。
"""
import importlib.util
import pathlib
import sys
import threading

ROOT = pathlib.Path(__file__).resolve().parents[1] / "src"


def load(module_name, relative_path):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# 手工搭建最小包结构，避免触发 src/__init__ 与第三方依赖
import types

for package in ("src", "src.services", "src.constants"):
    sys.modules.setdefault(package, types.ModuleType(package))
graph = load("src.services.graph_service", "services/graph_service.py")

PASS, FAIL = 0, 0


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} {detail}")


def expect_value_error(name, fn, fragment=""):
    try:
        fn()
    except ValueError as exc:
        check(name, fragment in str(exc), f"期望提示包含 {fragment!r}，实际：{exc}")
        return
    check(name, False, "应当拒绝但通过了")


def edge(source, target, weight, start, end=None, eid=None):
    return {"id": eid, "source": source, "target": target, "weight": weight,
            "start_date": start, "end_date": end}


print("== 1. 权重合计与基本校验 ==")
ok = [edge("C", "H", 1.0, "2026-09-01"), edge("H", "华东", 0.6, "2026-09-01"),
      edge("H", "华南", 0.4, "2026-09-01")]
graph.validate_edges(ok)
check("合法图通过校验", True)
expect_value_error("流出权重不等于 1 被拒绝",
                   lambda: graph.validate_edges([edge("C", "H", 1.0, "2026-09-01"),
                                                  edge("H", "华东", 0.6, "2026-09-01")]),
                   "必须等于 1")
expect_value_error("自环被拒绝", lambda: graph.validate_edges([edge("C", "C", 1.0, "2026-09-01")]), "自环")
expect_value_error("非正权重被拒绝", lambda: graph.validate_edges([edge("C", "H", 0.0, "2026-09-01")]), "权重")
expect_value_error("失效早于生效被拒绝",
                   lambda: graph.validate_edges([edge("C", "H", 1.0, "2026-10-02", "2026-10-01")]), "失效日期")

print("== 2. 交错有效期（同渠道权重按日期切换） ==")
staggered = [edge("C", "H", 1.0, "2026-09-01"),
             edge("H", "华东", 0.6, "2026-09-01", "2026-09-30"),
             edge("H", "华南", 0.4, "2026-09-01", "2026-09-30"),
             edge("H", "华东", 0.2, "2026-10-01"), edge("H", "华南", 0.8, "2026-10-01")]
graph.validate_edges(staggered)
sep = graph.propagate("s1", "C", "2026-09-15", staggered, 100.0, 10)
octo = graph.propagate("s1", "C", "2026-10-15", staggered, 100.0, 10)
sep_map = {x["region"]: x for x in sep}
octo_map = {x["region"]: x for x in octo}
check("9 月 R1 拿 60%", abs(sep_map["华东"]["weight"] - 0.6) < 1e-9, str(sep_map["华东"]["weight"]))
check("10 月 R1 切换为 20%", abs(octo_map["华东"]["weight"] - 0.2) < 1e-9, str(octo_map["华东"]["weight"]))
check("9 月金额按权重分摊", abs(sep_map["华南"]["amount"] - 40.0) < 1e-9)
check("单数同步按权重分摊", abs(sep_map["华南"]["orders"] - 4.0) < 1e-9)
# 同一对节点有效期重叠应拒绝
overlap_pair = ok + [edge("H", "华东", 0.5, "2026-09-20", "2026-10-10"),
                     edge("H", "华南", 0.5, "2026-09-20", "2026-10-10")]
expect_value_error("同关系重叠有效期被拒绝", lambda: graph.validate_edges(overlap_pair), "重叠有效期")

print("== 3. 汇合路径（多路径到同一区域合并） ==")
merge_graph = [
    edge("C", "H1", 0.6, "2026-09-01"), edge("C", "H2", 0.4, "2026-09-01"),
    edge("H1", "HR", 0.7, "2026-09-01"), edge("H1", "S", 0.3, "2026-09-01"),
    edge("H2", "HR", 1.0, "2026-09-01"),
    edge("HR", "E", 0.5, "2026-09-01"), edge("HR", "N", 0.5, "2026-09-01"),
]
graph.validate_edges(merge_graph)
shares = {x["region"]: x for x in graph.propagate("s1", "C", "2026-09-10", merge_graph, 1000.0, 20)}
# E：0.6*0.7*0.5 + 0.4*1.0*0.5 = 0.21 + 0.20 = 0.41
check("华东汇合权重 0.41", abs(shares["E"]["weight"] - 0.41) < 1e-9, str(shares["E"]["weight"]))
# N 同样 0.41；S：0.6*0.3=0.18
check("华北汇合权重 0.41", abs(shares["N"]["weight"] - 0.41) < 1e-9)
check("华南分支权重 0.18", abs(shares["S"]["weight"] - 0.18) < 1e-9)
check("终点权重合计为 1", abs(sum(x["weight"] for x in shares.values()) - 1.0) < 1e-9)
check("汇合金额守恒", abs(sum(x["amount"] for x in shares.values()) - 1000.0) < 1e-9)
check("汇合单数守恒", abs(sum(x["orders"] for x in shares.values()) - 20.0) < 1e-9)
check("保留两条到华东的路径", len(shares["E"]["paths"]) == 2, str(shares["E"]["paths"]))

print("== 4. 环路：重叠期拒绝、不重叠反向关系可用 ==")
cyclic = [edge("A", "B", 1.0, "2026-09-01"), edge("B", "C", 1.0, "2026-09-01"),
          edge("C", "A", 1.0, "2026-09-01")]
expect_value_error("重叠有效期环路拒绝", lambda: graph.validate_edges(cyclic), "环路")
reverse_ok = [
    edge("数字", "A", 1.0, "2026-09-01", "2026-09-30"),
    edge("数字", "B", 1.0, "2026-10-01"),
    # 9 月：A→B，B 收束到华南
    edge("A", "B", 1.0, "2026-09-01", "2026-09-30"),
    # 10 月：反向 B→A，A 收束到华北（两条反向边日期不重叠，永不共存）
    edge("B", "A", 1.0, "2026-10-01"),
    edge("B", "华南", 1.0, "2026-09-01", "2026-09-30"),
    edge("A", "华北", 1.0, "2026-10-01"),
]
graph.validate_edges(reverse_ok)
check("日期不重叠的反向关系通过", True)
sep_rev = {x["region"]: x for x in graph.propagate("d1", "数字", "2026-09-15", reverse_ok, 500, 5)}
octo_rev = {x["region"]: x for x in graph.propagate("d1", "数字", "2026-10-15", reverse_ok, 500, 5)}
check("9 月经 A→B 流向华南", list(sep_rev) == ["华南"], str(list(sep_rev)))
check("10 月经 B→A 流向华北", list(octo_rev) == ["华北"], str(list(octo_rev)))
# 让反向边在 10 月重叠 → 必须成环被拒
reverse_bad = reverse_ok + [edge("A", "B", 1.0, "2026-10-01")]
expect_value_error("反向关系重叠后成环拒绝", lambda: graph.validate_edges(reverse_bad), "环路")

print("== 5. 中间节点有入无出被拦截 ==")
dead_end = [edge("C", "H", 1.0, "2026-09-01"), edge("H", "华南", 0.5, "2026-09-01")]
expect_value_error("权重缺失先被拦截", lambda: graph.validate_edges(dead_end), "必须等于 1")
terminals = {"华东", "华北", "华南"}
dead_end2 = [edge("C", "H", 1.0, "2026-09-01", "2026-09-30"),
             edge("H", "华南", 1.0, "2026-09-01", "2026-09-30"),
             edge("C", "H2", 1.0, "2026-10-01")]
expect_value_error("失效后中间节点断流被拦截",
                   lambda: graph.propagate("s", "C", "2026-10-15", dead_end2, 10, 1, terminals), "没有流出权重")
# 提供终点集合时，合法区域汇点不会被误判
graph.propagate("s", "C", "2026-09-15", ok, 100, 4, terminals)
check("区域终点在 terminals 中不被误判为断流", True)

print("== 6. 并发成环：各自合法，合并后只允许一份 ==")
# 现状 A→B、C→D；两笔并发修改分别加入 B→C（合法链）与 D→A（单独合法），
# 但两者合并后 A→B→C→D→A 成环。锁串行化后第二笔必须失败。
base = [edge("A", "B", 1.0, "2026-09-01", eid=1), edge("C", "D", 1.0, "2026-09-01", eid=2)]
lock = threading.RLock()
committed = list(base)
errors = []


def transaction(add):
    with lock:  # 对应 pg_advisory_xact_lock 的串行化效果
        try:
            graph.validate_prospective(committed, add)
            committed.append(add)
        except ValueError as exc:
            errors.append(str(exc))


t1 = threading.Thread(target=transaction, args=(edge("B", "C", 1.0, "2026-09-01", eid=3),))
t2 = threading.Thread(target=transaction, args=(edge("D", "A", 1.0, "2026-09-01", eid=4),))
t1.start(); t2.start(); t1.join(); t2.join()
check("恰好一份并发修改被拒绝", len(errors) == 1, str(errors))
check("拒绝原因指向环路", all("环路" in e for e in errors), str(errors))
check("生效边集合保持无环（4 条→3 条）", len(committed) == 3, str(committed))
# 无论哪个线程先抢到锁，先到的那份一定生效
first = committed[-1]
check("先到的修改已落库", first["source"] in ("B", "D") and first["target"] in ("C", "A"))

print("== 7. 未配置来源回退旧区域（旧数据兼容） ==")
fallback = graph.propagate("legacy", "未知渠道", "2026-09-10", ok, 100, 4)
check("无归属配置返回空列表由上层回退", fallback == [])

print(f"\n结果：{PASS} 通过 / {FAIL} 失败")
sys.exit(1 if FAIL else 0)
