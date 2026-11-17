# Diagramas técnicos — Módulo `sales`

Documentación visual del módulo de Ventas y Facturación, derivada de
`specs/sales_spec.md` y del código final de `backend/src/modules/sales/` y
`frontend/src/modules/sales/`.

| Diagrama | Qué responde |
| --- | --- |
| Clases | Qué entidades SQLAlchemy existen, sus enums, relaciones y servicios |
| Componentes | Cómo viaja una petición desde React y TanStack Query hasta PostgreSQL e `inventory` |
| Secuencia | Qué ocurre al confirmar un pedido, facturarlo y registrar abonos o notas crédito |

---

## 1. Diagrama de clases

Entidades SQLAlchemy (`models.py`), enums de estado, servicios de dominio
(`services.py`) y el servicio de inventario que participa en el despacho.
`Decimal` corresponde a `Numeric(14, 2)`; `InvoicePayment` es la extensión
implementada para materializar el historial de abonos.

```mermaid
classDiagram

    class Base {
        <<abstract>>
        +metadata
    }

    class SalesOrderStatus {
        <<enumeration>>
        DRAFT
        QUOTATION
        CONFIRMED
        FULFILLED
        CANCELLED
    }

    class InvoiceStatus {
        <<enumeration>>
        ISSUED
        PAID
        VOID
    }

    class MovementType {
        <<enumeration>>
        INBOUND
        OUTBOUND
        TRANSFER
        ADJUSTMENT
    }

    class Customer {
        +int id PK
        +str tax_id UK
        +str company_name
        +str contact_name
        +str email
        +str phone nullable
        +str address
        +Decimal credit_limit
        +bool is_active
        +datetime created_at
        +list~SalesOrder~ orders
        +list~Invoice~ invoices
    }

    class SalesOrder {
        +int id PK
        +str code UK
        +int customer_id FK
        +SalesOrderStatus status
        +date issue_date
        +date valid_until nullable
        +Decimal subtotal
        +Decimal tax_amount
        +Decimal total
        +datetime created_at
        +list~SalesOrderItem~ items
        +list~Invoice~ invoices
    }

    class SalesOrderItem {
        +int id PK
        +int sales_order_id FK
        +int product_id FK
        +int quantity
        +Decimal unit_price
        +Decimal tax_rate
        +Decimal subtotal
    }

    class Invoice {
        +int id PK
        +str code UK
        +int sales_order_id FK nullable
        +int customer_id FK
        +InvoiceStatus status
        +date issue_date
        +date due_date
        +Decimal total
        +Decimal balance_due
        +datetime created_at
        +list~CreditNote~ credit_notes
        +list~InvoicePayment~ payments
    }

    class InvoicePayment {
        <<ledger>>
        +int id PK
        +int invoice_id FK
        +Decimal amount
        +date paid_at
        +datetime created_at
    }

    class CreditNote {
        +int id PK
        +str code UK
        +int invoice_id FK
        +Decimal amount
        +str reason nullable
        +date issue_date
        +datetime created_at
    }

    class Product {
        <<inventory>>
        +int id PK
        +str sku UK
        +str name
        +Decimal unit_price
        +int minimum_stock
        +bool is_active
    }

    class SalesService {
        <<service>>
        +create_customer(db, data) Customer
        +get_customer(db, customer_id) Customer
        +list_customers(db, filters) list
        +update_customer(db, customer_id, data) Customer
        +create_sales_order(db, data) SalesOrder
        +confirm_sales_order(db, order_id, warehouse_id, created_by) SalesOrder
        +cancel_sales_order(db, order_id, reason, created_by) SalesOrder
        +validate_order_credit(db, order) Decimal
        +issue_invoice(db, data) Invoice
        +register_invoice_payment(db, invoice_id, amount) Invoice
        +list_invoice_payments(db, invoice_id) list
        +void_invoice(db, invoice_id) Invoice
        +issue_credit_note(db, invoice_id, data) CreditNote
        +list_credit_notes(db, invoice_id) list
        +reject_invoice_mutation(db, invoice_id) None
    }

    class InventoryService {
        <<service>>
        +create_stock_movement(db, payload, allow_negative_stock, commit) StockMovement
        +list_stock(db, filters) list
    }

    Base <|-- Customer
    Base <|-- SalesOrder
    Base <|-- SalesOrderItem
    Base <|-- Invoice
    Base <|-- InvoicePayment
    Base <|-- CreditNote
    Base <|-- Product

    Customer "1" --> "0..*" SalesOrder : orders
    Customer "1" --> "0..*" Invoice : invoices
    SalesOrder "1" *-- "1..*" SalesOrderItem : items
    SalesOrder "1" --> "0..*" Invoice : invoices
    SalesOrderItem "0..*" --> "1" Product : product_id
    Invoice "1" --> "0..*" CreditNote : credit_notes
    Invoice "1" --> "0..*" InvoicePayment : payments

    SalesOrder ..> SalesOrderStatus : status
    Invoice ..> InvoiceStatus : status
    InventoryService ..> MovementType : OUTBOUND al despachar

    SalesService ..> Customer : gestiona
    SalesService ..> SalesOrder : gestiona
    SalesService ..> SalesOrderItem : calcula
    SalesService ..> Invoice : emite y cobra
    SalesService ..> InvoicePayment : registra
    SalesService ..> CreditNote : emite
    SalesService ..> InventoryService : despacha con commit false
```

