import { Navigate, createBrowserRouter } from "react-router-dom";

import { Layout } from "../components/Layout";
import { DownloadsPage } from "../pages/DownloadsPage";
import { LibraryPage } from "../pages/LibraryPage";
import { LoginPage } from "../pages/LoginPage";

export function createAppRouter() {
  return createBrowserRouter([
    {
      path: "/",
      element: <Layout />,
      children: [
        { index: true, element: <Navigate to="/downloads" replace /> },
        { path: "downloads", element: <DownloadsPage /> },
        { path: "library", element: <LibraryPage /> },
      ],
    },
    { path: "/login", element: <LoginPage /> },
  ]);
}
