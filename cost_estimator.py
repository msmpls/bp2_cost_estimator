import math
from itertools import permutations
from src.models import Schema, ParsedQuery, Table

def calculate_sort_cost(blocks_to_sort, M):
    """Calculates I/O cost of external merge sort."""
    if blocks_to_sort <= M:
        return 0  # Fits entirely in buffer memory, 0 extra disk I/Os
    
    # Number of merge passes needed
    passes = math.ceil(math.log(max(1, blocks_to_sort / M), M - 1))
    # Total I/O for sort = Read + Write for each pass + initial write
    return blocks_to_sort * (2 * passes + 1)

def evaluate_single_table_plan(parsed_query: ParsedQuery, schema: Schema, out_rows: float, out_blocks: int):
    table_name = parsed_query.from_tables[0]
    table = schema.get_table(table_name)
    M = schema.buffer_blocks
    
    equality_attrs = [c.left for c in parsed_query.where_conditions if c.operator == 'eq']
    order_by_attr = parsed_query.order_by_attribute
    
    # 1. Calculate Table Scan Cost
    table_scan_cost = table.block_count + out_blocks
    # If ORDER BY exists and no index is used, we must sort the output!
    if order_by_attr:
        table_scan_cost += calculate_sort_cost(out_blocks, M)
        
    best_plan = {
        "algorithm": "Table Scan",
        "cost": table_scan_cost
    }
    
    # 2. Check if we can use an Index
    for idx in table.indexes:
        if idx.attributes[0] in equality_attrs:
            
            if idx.type == 'HASH':
                if idx.clustered:
                    data_read = out_blocks
                else:
                    data_read = math.ceil(out_rows)
                    
                idx_cost = 1 + data_read + out_blocks
                
                # Hash indexes do NOT preserve order, so we still need to sort
                if order_by_attr:
                    idx_cost += calculate_sort_cost(out_blocks, M)
                    
                if idx_cost < best_plan["cost"]:
                    best_plan = {
                        "algorithm": f"Hash Index Scan (using {idx.name})",
                        "cost": idx_cost
                    }
                    
            elif idx.type == 'B_PLUS_TREE':
                if idx.clustered:
                    data_read = out_blocks
                else:
                    data_read = math.ceil(out_rows)
                    
                idx_cost = idx.tree_height + data_read + out_blocks
                
                # B+ Tree clustered index provides sorted output FOR FREE if it matches ORDER BY
                if order_by_attr and not (idx.clustered and idx.attributes[0] == order_by_attr):
                    idx_cost += calculate_sort_cost(out_blocks, M)
                    
                if idx_cost < best_plan["cost"]:
                    best_plan = {
                        "algorithm": f"B+ Tree Index Scan (using {idx.name})",
                        "cost": idx_cost
                    }
                    
    return best_plan

def get_local_selectivity(cond, table):
    attr = next((a for a in table.attributes if a.name == cond.left), None)
    if not attr:
        return 1.0
        
    if cond.operator == 'eq':
        return 1.0 / attr.distinct_values
    elif cond.operator in ('gt', 'lt', 'gte', 'lte'):
        # Domain-specific rule for Serbian grades (5, 6, 7, 8, 9, 10)
        if attr.name == 'ocena' and cond.operator == 'gte':
            try:
                val = int(cond.right)
                # If >= 7, matching values are 7, 8, 9, 10 (4 values)
                # If >= 9, matching values are 9, 10 (2 values)
                matching_values = max(0, 11 - val)
                return matching_values / attr.distinct_values
            except ValueError:
                pass  # Fallback if it's not a number
        return 1.0 / 3.0
    return 1.0

