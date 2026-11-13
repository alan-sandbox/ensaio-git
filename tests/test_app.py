import json
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

import api
import db


def _make_mock_conn(fetchone_return=None):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = fetchone_return
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    return mock_conn, mock_cursor


def test_db_log_and_hash(capsys, monkeypatch):
    monkeypatch.setenv("PASSWORD_SALT", "test-salt")
    entry = db.log_db("web", "test_op", "success", "req-001", "Mensagem de teste")
    captured = capsys.readouterr().out.strip()
    parsed = json.loads(captured)
    assert parsed["layer"] == "db"
    assert parsed["client"] == "web"
    assert parsed["request_id"] == "req-001"
    assert entry["status"] == "success"

    h1 = db.hash_password("segredo")
    h2 = db.hash_password("segredo")
    assert h1 == h2
    assert "segredo" not in h1


def test_get_connection_calls_psycopg2(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    with patch("db.psycopg2.connect") as mock_connect:
        mock_connect.return_value = "dummy-conn"
        conn = db.get_connection()
        assert conn == "dummy-conn"
        mock_connect.assert_called_once_with("postgresql://u:p@localhost:5432/db")


def test_init_db_executes_schema_and_admin_seed(monkeypatch):
    monkeypatch.setenv("INITIAL_ADMIN_USER", "admin")
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "admin123")
    mock_conn, mock_cursor = _make_mock_conn()
    with patch("db.get_connection", return_value=mock_conn):
        db.init_db(request_id="req-init-test")
    assert mock_cursor.execute.call_count == 3
    mock_conn.commit.assert_called_once()
    mock_conn.close.assert_called_once()


def test_web_authenticate_user_success_and_failure(monkeypatch):
    monkeypatch.setenv("PASSWORD_SALT", "salt-1")
    valid_hash = db.hash_password("senha-correta")

    conn_ok, _ = _make_mock_conn(fetchone_return=(valid_hash,))
    with patch("db.get_connection", return_value=conn_ok):
        assert db.web_authenticate_user("admin", "senha-correta", "req-1") is True
    conn_ok.close.assert_called_once()

    conn_fail, _ = _make_mock_conn(fetchone_return=None)
    with patch("db.get_connection", return_value=conn_fail):
        assert db.web_authenticate_user("admin", "errada", "req-2") is False
    conn_fail.close.assert_called_once()


def test_web_token_creation_and_verification(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    token = api.create_web_token("admin")
    assert api.verify_web_token(f"Bearer {token}", request_id="req-auth") == "admin"

    with pytest.raises(HTTPException) as exc1:
        api.verify_web_token(None)
    assert exc1.value.status_code == 401

    with pytest.raises(HTTPException) as exc2:
        api.verify_web_token("Bearer token-sem-ponto")
    assert exc2.value.status_code == 401

    with pytest.raises(HTTPException) as exc3:
        api.verify_web_token("Bearer admin.assinatura-invalida")
    assert exc3.value.status_code == 401


def test_api_endpoints_health_index_and_login():
    with patch("db.init_db") as mock_init:
        with TestClient(api.app) as client:
            res_index = client.get("/")
            assert res_index.status_code == 200
            assert "Loja Virtual" in res_index.text
            assert 'id="product-form"' in res_index.text
            assert 'id="product-description"' in res_index.text

            res_health = client.get("/api/web/health")
            assert res_health.status_code == 200
            assert res_health.json() == {"status": "ok", "client": "web"}

            with patch("db.web_authenticate_user", return_value=True):
                res_login_ok = client.post(
                    "/api/web/login",
                    json={"username": "admin", "password": "admin123"},
                )
                assert res_login_ok.status_code == 200
                body = res_login_ok.json()
                assert body["status"] == "ok"
                assert body["username"] == "admin"
                assert "token" in body

            with patch("db.web_authenticate_user", return_value=False):
                res_login_fail = client.post(
                    "/api/web/login",
                    json={"username": "admin", "password": "wrong"},
                )
                assert res_login_fail.status_code == 401
        mock_init.assert_called_once()


def test_product_payload_validates_and_normalizes_fields():
    payload = api.ProductPayload(
        name="  Teclado  ",
        category="Perifericos",
        price="99.90",
        stock=0,
    )
    assert payload.name == "Teclado"
    assert payload.description == ""

    with pytest.raises(ValueError):
        api.ProductPayload(
            name="  ",
            category="Perifericos",
            price="99.90",
            stock=0,
        )


def test_web_create_product_endpoint_logs_and_persists(capsys):
    product = {
        "id": 7,
        "name": "Teclado",
        "category": "Perifericos",
        "price": 99.9,
        "stock": 3,
        "description": "",
    }
    with patch("db.init_db"), patch("db.web_create_product", return_value=product) as create:
        with TestClient(api.app) as client:
            token = api.create_web_token("admin")
            response = client.post(
                "/api/web/records",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "name": "Teclado",
                    "category": "Perifericos",
                    "price": 99.9,
                    "stock": 3,
                },
            )

    assert response.status_code == 201
    assert response.json()["product"] == product
    assert create.call_args.kwargs["request_id"].startswith("req-")
    logs = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    api_log = next(entry for entry in logs if entry["layer"] == "api")
    assert api_log["operation"] == "create"
    assert api_log["request_id"] == create.call_args.kwargs["request_id"]


