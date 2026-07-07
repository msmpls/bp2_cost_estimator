import math
from src.models import Schema, ParsedQuery, Table

def get_selectivity(condition, table: Table) -> float:
    """Calculates selectivity for a single condition."""
    attr_name = condition.left
    attr = next((a for a in table.attributes if a.name == attr_name), None)
    if not attr:
        return 1.0 

    if condition.operator == 'eq':
        return 1.0 / attr.distinct_values
    elif condition.operator in ('gt', 'lt', 'gte', 'lte'):
        return 1.0 / 3.0
    else:
        return 1.0

def estimate_single_table(parsed_query: ParsedQuery, schema: Schema):
    table_name = parsed_query.from_tables[0]
    table = schema.get_table(table_name)
    
    if not table:
        return 0, 0

    out_rows = table.row_count
    for cond in parsed_query.where_conditions:
        if cond.left in [a.name for a in table.attributes]:
            out_rows *= get_selectivity(cond, table)
            
    out_blocks = math.ceil(out_rows / table.rows_per_block)
    return out_rows, out_blocks

def estimate_multi_table(parsed_query: ParsedQuery, schema: Schema):
    tables = parsed_query.from_tables
    table_rows = {}
    
    # 1. Initialize rows and apply local conditions
    for t_name in tables:
        table = schema.get_table(t_name)
        table_rows[t_name] = table.row_count
        
    join_denominators = []
    
    # 2. Separate conditions into local and join
    for cond in parsed_query.where_conditions:
        is_join = False
        
        # Check if both left and right are attributes in different tables
        for t1 in tables:
            for t2 in tables:
                if t1 != t2:
                    table1 = schema.get_table(t1)
                    table2 = schema.get_table(t2)
                    if table1 and table2:
                        # Is left in t1 and right in t2?
                        if any(a.name == cond.left for a in table1.attributes) and any(a.name == cond.right for a in table2.attributes):
                            v1 = next((a.distinct_values for a in table1.attributes if a.name == cond.left), 1)
                            v2 = next((a.distinct_values for a in table2.attributes if a.name == cond.right), 1)
                            join_denominators.append(max(v1, v2))
                            is_join = True
                            break
            if is_join:
                break
                
        # If it's not a join, it's a local condition
        if not is_join:
            for t_name in tables:
                table = schema.get_table(t_name)
                if any(a.name == cond.left for a in table.attributes):
                    table_rows[t_name] *= get_selectivity(cond, table)
                    break

    # 3. Calculate total join rows
    # Formula: (T1 * T2 * T3 ...) / (max(V1, V2) * max(V3, V4) ...)
    total_rows = 1.0
    for t_name in tables:
        total_rows *= table_rows[t_name]
        
    for denom in join_denominators:
        total_rows /= denom
        
    # 4. Estimate output blocks
    # For joins, output rows are wider. A simple heuristic is to assume 10 rows per block.
    # You can adjust this based on your professor's slides if they specify a formula.
    out_blocks = math.ceil(total_rows / 10)
    
    return total_rows, out_blocks