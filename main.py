import sys
import os
import glob

# Add parent directory to path so we can import the src module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.schema_parser import load_schema
from src.query_parser import parse_and_validate_sql
from src.estimator import estimate_single_table, estimate_multi_table
from src.cost_estimator import evaluate_single_table_plan, evaluate_multi_table_join

def main():
    # 1. Load Schema
    schema_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'schema.json')
    print("Loading schema...")
    schema = load_schema(schema_path)
    print(f"Loaded {len(schema.tables)} tables. Buffer size: {schema.buffer_blocks} blocks.\n")

    # 2. Find all .txt files in the queries folder
    queries_folder = os.path.join(os.path.dirname(__file__), '..', 'queries')
    query_files = glob.glob(os.path.join(queries_folder, '*.txt'))
    query_files.sort()

    if not query_files:
        print(f"No .txt files found in {queries_folder}")
        return

    # 3. Read, Parse, and Estimate
    for query_file in query_files:
        file_name = os.path.basename(query_file)
        print(f"--- Processing {file_name} ---")
        
        try:
            with open(query_file, 'r', encoding='utf-8') as f:
                sql = f.read().strip()
                
            if not sql:
                continue
                
            print(f"SQL: {sql}")
            
            parsed_query = parse_and_validate_sql(sql, schema)
            
            # If it's a single table query, estimate cardinality
            if len(parsed_query.from_tables) == 1:
                out_rows, out_blocks = estimate_single_table(parsed_query, schema)
                print(f"  -> Estimated Output: {out_rows:.2f} rows, {out_blocks} blocks")
                
                # Evaluate Physical Plans
                best_plan = evaluate_single_table_plan(parsed_query, schema, out_rows, out_blocks)
                print(f"  -> Chosen Plan: {best_plan['algorithm']}")
                print(f"  -> Total Cost: {best_plan['cost']} block transfers")
            else:
                out_rows, out_blocks = estimate_multi_table(parsed_query, schema)
                print(f"  -> Estimated Join Output: {out_rows:.2f} rows, {out_blocks} blocks")
                
                # Call the multi-table join evaluator
                best_plan = evaluate_multi_table_join(parsed_query, schema, parsed_query.from_tables, out_blocks)
                print(f"  -> Chosen Plan: {best_plan['algorithm']}")
                print(f"  -> Total Cost: {best_plan['cost']:.2f} block transfers")
            
            print("-" * 40)
            
        except ValueError as e:
            print(f"Error parsing {file_name}: {e}\n")
        except Exception as e:
            print(f"Unexpected error reading {file_name}: {e}\n")

if __name__ == "__main__":
    main()