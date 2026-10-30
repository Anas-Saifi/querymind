from langchain_mcp_adapters.client import MultiServerMCPClient
from dotenv import load_dotenv
import os

load_dotenv()

client = MultiServerMCPClient(
    {
        "mysql": {
            "transport": "stdio",
            "command": "uvx",
            "args": [
                "--with",
                "mcp[cli]==1.29.0",
                "mysql-mcp",
                "--access-mode=unrestricted",
            ],
            "env": {
                "DATABASE_URI": os.environ.get("DATABASE_URI", "")
            }
        }
    }
)


async def mysql_client():
    return await client.get_tools()
