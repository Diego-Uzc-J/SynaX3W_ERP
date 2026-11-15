# Base de datos y migraciones — ERP

El esquema se versiona con **Alembic**. La aplicación **no** crea tablas al
arrancar: `Base.metadata.create_all()` se usa solo en las pruebas con SQLite.

| Pieza | Ruta |
| --- | --- |
| Configuración de Alembic | `backend/alembic.ini` |
| Entorno (URL + metadatos) | `backend/alembic/env.py` |
| Migración inicial de inventario | `backend/alembic/versions/20261115_0001_inventory_initial.py` |
| Modelos ORM | `backend/src/modules/inventory/models.py` |
| URL de conexión | `DATABASE_URL` (normalizada a `postgresql+psycopg`) |

## Opción A — Docker Compose (recomendada)

```bash
# 1. Levantar PostgreSQL y esperar el healthcheck
docker compose up -d db

# 2. Construir la imagen del backend (incluye Alembic)
docker compose build api

# 3. Aplicar el esquema
docker compose exec api alembic upgrade head
#    Alternativa sin contenedor en ejecución:
#    docker compose run --rm api alembic upgrade head

# 4. Verificar
docker compose exec db psql -U erp_user -d erp_database -c "\dt"
docker compose exec api alembic current
```

El servicio se llama **`api`** (no `backend`). `alembic.ini` y `alembic/` están
montados en `/app`, por lo que no hace falta `-c alembic.ini` ni reconstruir la
imagen al añadir una migración.

Para levantar todo el stack:

```bash
docker compose up --build -d
docker compose exec api alembic upgrade head
```

## Opción B — Local (sin Docker para la API)

```bash
cd backend

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

export DATABASE_URL="postgresql://erp_user:erp_password@localhost:5432/erp_database"
alembic upgrade head

uvicorn src.main:app --reload --port 8000
```

Si usas `uv`: `uv sync` y luego los mismos comandos de Alembic.

## Comandos de Alembic

```bash
alembic current                  # revisión aplicada
alembic history --verbose        # historial de migraciones
alembic upgrade head             # aplicar todo lo pendiente
alembic downgrade -1             # revertir la última
alembic downgrade base           # revertir todo (borra las tablas del módulo)
```

### Crear una migración nueva

```bash
cd backend
export DATABASE_URL="postgresql://erp_user:erp_password@localhost:5432/erp_database"

alembic revision --autogenerate -m "descripcion del cambio"
# revisar el archivo generado en alembic/versions/ antes de aplicarlo
alembic upgrade head
alembic check                    # debe responder: No new upgrade operations detected
```

`env.py` tiene `compare_type=True`, así que los cambios de tipo también se
detectan. Los cambios de `server_default` no se comparan por defecto: si
modificas un default en el modelo, ajústalo a mano en la migración.

## Casos especiales

- **La base ya tiene las tablas** (por ejemplo, creadas con un
  `Base.metadata.create_all` manual): `alembic upgrade head` fallará con
  `DuplicateTable`. Si el esquema ya coincide, márcalo como aplicado:

  ```bash
  alembic stamp head
  alembic check
  ```

  Si no coincide, lo más limpio en desarrollo es recrear la base
  (`docker compose down -v`) y volver a aplicar `upgrade head`.

- **Reset completo en desarrollo** (destruye los datos):

  ```bash
  docker compose down -v
  docker compose up -d db
  docker compose exec api alembic upgrade head
  ```

- **Puerto 5432 ocupado**: cambia el mapeo del servicio `db` en
  `docker-compose.yml` (por ejemplo `"5433:5432"`) y ajusta `DATABASE_URL` de la
  API si corres la base fuera de Compose.

- **Enum `movement_type`**: es un tipo nativo de PostgreSQL. La migración lo
  crea antes de `stock_movements` y lo elimina al final del `downgrade`; si
  añades un valor al enum, necesitarás una migración explícita con
  `ALTER TYPE ... ADD VALUE`.

- **Pruebas**: `pytest` sigue usando SQLite en memoria y crea el esquema con
  `Base.metadata.create_all()`; no requiere PostgreSQL ni Alembic.
