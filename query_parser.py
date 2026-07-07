import sqlglot
from sqlglot import exp
from .models import Schema, ParsedQuery, Condition

def parse_and_validate_sql(sql_string: str, schema: Schema) -> ParsedQuery:
    try:
        # Parse SQL using sqlglot
        parsed = sqlglot.parse_one(sql_string)
    except Exception as e:
        raise ValueError(f"SQL Syntax Error: {e}")

    # 1. FROM Clause (Tables)
    from_tables = [table.name for table in parsed.find_all(exp.Table)]
    if len(from_tables) > 4:
        raise ValueError("Constraint Violation: Max 4 tables allowed in FROM clause.")
    if len(from_tables) == 0:
        raise ValueError("No tables in FROM clause.")

    # Semantic Check: Do tables exist in schema?
    for t_name in from_tables:
        try:
            schema.get_table(t_name)
        except ValueError:
            raise ValueError(f"Semantic Error: Table '{t_name}' does not exist in schema.")

    # 2. SELECT Clause (Attributes)
    select_attrs = []
    for select_expr in parsed.expressions:
        if isinstance(select_expr, exp.Column):
            # Extract just the column name (ignoring aliases for now, e.g., s.ime -> ime)
            select_attrs.append(select_expr.name)
        else:
            raise ValueError("Constraint Violation: SELECT list must contain only attributes (no aggregates/functions).")

    # 3. WHERE Clause (Conditions)
    conditions = []
    where_node = parsed.args.get("where")
    
    if where_node:
        # sqlglot stores "A AND B AND C" as a nested And() expression. 
        # We flatten it to get a list of individual conditions.
        conditions_nodes = list(where_node.find_all(exp.And))
        
        # If there are no 'And' nodes, there is only 1 condition
        if not conditions_nodes and where_node.this:
            conditions_nodes = [where_node.this]
        else:
            # find_all(And) returns the And nodes. The actual conditions are their children.
            # A safer way is to just find all direct comparison operators
            conditions_nodes = []
            
        # Extract all predicate expressions (=, <, >, etc.)
        for pred in where_node.find_all(exp.Predicate):
            # We need to make sure we don't parse subqueries (Assignment forbids them)
            if pred.find(exp.Subquery):
                raise ValueError("Constraint Violation: Subqueries are not allowed.")
            
            left = pred.this
            right = pred.expression

            # Format left and right sides to string
            left_str = left.name if isinstance(left, exp.Column) else str(left)
            right_str = right.name if isinstance(right, exp.Column) else str(right)
            
            # Get operator symbol
            op_str = pred.key # e.g., 'EQ', 'GT', 'LT'
            
            # Map sqlglot keys to standard operators
            op_map = {"EQ": "=", "GT": ">", "LT": "<", "GTE": ">=", "LTE": "<=", "NEQ": "!="}
            operator = op_map.get(op_str, op_str)
            
            conditions.append(Condition(left=left_str, operator=operator, right=right_str))

        if len(conditions) > 6:
            raise ValueError("Constraint Violation: Max 6 conditions allowed in WHERE clause.")

    # 4. ORDER BY Clause
    order_by_attr = None
    order_node = parsed.args.get("order")
    if order_node:
        order_cols = list(order_node.find_all(exp.Column))
        if len(order_cols) > 1:
            raise ValueError("Constraint Violation: Max 1 attribute in ORDER BY.")
        order_by_attr = order_cols[0].name

    return ParsedQuery(
        select_attributes=select_attrs,
        from_tables=from_tables,
        where_conditions=conditions,
        order_by_attribute=order_by_attr
    )