def evaluate_multi_table_join(parsed_query: ParsedQuery, schema: Schema, table_names: list, final_out_blocks: int):
    M = schema.buffer_blocks
    order_by_attr = parsed_query.order_by_attribute
    
    base_stats = {}
    for t_name in table_names:
        t = schema.get_table(t_name)
        rows = t.row_count
        blocks = t.block_count
        
        for cond in parsed_query.where_conditions:
            if cond.left in [a.name for a in t.attributes]:
                is_join_cond = False
                for other_t_name in table_names:
                    if other_t_name != t_name:
                        other_t = schema.get_table(other_t_name)
                        if cond.right in [a.name for a in other_t.attributes]:
                            is_join_cond = True
                            break
                if not is_join_cond:
                    rows *= get_local_selectivity(cond, t)
                    
        blocks = max(1, math.ceil(rows / t.rows_per_block))
        base_stats[t_name] = {"rows": rows, "blocks": blocks, "table": t}

    best_total_cost = float('inf')
    best_plan_details = None
    
    for order in permutations(table_names):
        if not order:
            continue
            
        current_left_tables = [order[0]]
        current_left_rows = base_stats[order[0]]["rows"]
        current_left_blocks = base_stats[order[0]]["blocks"]
        
        total_cost = 0
        plan_steps = []
        last_join_attr = None
        last_algo = None
        
        for i in range(1, len(order)):
            right_name = order[i]
            right_t = base_stats[right_name]["table"]
            right_rows = base_stats[right_name]["rows"]
            right_blocks = base_stats[right_name]["blocks"]
            
            join_attr_right = None
            join_attr_left = None
            
            for cond in parsed_query.where_conditions:
                if cond.operator == 'eq':
                    right_has_left = cond.left in [a.name for a in right_t.attributes]
                    right_has_right = cond.right in [a.name for a in right_t.attributes]
                    
                    if right_has_left:
                        for lt_name in current_left_tables:
                            lt = schema.get_table(lt_name)
                            if cond.right in [a.name for a in lt.attributes]:
                                join_attr_right = cond.left
                                join_attr_left = cond.right
                                break
                    elif right_has_right:
                        for lt_name in current_left_tables:
                            lt = schema.get_table(lt_name)
                            if cond.left in [a.name for a in lt.attributes]:
                                join_attr_right = cond.right
                                join_attr_left = cond.left
                                break
                if join_attr_right:
                    break
                    
            if not join_attr_right:
                step_out_rows = current_left_rows * right_rows
            else:
                v_left = 1
                for lt_name in current_left_tables:
                    lt = schema.get_table(lt_name)
                    attr = next((a for a in lt.attributes if a.name == join_attr_left), None)
                    if attr: v_left = max(v_left, attr.distinct_values)
                
                v_right = next(a.distinct_values for a in right_t.attributes if a.name == join_attr_right)
                max_v = max(v_left, v_right)
                step_out_rows = (current_left_rows * right_rows) / max_v
                
            step_out_blocks = max(1, math.ceil(step_out_rows / 10))
            
            bnlj_cost = current_left_blocks + (current_left_blocks / (M - 2)) * right_blocks + step_out_blocks
            sort_left = current_left_blocks * (2 * math.ceil(math.log(max(1, current_left_blocks / M), M - 1)) + 1) if current_left_blocks > M else current_left_blocks
            sort_right = right_blocks * (2 * math.ceil(math.log(max(1, right_blocks / M), M - 1)) + 1) if right_blocks > M else right_blocks
            smj_cost = sort_left + sort_right + current_left_blocks + right_blocks + step_out_blocks
            hj_cost = 2 * current_left_blocks + 2 * right_blocks + current_left_blocks + right_blocks + step_out_blocks
            
            plans = {
                "Block Nested Loop Join": bnlj_cost,
                "Sort-Merge Join": smj_cost,
                "Hash Join": hj_cost
            }
            
            if join_attr_right:
                for idx in right_t.indexes:
                    if idx.attributes[0] == join_attr_right:
                        matches_per_left_row = right_rows / next(a.distinct_values for a in right_t.attributes if a.name == join_attr_right)
                        if idx.clustered:
                            data_reads = 0 
                        else:
                            data_reads = math.ceil(matches_per_left_row)
                            
                        tree_cost = idx.tree_height if idx.type == 'B_PLUS_TREE' else 1
                        inlj_cost = current_left_blocks + (current_left_rows * (tree_cost + data_reads)) + step_out_blocks
                        plans["Index Nested Loop Join"] = inlj_cost
                        break
                        
            best_algo = min(plans, key=plans.get)
            total_cost += plans[best_algo]
            
            # Track the last algorithm and join attribute to check if ORDER BY is satisfied for free
            last_algo = best_algo
            last_join_attr = join_attr_right
            
            step_str = f"{best_algo}({' ⋈ '.join(current_left_tables)} ⋈ {right_name})"
            plan_steps.append(step_str)
            
            current_left_tables.append(right_name)
            current_left_rows = step_out_rows
            current_left_blocks = step_out_blocks
            
        # Add ORDER BY cost for multi-table queries
        # Multi-table outputs are only sorted for free if the final join was Sort-Merge Join AND the join attribute matches the ORDER BY attribute
        if order_by_attr:
            if not (last_algo == "Sort-Merge Join" and last_join_attr == order_by_attr):
                total_cost += calculate_sort_cost(step_out_blocks, M)
                
        if total_cost < best_total_cost:
            best_total_cost = total_cost
            best_plan_details = " -> ".join(plan_steps)
            
    return {"algorithm": best_plan_details, "cost": best_total_cost}