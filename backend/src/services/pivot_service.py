import hashlib,json
from collections import defaultdict
from ..constants.dimensions import BASE_FIELDS,Dimension
from .expression_service import compile_metrics,calculate
from . import graph_service

def _row_dict(row):
    return {"source_key":row.source_key,"day":row.day,"channel":row.channel,"region":row.region,
            "revenue":row.revenue,"cost":row.cost,"refunds":row.refunds,"orders":row.orders,
            "reference_net":row.reference_net}

def _fragments(rows,edges,terminals):
    """把来源行按归属图拆成带份额的碎片；未配置归属的来源回退到来源行旧区域（旧数据兼容）。"""
    fragments=[]
    for row in rows:
        channel=row["channel"]
        shares=graph_service.propagate(row["source_key"],channel,row["day"],edges,row["revenue"],row["orders"],terminals)
        if not shares:
            shares=[{"source_key":row["source_key"],"region":row["region"],"weight":1.0,
                     "paths":[[channel,row["region"]]],"fallback":True}]
        for share in shares:
            weight=share["weight"]
            fragment={key:row[key] for key in ("source_key","day","channel","region")}
            for field in BASE_FIELDS:
                fragment[field]=row[field]*weight
            fragment["reference_net"]=row["reference_net"]*weight
            fragment["target_region"]=share["region"]
            fragment["weight"]=weight
            fragment["paths"]=share["paths"]
            fragment["fallback"]=share.get("fallback",False)
            fragments.append(fragment)
    return fragments

def _allocation_basis(fragments):
    """来源 → 区域的分摊依据：同来源经多条路径到同一区域时在此合并。"""
    merged=defaultdict(lambda:{"amount":0.0,"orders":0.0,"weight":0.0,"paths":set(),"fallback":True})
    for fragment in fragments:
        key=(fragment["source_key"],fragment["target_region"])
        slot=merged[key]
        slot["amount"]+=fragment["revenue"]
        slot["orders"]+=fragment["orders"]
        slot["weight"]+=fragment["weight"]
        slot["fallback"]=slot["fallback"] and fragment["fallback"]
        for path in fragment["paths"]:
            slot["paths"].add(" → ".join(path))
    basis=[]
    for (source_key,region),slot in sorted(merged.items()):
        basis.append({"source_key":source_key,"region":region,"weight":round(slot["weight"],6),
                      "revenue":round(slot["amount"],6),"orders":round(slot["orders"],6),
                      "fallback":slot["fallback"],"paths":sorted(slot["paths"])})
    return basis

def build_report(rows,metrics,dimensions,edges=None,attribution_version_id=None,terminals=None):
    if not rows:raise ValueError("没有可计算的来源明细")
    if not dimensions or len(dimensions)>2 or len(set(dimensions))!=len(dimensions) or not set(dimensions)<=set(Dimension):raise ValueError("请选择一到两个不同的有效维度")
    rows=sorted((_row_dict(r) for r in rows),key=lambda r:r["source_key"])
    trees,order,deps=compile_metrics(metrics)
    if not order:raise ValueError("请先注册指标")
    use_attribution=bool(edges) and "region" in dimensions
    if use_attribution:
        fragments=_fragments(rows,edges,terminals)
        members_pool=fragments
        def dim_value(item,dim):
            if dim=="region":return item["target_region"]
            if dim=="month":return item["day"][:7]
            return item[dim]
    else:
        members_pool=rows
        def dim_value(item,dim):
            return item["day"][:7] if dim=="month" else item[dim]
    grouped=defaultdict(list)
    for item in members_pool:
        grouped[tuple(dim_value(item,dim) for dim in dimensions)].append(item)
    def aggregate(members):
        base={key:sum(m[key] for m in members) for key in BASE_FIELDS}
        computed=calculate(base,trees,order)
        reference=sum(m["reference_net"] for m in members)
        canonical=base['revenue']-base['refunds']
        difference=canonical-reference
        source_count=len({m['source_key'] for m in members})
        cell={"values":computed,"reference_net":round(reference,6),"canonical_net":round(canonical,6),
              "difference":round(difference,6),"relative_difference":difference/reference if reference else None,
              "source_count":source_count}
        if use_attribution:
            cell["allocation_weight"]=round(sum(m["weight"] for m in members),6)
        return cell
    cells=[{"dimensions":dict(zip(dimensions,key)),**aggregate(members)} for key,members in sorted(grouped.items())]
    total=aggregate(members_pool)
    checksum_payload=[(r["source_key"],r["day"],r["channel"],r["region"],r["revenue"],r["refunds"],r["cost"],r["orders"],r["reference_net"]) for r in rows]
    checksum=hashlib.sha256(json.dumps(checksum_payload,sort_keys=True).encode()).hexdigest()
    result={"dimensions":dimensions,"metrics":[{"key":m.key,"name":m.name,"expression":m.expression,"unit":m.unit} for m in metrics],"evaluation_order":order,"dependencies":deps,"cells":cells,"total":total,"affected_cells":sum(abs(c['difference'])>.01 for c in cells),"attribution":sorted([c for c in cells if abs(c['difference'])>.01],key=lambda c:abs(c['difference']),reverse=True),"source_checksum":checksum,"reconciliation_rule":"来源 revenue-refunds 与 reference_net 比较；绝对差异 > 0.01 元标记。比率指标在汇总原始字段后重算，不汇总比率。"}
    if use_attribution:
        basis=_allocation_basis(fragments)
        original_revenue=round(sum(r["revenue"] for r in rows),6)
        allocated_revenue=round(sum(f["revenue"] for f in fragments),6)
        original_orders=round(sum(r["orders"] for r in rows),6)
        allocated_orders=round(sum(f["orders"] for f in fragments),6)
        conserved=abs(original_revenue-allocated_revenue)<1e-6 and abs(original_orders-allocated_orders)<1e-6
        if not conserved:
            raise ValueError("跨区分摊不守恒：分摊前后金额或单数合计不一致")
        result.update({"attribution_version_id":attribution_version_id,
                       "allocation_basis":basis,
                       "allocation_rule":"区域单元先按归属版本把金额与单数分摊到终点区域，再汇总重算指标；同来源多路径到同一区域合并；无归属配置的来源沿用来源行旧区域。",
                       "conservation":{"revenue_before":original_revenue,"revenue_after":allocated_revenue,
                                       "orders_before":original_orders,"orders_after":allocated_orders,"conserved":conserved}})
    return result
