import React, { useEffect } from 'react'
import { Outlet, useParams, useNavigate, useLocation } from 'react-router-dom'
import Sidebar from './Sidebar'
import { useAuth } from '../store'
import { getMe } from '../api'

export default function StoreLayout() {
  const { slug } = useParams()
  const { dispatch } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  useEffect(() => {
    if (!slug) return
    getMe(slug)
      .then(data => dispatch({ type: 'SET_MEMBER', payload: data }))
      .catch(err => {
        if (err.response?.status === 403 || err.response?.status === 401) {
          navigate('/login', { replace: true })
        }
      })
  }, [slug])

  return (
    <div className="flex min-h-screen bg-gray-50">
      <Sidebar />
      <main className="flex-1 flex flex-col overflow-hidden">
        {/* key on pathname so every route change restarts the fade */}
        <div key={location.pathname} className="page-enter flex-1 flex flex-col overflow-hidden min-h-0">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
