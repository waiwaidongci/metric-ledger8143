import {useState} from 'react';import {useLedgerData} from '../hooks/useLedger';import {Notice} from '../components/common/Notice';import {DataTable} from '../components/common/DataTable';import {money,number,percent} from '../utils/format';import {Link} from 'react-router-dom';import {ArrowRight} from 'lucide-react';
export function Reconcile(){
  const s=useLedgerData(),r=s.reconciliation,region=s.regionReconciliation;
  const [tab,setTab]=useState<'channel'|'region'>('channel');
  const active=tab==='channel'?r:region;
  return <div className="page"><div className="page-title"><div><p className="eyebrow">SOURCE RECONCILIATION / 03</p><h1>来源核对<span>差异不只给总数，也要找到落点。</span></h1></div><button className="outline" onClick={s.refresh}>重新核对</button></div>
    <Notice message={s.error} retry={s.refresh}/>
    <div className="tab-bar"><button className={tab==='channel'?'tab active':'tab'} onClick={()=>setTab('channel')}>渠道口径 · 原区域历史</button><button className={tab==='region'?'tab active':'tab'} onClick={()=>setTab('region')}>区域口径 · 归属分摊</button></div>
    {active&&<>
      <div className="reconcile-summary"><div><span>参考账本净收入</span><strong>{money(active.total.reference_net)}</strong></div><div><span>来源重算净收入</span><strong>{money(active.total.canonical_net)}</strong></div><div><span>总差异 / {active.affected_cells} 个单元</span><strong className="difference">{money(active.total.difference)}</strong></div></div>
      {tab==='region'&&active.conservation&&<div className="allocation-banner compact"><div><span>金额守恒</span><b className={active.conservation.conserved?'ok':'difference'}>{active.conservation.conserved?'守恒':'异常'}</b></div><div><span>分摊前/后收入</span><b className="mono">{money(active.conservation.revenue_before)} / {money(active.conservation.revenue_after)}</b></div><div><span>分摊前/后单数</span><b className="mono">{active.conservation.orders_before} / {active.conservation.orders_after}</b></div><div><span>归属版本</span><b className="mono">当前关系（归档报表用冻结版）</b></div></div>}
      <div className="section-heading"><h2>{tab==='channel'?'差异归因':'区域分摊后差异'}</h2><span>按绝对差异排序 / 阈值 0.01 元</span></div>
      <DataTable head={[tab==='channel'?'渠道':'区域','月份',...(tab==='region'?['分摊权重']:[]),'来源重算 / 元','参考账本 / 元','差异 / 元','相对差异','明细数']}>
        {active.attribution.length?active.attribution.map((c,i)=><tr key={i}><td>{c.dimensions.channel||c.dimensions.region}</td><td>{c.dimensions.month}</td>{tab==='region'&&<td className="mono">{number(c.allocation_weight||0,4)}</td>}<td>{number(c.canonical_net)}</td><td>{number(c.reference_net)}</td><td className="difference">{number(c.difference)}</td><td>{percent(c.relative_difference)}</td><td>{c.source_count}</td></tr>):<tr><td colSpan={tab==='region'?8:7}>本次无超阈值差异，可继续生成交付报表。</td></tr>}
      </DataTable>
      <p className="caption">{active.reconciliation_rule}</p>
      {tab==='region'&&<p className="caption">{active.allocation_rule} <Link to="/attribution">维护归属关系 <ArrowRight size={12}/></Link></p>}
    </>}
    {tab==='channel'&&<><div className="section-heading"><h2>原始结算明细</h2><span>hengchi-settlement-202611.csv / 前100条</span></div>
    <DataTable head={['来源编号','日期','渠道 / 区域','收入 / 元','退款 / 元','成本 / 元','单数']}>{s.sources.map(row=><tr key={row.source_key}><td className="mono">{row.source_key}</td><td>{row.day}</td><td>{row.channel} / {row.region}</td><td>{number(row.revenue)}</td><td>{number(row.refunds)}</td><td>{number(row.cost)}</td><td>{row.orders}</td></tr>)}</DataTable></>}
  </div>;
}
