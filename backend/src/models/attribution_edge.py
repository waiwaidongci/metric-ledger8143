from sqlalchemy import JSON
from sqlalchemy.orm import Mapped,mapped_column
from ..config.database import Base
from ..utils.clock import now
class AttributionEdge(Base):
    """版本化归属边：source 按 weight 流向 target，仅在 [start_date,end_date] 内生效。

    同一对节点允许存在多条不重叠有效期的版本；重叠校验在服务层全量图校验中完成，
    避免数据库约束误伤合法的历史版本。
    """
    __tablename__="attribution_edges"
    id: Mapped[int]=mapped_column(primary_key=True)
    source: Mapped[str]
    target: Mapped[str]
    weight: Mapped[float]
    start_date: Mapped[str]
    end_date: Mapped[str|None]=mapped_column(nullable=True)
    owner: Mapped[str]
    created_at: Mapped[str]=mapped_column(default=now)
class AttributionVersion(Base):
    """每次报表计算入队时冻结的归属关系版本，手工与定时交付共用同一版本机制。"""
    __tablename__="attribution_versions"
    id: Mapped[int]=mapped_column(primary_key=True)
    snapshot: Mapped[list]=mapped_column(JSON)
    terminals: Mapped[list]=mapped_column(JSON,default=list)
    note: Mapped[str]=mapped_column(default="")
    created_at: Mapped[str]=mapped_column(default=now)
    owner: Mapped[str]
