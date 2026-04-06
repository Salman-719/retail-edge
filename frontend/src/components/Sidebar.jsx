import React from 'react'
import { NavLink, useNavigate } from 'react-router-dom'

const NAV_ITEMS = [
  { path: '/', label: 'Store Onboarding', icon: '🏪' },
  { path: '/live-monitoring', label: 'Live Monitoring', icon: '📹' },
  { path: '/analytics', label: 'Analytics', icon: '📊' },
  { path: '/ai-agent', label: 'AI Agent', icon: '🤖' },
]

export default function Sidebar() {
  const navigate = useNavigate()

  const handleLogout = () => {
    sessionStorage.removeItem('rv_logged_in')
    navigate('/login')
  }

  return (
    <aside className="w-56 flex flex-col py-6 px-3 shrink-0" style={{ background: '#1B3A5C' }}>
      <div className="mb-8 px-2">
        <h1 className="text-lg font-bold text-white leading-tight">RetailVision AI</h1>
        <p className="text-xs text-blue-300 mt-0.5">Analytics Platform</p>
      </div>

      <nav className="flex flex-col gap-1 flex-1">
        {NAV_ITEMS.map(item => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === '/'}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
                isActive
                  ? 'bg-blue-600 text-white font-semibold'
                  : 'text-blue-200 hover:bg-blue-900'
              }`
            }
          >
            <span>{item.icon}</span>
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="pt-4 border-t border-blue-900">
        <button
          onClick={handleLogout}
          className="w-full text-xs px-3 py-2 rounded-lg text-left text-blue-300 hover:bg-blue-800 transition flex items-center gap-2"
        >
          <span>🚪</span> Sign Out
        </button>
      </div>
    </aside>
  )
}
