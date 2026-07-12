import { NavLink, Outlet } from "react-router-dom";

export default function App() {
  return (
    <>
      <header className="topbar">
        <div className="brand">
          <span className="brand-name">GRAYCLIFF</span>
          <span className="brand-sub">AI Concierge · powered by PythaFlow</span>
        </div>
        <nav className="nav">
          <NavLink to="/" end>Guest Menu</NavLink>
          <NavLink to="/dashboard">Dashboard</NavLink>
          <NavLink to="/voice">Voice</NavLink>
          <NavLink to="/marketing">Marketing</NavLink>
          <NavLink to="/knowledge">Knowledge</NavLink>
        </nav>
      </header>
      <Outlet />
    </>
  );
}
