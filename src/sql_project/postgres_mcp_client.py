"""Backward-compatibility module for MCP client.
Delegates to mysql_mcp_client for MySQL configurations.
"""
from .mysql_mcp_client import client, mysql_client

postgres_client = mysql_client