### Reglas reflejadas en el modelo

- `sales_order_items.sales_order_id` usa `ON DELETE CASCADE`: las líneas son
  dependientes del pedido mientras este sigue en borrador o cotización.
- Las demás claves foráneas usan `RESTRICT`: clientes, pedidos, facturas,
  abonos y notas crédito conservan el historial comercial.
- `SalesOrder` calcula `subtotal`, `tax_amount` y `total` desde sus líneas;
  `Invoice` nace con `balance_due = total` y solo lo reducen pagos o notas.
- `MovementType.OUTBOUND` es el vínculo con `inventory`; la cancelación de un
  pedido `CONFIRMED` genera un `INBOUND` de reversión sin borrar el salida
  original.

---

## 2. Diagrama de componentes

Arquitectura full-stack: vistas React → guardias RBAC → hooks de TanStack Query
→ cliente HTTP → routers, esquemas y servicios de FastAPI → tablas PostgreSQL
de `sales` e `inventory`.

```mermaid
flowchart TB
    subgraph CLIENTE["Frontend · React 19 + Vite 8"]
        direction TB
        OP["Usuario"]
        ROUTES["routes/index.tsx<br/>/sales/customers · orders<br/>invoices · invoices/:id"]
        GUARD["routes/guards.tsx<br/>RequireModule + RequireRole<br/>sales · administrator"]
        VIEWS["Vistas de lista<br/>CustomerList · SalesOrderList<br/>InvoiceList"]
        FORMS["Formularios y diálogos<br/>CustomerForm · SalesOrderForm<br/>IssueInvoiceDialog · OrderActionDialogs<br/>PaymentForm · CreditNoteForm"]
        DETAIL["InvoiceDetail<br/>resumen · historial · notas"]
        UTILS["constants · format · errors<br/>SalesTabs · SalesStatusBadge"]
    end

    subgraph DATA["Capa de datos del cliente"]
        direction TB
        HOOKS["api/sales.ts<br/>useCustomers · useSalesOrders<br/>useInvoices · useInvoice<br/>useConfirmSalesOrder · useIssueInvoice<br/>useRegisterInvoicePayment · useIssueCreditNote"]
        KEYS["salesKeys<br/>customers · orders · invoices<br/>detail · payments · creditNotes"]
        HTTP["api/client.ts<br/>apiRequest · buildQuery<br/>ApiError 400 / 404 / 409"]
    end

    subgraph API["API · FastAPI /api/v1/sales"]
        direction TB
        RBAC["require_sales<br/>RoleEnum SALES<br/>ADMINISTRATOR bypass"]
        ROUTERS["router.py<br/>customers · orders · invoices<br/>pay · void · credit-notes"]
        SCHEMAS["schemas.py<br/>Pydantic v2<br/>Create · Update · Response"]
        SERVICES["services.py<br/>crédito · stock · facturación<br/>pagos · notas · COMMIT"]
        MODELS["models.py<br/>SQLAlchemy 2.x<br/>Mapped / mapped_column"]
        ERR["sales_exception_handler<br/>SalesServiceError → HTTP"]
    end

    subgraph INVENTORY["Módulo inventory"]
        direction TB
        ISVC["inventory.services<br/>create_stock_movement<br/>commit=False"]
        ITAB["products · warehouses<br/>stocks · stock_movements"]
    end

    subgraph DB["PostgreSQL · tablas sales"]
        direction TB
        T_C["customers"]
        T_O["sales_orders"]
        T_OI["sales_order_items"]
        T_I["invoices"]
        T_IP["invoice_payments"]
        T_CN["credit_notes"]
        T_EN["enum sales_order_status<br/>enum invoice_status"]
    end

    OP --> ROUTES
    ROUTES --> GUARD
    GUARD --> VIEWS
    GUARD --> DETAIL
    VIEWS --> FORMS
    VIEWS --> UTILS
    DETAIL --> UTILS
    VIEWS -->|"hooks de listado y mutación"| HOOKS
    FORMS -->|"mutaciones y preflight"| HOOKS
    DETAIL -->|"useInvoice · useInvoicePayments<br/>useCreditNotes"| HOOKS
    HOOKS --> KEYS
    HOOKS --> HTTP

    HTTP -->|"GET /customers · GET /orders"| ROUTERS
    HTTP -->|"POST /orders/{id}/confirm"| ROUTERS
    HTTP -->|"POST /invoices · GET /invoices"| ROUTERS
    HTTP -->|"POST /pay · POST /credit-notes"| ROUTERS
    ROUTERS --> RBAC
    ROUTERS -->|"payload JSON snake_case"| SCHEMAS
    SCHEMAS -->|"datos validados"| SERVICES
    SERVICES --> MODELS
    SERVICES -->|"commit=False en confirm/cancel"| ISVC
    ISVC --> ITAB
    MODELS -->|"SELECT FOR UPDATE · INSERT · UPDATE"| T_C
    MODELS --> T_O
    MODELS --> T_OI
    MODELS --> T_I
    MODELS -->|"historial de abonos"| T_IP
    MODELS -->|"contrapartidas"| T_CN
    MODELS --> T_EN
    ROUTERS -->|"SalesServiceError"| ERR
    ERR -->|"400 · 404 · 409 con detail"| HTTP
    HTTP -->|"JSON tipado"| HOOKS
    HOOKS -->|"invalida salesKeys e inventoryKeys"| VIEWS
    HOOKS -->|"invalida detail y listado"| DETAIL
```

