from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import db


class LoginPayload(BaseModel):
    username: str
    password: str


def new_request_id() -> str:
    return f"req-{uuid.uuid4().hex[:8]}"


def log_api(
    client: str,
    operation: str,
    status: str,
    request_id: str,
    message: str,
    level: str = "INFO",
) -> dict:
    entry = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "level": level,
        "layer": "api",
        "client": client,
        "operation": operation,
        "status": status,
        "request_id": request_id,
        "message": message,
    }
    print(json.dumps(entry, ensure_ascii=False), flush=True)
    return entry


def _sign_value(value: str) -> str:
    secret = os.getenv("SECRET_KEY", "loja-virtual-secret-key").encode("utf-8")
    return hmac.new(secret, value.encode("utf-8"), hashlib.sha256).hexdigest()


def create_web_token(username: str) -> str:
    signature = _sign_value(f"web:{username}")
    return f"{username}.{signature}"


def verify_web_token(authorization: str | None, request_id: str = "req-auth") -> str:
    if not authorization or not authorization.startswith("Bearer "):
        log_api(
            client="web",
            operation="auth",
            status="error",
            request_id=request_id,
            message="Token Web ausente ou malformado",
            level="WARN",
        )
        raise HTTPException(status_code=401, detail="Nao autorizado")

    raw_token = authorization.removeprefix("Bearer ").strip()
    if "." not in raw_token:
        log_api(
            client="web",
            operation="auth",
            status="error",
            request_id=request_id,
            message="Formato de token Web invalido",
            level="WARN",
        )
        raise HTTPException(status_code=401, detail="Nao autorizado")

    username, signature = raw_token.split(".", 1)
    expected_sig = _sign_value(f"web:{username}")
    if not username or not hmac.compare_digest(signature, expected_sig):
        log_api(
            client="web",
            operation="auth",
            status="error",
            request_id=request_id,
            message="Assinatura de token Web invalida",
            level="WARN",
        )
        raise HTTPException(status_code=401, detail="Nao autorizado")

    return username


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db(request_id=new_request_id())
    yield


app = FastAPI(title="Loja Virtual — CRUD Produtos", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
def serve_index():
    html_path = Path(__file__).with_name("index.html")
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.get("/api/web/health")
def web_health():
    req_id = new_request_id()
    log_api(
        client="web",
        operation="health",
        status="success",
        request_id=req_id,
        message="Healthcheck Web OK",
    )
    return {"status": "ok", "client": "web"}


@app.post("/api/web/login")
def web_login(payload: LoginPayload):
    req_id = new_request_id()
    authenticated = db.web_authenticate_user(
        payload.username, payload.password, request_id=req_id
    )
    if not authenticated:
        log_api(
            client="web",
            operation="login",
            status="error",
            request_id=req_id,
            message="Credenciais Web invalidas",
            level="WARN",
        )
        raise HTTPException(status_code=401, detail="Credenciais invalidas")

    token = create_web_token(payload.username)
    log_api(
        client="web",
        operation="login",
        status="success",
        request_id=req_id,
        message="Login Web realizado com sucesso",
    )
    return {"status": "ok", "token": token, "username": payload.username}
