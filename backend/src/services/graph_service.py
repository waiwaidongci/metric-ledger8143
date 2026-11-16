"""多层归属图：按生效日期维护的加权有向图，支持环路/权重校验与按天传播。

设计要点（对应渠道拆并后的归属分摊需求）：
- 边按生效日期版本化：start_date <= day <= end_date（end_date 为空表示开放区间）。
- 任一节点在任一生效日的流出权重合计必须等于 1（容差 1e-6），否则拒绝登记。
- 有效期区间内任一关键日期的生效子图出现环路即拒绝；日期不重叠的反向关系不构成环。
- 同一对有序节点的有效期不得重叠（同一关系每日只有一个权重）。
- 传播按拓扑顺序逐层推进；同一来源经多条路径抵达同一区域时在汇合点合并。
本模块只依赖标准库，入参为普通 dict 列表，便于离线单测与版本快照复用。
"""
from collections import defaultdict
from datetime import date

EPS = 1e-6


def _to_day(value):
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def edge_active(edge, day):
    d = _to_day(day)
    start = _to_day(edge["start_date"])
    if d < start:
        return False
    end = edge.get("end_date")
    return end is None or d <= _to_day(end)


def active_edges(edges, day):
    return [e for e in edges if edge_active(e, day)]


def _key_days(edges, start=None, end=None):
    """只需在边区间端点切换日校验：区间内生效边集合仅在这些日期变化。"""
    days = {_to_day(e["start_date"]) for e in edges}
    days.update(_to_day(e["end_date"]) for e in edges if e.get("end_date"))
    if start is not None:
        days.add(_to_day(start))
    if end is not None:
        days.add(_to_day(end))
    return sorted(days)


def find_cycle(edges, day):
    """对 day 的生效子图做 DFS 三色标记，返回构成环路的节点序列（无环返回 []）。"""
    adjacency = defaultdict(list)
    nodes = set()
    for edge in active_edges(edges, day):
        adjacency[edge["source"]].append(edge["target"])
        nodes.add(edge["source"])
        nodes.add(edge["target"])
    color = {}  # 0=未访问 1=访问中 2=完成
    stack = []

    def dfs(node):
        color[node] = 1
        stack.append(node)
        for nxt in sorted(adjacency[node]):
            state = color.get(nxt, 0)
            if state == 1:
                idx = stack.index(nxt)
                return stack[idx:] + [nxt]
            if state == 0:
                found = dfs(nxt)
                if found:
                    return found
        stack.pop()
        color[node] = 2
        return []

    for node in sorted(nodes):
        if color.get(node, 0) == 0:
            cycle = dfs(node)
            if cycle:
                return cycle
    return []


def _overlap(a_start, a_end, b_start, b_end):
    s = max(a_start, b_start)
    a_end = a_end or date.max
    b_end = b_end or date.max
    e = min(a_end, b_end)
    return s <= e


def validate_edges(edges, start=None, end=None):
    """对完整边集合做结构校验，失败时抛出带中文原因的 ValueError。"""
    if not edges:
        return
    parsed = []
    for edge in edges:
        s = _to_day(edge["start_date"])
        e = _to_day(edge["end_date"]) if edge.get("end_date") else None
        if e is not None and e < s:
            raise ValueError(f"边 {edge['source']} → {edge['target']} 的失效日期早于生效日期")
        weight = float(edge["weight"])
        if weight <= 0 or weight > 1:
            raise ValueError(f"边 {edge['source']} → {edge['target']} 权重必须在 (0,1] 之间")
        if edge["source"] == edge["target"]:
            raise ValueError(f"节点 {edge['source']} 不允许自环")
        parsed.append((edge, s, e, weight))
    # 同一对有序节点的有效期不允许重叠；反向关系（source/target 对调）不受此限制
    for i in range(len(parsed)):
        edge, s1, e1, _ = parsed[i]
        for j in range(i + 1, len(parsed)):
            other, s2, e2, _ = parsed[j]
            if edge["source"] == other["source"] and edge["target"] == other["target"] and _overlap(s1, e1, s2, e2):
                raise ValueError(
                    f"同一关系 {edge['source']} → {edge['target']} 存在重叠有效期："
                    f"{s1.isoformat()}~{e1 or '开放'} 与 {s2.isoformat()}~{e2 or '开放'}"
                )
    for day in _key_days([p[0] for p in parsed], start, end):
        current = active_edges([p[0] for p in parsed], day)
        cycle = find_cycle(current, day)
        if cycle:
            raise ValueError(f"生效日期 {day.isoformat()} 的归属关系存在环路：{' → '.join(cycle)}")
        totals = defaultdict(float)
        for edge in current:
            totals[edge["source"]] += float(edge["weight"])
        for node, total in totals.items():
            if abs(total - 1.0) > EPS:
                raise ValueError(
                    f"节点 {node} 在 {day.isoformat()} 的流出权重合计为 {round(total, 6)}，必须等于 1"
                )


