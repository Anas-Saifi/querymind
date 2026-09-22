import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

ROLE_PERMISSIONS = {
    "employee": {"customers", "products", "sales"},
    "manager": {"customers", "products", "sales", "employees"},
    "admin": {"customers", "products", "sales", "employees"},
    "hr": {"employees"},
}

# Fixed mapping, so a role name never comes from user input
DB_ROLES = {role: f"{role}" for role in ROLE_PERMISSIONS}

# Order and spelling must match the training prompt exactly
TABLE_COLUMNS = {
    "employees": ["id", "name", "department", "title", "salary", "hire_date", "manager_id", "region"],
    "customers": ["id", "name", "industry", "region", "account_tier", "signup_date"],
    "products": ["id", "name", "category", "unit_price"],
    "sales": ["id", "product", "monthly", "quarterly", "revenue", "profit(%)"],
}

RELATIONSHIPS = [
    ({"employees"}, "employees.manager_id = employees.id"),
    ({"sales", "products"}, "sales.product = products.name"),
]


class AccessDenied(Exception):
    pass


def get_allowed_tables(role: str) -> set[str]:
    return ROLE_PERMISSIONS.get(role, set())


def build_schema(role: str) -> str:
    allowed = get_allowed_tables(role)
    blocks = [
        f"{name}(\n" + ",\n".join(f"    {c}" for c in cols) + "\n)"
        for name, cols in TABLE_COLUMNS.items()
        if name in allowed
    ]
    text = "\n\n".join(blocks)
    rels = [r for needed, r in RELATIONSHIPS if needed <= allowed]
    if rels:
        text += "\n\nRelationships:\n\n" + "\n".join(rels)
    return text


def validate_sql(sql: str, role: str) -> str:
    allowed = get_allowed_tables(role)
    if not allowed:
        raise AccessDenied("no permissions")
    try:
        stmts = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except (ParseError, TokenError):
        raise AccessDenied("invalid sql")

    if len(stmts) != 1 or not isinstance(stmts[0], (exp.Select, exp.Union)):
        raise AccessDenied("only a single SELECT is allowed")
    tree = stmts[0]

    if tree.find(exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create) or tree.args.get("into"):
        raise AccessDenied("write operations are not allowed")

    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    tables = set()
    for t in tree.find_all(exp.Table):
        if t.db or t.catalog:                    # blocks pg_catalog.*, information_schema.*, etc.
            raise AccessDenied("schema-qualified tables are not allowed")
        tables.add(t.name.lower())
    tables -= ctes

    if tables - allowed:
        raise AccessDenied("table not permitted")
    return sql


def run_query(engine, sql: str, role: str, max_rows: int = 200) -> dict:
    safe_sql = validate_sql(sql, role)
    db_role = DB_ROLES[role]                     # KeyError impossible after validate_sql
    with engine.connect() as conn:
        with conn.begin():
            conn.exec_driver_sql(f'SET LOCAL ROLE "{db_role}"')
            conn.exec_driver_sql("SET LOCAL statement_timeout = '5000'")
            conn.exec_driver_sql("SET LOCAL default_transaction_read_only = on")
            result = conn.exec_driver_sql(safe_sql)   # exec_driver_sql so LIKE '%x%' and ':' aren't parsed as params
            rows = result.fetchmany(max_rows)
            return {"columns": list(result.keys()), "rows": [list(r) for r in rows]}