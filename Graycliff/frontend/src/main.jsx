import React from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import "./index.css";
import App from "./App.jsx";
import MenuPage from "./pages/MenuPage.jsx";
import DashboardPage from "./pages/DashboardPage.jsx";
import VoicePage from "./pages/VoicePage.jsx";
import MarketingPage from "./pages/MarketingPage.jsx";

const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <MenuPage /> },
      { path: "dashboard", element: <DashboardPage /> },
      { path: "voice", element: <VoicePage /> },
      { path: "marketing", element: <MarketingPage /> },
    ],
  },
]);

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>
);
