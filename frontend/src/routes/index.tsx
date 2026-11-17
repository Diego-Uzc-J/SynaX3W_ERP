import { createBrowserRouter, Navigate } from "react-router-dom";

import AppLayout from "../layouts/AppLayout";
import InventoryPage from "../modules/inventory/InventoryPage";
import ProductList from "../modules/inventory/ProductList";
import WarehouseList from "../modules/inventory/WarehouseList";
import CustomerList from "../modules/sales/CustomerList";
import InvoiceDetail from "../modules/sales/InvoiceDetail";
import InvoiceList from "../modules/sales/InvoiceList";
import SalesOrderList from "../modules/sales/SalesOrderList";
import LoginPage from "../modules/users/LoginPage";
import UserList from "../modules/users/UserList";
import AccessDenied from "./AccessDenied";
import { IndexRedirect, RequireAuth, RequireModule, RequireRole } from "./guards";
import ModulePlaceholder from "./ModulePlaceholder";

export const router = createBrowserRouter([
  {
    path: "/login",
    element: <LoginPage />,
  },
  {
    element: <RequireAuth />,
    children: [
      {
        path: "/",
        element: <AppLayout />,
        children: [
          { index: true, element: <IndexRedirect /> },

          {
            element: <RequireModule module="inventory" />,
            children: [
              { path: "inventory", element: <InventoryPage /> },
              { path: "inventory/products", element: <ProductList /> },
              { path: "inventory/warehouses", element: <WarehouseList /> },
            ],
          },

          {
            element: <RequireModule module="users" />,
            children: [{ path: "users", element: <UserList /> }],
          },

          {
            element: <RequireModule module="sales" />,
            children: [
              {
                element: (
                  <RequireRole
                    roles={["sales", "administrator"]}
                    module="sales"
                  />
                ),
                children: [
                  {
                    path: "sales",
                    element: <Navigate to="/sales/customers" replace />,
                  },
                  { path: "sales/customers", element: <CustomerList /> },
                  { path: "sales/orders", element: <SalesOrderList /> },
                  { path: "sales/invoices", element: <InvoiceList /> },
                  {
                    path: "sales/invoices/:invoiceId",
                    element: <InvoiceDetail />,
                  },
                ],
              },
            ],
          },
          {
            element: <RequireModule module="purchasing" />,
            children: [
              {
                path: "purchasing",
                element: <ModulePlaceholder module="purchasing" />,
              },
            ],
          },
          {
            element: <RequireModule module="accounting" />,
            children: [
              {
                path: "accounting",
                element: <ModulePlaceholder module="accounting" />,
              },
            ],
          },
          {
            element: <RequireModule module="hr" />,
            children: [
              {
                path: "hr",
                element: <ModulePlaceholder module="hr" />,
              },
            ],
          },
          {
            element: <RequireModule module="manufacturing" />,
            children: [
              {
                path: "manufacturing",
                element: <ModulePlaceholder module="manufacturing" />,
              },
            ],
          },

          { path: "sin-acceso", element: <AccessDenied module={null} /> },
          { path: "*", element: <Navigate to="/" replace /> },
        ],
      },
    ],
  },
]);
