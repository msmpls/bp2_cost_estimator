import json
from .models import Schema, Table, Attribute, Index

def load_schema(json_path: str) -> Schema:
    with open(json_path, 'r', encoding='utf-8') as file:
        data = json.load(file)
        
    schema = Schema(buffer_blocks=data["bufferBlocks"])
    
    for table_data in data["schema"]["tables"]:
        attrs = [
            Attribute(
                name=a["name"],
                type=a["type"],
                unique=a["unique"],
                distinct_values=a["distinctValues"]
            ) for a in table_data["attributes"]
        ]
        
        idxs = []
        for idx_data in table_data.get("indexes", []):
            idxs.append(Index(
                name=idx_data["name"],
                attributes=idx_data["attributes"],
                type=idx_data["type"],
                clustered=idx_data["clustered"],
                tree_height=idx_data.get("treeHeight", 0) # .get() because hash doesn't have treeHeight
            ))
            
        table = Table(
            name=table_data["name"],
            row_count=table_data["rowCount"],
            block_count=table_data["blockCount"],
            rows_per_block=table_data["rowsPerBlock"],
            attributes=attrs,
            indexes=idxs
        )
        schema.tables.append(table)
        
    return schema