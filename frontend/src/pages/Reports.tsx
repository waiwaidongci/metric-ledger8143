import {FormEvent,useState} from 'react';import {useSearchParams} from 'react-router-dom';import {Download,ArrowRight,Files} from 'lucide-react';import {useLedgerData} from '../hooks/useLedger';import {useAuth} from '../stores/auth';import {useAction} from '../hooks/useAction';import {createReport} from '../api/reports';import {download} from '../api/client';import {StatusBadge} from '../components/common/StatusBadge';import {Notice} from '../components/common/Notice';import {PivotTable} from '../components/PivotTable';import {AllocationBasisTable} from '../components/AllocationBasisTable';import {Dimensions} from '../constants/enums';import {time,money} from '../utils/format';
export function Reports(){
  const s=useLedgerData(true),{user}=useAuth(),action=useAction();
  const [params]=useSearchParams(),[selected,setSelected]=useState(Number(params.get('run'))||0),[name,setName]=useState(''),[dim,setDim]=useState('channel');
  const run=s.reports.find(r=>r.id===selected)||s.reports[0];
  const allocated=run?.status==='completed'&&!!run.result?.allocation_basis;
  function submit(e:FormEvent){e.preventDefault();action.execute(async()=>{const r=await createReport({name,dimensions:[dim,'month']});setSelected(r.id);setName('');await s.refresh();});}
  return <div className="page reports-page">
    <div className="page-title"><div><p className="eyebrow">PIVOT WORKSHEET / 04</p><h1>透视报表<span>先分摊金额与单数，再按冻结口径重算指标。</span></h1></div>{run?.status==='completed'&&<div className="export-group"><button className="outline" onClick={()=>action.execute(async()=>{await download(`/reports/${run.id}/export`,`metric-report-${run.id}.csv`);})}><Download size={16}/>导出 CSV</button>{allocated&&<button className="outline" onClick={()=>action.execute(async()=>{await download(`/reports/${run.id}/basis-export`,`allocation-basis-${run.id}.csv`);})}><Files size={16}/>导出分摊依据</button>}</div>}</div>
    <Notice message={s.error||action.error} retry={s.refresh}/>
    {user?.role!=='viewer'&&<form className="inline-form" onSubmit={submit}><label>报表名称<input aria-label="报表名称" value={name} onChange={e=>setName(e.target.value)} minLength={2} placeholder="例如：11月区域经营核对" required/></label><label>透视维度<select aria-label="透视维度" value={dim} onChange={e=>setDim(e.target.value)}><option value="channel">渠道 × 月份（不分摊）</option><option value="region">区域 × 月份（按归属分摊）</option></select></label><button className="primary" disabled={action.busy}>排队计算 <ArrowRight size={15}/></button></form>}
    <div className="run-picker"><label>归档报表<select aria-label="归档报表" value={run?.id||''} onChange={e=>setSelected(Number(e.target.value))}>{s.reports.map(r=><option key={r.id} value={r.id}>#{r.id} · {r.name} · {r.status}</option>)}</select></label>{run&&<StatusBadge status={run.status}/>}</div>
    {run?.status==='completed'?<>
      <div className="report-heading"><div><span className="eyebrow">WORKSHEET #{String(run.id).padStart(3,'0')}</span><h2>{run.name}</h2><p>{time(run.created_at)} · {run.owner} · {run.dimensions.map(d=>Dimensions[d as keyof typeof Dimensions]).join(' × ')}</p></div><div><span>统一口径净收入</span><strong>{money(run.result.total.canonical_net)}</strong></div></div>
      {allocated&&<div className="allocation-banner">
        <div><span>归属版本</span><b className="mono">#{run.result.attribution_version_id}</b></div>
        <div><span>金额守恒</span><b className={run.result.conservation?.conserved?'ok':'difference'}>{run.result.conservation?.conserved?'是 · 跨区合计守恒':'否'}</b></div>
        <div><span>分摊前/后收入</span><b className="mono">{money(run.result.conservation?.revenue_before)} / {money(run.result.conservation?.revenue_after)}</b></div>
        <div><span>分摊前/后单数</span><b className="mono">{run.result.conservation?.orders_before} / {run.result.conservation?.orders_after}</b></div>
        <p>{run.result.allocation_rule}</p>
      </div>}
      <PivotTable result={run.result}/>
      {allocated&&<AllocationBasisTable basis={run.result.allocation_basis!}/>}
      <div className="report-footnote"><p>{run.result.reconciliation_rule}</p><small>口径快照：{run.result.metrics.map(m=>`${m.key}=${m.expression}`).join(' / ')}</small><small>来源SHA256：{run.result.source_checksum}</small>{run.attribution_version_id&&<small>归属版本快照：#{run.attribution_version_id}（计算期间改归属不影响本报表，页面与导出一致）</small>}</div>
    </>:run?<div className="pending"><h2>{run.status==='failed'?'本次计算失败':'后台正在整理透视底稿'}</h2><p>{run.error||'队列执行后会自动更新本页。定义和来源校验由Python后端完成。'}</p></div>:<div className="pending">还没有报表，请填写名称和维度，提交第一次计算。</div>}
  </div>;
}
