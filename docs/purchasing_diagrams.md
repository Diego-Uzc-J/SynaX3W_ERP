# Diagramas técnicos — Módulo `purchasing`

Documentación visual del módulo de Compras y Proveedores, derivada de
`specs/purchasing_spec.md` y del código final de
`backend/src/modules/purchasing/` y `frontend/src/modules/purchasing/`.

| Diagrama | Qué responde |
| --- | --- |
| Clases | Qué entidades SQLAlchemy existen, sus enums, relaciones y servicios de dominio |
| Componentes | Cómo viaja una petición desde React y TanStack Query hasta PostgreSQL e `inventory` |
| Secuencia | Qué ocurre al recibir mercancía, actualizar stock y registrar la factura del proveedor |

---

## 1. Diagrama de clases

Entidades SQLAlchemy (`models.py`), enums de estado, tipos de datos y servicios
de dominio (`services.py`). `Decimal` corresponde a `Numeric(14, 2)`,
`tax_rate` a `Numeric(5, 2)` y `MovementType` se reutiliza de `inventory`.
`SupplierBillPayment` es la extensión implementada para materializar el ledger
de abonos; `Product` y `Warehouse` pertenecen al catálogo de `inventory`.

```mermaid
classDiagram

    class Base {
        <<abstract>>
        +metadata
    }

    class PurchaseOrderStatus {
        <<enumeration>>
        DRAFT
        SENT
        APPROVED
        PARTIALLY_RECEIVED
        COMPLETED
        FORCE_CLOSED
        CANCELLED
    }

    class SupplierBillStatus {
        <<enumeration>>
        PENDING
        PARTIALLY_PAID
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

    class Supplier {
        +int id PK
        +str tax_id UK
        +str company_name
        +str contact_name
        +str email
        +str phone nullable
        +str address
        +int payment_terms_days
        +bool is_active
        +datetime created_at
        +list~PurchaseOrder~ orders
        +list~SupplierBill~ bills
    }

    class PurchaseOrder {
        +int id PK
        +str code UK
        +int supplier_id FK
        +PurchaseOrderStatus status
        +date issue_date
        +date expected_delivery_date
        +Decimal subtotal
        +Decimal tax_amount
        +Decimal total
        +datetime created_at
        +Supplier supplier
        +list~PurchaseOrderItem~ items
        +list~GoodsReceipt~ receipts
        +list~SupplierBill~ bills
    }

    class PurchaseOrderItem {
        +int id PK
        +int purchase_order_id FK
        +int product_id FK
        +int quantity
        +int received_quantity
        +Decimal unit_price
        +Decimal tax_rate
        +Decimal subtotal
        +PurchaseOrder order
        +Product product
        +list~GoodsReceiptItem~ receipt_items
    }

    class GoodsReceipt {
        <<immutable>>
        +int id PK
        +str code UK
        +int purchase_order_id FK
        +int warehouse_id FK
        +date receipt_date
        +str received_by nullable
        +str notes nullable
        +datetime created_at
        +PurchaseOrder order
        +Warehouse warehouse
        +list~GoodsReceiptItem~ items
        +list~SupplierBill~ bills
    }

    class GoodsReceiptItem {
        <<immutable>>
        +int id PK
        +int goods_receipt_id FK
        +int purchase_order_item_id FK
        +int quantity
        +GoodsReceipt receipt
        +PurchaseOrderItem order_item
    }

    class SupplierBill {
        <<immutable>>
        +int id PK
        +str code UK
        +int supplier_id FK
        +int purchase_order_id FK nullable
        +int goods_receipt_id FK nullable
        +str supplier_invoice_number
        +SupplierBillStatus status
        +date issue_date
        +date due_date
        +Decimal subtotal
        +Decimal tax_amount
        +Decimal total
        +Decimal balance_due
        +datetime created_at
        +Supplier supplier
        +PurchaseOrder purchase_order
        +GoodsReceipt goods_receipt
        +list~SupplierBillPayment~ payments
    }

    class SupplierBillPayment {
        <<ledger>>
        +int id PK
        +int bill_id FK
        +Decimal amount
        +date paid_at
        +str reference nullable
        +datetime created_at
        +SupplierBill bill
    }

    class Product {
        <<inventory>>
        +int id PK
        +str sku UK
        +str name
        +Decimal unit_price
        +bool is_active
    }

    class Warehouse {
        <<inventory>>
        +int id PK
        +str code UK
        +str name
        +bool is_active
    }

    class PurchasingService {
        <<service>>
        +create_supplier(db, data) Supplier
        +get_supplier(db, supplier_id) Supplier
        +list_suppliers(db, filters) list
        +update_supplier(db, supplier_id, data) Supplier
        +ensure_supplier_active(db, supplier_id, for_update) Supplier
        +create_purchase_order(db, data) PurchaseOrder
        +get_purchase_order(db, order_id, for_update) PurchaseOrder
        +list_purchase_orders(db, filters) list
        +update_purchase_order(db, order_id, data) PurchaseOrder
        +approve_purchase_order(db, order_id, send) PurchaseOrder
        +cancel_purchase_order(db, order_id, reason) PurchaseOrder
        +force_close_purchase_order(db, order_id) PurchaseOrder
        +create_goods_receipt(db, receipt_data) GoodsReceipt
        +get_goods_receipt(db, receipt_id) GoodsReceipt
        +list_goods_receipts(db, filters) list
        +create_supplier_bill(db, data) SupplierBill
        +get_supplier_bill(db, bill_id) SupplierBill
        +list_supplier_bills(db, filters) list
        +register_bill_payment(db, bill_id, data) SupplierBill
        +list_bill_payments(db, bill_id) list
        +void_supplier_bill(db, bill_id) SupplierBill
        +reject_bill_mutation(db, bill_id) None
        +_validate_receipt_lines(receipt_code, order, data) list
        +_expected_bill_amounts(order, receipt) tuple
        +_billed_amounts(db, order_id, receipt_id) tuple
    }

    class InventoryService {
        <<service>>
        +create_stock_movement(db, payload, commit) StockMovement
        +get_warehouse(db, warehouse_id) Warehouse
    }

    Base <|-- Supplier
    Base <|-- PurchaseOrder
    Base <|-- PurchaseOrderItem
    Base <|-- GoodsReceipt
    Base <|-- GoodsReceiptItem
    Base <|-- SupplierBill
    Base <|-- SupplierBillPayment
    Base <|-- Product
    Base <|-- Warehouse

    Supplier "1" --> "0..*" PurchaseOrder : orders
    Supplier "1" --> "0..*" SupplierBill : bills
    PurchaseOrder "1" *-- "1..*" PurchaseOrderItem : items
    PurchaseOrder "1" --> "0..*" GoodsReceipt : receipts
    PurchaseOrder "1" --> "0..*" SupplierBill : bills
    PurchaseOrderItem "1" --> "0..*" GoodsReceiptItem : receipt_items
    PurchaseOrderItem "0..*" --> "1" Product : product_id
    GoodsReceipt "1" *-- "1..*" GoodsReceiptItem : items
    GoodsReceiptItem "0..*" --> "1" PurchaseOrderItem : order_item
    GoodsReceipt "0..*" --> "1" Warehouse : warehouse_id
    SupplierBill "0..1" --> "1" PurchaseOrder : purchase_order
    SupplierBill "0..1" --> "1" GoodsReceipt : goods_receipt
    SupplierBill "1" *-- "0..*" SupplierBillPayment : payments

    PurchaseOrder ..> PurchaseOrderStatus : status
    SupplierBill ..> SupplierBillStatus : status
    InventoryService ..> MovementType : INBOUND en recepciones

    PurchasingService ..> Supplier : gestiona
    PurchasingService ..> PurchaseOrder : gestiona y transiciona
    PurchasingService ..> GoodsReceipt : registra sin editar
    PurchasingService ..> SupplierBill : valida y abona
    PurchasingService ..> InventoryService : commit false en recepciones
```

