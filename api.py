from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Literal
import uuid

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field, StrictInt, field_validator

import db


class LoginPayload(BaseModel):
    username: str
    password: str


class ProductPayload(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    category: Literal["Eletronicos", "Perifericos", "Moveis", "Vestuario", "Outros"]
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    stock: StrictInt = Field(ge=0, le=2_147_483_647)
    description: str = ""

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("O nome deve ter pelo menos 2 caracteres")
        return normalized


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


@app.exception_handler(RequestValidationError)
async def log_validation_error(request: Request, exc: RequestValidationError):
    req_id = new_request_id()
    client = request.url.path.split("/")[2]
    log_api(
        client=client,
        operation="validation",
        status="error",
        request_id=req_id,
        message="Dados da requisicao invalidos",
        level="WARN",
    )
    return JSONResponse(
        status_code=422,
        content={"detail": jsonable_encoder(exc.errors())},
    )


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


@app.post("/api/web/records", status_code=201)
def web_create_product(
    payload: ProductPayload,
    authorization: str | None = Header(default=None),
):
    req_id = new_request_id()
    verify_web_token(authorization, request_id=req_id)
    product = db.web_create_product(
        name=payload.name,
        category=payload.category,
        price=payload.price,
        stock=payload.stock,
        description=payload.description,
        request_id=req_id,
    )
    log_api(
        client="web",
        operation="create",
        status="success",
        request_id=req_id,
        message="Produto criado",
    )
    return {"status": "ok", "product": product}


@app.put("/api/web/records/{product_id}")
def web_update_product(
    product_id: int,
    payload: ProductPayload,
    authorization: str | None = Header(default=None),
):
    req_id = new_request_id()
    verify_web_token(authorization, request_id=req_id)
    product = db.web_update_product(
        product_id=product_id,
        name=payload.name,
        category=payload.category,
        price=payload.price,
        stock=payload.stock,
        description=payload.description,
        request_id=req_id,
    )
    if product is None:
        log_api(
            client="web",
            operation="update",
            status="error",
            request_id=req_id,
            message="Produto nao encontrado",
            level="WARN",
        )
        raise HTTPException(status_code=404, detail="Produto nao encontrado")

    log_api(
        client="web",
        operation="update",
        status="success",
        request_id=req_id,
        message="Produto atualizado",
    )
    return {"status": "ok", "product": product}
