import { createBrowserRouter, Navigate } from "react-router-dom";

import AppLayout from "../layouts/AppLayout";
import InventoryPage from "../modules/inventory/InventoryPage";
import ProductList from "../modules/inventory/ProductList";
import WarehouseList from "../modules/inventory/WarehouseList";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppLayout />,
    children: [
      { index: true, element: <Navigate to="/inventory" replace /> },
      { path: "inventory", element: <InventoryPage /> },
      { path: "inventory/products", element: <ProductList /> },
      { path: "inventory/warehouses", element: <WarehouseList /> },
      { path: "*", element: <Navigate to="/inventory" replace /> },
    ],
  },
]);