def test_web_create_product_requires_authentication():
    with patch("db.init_db"):
        with TestClient(api.app) as client:
            response = client.post(
                "/api/web/records",
                json={
                    "name": "Teclado",
                    "category": "Perifericos",
                    "price": 99.9,
                    "stock": 3,
                },
            )
    assert response.status_code == 401


def test_web_create_product_rejects_invalid_payload_and_logs(capsys):
    with patch("db.init_db"):
        with TestClient(api.app) as client:
            token = api.create_web_token("admin")
            response = client.post(
                "/api/web/records",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "name": "T",
                    "category": "Invalida",
                    "price": 0,
                    "stock": -1,
                },
            )
    assert response.status_code == 422
    log = json.loads(capsys.readouterr().out.strip())
    assert log["client"] == "web"
    assert log["operation"] == "validation"
    assert log["status"] == "error"


def test_web_update_product_endpoint_success_and_not_found(capsys):
    product = {
        "id": 7,
        "name": "Teclado atualizado",
        "category": "Perifericos",
        "price": 109.9,
        "stock": 4,
        "description": "Mecanico",
    }
    with patch("db.init_db"), patch(
        "db.web_update_product", side_effect=[product, None]
    ) as update:
        with TestClient(api.app) as client:
            token = api.create_web_token("admin")
            headers = {"Authorization": f"Bearer {token}"}
            payload = {
                "name": "Teclado atualizado",
                "category": "Perifericos",
                "price": 109.9,
                "stock": 4,
                "description": "Mecanico",
            }
            success = client.put("/api/web/records/7", headers=headers, json=payload)
            missing = client.put("/api/web/records/8", headers=headers, json=payload)

    assert success.status_code == 200
    assert success.json()["product"] == product
    assert missing.status_code == 404
    assert update.call_count == 2
    logs = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    api_logs = [entry for entry in logs if entry["layer"] == "api" and entry["operation"] == "update"]
    assert [entry["status"] for entry in api_logs] == ["success", "error"]
    assert api_logs[0]["request_id"] == update.call_args_list[0].kwargs["request_id"]
    assert api_logs[1]["request_id"] == update.call_args_list[1].kwargs["request_id"]


def test_web_update_product_requires_authentication():
    with patch("db.init_db"):
        with TestClient(api.app) as client:
            response = client.put(
                "/api/web/records/7",
                json={
                    "name": "Teclado",
                    "category": "Perifericos",
                    "price": 99.9,
                    "stock": 3,
                },
            )
    assert response.status_code == 401


def test_db_web_create_and_update_products(capsys):
    create_conn, create_cursor = _make_mock_conn(
        fetchone_return=(7, "Teclado", "Perifericos", 99.9, 3, "")
    )
    with patch("db.get_connection", return_value=create_conn):
        created = db.web_create_product(
            "Teclado", "Perifericos", 99.9, 3, "", "req-create"
        )
    assert created["id"] == 7
    assert created["price"] == 99.9
    assert "INSERT INTO products" in create_cursor.execute.call_args.args[0]
    assert create_conn.commit.called
    assert create_conn.close.called

    update_conn, update_cursor = _make_mock_conn(
        fetchone_return=(7, "Teclado Pro", "Perifericos", 129.9, 2, "Mecanico")
    )
    with patch("db.get_connection", return_value=update_conn):
        updated = db.web_update_product(
            7, "Teclado Pro", "Perifericos", 129.9, 2, "Mecanico", "req-update"
        )
    assert updated["name"] == "Teclado Pro"
    assert updated["price"] == 129.9
    assert "WHERE id = %s" in update_cursor.execute.call_args.args[0]
    assert update_cursor.execute.call_args.args[1][-1] == 7
    assert update_conn.commit.called
    assert update_conn.close.called

    missing_conn, _ = _make_mock_conn(fetchone_return=None)
    with patch("db.get_connection", return_value=missing_conn):
        assert db.web_update_product(
            8, "Teclado", "Perifericos", 99.9, 3, "", "req-missing"
        ) is None
    assert missing_conn.close.called
    logs = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    db_logs = [entry for entry in logs if entry["layer"] == "db"]
    assert [entry["status"] for entry in db_logs] == ["success", "success", "error"]
    assert db_logs[-1]["request_id"] == "req-missing"
