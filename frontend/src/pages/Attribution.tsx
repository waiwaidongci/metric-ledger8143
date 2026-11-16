import {FormEvent,useMemo,useState} from 'react';
import {GitBranch,Trash2,Plus,ShieldCheck,History} from 'lucide-react';
import {useLedgerData} from '../hooks/useLedger';
import {useAuth} from '../stores/auth';
import {useAction} from '../hooks/useAction';
import {createEdge,deleteEdge} from '../api/attribution';
import {Notice} from '../components/common/Notice';
import {DataTable} from '../components/common/DataTable';
import {time,number} from '../utils/format';

const kindName:Record<string,string>={channel:'来源渠道',hub:'中间节点',region:'终点区域'};

export function Attribution(){
  const s=useLedgerData(true),{user}=useAuth(),action=useAction();
  const editable=user?.role==='admin';
  const channels=useMemo(()=>s.nodes.filter(n=>n.kind==='channel'),[s.nodes]);
  const hubs=useMemo(()=>s.nodes.filter(n=>n.kind==='hub'),[s.nodes]);
  const regions=useMemo(()=>s.nodes.filter(n=>n.kind==='region'),[s.nodes]);
  const [source,setSource]=useState(''),[target,setTarget]=useState(''),[weight,setWeight]=useState(0.5),[start,setStart]=useState('2026-09-01'),[end,setEnd]=useState('');
  const nodeLabel=(name:string)=>s.nodes.find(n=>n.node===name)?.label||name;
  function submit(e:FormEvent){
    e.preventDefault();
    action.execute(async()=>{
      await createEdge({source,target,weight,start_date:start,end_date:end||null});
      setSource('');setTarget('');setWeight(0.5);
      await s.refresh();
    });
  }
  function remove(id:number){
    action.execute(async()=>{await deleteEdge(id);await s.refresh();});
  }
  // 按节点汇总当日流出权重，帮助快速识别不等于 1 的节点
  const today=new Date().toISOString().slice(0,10);
  const outgoingCheck=useMemo(()=>{
    const totals:Record<string,number>={};
    for(const edge of s.edges){
      if(edge.end_date&&edge.end_date<today)continue;
      if(edge.start_date>today)continue;
      totals[edge.source]=(totals[edge.source]||0)+edge.weight;
    }
    return totals;
  },[s.edges,today]);
  return (
    <div className="page">
      <div className="page-title">
        <div>
          <p className="eyebrow">ATTRIBUTION GRAPH / 05</p>
          <h1>归属分摊<span>按生效日期维护多层关系，渠道经中间节点按权重流向区域。</span></h1>
        </div>
        <span className="issue-tag">{s.edges.length} 条生效关系</span>
      </div>
      <Notice message={s.error||action.error} retry={s.refresh}/>

      <div className="attribution-layout">
        <section>
          <div className="section-heading top">
            <h2><GitBranch size={17}/> 归属关系登记</h2>
            <span>每个节点每天流出权重合计须等于 1</span>
          </div>
          {editable&&(
            <form className="edge-form" onSubmit={submit}>
              <label>来源节点
                <select aria-label="来源节点" value={source} onChange={e=>setSource(e.target.value)} required>
                  <option value="">选择渠道/中间节点</option>
                  <optgroup label="来源渠道">{channels.map(n=><option key={n.id} value={n.node}>{n.label}</option>)}</optgroup>
                  <optgroup label="中间节点">{hubs.map(n=><option key={n.id} value={n.node}>{n.label}</option>)}</optgroup>
                </select>
              </label>
              <label>流向节点
                <select aria-label="流向节点" value={target} onChange={e=>setTarget(e.target.value)} required>
                  <option value="">选择中间节点/区域</option>
                  <optgroup label="中间节点">{hubs.map(n=><option key={n.id} value={n.node}>{n.label}</option>)}</optgroup>
                  <optgroup label="终点区域">{regions.map(n=><option key={n.id} value={n.node}>{n.label}</option>)}</optgroup>
                </select>
              </label>
              <label>权重
                <input aria-label="权重" type="number" step="0.01" min="0.01" max="1" value={weight} onChange={e=>setWeight(Number(e.target.value))} required/>
              </label>
              <label>生效日期
                <input aria-label="生效日期" type="date" value={start} onChange={e=>setStart(e.target.value)} required/>
              </label>
              <label>失效日期（留空长期有效）
                <input aria-label="失效日期" type="date" value={end} onChange={e=>setEnd(e.target.value)} min={start}/>
              </label>
              <button className="primary" disabled={action.busy}><Plus size={15}/>登记关系</button>
            </form>
          )}
          {!editable&&<p className="role-note">当前角色只读；归属关系由口径负责人维护，登记即做环路与权重校验。</p>}

          <DataTable head={['来源','流向','权重','生效区间','流出合计','操作']}>
            {s.edges.map(edge=>(
              <tr key={edge.id}>
                <td><b>{nodeLabel(edge.source)}</b><small>{edge.source}</small></td>
                <td><b>{nodeLabel(edge.target)}</b><small>{edge.target}</small></td>
                <td className="mono">{number(edge.weight,2)}</td>
                <td className="mono">{edge.start_date} ~ {edge.end_date||'长期'}</td>
                <td className={Math.abs((outgoingCheck[edge.source]||0)-1)>1e-6?'difference':''}>
                  {number(outgoingCheck[edge.source]||0,2)}
                </td>
                <td>{editable&&<button className="icon-button" aria-label={`删除关系 ${edge.id}`} onClick={()=>remove(edge.id)}><Trash2 size={15}/></button>}</td>
              </tr>
            ))}
          </DataTable>

          <div className="section-heading"><h2><History size={16}/> 冻结版本（同版关系复算）</h2><span>报表入队时快照，手工与定时共用</span></div>
          <DataTable head={['版本','说明','关系数','冻结时间','冻结人','状态']}>
            {s.versions.map(v=>(
              <tr key={v.id}>
                <td className="mono">#{v.id}</td>
                <td>{v.note}</td>
                <td>{v.edge_count}</td>
                <td>{time(v.created_at)}</td>
                <td>{v.owner}</td>
                <td>{v.in_use?<span className="schedule-status active">被报表引用</span>:<span className="schedule-status">可归档</span>}</td>
              </tr>
            ))}
            {!s.versions.length&&<tr><td colSpan={6}>创建区域报表后会在此留下归属版本快照。</td></tr>}
          </DataTable>
        </section>

        <aside className="registration">
          <span className="eyebrow">GRAPH RULES / 校验口径</span>
          <h2>维护规则</h2>
          <ul className="rule-list">
            <li><ShieldCheck size={15}/> 各节点每个生效日的流出权重合计为 1，否则拒绝登记。</li>
            <li><ShieldCheck size={15}/> 有效期重叠的环路直接拒绝；日期不重叠的反向关系可用。</li>
            <li><ShieldCheck size={15}/> 并发修改各自合法、合并后成环时，只允许先提交的一份生效。</li>
            <li><ShieldCheck size={15}/> 同一来源经多条路径到同一区域时自动合并，并保留全部路径。</li>
            <li><ShieldCheck size={15}/> 未配置归属的来源沿用来源行旧区域，历史报表保持不变。</li>
          </ul>
          <div className="method-note">
            <b>节点登记</b>
            <p>{channels.length} 个来源渠道 · {hubs.length} 个中间节点 · {regions.length} 个终点区域。区域为归属终点，渠道为起点。</p>
            <div className="node-chips">
              {s.nodes.map(n=><span key={n.id} className={`chip chip-${n.kind}`}>{n.label}<small>{kindName[n.kind]}</small></span>)}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
