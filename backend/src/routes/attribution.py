from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy.orm import Session
from ..config.database import get_db
from ..controllers.dependencies import current_user,roles
from ..constants.roles import Role
from ..schemas.attribution import EdgeInput,EdgePatch,NodeInput
from ..services.attribution_service import (list_edges,list_nodes,list_versions,
    create_edge,update_edge,delete_edge)
from ..models import AttributionNode
from ..utils.serialize import record
from ..services.audit_service import log
router=APIRouter(prefix="/attribution",tags=["attribution"])
@router.get("/edges")
def edges(db:Session=Depends(get_db),user=Depends(current_user)):return list_edges(db)
@router.get("/nodes")
def nodes(db:Session=Depends(get_db),user=Depends(current_user)):return list_nodes(db)
@router.get("/versions")
def versions(db:Session=Depends(get_db),user=Depends(current_user)):return list_versions(db)
@router.post("/edges",status_code=201)
def add_edge(data:EdgeInput,db:Session=Depends(get_db),user=Depends(roles(Role.ADMIN))):return create_edge(db,data,user)
@router.patch("/edges/{edge_id}")
def patch_edge(edge_id:int,data:EdgePatch,db:Session=Depends(get_db),user=Depends(roles(Role.ADMIN))):return update_edge(db,edge_id,data,user)
@router.delete("/edges/{edge_id}")
def remove_edge(edge_id:int,db:Session=Depends(get_db),user=Depends(roles(Role.ADMIN))):return delete_edge(db,edge_id,user)
@router.post("/nodes",status_code=201)
def add_node(data:NodeInput,db:Session=Depends(get_db),user=Depends(roles(Role.ADMIN))):
    if db.query(AttributionNode).filter_by(node=data.node).first():
        raise HTTPException(409,"节点标识已存在")
    row=AttributionNode(**data.model_dump())
    db.add(row);db.flush();log(db,user.email,"attribution.node.create",row.node);db.commit()
    return record(row)