### Lectura del diagrama

- **Una sola capa de datos en el cliente.** Las vistas nunca llaman a `fetch`
  directamente: consumen hooks de `api/sales.ts`, que comparten `salesKeys`
  para invalidar caché de forma selectiva.
- **Doble guardia RBAC.** `RequireModule` valida `allowed_modules` y
  `RequireRole` exige `sales` o `administrator`, igual que `require_sales` en
  el backend; evita abrir rutas que la API rechazaría con 403.
- **Contrato único.** Los tipos TypeScript replican en `snake_case` los
  esquemas Pydantic. `Decimal` viaja como string para no perder precisión.
- **Inventario participa en la misma transacción.** `confirm_sales_order`
  llama a `create_stock_movement(..., commit=False)`; el `COMMIT` final lo hace
  `services.py`, de modo que no quedan salidas parciales.
- **Los errores de dominio se traducen en el router.** Crédito insuficiente y
  stock insuficiente son 400; estado inválido es 409; recurso ausente es 404.

---

## 3. Diagrama de secuencia — confirmación, facturación y cobros

Flujo completo desde la confirmación de un pedido hasta el registro de abonos y
notas crédito. Incluye la validación de crédito, la transacción ACID que
descuenta `stocks` y escribe `stock_movements`, el rechazo HTTP 400 por crédito
o stock insuficiente, la emisión de la factura y la actualización del saldo.

