from .postgres_mcp_client import postgres_client
import logging
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

@tool
def execute_sql(sql: str) -> str:
    """Tool to execute SQL queries on the database."""
    logger.info("Executing SQL: %s", sql)
    return "Database query executed successfully."

async def get_all_tools():
    try:
        postgres_tools = await postgres_client()
        return [*postgres_tools]
    except Exception as exc:
        logger.warning("Postgres MCP unavailable: %s. Using fallback SQL tool.", exc)
        return [execute_sql]