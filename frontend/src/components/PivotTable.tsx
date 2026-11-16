import {ReportResult} from '../types/domain';import {DataTable} from './common/DataTable';import {Dimensions} from '../constants/enums';import {number} from '../utils/format';
export function PivotTable({result}:{result:ReportResult}){
  const hasWeight=result.cells.some(c=>c.allocation_weight!==undefined);
  return <DataTable head={[...result.dimensions.map(d=>Dimensions[d as keyof typeof Dimensions]),...(hasWeight?['分摊权重']:[]),...result.metrics.map(m=>m.name),'对照差异 / 元','明细数']}>
    {result.cells.map((cell,i)=><tr key={i}>{result.dimensions.map(d=><td key={d}>{cell.dimensions[d]}</td>)}
      {hasWeight&&<td className="mono">{number(cell.allocation_weight||0,4)}</td>}
      {result.metrics.map(m=><td key={m.key}>{number(cell.values[m.key],m.unit==='比率'?4:2)}</td>)}
      <td className={Math.abs(cell.difference)>.01?'difference':''}>{number(cell.difference)}</td>
      <td>{cell.source_count}</td></tr>)}
    <tr className="total-row"><td colSpan={result.dimensions.length}>重算合计</td>{hasWeight&&<td>—</td>}{result.metrics.map(m=><td key={m.key}>{number(result.total.values[m.key],m.unit==='比率'?4:2)}</td>)}<td className="difference">{number(result.total.difference)}</td><td>{result.total.source_count}</td></tr>
  </DataTable>;
}
