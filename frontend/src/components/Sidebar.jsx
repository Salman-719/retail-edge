import React from 'react'
import { NavLink, useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../store'
import { logout } from '../api'

const NAV = [
  { label: 'Store Config', path: 'config' },
  { label: 'Live Monitoring', path: 'live' },
  { label: 'Analytics', path: 'analytics' },
  { label: 'AI Assistant', path: 'agent' },
  { label: 'Employees', path: 'employees' },
  { label: 'Shifts', path: 'shifts' },
  { label: 'Members', path: 'members' },
  { label: 'Audit Log', path: 'audit' },
  { label: 'Settings', path: 'settings' },
]

export default function Sidebar() {
  const { slug } = useParams()
  const { state, dispatch } = useAuth()
  const navigate = useNavigate()

  async function handleLogout() {
    try {
      if (state.tokens?.refresh_token) await logout(state.tokens.refresh_token)
    } finally {
      dispatch({ type: 'LOGOUT' })
      navigate('/login')
    }
  }

  return (
    <aside className="w-56 min-h-screen flex flex-col shrink-0" style={{ backgroundColor: '#1B3A5C' }}>
      <div className="px-4 py-5 border-b border-blue-900">
        <h1 className="text-white font-bold text-sm leading-tight">RetailVision AI</h1>
        {state.currentStore && (
          <p className="text-blue-300 text-xs mt-0.5 truncate">{state.currentStore.name}</p>
        )}
      </div>

      <nav className="flex-1 py-3 px-2 flex flex-col gap-0.5">
        {NAV.map(({ label, path }) => (
          <NavLink
            key={path}
            to={`/store/${slug}/${path}`}
            className={({ isActive }) =>
              `block px-3 py-2 rounded-lg text-sm transition-colors ${
                isActive
                  ? 'bg-blue-600 text-white font-semibold'
                  : 'text-blue-200 hover:bg-blue-900 hover:text-white'
              }`
            }
          >
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="px-2 py-3 border-t border-blue-900">
        <button
          onClick={handleLogout}
          className="w-full text-left px-3 py-2 rounded-lg text-sm text-blue-300 hover:bg-blue-800 hover:text-white transition-colors"
        >
          Sign Out
        </button>
      </div>
    </aside>
  )
}
