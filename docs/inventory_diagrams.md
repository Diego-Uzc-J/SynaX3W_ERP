# Diagramas técnicos — Módulo `inventory`

Documentación visual del módulo de Inventario y Logística, derivada de
`specs/inventory_spec.md` y del código real de `backend/src/modules/inventory/`
y `frontend/src/modules/inventory/`.

| Diagrama | Qué responde |
| --- | --- |
| Clases | Qué entidades existen, cómo se relacionan y qué servicios las gobiernan |
| Componentes | Cómo viaja una petición desde React hasta PostgreSQL |
| Secuencia | Qué ocurre exactamente al registrar un movimiento y por qué se rechaza un stock negativo |

---

## 1. Diagrama de clases

Entidades SQLAlchemy (`models.py`), el enum `MovementType` y la capa de servicio
(`services.py`). Los tipos son los que expone el modelo ORM; `Decimal` proviene
de `Numeric(12, 2)` y todas las fechas son `DateTime(timezone=True)`.

```mermaid
classDiagram

    class Base {
        <<abstract>>
        +metadata
    }

    class MovementType {
        <<enumeration>>
        INBOUND
        OUTBOUND
        TRANSFER
        ADJUSTMENT
    }

    class Warehouse {
        +int id
        +str code
        +str name
        +str address
        +bool is_active
        +datetime created_at
        +list~Stock~ stocks
        +list~StockMovement~ outgoing_movements
        +list~StockMovement~ incoming_movements
    }

    class Product {
        +int id
        +str sku
        +str name
        +str description
        +Decimal unit_price
        +int minimum_stock
        +bool is_active
        +datetime created_at
        +list~Stock~ stocks
        +list~StockMovement~ movements
    }

    class Stock {
        +int id
        +int product_id
        +int warehouse_id
        +int quantity
        +datetime updated_at
        +Product product
        +Warehouse warehouse
    }

    class StockMovement {
        +int id
        +int product_id
        +int warehouse_source_id
        +int warehouse_destination_id
        +MovementType movement_type
        +int quantity
        +str reference_document
        +str notes
        +str created_by
        +datetime created_at
    }

    class InventoryService {
        <<service>>
        +create_product(db, data)
        +get_product(db, product_id)
        +list_products(db, filters)
        +update_product(db, product_id, data)
        +create_warehouse(db, data)
        +get_warehouse(db, warehouse_id)
        +list_warehouses(db, filters)
        +update_warehouse(db, warehouse_id, data)
        +create_stock_movement(db, data, allow_negative_stock)
        +list_stock(db, filters)
        +list_stock_movements(db, filters)
        -validate_movement_shape(data)
        -get_or_create_stock(db, product_id, warehouse_id)
        -increase(stock, quantity)
        -decrease(stock, quantity, allow_negative_stock)
    }

    Base <|-- Warehouse
    Base <|-- Product
    Base <|-- Stock
    Base <|-- StockMovement

    Product "1" --> "0..*" Stock : saldos por almacén
    Warehouse "1" --> "0..*" Stock : existencias
    Product "1" --> "0..*" StockMovement : historial
    Warehouse "0..1" --> "0..*" StockMovement : origen
    Warehouse "0..1" --> "0..*" StockMovement : destino
    StockMovement --> MovementType : movement_type

    InventoryService ..> Product : gestiona
    InventoryService ..> Warehouse : gestiona
    InventoryService ..> Stock : lee y actualiza
    InventoryService ..> StockMovement : inserta

    note for Stock "UNIQUE(product_id, warehouse_id)"
    note for StockMovement "Inmutable: sin UPDATE ni DELETE"
    note for InventoryService "Saldo e historial en una sola transacción"
```

### Lectura del diagrama

- **Cardinalidades reales.** `Stock` materializa el muchos-a-muchos entre
  `Product` y `Warehouse`; la unicidad `(product_id, warehouse_id)` impide
  duplicar saldos.
- **Dos relaciones opcionales hacia `Warehouse`.** `StockMovement` usa
  `warehouse_source_id` y `warehouse_destination_id`, ambos anulables: las
  entradas puras no tienen origen y las salidas puras no tienen destino.
- **`quantity > 0` siempre.** En `StockMovement` lo impone
  `ck_stock_movements_quantity_positive`; la dirección se expresa con
  `movement_type` y las bodegas, no con cantidades negativas.
- **`ADJUSTMENT` es incremental, no absoluto.** Con bodega de destino suma y con
  bodega de origen resta; la spec exige exactamente una de las dos.
- **Inmutabilidad.** No existe `StockMovementUpdate` en `schemas.py` ni endpoints
  `PATCH`/`DELETE`; los listeners `before_update` y `before_delete` lanzan
  `ImmutableMovementError` y la corrección se hace con un nuevo `ADJUSTMENT`.
- **`InventoryService`** agrupa las funciones de `services.py`; las marcadas con
  `-` son utilidades internas (lock de fila, aritmética de saldo y validación
  redundante de la forma del movimiento).

---

## 2. Diagrama de componentes