### Reglas reflejadas en el modelo

- `PurchaseOrder` nace en `DRAFT`; solo `APPROVED` y `PARTIALLY_RECEIVED` admiten
  recepciones. La recepción total la lleva a `COMPLETED` y la parcial a
  `PARTIALLY_RECEIVED`; `FORCE_CLOSED` libera saldos pendientes y `CANCELLED`
  está prohibido si ya hay recepciones.
- `received_quantity` se acumula por línea y el `CHECK` de base de datos exige
  `0 <= received_quantity <= quantity`, respaldando la validación de
  sobre-recepción del servicio.
- `GoodsReceipt`, `GoodsReceiptItem`, `SupplierBill` y `SupplierBillPayment` son
  inmutables: los listeners ORM bloquean cambios y borrados; en una factura solo
  `status` y `balance_due` pueden cambiar al abonar o anular.
- `SupplierBill` exige al menos un documento origen (`purchase_order_id` o
  `goods_receipt_id`) y nace en `PENDING` con `balance_due = total`.
  `due_date` se deriva de `issue_date + supplier.payment_terms_days`.
- `ON DELETE RESTRICT` protege documentos comerciales y financieros;
  `CASCADE` solo aplica a las líneas dependientes de su documento.

---

## 2. Diagrama de componentes

