from sqlalchemy.orm import Mapped,mapped_column
from ..config.database import Base
class AttributionNode(Base):
    __tablename__="attribution_nodes"
    id: Mapped[int]=mapped_column(primary_key=True)
    node: Mapped[str]=mapped_column(unique=True)
    kind: Mapped[str]  # channel 来源渠道 / hub 中间节点 / region 终点区域
    label: Mapped[str]