Arquitectura full-stack: vistas React → hooks de TanStack Query → cliente HTTP →
routers, esquemas Pydantic y servicios de FastAPI → tablas PostgreSQL.

```mermaid
flowchart TB
    subgraph CLIENTE["Cliente · React 19 + Vite 8"]
        direction TB
        OP["Operador de bodega"]
        ROUTES["routes/index.tsx<br/>createBrowserRouter"]
        LAYOUT["layouts/AppLayout.tsx<br/>navegación y shell"]
        PAGE["InventoryPage.tsx<br/>tabla producto × bodega<br/>filtros y paginación"]
        MODAL["MovementFormModal.tsx<br/>sheet INBOUND · OUTBOUND<br/>TRANSFER · ADJUSTMENT"]
        CONST["constants.ts<br/>MOVEMENT_LABELS y MOVEMENT_HINTS"]
    end

    subgraph DATA["Capa de datos del cliente"]
        direction TB
        HOOKS["api/inventory.ts<br/>useProducts · useWarehouses<br/>useStock · useCreateMovement"]
        KEYS["inventoryKeys<br/>claves jerárquicas de caché"]
        HTTP["Cliente HTTP fetch<br/>buildQuery · InventoryApiError<br/>extrae detail de 400 / 422"]
    end

    subgraph API["API · FastAPI"]
        direction TB
        MAIN["main.py<br/>app + exception handler global"]
        ROUTERS["router.py<br/>products · warehouses<br/>movements · stock"]
        SCHEMAS["schemas.py<br/>Pydantic v2<br/>Create · Update · Response"]
        SERVICES["services.py<br/>reglas de negocio<br/>transacción atómica"]
        MODELS["models.py<br/>SQLAlchemy 2.x<br/>Mapped / mapped_column"]
        ERR["inventory_exception_handler<br/>InventoryError → HTTP"]
    end

    subgraph DB["PostgreSQL"]
        direction TB
        T_W["warehouses"]
        T_P["products"]
        T_S["stocks<br/>UNIQUE(product_id, warehouse_id)"]
        T_M["stock_movements<br/>histórico inmutable"]
        T_E["enum movement_type"]
    end

    OP --> ROUTES
    ROUTES --> LAYOUT
    LAYOUT --> PAGE
    PAGE --> CONST
    PAGE --> MODAL
    PAGE -->|"useProducts · useWarehouses · useStock"| HOOKS
    MODAL -->|"useCreateMovement"| HOOKS
    HOOKS --> KEYS
    HOOKS --> HTTP
    HTTP -->|"GET /api/v1/inventory/products"| ROUTERS
    HTTP -->|"GET /api/v1/inventory/warehouses"| ROUTERS
    HTTP -->|"GET /api/v1/inventory/stock"| ROUTERS
    HTTP -->|"POST /api/v1/inventory/movements"| ROUTERS
    ROUTERS -->|"payload JSON snake_case"| SCHEMAS
    SCHEMAS -->|"datos validados"| SERVICES
    SERVICES --> MODELS
    ROUTERS -->|"InventoryError"| ERR
    MAIN --> ROUTERS
    MAIN --> ERR
    MODELS -->|"SELECT · INSERT · UPDATE ... FOR UPDATE"| T_S
    MODELS -->|"INSERT histórico"| T_M
    MODELS --> T_P
    MODELS --> T_W
    MODELS --> T_E
    ERR -->|"400 · 404 · 409 · detail"| HTTP
    HTTP -->|"JSON tipado"| HOOKS
    HOOKS -->|"invalida movements.all y stock.all"| PAGE
```

### Lectura del diagrama

- **Una sola capa de datos en el cliente.** `InventoryPage` y
  `MovementFormModal` nunca llaman a `fetch` directamente: consumen hooks, y
  estos comparten `inventoryKeys` para invalidar caché de forma selectiva.
- **Contrato único.** Los tipos TypeScript replican en `snake_case` los esquemas
  Pydantic; el cliente HTTP traduce `{ "detail": "..." }` y las listas de
  validación 422 a un `InventoryApiError` legible.
- **Validación en dos capas.** Pydantic (`schemas.py`) valida tipos, longitudes y
  la forma del movimiento por tipo; `services.py` repite la validación de bodegas
  como defensa en profundidad para llamadas internas.
- **`main.py` centraliza el mapeo de errores.** `InventoryError` se traduce a
  404 (`ResourceNotFoundError`), 409 (`DuplicateResourceError`,
  `ImmutableMovementError`) o 400 (`InvalidMovementError`,
  `InsufficientStockError`).
- **El frontend no escribe en `stocks`.** Solo `create_stock_movement` modifica
  saldos; el cliente refresca vía invalidación de `stock.all`.

---

## 3. Diagrama de secuencia — registro de un movimiento

Flujo completo de `POST /api/v1/inventory/movements`, incluyendo validación
Pydantic, transacción atómica, bloqueo de stock negativo (HTTP 400) e
inmutabilidad del histórico.

