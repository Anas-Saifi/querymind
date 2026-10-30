import logging

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

logger = logging.getLogger(__name__)

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


def _strip_sql(sql: str) -> str:
    """Strip surrounding whitespace and a single trailing semicolon."""
    return sql.strip().rstrip(";").strip()


def validate_sql(sql: str, role: str) -> str:
    """
    Validate that *sql* is a safe, single SELECT that only touches tables
    the *role* is permitted to read.

    Always parsed as MySQL dialect because the LLM is prompted to generate
    MySQL queries regardless of the underlying database engine.
    """
    allowed = get_allowed_tables(role)
    if not allowed:
        raise AccessDenied("no permissions")

    clean = _strip_sql(sql)

    try:
        stmts = [s for s in sqlglot.parse(clean, read="mysql") if s is not None]
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
        if t.db or t.catalog:          # blocks mysql.*, information_schema.*, pg_catalog.*, etc.
            raise AccessDenied("schema-qualified tables are not allowed")
        tables.add(t.name.lower())
    tables -= ctes

    if tables - allowed:
        raise AccessDenied("table not permitted")

    return clean   # return the cleaned (no trailing semicolon) original SQL


def _transpile(sql: str, target_dialect: str) -> str:
    """
    Transpile a MySQL query to *target_dialect* using sqlglot.
    Falls back to the original SQL if transpilation fails so the DB driver
    can surface a meaningful error.

    sqlglot dialect names: 'mysql', 'postgres', 'sqlite', 'bigquery', etc.
    SQLAlchemy dialect names: 'mysql', 'postgresql', 'sqlite', …
    We map 'postgresql' -> 'postgres' for sqlglot.
    """
    write_dialect = "postgres" if target_dialect == "postgresql" else target_dialect

    if write_dialect == "mysql":
        return sql   # already MySQL, no transpilation needed

    try:
        transpiled = sqlglot.transpile(sql, read="mysql", write=write_dialect, pretty=False)
        result = transpiled[0] if transpiled else sql
        logger.debug("Transpiled [mysql->%s]: %s  =>  %s", write_dialect, sql, result)
        return result
    except Exception as exc:
        logger.warning("sqlglot transpile mysql->%s failed (%s); using original SQL.", write_dialect, exc)
        return sql


def run_query(engine, sql: str, role: str, max_rows: int = 200) -> dict:
    # 1. Validate & clean (strips semicolon, parses as MySQL, checks RBAC)
    safe_sql = validate_sql(sql, role)
    db_role = DB_ROLES[role]          # KeyError impossible after validate_sql

    # 2. Transpile MySQL query to the actual database dialect
    dialect_name = getattr(engine.dialect, "name", "mysql")   # e.g. 'postgresql', 'mysql'
    executable_sql = _transpile(safe_sql, dialect_name)

    with engine.connect() as conn:
        if "mysql" in dialect_name:
            # --- MySQL execution controls ---
            # Timeout: max_execution_time (MySQL 5.7.8+, milliseconds)
            try:
                conn.exec_driver_sql("SET SESSION max_execution_time = 5000")
            except Exception:
                pass

            # Role impersonation (MySQL 8.0+)
            try:
                conn.exec_driver_sql(f"SET ROLE `{db_role}`")
            except Exception:
                pass

            # Read-only enforcement
            try:
                conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            except Exception:
                pass

            with conn.begin():
                result = conn.exec_driver_sql(executable_sql)
                rows = result.fetchmany(max_rows)
                return {"columns": list(result.keys()), "rows": [list(r) for r in rows]}

        else:
            # --- PostgreSQL execution controls ---
            with conn.begin():
                conn.exec_driver_sql(f'SET LOCAL ROLE "{db_role}"')
                conn.exec_driver_sql("SET LOCAL statement_timeout = '5000'")
                conn.exec_driver_sql("SET LOCAL default_transaction_read_only = on")
                result = conn.exec_driver_sql(executable_sql)
                rows = result.fetchmany(max_rows)
                return {"columns": list(result.keys()), "rows": [list(r) for r in rows]}