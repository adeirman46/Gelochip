import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

// apply the saved theme before first paint (no flash of the wrong theme)
document.documentElement.setAttribute("data-theme", localStorage.getItem("anoa-theme") || "dark");

// NOTE: StrictMode intentionally omitted — it double-invokes state updaters in dev,
// which duplicates streamed transcript blocks. The updaters are now pure regardless.
ReactDOM.createRoot(document.getElementById("root")!).render(<App />);