```mermaid
sequenceDiagram
    autonumber
    actor Op as Operador
    participant UI as Modal + Página
    participant API as Query + HTTP
    participant R as Router + Pydantic
    participant S as create_stock_movement
    participant DB as PostgreSQL

    Op->>UI: Enviar formulario del movimiento
    UI->>UI: validate() local de campos y bodegas

    alt Validación local fallida
        UI-->>Op: Error inline, sin petición HTTP
    else Payload válido
        UI->>API: mutate() y createMovement(payload)
        API->>R: POST /api/v1/inventory/movements
        R->>R: StockMovementCreate valida tipos y forma

        alt Payload inválido
            R-->>API: 422 Unprocessable Entity
            API-->>UI: InventoryApiError con detail
            UI-->>Op: Muestra el detalle
        else Payload válido
            R->>S: create_stock_movement(db, payload)
            S->>S: _validate_movement_shape()
            S->>DB: Buscar producto y bodegas por id

            alt Producto o bodega inexistente
                S-->>R: ResourceNotFoundError
                R-->>API: 404 Not Found
                API-->>UI: InventoryApiError 404
                UI-->>Op: Muestra el error
            else Recursos existentes
                S->>S: _resolve_allow_negative_stock()
                Note over S,DB: Una sola transacción para saldo e histórico
                S->>DB: SELECT stocks FOR UPDATE

                opt Saldo inexistente
                    S->>DB: INSERT stocks en 0 vía savepoint
                end

                alt INBOUND o ADJUSTMENT con destino
                    S->>S: _increase(stock, quantity)
                else OUTBOUND, TRANSFER o ADJUSTMENT con origen
                    S->>S: _decrease(stock, quantity)
                end

                alt Saldo negativo y flag desactivado
                    S->>DB: ROLLBACK
                    S-->>R: InsufficientStockError(disponible, solicitado)
                    R-->>API: 400 con detail de stock insuficiente
                    API-->>UI: InventoryApiError 400
                    UI-->>Op: Error en el sheet, el saldo no cambia
                else Saldo válido o flag activo
                    S->>DB: UPDATE stocks
                    opt TRANSFER
                        S->>DB: UPDATE stocks destino
                    end
                    S->>DB: INSERT stock_movements y COMMIT
                    S-->>R: StockMovement persistido
                    R-->>API: 201 Created
                    API-->>UI: JSON del movimiento
                    API->>API: invalida movements.all y stock.all
                    UI-->>Op: Cierra el sheet y confirma
                end
            end
        end
    end

    Note over S,DB: Inmutable, corregir con un nuevo ADJUSTMENT
```

### Lectura del diagrama

- **Doble validación de forma.** El cliente valida lo mínimo para dar feedback
  inmediato; Pydantic es la fuente de verdad del contrato y devuelve **422** con
  la lista de errores, mientras `services._validate_movement_shape` protege
  llamadas internas que no pasan por el router.
- **Reglas por tipo (`model_validator`).** `INBOUND` exige solo destino,
  `OUTBOUND` solo origen, `TRANSFER` ambos y distintos, y `ADJUSTMENT`
  exactamente una bodega. Un incumplimiento nunca llega a tocar `stocks`.
- **Atomicidad.** `_get_or_create_stock` usa `SELECT ... FOR UPDATE` para
  serializar movimientos concurrentes del mismo producto y bodega, y crea la
  fila en 0 dentro de un savepoint para tolerar carreras. El `UPDATE` de saldo y
  el `INSERT` del histórico se confirman en el mismo `COMMIT`; cualquier
  excepción ejecuta `db.rollback()`.
- **Bloqueo de stock negativo (escenario 2 de la spec).** `_decrease` calcula el
  saldo resultante; si es negativo y `ALLOW_NEGATIVE_STOCK` está desactivado,
  lanza `InsufficientStockError`, el router responde **400** con
  `detail: "Stock insuficiente ... disponible N, solicitado M"` y no se persiste
  ni el saldo ni el movimiento.
- **Transferencias sin deadlocks.** El servicio bloquea los saldos en orden
  ascendente de `warehouse_id`, de modo que dos transferencias cruzadas no se
  bloqueen mutuamente.
- **Inmutabilidad.** No hay `PATCH` ni `DELETE` sobre movimientos; los listeners
  `before_update` y `before_delete` lanzan `ImmutableMovementError` (409) y la
  única corrección admitida es un nuevo `ADJUSTMENT`.

---

## Referencias

- Contrato funcional: `specs/inventory_spec.md` (§2 entidades, §3 reglas, §4 API,
  §5 criterios de aceptación).
- Backend: `backend/src/modules/inventory/{models,schemas,services,router}.py`,
  `backend/src/core/database.py`, `backend/src/main.py`.
- Frontend: `frontend/src/modules/inventory/{InventoryPage,MovementFormModal,constants}.tsx`,
  `frontend/src/api/inventory.ts`, `frontend/src/routes/index.tsx`,
  `frontend/src/layouts/AppLayout.tsx`.
- Pruebas de aceptación: `backend/tests/test_inventory.py`.