Arquitectura full-stack: vistas React → guardias RBAC → hooks de TanStack Query
→ cliente HTTP → routers, esquemas y servicios de FastAPI → tablas PostgreSQL de
`purchasing` e `inventory`.

```mermaid
flowchart TB
    subgraph CLIENTE["Frontend · React 19 + Vite 8"]
        direction TB
        OP["Usuario"]
        ROUTES["routes/index.tsx<br/>/purchasing/suppliers · orders<br/>receipts · bills · bills/:billId"]
        GUARD["routes/guards.tsx<br/>RequireModule purchasing<br/>RequireRole purchasing · administrator"]
        VIEWS["Vistas de lista<br/>SupplierList · PurchaseOrderList<br/>GoodsReceiptList · SupplierBillList"]
        FORMS["Formularios y diálogos<br/>SupplierForm · PurchaseOrderForm<br/>GoodsReceiptForm · OrderActionDialogs<br/>SupplierBillForm · BillPaymentForm"]
        DETAIL["SupplierBillDetail<br/>resumen · abonos · anulación"]
        UTILS["constants · format · errors<br/>PurchasingTabs · PurchasingStatusBadge"]
    end

    subgraph DATA["Capa de datos del cliente"]
        direction TB
        HOOKS["api/purchasing.ts<br/>useSuppliers · usePurchaseOrders<br/>useGoodsReceipts · useSupplierBills<br/>useCreateGoodsReceipt · usePaySupplierBill"]
        KEYS["purchasingKeys<br/>suppliers · orders · receipts<br/>bills · detail · billPayments"]
        HTTP["api/client.ts<br/>apiRequest · buildQuery<br/>ApiError 400 / 404 / 409"]
        INVHOOKS["api/inventory.ts<br/>useProducts · useWarehouses<br/>inventoryKeys.stock · movements"]
    end

    subgraph API["API · FastAPI /api/v1/purchasing"]
        direction TB
        RBAC["require_purchasing<br/>RoleEnum PURCHASING<br/>ADMINISTRATOR bypass"]
        ROUTERS["router.py<br/>suppliers · orders · receipts<br/>bills · pay · void · payments"]
        SCHEMAS["schemas.py<br/>Pydantic v2<br/>Create · Update · Response"]
        SERVICES["services.py<br/>validación de negocio<br/>transacciones ACID y COMMIT"]
        MODELS["models.py<br/>SQLAlchemy 2.x<br/>Mapped / mapped_column"]
        ERR["purchasing_exception_handler<br/>PurchasingServiceError → HTTP"]
    end

    subgraph INVENTORY["Módulo inventory"]
        direction TB
        ISVC["inventory.services<br/>create_stock_movement<br/>commit=False · SELECT FOR UPDATE"]
        ITAB["products · warehouses<br/>stocks · stock_movements"]
    end

    subgraph DB["PostgreSQL · tablas purchasing"]
        direction TB
        T_S["suppliers"]
        T_PO["purchase_orders"]
        T_POI["purchase_order_items"]
        T_GR["goods_receipts"]
        T_GRI["goods_receipt_items"]
        T_B["supplier_bills"]
        T_BP["supplier_bill_payments"]
        T_EN["enum purchase_order_status<br/>enum supplier_bill_status"]
    end

    OP --> ROUTES
    ROUTES --> GUARD
    GUARD --> VIEWS
    GUARD --> DETAIL
    VIEWS --> FORMS
    VIEWS --> UTILS
    DETAIL --> UTILS
    FORMS --> INVHOOKS
    VIEWS -->|"hooks de listado"| HOOKS
    FORMS -->|"mutaciones y preflight"| HOOKS
    DETAIL -->|"useSupplierBill · useBillPayments"| HOOKS
    HOOKS --> KEYS
    HOOKS --> HTTP
    INVHOOKS --> HTTP

    HTTP -->|"GET /suppliers · GET /orders"| ROUTERS
    HTTP -->|"POST /approve · /cancel · /force-close"| ROUTERS
    HTTP -->|"POST /receipts"| ROUTERS
    HTTP -->|"POST /bills · /pay · /void"| ROUTERS
    ROUTERS --> RBAC
    ROUTERS -->|"payload JSON snake_case"| SCHEMAS
    SCHEMAS -->|"datos validados"| SERVICES
    SERVICES --> MODELS
    SERVICES -->|"INBOUND en la misma transacción"| ISVC
    ISVC --> ITAB
    MODELS --> T_S
    MODELS --> T_PO
    MODELS --> T_POI
    MODELS -->|"historial de recepciones"| T_GR
    MODELS --> T_GRI
    MODELS -->|"cuentas por pagar"| T_B
    MODELS -->|"ledger de abonos"| T_BP
    MODELS --> T_EN
    ROUTERS -->|"PurchasingServiceError"| ERR
    ERR -->|"400 · 404 · 409 con detail"| HTTP
    HTTP -->|"JSON tipado"| HOOKS
    HOOKS -->|"invalida purchasingKeys e inventoryKeys"| VIEWS
    HOOKS -->|"refresca saldo e historial"| DETAIL
```

