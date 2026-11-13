# Loja Virtual — CRUD de Produtos (Web + CLI)

Aplicação CRUD para gerenciamento de produtos de uma loja virtual com interface **Web** (`index.html`) e **CLI** (`cli.py`) consumindo a mesma **API REST** (`api.py`) e banco **PostgreSQL** (`db.py`), executada integralmente via **Docker Compose**.

---

## Issue #1 — Estrutura Web, Autenticação e Logs

### 1. Como iniciar a aplicação (Web, API e Banco)

Certifique-se de ter apenas **Docker** e **Docker Compose** instalados no host. Execute na raiz do projeto:

```bash
docker compose up -d --build
```

- **Interface Web:** acesse `http://localhost:8000/` no navegador.
- **Healthcheck Web:** `GET http://localhost:8000/api/web/health` (retorna HTTP 200 `{"status":"ok","client":"web"}`).

---

### 2. Configuração de Autenticação e Usuário Inicial

Na inicialização (`db.init_db`), o sistema cria automaticamente as tabelas `users` e `products` e configura o usuário inicial. A senha nunca é salva nem registrada em texto puro (é armazenada com hash SHA-256 + salt).

As credenciais iniciais podem ser configuradas por variáveis de ambiente no `docker-compose.yml` (valores padrão de desenvolvimento abaixo):

| Variável | Valor Padrão (Dev) | Descrição |
| :--- | :--- | :--- |
| `INITIAL_ADMIN_USER` | `admin` | Usuário inicial criado no banco |
| `INITIAL_ADMIN_PASSWORD` | `admin123` | Senha inicial (convertida em hash SHA-256 no banco) |
| `PASSWORD_SALT` | `loja-virtual-salt` | Salt aplicado ao hash de senha |
| `SECRET_KEY` | `loja-virtual-secret-key` | Chave HMAC-SHA256 para assinatura de tokens |

Para autenticar na Web:
1. Abra `http://localhost:8000/`.
2. Informe o usuário e a senha configurados e clique em **Entrar** (ou envie `POST /api/web/login` com `{"username": "...", "password": "..."}`).
3. Credenciais válidas retornam **HTTP 200** com token assinado; credenciais ausentes ou inválidas retornam **HTTP 401**.

---

### 3. Como consultar os Logs Estruturados (JSON)

Todas as operações emitem uma linha JSON no `stdout` da camada `api` e, quando acessam o banco, uma linha JSON na camada `db` compartilhando o mesmo `request_id`.

Para visualizar os logs em tempo real:

```bash
docker compose logs -f api
```

Exemplo de saída correlacionada de login:

```json
{"timestamp":"2026-11-12T19:30:00Z","level":"INFO","layer":"db","client":"web","operation":"login","status":"success","request_id":"req-a1b2c3d4","message":"Usuario Web autenticado no banco"}
{"timestamp":"2026-11-12T19:30:00Z","level":"INFO","layer":"api","client":"web","operation":"login","status":"success","request_id":"req-a1b2c3d4","message":"Login Web realizado com sucesso"}
```

---

### 4. Como executar os Testes Unitários e verificar 100% de Cobertura

Os testes unitários e a medição de cobertura de linhas rodam dentro do contêiner via Docker Compose:

```bash
docker compose run --rm api pytest --cov=api --cov=db --cov-report=term-missing --cov-fail-under=100
```

---

## Issue #2 — Cadastro e Edição Web de Produtos

Após entrar na Web, use o formulário **Painel de Produtos** para cadastrar um produto ou editar um produto existente. Nome, categoria, preço e estoque são obrigatórios; a descrição é opcional. Para editar, informe o ID do produto no campo correspondente. Após salvar, o ID e os dados retornados pela API ficam preenchidos no formulário.

Categorias aceitas: `Eletronicos`, `Perifericos`, `Moveis`, `Vestuario` e `Outros`. O nome deve ter pelo menos 2 caracteres, o preço deve ser maior que zero e o estoque deve ser um inteiro não negativo. A API valida os mesmos campos, exige o token obtido no login Web e retorna HTTP 404 quando o ID de edição não existe.

As operações usam `POST /api/web/records` para cadastro e `PUT /api/web/records/{id}` para edição. Cada requisição emite logs JSON correlacionados na API e no banco; consulte-os com:

```bash
docker compose logs -f api
```

Os testes da entrega continuam usando a cobertura integral de `api.py` e `db.py`:

```bash
docker compose run --rm api pytest --cov=api --cov=db --cov-report=term-missing --cov-fail-under=100
```
