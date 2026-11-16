from datetime import date
from pydantic import BaseModel,Field
class EdgeInput(BaseModel):
    source:str=Field(min_length=1,max_length=60)
    target:str=Field(min_length=1,max_length=60)
    weight:float=Field(gt=0,le=1)
    start_date:date
    end_date:date|None=None
class EdgePatch(BaseModel):
    target:str|None=Field(default=None,min_length=1,max_length=60)
    weight:float|None=Field(default=None,gt=0,le=1)
    start_date:date|None=None
    end_date:date|None=None
class NodeInput(BaseModel):
    node:str=Field(min_length=1,max_length=60)
    kind:str=Field(pattern=r"^(channel|hub|region)$")
    label:str=Field(min_length=1,max_length=60)
class EdgeOutput(BaseModel):
    id:int
    source:str
    target:str
    weight:float
    start_date:str
    end_date:str|None
