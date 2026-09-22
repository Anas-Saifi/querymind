import asyncio
import os
from typing import TypedDict

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from sqlalchemy.exc import DBAPIError

from .access import AccessDenied, run_query

load_dotenv()

BASE_URL = "https://sql-model-70892236230.us-central1.run.app/v1"
API_KEY = os.environ["SQL_MODEL_KEY"]

SYSTEM_PROMPT = "You are Qwen, created by Alibaba Cloud. You are a helpful assistant."

TABLES = {
    "employees": ["id", "name", "department", "title", "salary", "hire_date", "manager_id", "region"],
    "customers": ["id", "name", "industry", "region", "account_tier", "signup_date"],
    "products": ["id", "name", "category", "unit_price"],
    "sales": ["id", "product", "monthly", "quarterly", "revenue", "profit(%)"],
}

RELATIONSHIPS = """employees.manager_id = employees.id
sales.product = products.name"""


def _table_block(name: str, cols: list[str]) -> str:
    body = ",\n".join(f"    {c}" for c in cols)
    return f"{name}(\n{body}\n)"


SCHEMA = (
    "\n\n".join(_table_block(n, c) for n, c in TABLES.items())
    + f"\n\nRelationships:\n\n{RELATIONSHIPS}"
)


def build_prompt(question: str) -> str:
    return (
        f"Database schema:\n\n{SCHEMA}\n\n"
        "Generate the SQL query for the following request.\n"
        "Return only the SQL query.\n\n"
        f"Question: {question}"
    )


def _clean_sql(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("sql"):
            text = text[3:]
    return text.strip()


llm = ChatOpenAI(
    base_url=BASE_URL,
    api_key=API_KEY,
    model="model",
    temperature=0,
    max_tokens=300,
    timeout=120,
    max_retries=1,
)
chain = llm | StrOutputParser()


class State(TypedDict, total=False):
    question: str
    role: str
    query: str
    data: dict
    denied: bool
    error: str


async def generate_sql(state: State):
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=build_prompt(state["question"])),
    ]
    # When sql-model wakes up from 0 instances, it returns 503 "Loading model" for ~20-30s.
    # Retry with a delay so it warms up without crashing or costing money for warm instances.
    max_attempts = 15
    for attempt in range(max_attempts):
        try:
            res = _clean_sql(await chain.ainvoke(messages))
            return {"query": res}
        except Exception as e:
            err_msg = str(e).lower()
            if any(k in err_msg for k in ["loading model", "503", "unavailable", "server error", "connection error"]) and attempt < max_attempts - 1:
                await asyncio.sleep(4)
                continue
            raise


async def build_graph(engine):
    async def execute_node(state: State):
        try:
            data = await asyncio.to_thread(run_query, engine, state["query"], state["role"])
            return {"data": data}
        except AccessDenied:
            return {"denied": True}
        except DBAPIError as e:
            if getattr(e.orig, "pgcode", None) == "42501":
                return {"denied": True}
            return {"error": "The generated query failed to run"}

    build = StateGraph(State)
    build.add_node("sql_generator", generate_sql)
    build.add_node("execute", execute_node)
    build.set_entry_point("sql_generator")
    build.add_edge("sql_generator", "execute")
    build.add_edge("execute", END)

    graph = build.compile()
    if os.getenv("DRAW_GRAPH"):
        graph.get_graph().draw_mermaid_png(output_file_path="graph.png")
    return graph


if __name__ == "__main__":
    from sqlalchemy import create_engine

    async def main():
        engine = create_engine(os.environ["DATABASE_URI"])
        graph = await build_graph(engine)
        for role in ("manager", "employee"):
            result = await graph.ainvoke({
                "question": "List all the employees from the Engineering department",
                "role": role,
            })
            print(role, "->", result)

    asyncio.run(main())