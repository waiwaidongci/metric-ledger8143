import random,json
from datetime import datetime,timedelta,timezone,date
from src.config.database import SessionLocal,Base,engine
from src.models import User,Metric,SourceRow,ReportRun,DeliverySchedule,Delivery,AttributionNode,AttributionEdge,AttributionVersion
from src.utils.security import hash_password
from src.services.pivot_service import build_report

def _seed_attribution(db):
    # 节点：3 个来源渠道、4 个中间节点、3 个终点区域
    nodes=[("直营渠道","channel","直营渠道"),("书店合作","channel","书店合作渠道"),("数字发行","channel","数字发行渠道"),
           ("线上联营中心","hub","线上联营中心"),("线下联营中心","hub","线下联营中心"),
           ("华东发行枢纽","hub","华东发行枢纽"),("华北发行枢纽","hub","华北发行枢纽"),("数字联营A","hub","数字联营A"),("数字联营B","hub","数字联营B"),
           ("华东","region","华东区域"),("华北","region","华北区域"),("华南","region","华南区域")]
    for node,kind,label in nodes:
        if not db.query(AttributionNode).filter_by(node=node).first():
            db.add(AttributionNode(node=node,kind=kind,label=label))
    db.flush()
    # 自然键 (source,target,start_date)，重复执行只补缺失行
    edges=[
        # 直营渠道：同来源多路径在华东汇合（线上/线下两个联营中心都流向华东发行枢纽）
        ("直营渠道","线上联营中心",0.6,"2026-09-01",None),
        ("直营渠道","线下联营中心",0.4,"2026-09-01",None),
        ("线上联营中心","华东发行枢纽",0.7,"2026-09-01",None),
        ("线上联营中心","华南",0.3,"2026-09-01",None),
        ("线下联营中心","华东发行枢纽",1.0,"2026-09-01",None),
        ("华东发行枢纽","华东",0.5,"2026-09-01",None),
        ("华东发行枢纽","华北",0.5,"2026-09-01",None),
        # 书店合作：交错有效期，9 月与 10 月权重切换
        ("书店合作","华北发行枢纽",0.55,"2026-09-01","2026-09-30"),
        ("书店合作","华东",0.45,"2026-09-01","2026-09-30"),
        ("书店合作","华北发行枢纽",0.35,"2026-10-01",None),
        ("书店合作","华东",0.65,"2026-10-01",None),
        ("华北发行枢纽","华北",0.8,"2026-09-01",None),
        ("华北发行枢纽","华南",0.2,"2026-09-01",None),
        # 数字发行：日期不重叠的反向关系——9 月 A→B，10 月 B→A，两条边永不共存故无环；
        # 终点出口也按窗口错开，保证 A、B 在各自窗口的流出权重合计都恰好为 1
        ("数字发行","数字联营A",1.0,"2026-09-01","2026-09-30"),
        ("数字发行","数字联营B",1.0,"2026-10-01",None),
        ("数字联营A","数字联营B",1.0,"2026-09-01","2026-09-30"),
        ("数字联营B","数字联营A",1.0,"2026-10-01",None),
        ("数字联营B","华南",1.0,"2026-09-01","2026-09-30"),
        ("数字联营A","华北",1.0,"2026-10-01",None),
    ]
    existing={(x.source,x.target,x.start_date,x.end_date) for x in db.query(AttributionEdge).all()}
    for source,target,weight,start,end in edges:
        if (source,target,start,end) not in existing:
            db.add(AttributionEdge(source=source,target=target,weight=weight,start_date=start,end_date=end,owner="陆知衡 · 口径负责人"))
    db.flush()

def seed():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        _seed_attribution(db)
        for role,name in [("admin","陆知衡 · 口径负责人"),("analyst","宋予 · 经营分析师"),("viewer","叶言 · 渠道阅读者")]:
            email=role+"@hengchi.demo"
            if not db.query(User).filter_by(email=email).first():db.add(User(email=email,name=name,role=role,password_hash=hash_password("Hengchi2026!")))
        for key,name,expression,unit,description in [
            ("net_revenue","净收入","revenue-refunds","元","渠道收入减退款，不扣履约成本。"),
            ("gross_profit","贡献毛利","net_revenue-cost","元","净收入扣除渠道履约成本的贡献。"),
            ("margin_rate","贡献毛利率","gross_profit/net_revenue","比率","先汇总净收入和毛利，再计算比例。"),
            ("net_per_order","每单净收入","net_revenue/orders","元/单","汇总净收入除以有效单数，禁止简单平均。"),
            ("refund_rate","退款率","refunds/revenue","比率","退款金额占渠道原始收入的比例。")]:
            if not db.query(Metric).filter_by(key=key).first():db.add(Metric(key=key,name=name,expression=expression,unit=unit,description=description,owner="陆知衡 · 口径负责人"))
        rng=random.Random(73);existing=set(x[0] for x in db.query(SourceRow.source_key))
        for i in range(1800):
            key=f"HC-{i+1:06}";day=(date(2026,9,1)+timedelta(days=i//30)).isoformat();channel=["直营渠道","书店合作","数字发行"][i%3];region=["华东","华北","华南"][(i//3)%3]
            revenue=round(rng.uniform(150,950),2);refunds=round(revenue*rng.uniform(.01,.12),2);cost=round(revenue*rng.uniform(.35,.6),2);orders=rng.randint(5,24)
            reference=round(revenue-refunds+(2.5 if channel=="书店合作" and day.startswith("2026-10") else 0),2)
            if key not in existing:db.add(SourceRow(source_key=key,day=day,channel=channel,region=region,revenue=revenue,refunds=refunds,cost=cost,orders=orders,reference_net=reference))
        db.flush();schedules=[]
        for name,mins,active in [("经营周报 · 渠道/月",10080,True),("区域午间校对",1440,False)]:
            schedule=db.query(DeliverySchedule).filter_by(name=name).first()
            if not schedule:
                schedule=DeliverySchedule(name=name,dimensions=["channel","month"] if mins==10080 else ["region","month"],interval_minutes=mins,next_run_at=(datetime.now(timezone.utc)+timedelta(days=7)).isoformat(),active=active,owner="陆知衡 · 口径负责人")
                db.add(schedule);db.flush()
            schedules.append(schedule)
        if not db.query(ReportRun).filter_by(name="11月经营口径核对 · 基准").first():
            result=build_report(db.query(SourceRow).order_by(SourceRow.id).all(),db.query(Metric).order_by(Metric.id).all(),["channel","month"])
            run=ReportRun(name="11月经营口径核对 · 基准",dimensions=["channel","month"],status="completed",result=result,owner="宋予 · 经营分析师",schedule_id=schedules[0].id)
            db.add(run);db.flush();db.add(Delivery(schedule_id=schedules[0].id,run_id=run.id,title="经营周报 · 基准交付"))
        db.commit();print(json.dumps({m.__tablename__:db.query(m).count() for m in [User,Metric,SourceRow,ReportRun,DeliverySchedule,Delivery]},ensure_ascii=False))
if __name__=="__main__":seed()
