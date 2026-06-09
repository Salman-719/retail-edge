import React, { useEffect, useState } from 'react'
import { NavLink, useNavigate, useParams } from 'react-router-dom'
import {
  Store, Radio, BarChart2, Bot, Users, Calendar,
  UserCheck, ClipboardList, SlidersHorizontal, ChevronLeft, Video, Bug, Bell,
} from 'lucide-react'
import { useAuth } from '../store'
import { logout, getActiveAlerts, getActiveVersion } from '../api'

const NAV_GROUPS = [
  {
    label: null,
    items: [
      { label: 'Live Monitoring', path: 'live',      Icon: Radio },
      { label: 'Live View',       path: 'live-view', Icon: Video },
      { label: 'Analytics',       path: 'analytics', Icon: BarChart2 },
      { label: 'Alerts',          path: 'alerts',    Icon: Bell },
      { label: 'AI Assistant',    path: 'agent',     Icon: Bot },
    ],
  },
  {
    label: 'Management',
    items: [
      { label: 'Store Config', path: 'config',    Icon: Store },
      { label: 'Employees',    path: 'employees', Icon: Users },
      { label: 'Shifts',       path: 'shifts',    Icon: Calendar },
      { label: 'Members',      path: 'members',   Icon: UserCheck },
    ],
  },
  {
    label: 'System',
    items: [
      { label: 'Audit Log', path: 'audit',    Icon: ClipboardList },
      { label: 'Settings',  path: 'settings', Icon: SlidersHorizontal },
    ],
  },
]

export default function Sidebar() {
  const { slug } = useParams()
  const { state, dispatch } = useAuth()
  const navigate = useNavigate()
  const [alertCount, setAlertCount] = useState(0)
  const [hasUnmappedFloorPlan, setHasUnmappedFloorPlan] = useState(false)

  useEffect(() => {
    if (!slug) return
    getActiveAlerts(slug)
      .then(data => setAlertCount(Array.isArray(data) ? data.length : (data?.count ?? 0)))
      .catch(() => {})
    getActiveVersion(slug)
      .then(v => setHasUnmappedFloorPlan(!v?.floor_plan?.image_uploaded))
      .catch(() => {})
  }, [slug])

  async function handleLogout() {
    try {
      if (state.tokens?.refresh_token) await logout(state.tokens.refresh_token)
    } finally {
      dispatch({ type: 'LOGOUT' })
      navigate('/login')
    }
  }

  return (
    <aside
      className="w-56 min-h-screen flex flex-col shrink-0"
      style={{ background: 'linear-gradient(180deg, #1a2744 0%, #0f1729 100%)' }}
    >
      {/* Logo */}
      <div className="px-4 py-5 border-b border-white/10">
        <h1 className="text-white font-bold text-sm leading-tight tracking-wide">RetailVision AI</h1>
        {state.currentStore && (
          <p className="text-blue-300/70 text-xs mt-1 truncate">{state.currentStore.name}</p>
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 py-3 px-2 flex flex-col">
        {NAV_GROUPS.map((group, gi) => (
          <div key={gi}>
            {group.label && (
              <p className="text-[10px] font-semibold uppercase tracking-widest text-gray-500 px-4 pt-5 pb-1">
                {group.label}
              </p>
            )}
            <div className="flex flex-col gap-0.5">
              {group.items.map(({ label, path, Icon }) => (
                <NavLink
                  key={path}
                  to={`/store/${slug}/${path}`}
                  className={({ isActive }) =>
                    `nav-item flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-all duration-150 border-l-2 pl-[10px] ${
                      isActive
                        ? 'bg-blue-600/20 text-white font-semibold border-blue-500 active'
                        : 'text-blue-200/80 hover:bg-blue-500/10 hover:text-white border-transparent'
                    }`
                  }
                >
                  <Icon size={15} className="nav-icon shrink-0" />
                  <span className="flex-1 truncate">{label}</span>
                  {(path === 'live' || path === 'alerts') && alertCount > 0 && (
                    <span className="bg-red-500 text-white text-[10px] font-bold px-1.5 py-0.5 rounded-full min-w-[18px] text-center leading-none shrink-0">
                      {alertCount}
                    </span>
                  )}
                  {path === 'config' && hasUnmappedFloorPlan && (
                    <span className="w-2 h-2 rounded-full bg-amber-400 shrink-0" />
                  )}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </nav>

      {/* Dev-only nav — remove with VisionDebugConsole.jsx before shipping */}
      {import.meta.env.DEV && (
        <div className="px-2 pb-1">
          <p className="text-[10px] font-semibold uppercase tracking-widest text-amber-500/60 px-4 pt-4 pb-1">
            Dev
          </p>
          <NavLink
            to={`/store/${slug}/dev/vision`}
            className={({ isActive }) =>
              `nav-item flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-all duration-150 border-l-2 pl-[10px] ${
                isActive
                  ? 'bg-amber-600/20 text-amber-300 font-semibold border-amber-500 active'
                  : 'text-amber-400/60 hover:bg-amber-500/10 hover:text-amber-300 border-transparent'
              }`
            }
          >
            <Bug size={15} className="nav-icon shrink-0" />
            <span className="flex-1 truncate">Vision Debug</span>
          </NavLink>
          <NavLink
            to={`/store/${slug}/dev/e2e`}
            className={({ isActive }) =>
              `nav-item flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-all duration-150 border-l-2 pl-[10px] ${
                isActive
                  ? 'bg-amber-600/20 text-amber-300 font-semibold border-amber-500 active'
                  : 'text-amber-400/60 hover:bg-amber-500/10 hover:text-amber-300 border-transparent'
              }`
            }
          >
            <Video size={15} className="nav-icon shrink-0" />
            <span className="flex-1 truncate">Main Vision Debug</span>
          </NavLink>
        </div>
      )}

      {/* Bottom actions */}
      <div className="px-2 py-3 border-t border-white/10 flex flex-col gap-0.5">
        {state.user?.account_type === 'owner' && (
          <button
            onClick={() => navigate('/dashboard')}
            className="w-full text-left px-3 py-2 rounded-lg text-sm text-blue-300/70 hover:bg-blue-500/10 hover:text-white transition-colors flex items-center gap-2"
          >
            <ChevronLeft size={15} className="shrink-0" />
            All Stores
          </button>
        )}
        <button
          onClick={handleLogout}
          className="w-full text-left px-3 py-2 rounded-lg text-sm text-blue-300/70 hover:bg-blue-500/10 hover:text-white transition-colors"
        >
          Sign Out
        </button>
      </div>
    </aside>
  )
}
