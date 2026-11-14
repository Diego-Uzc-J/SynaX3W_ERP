# 🏢 SynaX3W_ERP

**Sistema ERP Modular Full-Stack** construido bajo una arquitectura de **Monolito Modular** (`FastAPI` + `PostgreSQL`) y una interfaz **SPA moderna** (`React` + `Vite` + `TypeScript`).

---

## 📋 Descripción General

**SynaX3W_ERP** está diseñado para gestionar de forma integral las operaciones centrales de empresas medianas e industriales. Su enfoque de **monolito modular** garantiza un desacoplamiento estricto por dominios de negocio, facilitando el mantenimiento diario y permitiendo una futura migración hacia microservicios sin reescribir la lógica central.

El desarrollo del sistema sigue la metodología **Spec-Driven Development (SDD)**: cada funcionalidad nace a partir de contratos funcionales y técnicos ubicados en `specs/` antes de escribir código en el servidor o en el cliente.

### 🧩 Módulos del Sistema
* 📦 **Inventario y Logística (`inventory`):** Control de almacenes, stock en tiempo real y trazabilidad de movimientos.
* 💼 **Ventas y Facturación (`sales`):** Gestión comercial, cotizaciones, pedidos y emisión de facturas.
* 🛒 **Compras y Proveedores (`purchasing`):** Órdenes de compra, recepciones y gestión de abastecimiento.
* 📊 **Finanzas y Contabilidad (`accounting`):** Partida doble, asientos contables y reportes financieros.
* 👥 **Recursos Humanos (`hr`):** Gestión de empleados, contratos y nómina.
* 🏭 **Manufactura y Producción (`manufacturing`):** Listas de materiales (BOM), recetas y órdenes de producción.

---

## 🛠️ Stack Tecnológico

| Capa | Tecnologías Principales |
| :--- | :--- |
| **Backend** | Python 3.15+, FastAPI, SQLAlchemy 2.1+, Alembic, Pydantic v2, `uv`, Ruff, Pytest |
| **Frontend** | React 19+, Vite 8+, TypeScript 5.8+, TanStack Query v5, Zustand v5, Tailwind CSS v4, React Router v7, Vitest |
| **Base de Datos** | PostgreSQL 18+ |
| **Infraestructura** | Docker & Docker Compose |


---
*Creado por Ing. Diego A. Uzcátegui J. | www.linkedin.com/in/diego-uzc-j | Portafolio Profesional*