### Lectura del diagrama

- **Una sola capa de datos en el cliente.** Las vistas consumen hooks de
  `api/purchasing.ts`, que comparten `purchasingKeys` para invalidar caché de
  forma selectiva. El catálogo y las bodegas se leen con `api/inventory.ts`
  porque el rol `PURCHASING` solo tiene `inventory:read`.
- **Doble guardia RBAC.** `RequireModule` valida `allowed_modules` y
  `RequireRole` exige `purchasing` o `administrator`, igual que
  `require_purchasing` en el backend; evita abrir rutas que la API rechazaría
  con 403.
- **Contrato único.** Los tipos TypeScript replican en `snake_case` los
  esquemas Pydantic. Los importes `Decimal` viajan como string para no perder
  precisión; las vistas calculan en centavos.
- **Inventario participa en la misma transacción.** `create_goods_receipt`
  llama a `create_stock_movement(..., commit=False)`; el `COMMIT` final lo hace
  `services.py`, de modo que no quedan recepciones ni stocks parciales.
- **Los errores de dominio se traducen en el router.** Sobre-recepción,
  proveedor/producto inactivo e importe inválido son 400; estado inválido es
  409; recurso ausente es 404.

---

## 3. Diagrama de secuencia — recepción, stock y facturación

Flujo completo desde la acción **Recibir** (`/receive`) sobre una orden
aprobada hasta el registro de la factura del proveedor. Incluye la validación
de sobre-recepción, la transacción ACID que incrementa el stock de `inventory`,
el rechazo HTTP 400 sin escrituras parciales y la validación financiera de la
factura contra costos pactados y cantidades realmente recibidas.

