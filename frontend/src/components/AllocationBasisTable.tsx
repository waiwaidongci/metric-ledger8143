import {useMemo,useState} from 'react';
import {ChevronDown,ChevronUp,Route} from 'lucide-react';
import {AllocationBasis} from '../types/domain';
import {DataTable} from './common/DataTable';
import {number} from '../utils/format';

export function AllocationBasisTable({basis}:{basis:AllocationBasis[]}){
  const [open,setOpen]=useState(false);
  const [region,setRegion]=useState('全部');
  const regions=useMemo(()=>['全部',...Array.from(new Set(basis.map(b=>b.region)))],[basis]);
  const shown=useMemo(()=>basis.filter(b=>region==='全部'||b.region===region).slice(0,open?200:8),[basis,region,open]);
  return (
    <div className="basis-block">
      <div className="section-heading">
        <h2><Route size={16}/> 来源 → 区域分摊依据</h2>
        <div className="basis-controls">
          <select aria-label="按区域筛选" value={region} onChange={e=>setRegion(e.target.value)}>{regions.map(r=><option key={r} value={r}>{r==='全部'?'全部终点区域':r}</option>)}</select>
          <button className="ghost" onClick={()=>setOpen(v=>!v)}>{open?<><ChevronUp size={14}/>收起</>:<><ChevronDown size={14}/>展开全部 {basis.length} 条</>}</button>
        </div>
      </div>
      <DataTable head={['来源编号','终点区域','分摊权重','分摊收入 / 元','分摊单数','取数方式','分摊路径（多路径已合并）']}>
        {shown.map((b,i)=>(
          <tr key={b.source_key+b.region+i}>
            <td className="mono">{b.source_key}</td>
            <td><b>{b.region}</b></td>
            <td className="mono">{number(b.weight,4)}</td>
            <td>{number(b.revenue)}</td>
            <td>{number(b.orders,2)}</td>
            <td><span className={b.fallback?'tag tag-fallback':'tag tag-allocated'}>{b.fallback?'来源行旧区域':'归属版本分摊'}</span></td>
            <td className="path-cell">{b.paths.map(p=><span key={p} className="path-chip">{p}</span>)}</td>
          </tr>
        ))}
      </DataTable>
      <p className="caption">同一来源经多条路径到达同一区域时合并为一行，路径列保留合并前的全部流向；权重列为该来源流向该区域的合计份额。</p>
    </div>
  );
}
