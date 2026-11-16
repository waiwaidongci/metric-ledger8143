import {request} from './client';
export interface AttributionNode{id:number;node:string;kind:string;label:string}
export interface AttributionEdge{id:number;source:string;target:string;weight:number;start_date:string;end_date:string|null}
export interface AttributionVersion{id:number;note:string;owner:string;created_at:string;edge_count:number;in_use:boolean}
export interface AllocationBasis{source_key:string;region:string;weight:number;revenue:number;orders:number;fallback:boolean;paths:string[]}
export const getNodes=()=>request<AttributionNode[]>('/attribution/nodes');
export const getEdges=()=>request<AttributionEdge[]>('/attribution/edges');
export const getVersions=()=>request<AttributionVersion[]>('/attribution/versions');
export const createEdge=(data:{source:string;target:string;weight:number;start_date:string;end_date:string|null})=>request<AttributionEdge>('/attribution/edges',{method:'POST',body:JSON.stringify(data)});
export const updateEdge=(id:number,data:Partial<{target:string;weight:number;start_date:string;end_date:string|null}>)=>request<AttributionEdge>(`/attribution/edges/${id}`,{method:'PATCH',body:JSON.stringify(data)});
export const deleteEdge=(id:number)=>request<{deleted:number}>(`/attribution/edges/${id}`,{method:'DELETE'});
