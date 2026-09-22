import os
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from fastapi.middleware.cors import CORSMiddleware

from jose import JWTError, jwt
from passlib.context import CryptContext

from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from dotenv import load_dotenv
load_dotenv()

from pydantic import BaseModel

from sql_project.agent import build_graph

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from sql_project.agent import build_graph
from sql_project.access import (
    AccessDenied, build_schema, get_allowed_tables, run_query,
)

load_dotenv()



graph = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global graph

    graph = await build_graph(engine)

    yield



app = FastAPI(
    title="Text-to-SQL Executor",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)



class AgentRequest(BaseModel):
    question: str

# ============================================================
# CONFIG
# ============================================================

DATABASE_URL = os.getenv("DATABASE_URI")

JWT_SECRET = os.getenv("JWT_SECRET_KEY")

JWT_ALGORITHM = "HS256"
TOKEN_EXPIRE_MINUTES = 60


# ============================================================
# DATABASE
# ============================================================
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
DB_NAME = os.environ["DB_NAME"]
INSTANCE_CONNECTION_NAME = os.environ["INSTANCE_CONNECTION_NAME"]

DATABASE_URL = (
    f"postgresql://{DB_USER}:{DB_PASSWORD}@/{DB_NAME}"
    f"?host=/cloudsql/{INSTANCE_CONNECTION_NAME}"
)



engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False
)

Base = declarative_base()


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


# ============================================================
# EXISTING USERS TABLE
# ============================================================

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False)


# IMPORTANT:
# Do NOT call Base.metadata.create_all()
# because your users table already exists.


# ============================================================
# PASSWORD VERIFICATION
# ============================================================

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)


def verify_password(
    plain_password: str,
    password_hash: str
) -> bool:

    return pwd_context.verify(
        plain_password,
        password_hash
    )


# ============================================================
# JWT
# ============================================================

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/auth/login"
)


def create_access_token(
    user_id: int,
    role: str
):

    expires_at = (
        datetime.now(timezone.utc)
        + timedelta(minutes=TOKEN_EXPIRE_MINUTES)
    )

    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": expires_at
    }

    return jwt.encode(
        payload,
        JWT_SECRET,
        algorithm=JWT_ALGORITHM
    )


# ============================================================
# AUTHENTICATE CURRENT USER
# ============================================================

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={
            "WWW-Authenticate": "Bearer"
        }
    )

    try:

        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM]
        )

        user_id = payload.get("sub")

        if user_id is None:
            raise credentials_exception

        user_id = int(user_id)

    except (JWTError, ValueError):

        raise credentials_exception

    user = (
        db.query(User)
        .filter(User.id == user_id)
        .first()
    )

    if user is None:
        raise credentials_exception

    return user


# ============================================================
# APP
# ============================================================




# ============================================================
# LOGIN
# ============================================================

@app.post("/auth/login")
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):

    user = (
        db.query(User)
        .filter(User.username == form_data.username)
        .first()
    )

    if user is None:

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )

    if not verify_password(
        form_data.password,
        user.password_hash
    ):

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )

    access_token = create_access_token(
        user_id=user.id,
        role=user.role
    )

    return {
        "access_token": access_token,
        "token_type": "bearer"
    }


# ============================================================
# CURRENT USER
# ============================================================

@app.get("/auth/me")
def me(
    current_user: User = Depends(get_current_user)
):

    return {
        "id": current_user.id,
        "username": current_user.username,
        "role": current_user.role
    }


# ============================================================
# TEXT-TO-SQL PERMISSIONS
# ============================================================






# ============================================================
# SQL EXECUTION
# ============================================================

class SqlRequest(BaseModel):
    sql: str


@app.post("/sql/execute")   # delete this endpoint if you don't need it
def execute_sql(request: SqlRequest, current_user: User = Depends(get_current_user)):
    try:
        return run_query(engine, request.sql, current_user.role)
    except AccessDenied:
        raise HTTPException(status_code=403, detail="Access denied")


@app.post("/agent/query")
async def agent_query(request: AgentRequest, current_user: User = Depends(get_current_user)):
    role = current_user.role
    if not get_allowed_tables(role):
        raise HTTPException(status_code=403, detail="User has no database permissions")
    if graph is None:
        raise HTTPException(status_code=503, detail="Agent is not initialized")

    try:
        result = await graph.ainvoke({"question": request.question, "role": role})
    except Exception as e:
        err_msg = str(e)
        if any(k in err_msg.lower() for k in ["loading model", "503", "unavailable"]):
            raise HTTPException(
                status_code=503,
                detail="Model is currently warming up from sleep. Please try again in a few seconds."
            )
        raise HTTPException(status_code=500, detail=f"Query error: {err_msg}")

    if result.get("denied"):
        raise HTTPException(status_code=403, detail="You don't have access to the data needed for this question")
    if result.get("error"):
        raise HTTPException(status_code=422, detail="Couldn't produce a working query for that question")

    response = {
        "user": {"id": current_user.id, "username": current_user.username, "role": role},
        "data": result["data"],
    }
    if role == "admin":
        response["sql"] = result["query"]
    return response


# Serve frontend — must be mounted LAST so API routes take precedence
app.mount("/ui", StaticFiles(directory="src/backend/static", html=True), name="ui")