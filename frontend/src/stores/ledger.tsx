import {createContext,useContext,useState,useCallback,ReactNode} from 'react';
import {Metric,SourceRow,ReportRun,Schedule,Delivery,Audit,ReportResult,AttributionNode,AttributionEdge,AttributionVersion} from '../types/domain';
import {getMetrics} from '../api/metrics';
import {getSources,getReconciliation,getRegionReconciliation} from '../api/sources';
import {getReports} from '../api/reports';
import {getSchedules} from '../api/schedules';
import {getDeliveries} from '../api/deliveries';
import {getAudits} from '../api/audits';
import {getNodes,getEdges,getVersions} from '../api/attribution';
interface Ledger{
  metrics:Metric[];sources:SourceRow[];reports:ReportRun[];schedules:Schedule[];deliveries:Delivery[];audits:Audit[];
  order:string[];reconciliation:ReportResult|null;regionReconciliation:ReportResult|null;
  nodes:AttributionNode[];edges:AttributionEdge[];versions:AttributionVersion[];
  error:string;refresh:()=>Promise<void>;
}
const Context=createContext<Ledger>(null!);
export function LedgerProvider({children}:{children:ReactNode}){
  const [data,setData]=useState<Omit<Ledger,'refresh'>>({metrics:[],sources:[],reports:[],schedules:[],deliveries:[],audits:[],order:[],reconciliation:null,regionReconciliation:null,nodes:[],edges:[],versions:[],error:''});
  const refresh=useCallback(async()=>{
    try{
      const [metrics,sources,reports,schedules,deliveries,audits,reconciliation,regionReconciliation,nodes,edges,versions]=await Promise.all([
        getMetrics(),getSources(),getReports(),getSchedules(),getDeliveries(),getAudits(),getReconciliation(),getRegionReconciliation(),getNodes(),getEdges(),getVersions()]);
      setData({metrics:metrics.items,order:metrics.evaluation_order,sources,reports,schedules,deliveries,audits,reconciliation,regionReconciliation,nodes,edges,versions,error:''});
    }catch(e){setData(d=>({...d,error:(e as Error).message}));}
  },[]);
  return <Context.Provider value={{...data,refresh}}>{children}</Context.Provider>;
}
export const useLedger=()=>useContext(Context);