```mermaid
sequenceDiagram
    autonumber
    actor Op as Usuario
    participant UI as Vistas React
    participant Q as TanStack Query
    participant R as Router + Pydantic
    participant S as purchasing.services
    participant I as inventory.services
    participant DB as PostgreSQL

    Op->>UI: Acción Recibir (/receive) desde PurchaseOrderList
    UI->>UI: GoodsReceiptForm precarga quantity menos received_quantity
    alt Cantidad local mayor al pendiente
        UI--xOp: Validación local sin petición HTTP
    else Cantidades válidas
        UI->>Q: useCreateGoodsReceipt(payload)
        Q->>R: POST /api/v1/purchasing/receipts
        R->>R: require_purchasing con bypass de ADMINISTRATOR
        R->>R: GoodsReceiptCreate rechaza líneas duplicadas
        R->>S: create_goods_receipt(db, payload)

        S->>DB: SELECT purchase_orders FOR UPDATE con líneas
        S->>S: Exige APPROVED o PARTIALLY_RECEIVED
        S->>S: ensure_supplier_active y bodega destino existe
        S->>DB: Advisory lock y siguiente código REC-YYYY-XXXX

        loop Cada línea de GoodsReceiptCreate
            S->>S: pending equals quantity menos received_quantity
            alt quantity mayor que pending
                S--xR: OverReceiptError 400
                R--xQ: ApiError 400
                Q--xUI: errorHint de sobre-recepción
                UI--xOp: Aviso con pendiente y solicitado
                Note over S,DB: Sin INSERT ni UPDATE, la transacción se revierte
            else Línea válida
                S-->>S: Línea agregada a validadas
            end
        end

        S->>DB: INSERT goods_receipts y goods_receipt_items
        S->>DB: UPDATE purchase_order_items.received_quantity
        S->>DB: UPDATE status a PARTIALLY_RECEIVED o COMPLETED

        loop Cada línea validada
            S->>I: create_stock_movement(commit=False, INBOUND)
            I->>DB: SELECT stocks FOR UPDATE
            I->>DB: UPDATE stocks con el saldo recibido
            I->>DB: INSERT stock_movements con referencia REC
        end

        alt Fallo en inventario o en el COMMIT
            S->>DB: ROLLBACK de recepción, acumulados, estado y stock
            S--xR: Error de dominio 400 o 409 con detail
            R--xQ: ApiError
            Q--xUI: Error mostrado en el formulario
            UI--xOp: Aviso de recepción rechazada
        else Transacción correcta
            S->>DB: COMMIT único y atómico
            S-->>R: GoodsReceipt REC-YYYY-XXXX
            R-->>Q: 201 JSON
            Q->>Q: invalida receipts.all, orders.all, stock.all y movements.all
            Q-->>UI: Historial y OC actualizados
            UI-->>Op: Aviso de mercancía recibida
        end
    end

    Op->>UI: Facturar desde GoodsReceiptList
    UI->>Q: useCreateSupplierBill con receipt preseleccionada
    Q->>R: POST /api/v1/purchasing/bills
    R->>R: require_purchasing y SupplierBillCreate
    R->>S: create_supplier_bill(db, data)

    S->>DB: SELECT supplier, OC y recepción de origen
    S->>S: Verifica que OC y recepción compartan proveedor
    S->>DB: SUM subtotales e impuestos de facturas no VOID
    S->>S: expected_bill_amounts desde cantidades recibidas y tarifas
    S->>S: Subtotal e impuestos no pueden superar lo pendiente facturable

    alt Factura inconsistente
        S--xR: InvalidBillError 400
        R--xQ: ApiError 400
        Q--xUI: errorHint de importe o tasa impositiva
        UI--xOp: Aviso para ajustar la factura
    else Factura válida
        S->>S: due_date equals issue_date más payment_terms_days
        S->>DB: INSERT supplier_bills PENDING con balance_due igual al total
        S->>DB: COMMIT
        S-->>R: SupplierBill BILL-YYYY-XXXX
        R-->>Q: 201 JSON
        Q->>Q: invalida bills.all y orders.all
        Q-->>UI: Factura visible en SupplierBillList y su detalle
        UI-->>Op: Código, vencimiento y saldo pendiente

        Op->>UI: Registrar abono en SupplierBillDetail
        UI->>Q: usePaySupplierBill
        Q->>R: POST /api/v1/purchasing/bills/{id}/pay
        R->>S: register_bill_payment(db, bill_id, data)
        S->>DB: SELECT supplier_bills FOR UPDATE
        S->>DB: INSERT supplier_bill_payments
        S->>DB: UPDATE balance_due y status PARTIALLY_PAID o PAID
        S->>DB: COMMIT
        Q-->>UI: Historial y saldo refrescados
        UI-->>Op: Aviso de abono registrado
    end
```

### Puntos críticos del flujo

- **Sobre-recepción atómica.** Si una línea supera su pendiente, se responde
  400 antes de cualquier escritura: no quedan `GoodsReceipt`, acumulados,
  movimientos ni stock parcial.
- **ACID de extremo a extremo.** Recepciones, acumulados, transición de la OC y
  movimientos `INBOUND` se confirman con un único `COMMIT`. El saldo se bloquea
  con `SELECT FOR UPDATE` dentro de `inventory`.
- **Facturación consistente.** La factura nace `PENDING` con
  `balance_due = total`; el backend valida proveedor, costos pactados, tasa
  impositiva y saldo pendiente descontando facturas no `VOID`.
- **Inmutibilidad financiera y logística.** No se editan recepciones ni
  facturas: los ajustes son nuevos abonos, anulaciones `VOID` o movimientos de
  inventario de contrapartida. `PATCH` y `DELETE` responden 400.
- **Coherencia de caché.** Registrar la recepción invalida también
  `inventoryKeys.stock` y `inventoryKeys.movements`; abonar refresca el
  detalle, el listado y el historial de la factura.