def validate_prospective(existing, candidate):
    """登记/修改单条边时，把候选边并入现有集合后整体校验。"""
    merged = [e for e in existing if e.get("id") != candidate.get("id")]
    merged.append(candidate)
    validate_edges(merged)


def propagation_graph(edges, day, terminals=None):
    """返回 day 的生效图 (邻接表, 拓扑序列)。

    terminals 为已知终点（区域）集合：提供时，中间节点有入无出会报错；
    不提供时纯图模式把所有汇点视为合法终点（离线/兼容场景）。
    """
    current = active_edges(edges, day)
    cycle = find_cycle(current, day)
    if cycle:
        raise ValueError(f"生效日期 {_to_day(day).isoformat()} 的归属关系存在环路：{' → '.join(cycle)}")
    adjacency = defaultdict(list)
    indegree = defaultdict(int)
    nodes = set()
    for edge in current:
        adjacency[edge["source"]].append((edge["target"], float(edge["weight"])))
        indegree[edge["target"]] += 1
        nodes.add(edge["source"])
        nodes.add(edge["target"])
    incoming_nodes = {edge["target"] for edge in current}
    queue = sorted(n for n in nodes if indegree[n] == 0)
    order = []
    indegree = dict(indegree)
    while queue:
        node = queue.pop(0)
        order.append(node)
        for nxt, _ in sorted(adjacency[node]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
        queue.sort()
    if len(order) != len(nodes):
        raise ValueError(f"生效日期 {_to_day(day).isoformat()} 的归属关系存在环路")
    if terminals is not None:
        for node in order:
            if node in incoming_nodes and not adjacency.get(node) and node not in terminals:
                raise ValueError(f"中间节点 {node} 在 {_to_day(day).isoformat()} 没有流出权重，流量无法到达区域")
    return adjacency, order


def propagate(source_key, source_node, day, edges, amount, orders, terminals=None):
    """单条来源在某日按权重逐层流向区域，返回 [(区域, 金额权重, 单数权重, 路径)]。

    汇合不在这里合并：同一 source_key 只会产出按区域区分的份额，
    跨来源到同一区域的合并在上层分组时完成；同来源多路径的份额也各自带路径留痕。
    """
    adjacency, order = propagation_graph(edges, day, terminals)
    if source_node not in order:
        return []  # 该来源当日未配置归属：回退到来源行旧区域
    # 每个节点持有 (累计金额权重, 累计单数权重, 路径列表)
    flows = {source_node: (1.0, 1.0, [[source_node]])}
    for node in order:
        if node not in flows:
            continue
        weight_sum, order_sum, paths = flows[node]
        outgoing = adjacency.get(node, [])
        if not outgoing:
            continue  # 终点区域
        for target, weight in outgoing:
            piece = (weight_sum * weight, order_sum * weight, [p + [target] for p in paths])
            if target in flows:
                old_w, old_o, old_paths = flows[target]
                flows[target] = (old_w + piece[0], old_o + piece[1], old_paths + piece[2])
            else:
                flows[target] = piece
    results = []
    for node, (weight_sum, order_weight, paths) in flows.items():
        if adjacency.get(node):
            continue  # 仅保留终点
        results.append({
            "source_key": source_key,
            "region": node,
            "weight": weight_sum,
            "amount": amount * weight_sum,
            "orders": orders * order_weight,
            "paths": paths,
        })
    return results
