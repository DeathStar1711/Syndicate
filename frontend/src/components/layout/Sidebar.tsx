import { NavLink } from 'react-router-dom';
import { LayoutDashboard, Zap, Briefcase, Settings } from 'lucide-react';

const links = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/signals', icon: Zap, label: 'Signals' },
  { to: '/portfolio', icon: Briefcase, label: 'Portfolio' },
  { to: '/settings', icon: Settings, label: 'Settings' },
];

export function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <img src="/logo.png" alt="Syndicate Logo" style={{ width: 32, height: 32, borderRadius: 8 }} />
        <span>Syndicate</span>
      </div>
      <nav className="sidebar-nav">
        {links.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}
          >
            <Icon size={18} />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>
      <div className="sidebar-footer" style={{ marginTop: 'auto', padding: '16px 20px' }}>
        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          LLM: Groq<br />
          Paper Trading Mode
        </div>
      </div>
    </aside>
  );
}

export function BottomNav() {
  return (
    <nav className="bottom-nav">
      {links.map(({ to, icon: Icon, label }) => (
        <NavLink
          key={to}
          to={to}
          className={({ isActive }) => `bottom-nav-link ${isActive ? 'active' : ''}`}
        >
          <Icon size={20} />
          <span>{label}</span>
        </NavLink>
      ))}
    </nav>
  );
}
