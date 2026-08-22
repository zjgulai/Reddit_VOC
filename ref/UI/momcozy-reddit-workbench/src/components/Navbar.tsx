import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { MessageSquare, Menu, X, Bell } from 'lucide-react';

const navLinks = [
  { path: '/features', label: '功能' },
  { path: '/cases', label: '案例广场' },
  { path: '/how-it-works', label: '使用流程' },
  { path: '/faq', label: '常见问题' },
];

export default function Navbar() {
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  return (
    <nav className="sticky top-0 z-50 backdrop-blur-xl bg-white/80 border-b border-border-divider" role="navigation" aria-label="主导航">
      <div className="max-w-container mx-auto px-6 lg:px-16">
        <div className="flex items-center justify-between h-[68px]">
          {/* Logo */}
          <Link to="/" className="flex items-center gap-2.5 group" aria-label="Momcozy & Reddit 舆情工作台 - 首页">
            <div className="w-8 h-8 rounded-icon bg-primary flex items-center justify-center">
              <MessageSquare className="w-[18px] h-[18px] text-white" strokeWidth={1.5} />
            </div>
            <span className="text-base font-semibold text-foreground tracking-tight group-hover:text-primary transition-colors duration-200">
              Momcozy & Reddit
            </span>
          </Link>

          {/* Desktop Nav */}
          <div className="hidden md:flex items-center gap-8">
            {navLinks.map((link) => (
              <Link
                key={link.path}
                to={link.path}
                className={`nav-link ${location.pathname === link.path ? 'nav-link-active' : ''}`}
                aria-current={location.pathname === link.path ? 'page' : undefined}
              >
                {link.label}
              </Link>
            ))}
          </div>

          {/* CTA + Mobile Menu Toggle */}
          <div className="flex items-center gap-3">
            <Link
              to="/dashboard/messages"
              className="relative p-2 rounded-icon text-foreground-secondary hover:bg-surface-tertiary transition-all"
              aria-label="通知"
            >
              <Bell className="w-5 h-5" strokeWidth={1.5} />
            </Link>
            <Link
              to="/dashboard"
              className="btn-primary text-body-sm px-5 py-2.5 hidden sm:inline-flex"
            >
              开始使用
            </Link>
            <button
              className="md:hidden w-10 h-10 rounded-icon flex items-center justify-center text-foreground-secondary hover:bg-surface-tertiary transition-all"
              onClick={() => setMobileOpen(!mobileOpen)}
              aria-expanded={mobileOpen}
              aria-controls="mobile-menu"
              aria-label={mobileOpen ? '关闭菜单' : '打开菜单'}
            >
              {mobileOpen ? (
                <X className="w-5 h-5" strokeWidth={1.5} />
              ) : (
                <Menu className="w-5 h-5" strokeWidth={1.5} />
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Mobile Menu */}
      <div
        id="mobile-menu"
        className={`md:hidden border-t border-border-divider bg-white/95 backdrop-blur-xl transition-all duration-300 overflow-hidden ${
          mobileOpen ? 'max-h-[400px] opacity-100' : 'max-h-0 opacity-0'
        }`}
      >
        <div className="max-w-container mx-auto px-6 py-4 space-y-1">
          {navLinks.map((link) => (
            <Link
              key={link.path}
              to={link.path}
              className={`block px-4 py-3 rounded-icon text-body-sm font-medium transition-all ${
                location.pathname === link.path
                  ? 'bg-primary-light text-primary'
                  : 'text-foreground-secondary hover:bg-surface-tertiary hover:text-foreground'
              }`}
              aria-current={location.pathname === link.path ? 'page' : undefined}
              onClick={() => setMobileOpen(false)}
            >
              {link.label}
            </Link>
          ))}
          <div className="pt-2 border-t border-border-divider mt-2">
            <Link
              to="/dashboard"
              className="btn-primary text-body-sm px-5 py-2.5 w-full text-center"
              onClick={() => setMobileOpen(false)}
            >
              开始使用
            </Link>
          </div>
        </div>
      </div>
    </nav>
  );
}
