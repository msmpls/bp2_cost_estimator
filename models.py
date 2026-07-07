from dataclasses import dataclass, field
from typing import List

@dataclass
class Attribute:
    name: str
    type: str
    unique: bool
    distinct_values: int

@dataclass
class Index:
    name: str
    attributes: List[str]
    type: str  # B_PLUS_TREE or HASH
    clustered: bool
    tree_height: int = 0  # 0 for hash indexes

@dataclass
class Table:
    name: str
    row_count: int
    block_count: int
    rows_per_block: int
    attributes: List[Attribute] = field(default_factory=list)
    indexes: List[Index] = field(default_factory=list)

@dataclass
class Schema:
    buffer_blocks: int
    tables: List[Table] = field(default_factory=list)
    
    def get_table(self, table_name: str) -> Table:
        for t in self.tables:
            if t.name.lower() == table_name.lower():
                return t
        raise ValueError(f"Table {table_name} not found in schema!")

@dataclass
class Condition:
    left: str       # e.g., "s.indeks" or "ime"
    operator: str   # =, <, >, <=, >=, !=
    right: str      # e.g., "i.studentIndeks" or "'Ana'" or "5"

@dataclass
class ParsedQuery:
    select_attributes: List[str]
    from_tables: List[str]
    where_conditions: List[Condition]
    order_by_attribute: str = None