```mermaid
sequenceDiagram
    autonumber
    actor Op as Usuario
    participant UI as Vistas React
    participant Q as TanStack Query
    participant R as Router + Pydantic
    participant S as sales.services
    participant C as validate_order_credit
    participant I as inventory.services
    participant DB as PostgreSQL

    Op->>UI: Confirmar pedido desde SalesOrderList
    UI->>Q: useConfirmSalesOrder(id, warehouseId)
    Q->>R: POST /api/v1/sales/orders/{id}/confirm
    R->>R: require_sales y SalesOrderConfirmRequest
    R->>S: confirm_sales_order(db, id, warehouse_id)

    S->>DB: SELECT sales_orders FOR UPDATE
    S->>S: Solo DRAFT o QUOTATION, CONFIRMED es idempotente
    S->>C: validate_order_credit(db, order)
    C->>DB: SELECT customers FOR UPDATE
    C->>DB: SUM balance_due de facturas ISSUED

    alt Crédito insuficiente
        C--xS: CreditLimitExceededError
        S->>DB: ROLLBACK
        S--xR: 400 con detail de crédito
        R--xQ: ApiError 400
        Q--xUI: errorHint de crédito
        UI--xOp: Aviso: reduzca el pedido o amplíe el cupo
    else Crédito suficiente
        C-->>S: cupo restante
        S->>DB: SELECT warehouses activas
        Note over S,DB: Una transacción ACID para estado, saldo e histórico

        loop Cada SalesOrderItem
            S->>I: create_stock_movement(commit=False, allow_negative_stock=False)
            I->>DB: UPDATE stocks
            I->>DB: INSERT stock_movements OUTBOUND

            alt Stock insuficiente
                I--xS: InsufficientStockError
                S->>DB: ROLLBACK sin movimientos parciales
                S--xR: 400 con detail de stock
                R--xQ: ApiError 400
                Q--xUI: errorHint de stock
                UI--xOp: Aviso: reponga existencias o elija otra bodega
            else Stock suficiente
                I-->>S: OUTBOUND registrado
            end
        end

        S->>DB: UPDATE sales_orders.status = CONFIRMED
        S->>DB: COMMIT
        S-->>R: SalesOrder CONFIRMED
        R-->>Q: 200 JSON
        Q->>Q: invalida orders.all, stock.all y movements.all
        Q-->>UI: Pedido confirmado
        UI-->>Op: Se habilita la acción Facturar
    end

    Op->>UI: Emitir factura desde IssueInvoiceDialog
    UI->>Q: useIssueInvoice(payload)
    Q->>R: POST /api/v1/sales/invoices
    R->>S: issue_invoice(db, data)
    S->>DB: Valida pedido CONFIRMED y sin factura vigente
    S->>DB: INSERT invoices ISSUED con balance_due igual al total
    S-->>R: Invoice FAC-AAAA-0000
    R-->>Q: 201 JSON
    Q->>Q: invalida salesKeys.invoices.all
    Q-->>UI: Factura disponible en InvoiceList
    UI-->>Op: Muestra code, vencimiento y saldo pendiente

    Op->>UI: Registrar abono o nota crédito en InvoiceDetail
    UI->>Q: useRegisterInvoicePayment o useIssueCreditNote
    Q->>R: POST /invoices/{id}/pay o /credit-notes
    R->>S: register_invoice_payment o issue_credit_note
    S->>DB: SELECT invoices FOR UPDATE

    alt Abono sobre factura ISSUED
        S->>DB: INSERT invoice_payments
        S->>DB: UPDATE balance_due
        S->>DB: UPDATE status a PAID si el saldo llega a cero
    else Nota crédito sobre ISSUED o PAID
        S->>DB: INSERT credit_notes
        S->>DB: UPDATE balance_due sin superar el total
        S->>DB: UPDATE status a PAID si queda en cero
    end

    S->>DB: COMMIT
    S-->>R: Invoice o CreditNote actualizado
    R-->>Q: 200 o 201 JSON
    Q->>Q: invalida detail, list, payments y creditNotes
    Q-->>UI: Saldo e historial refrescados
    UI-->>Op: Feedback con importe, código y saldo final
```

### Puntos críticos del flujo

- **Idempotencia.** Un pedido ya `CONFIRMED` se devuelve sin descontar stock
  otra vez; el bloqueo `FOR UPDATE` se libera con `ROLLBACK`.
- **ACID.** Si falla una línea por falta de stock, se revierte el cambio de
  estado y no queda ningún `OUTBOUND` parcial. El error se convierte en 400.
- **Inmutabilidad financiera.** La factura no se edita: los ajustes se registran
  como `InvoicePayment` o `CreditNote`, y `PATCH`/`DELETE` responden 400.
- **Coherencia de caché.** Confirmar invalida inventario; abonar o acreditar
  invalida el detalle, el listado y el historial de la factura.
