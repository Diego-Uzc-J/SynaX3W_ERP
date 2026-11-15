import { createBrowserRouter, Navigate } from "react-router-dom";

import AppLayout from "../layouts/AppLayout";
import InventoryPage from "../modules/inventory/InventoryPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppLayout />,
    children: [
      { index: true, element: <Navigate to="/inventory" replace /> },
      { path: "inventory", element: <InventoryPage /> },
      { path: "*", element: <Navigate to="/inventory" replace /> },
    ],
  },
]);
