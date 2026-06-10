import React from 'react'
import { Navigate, useParams } from 'react-router-dom'
import { useAuth } from '../store'

// `adminOnly` is a UX guard only — real enforcement is the backend (A1/A2/A4).
export default function PrivateRoute({ children, adminOnly = false }) {
  const { state } = useAuth()
  const { slug } = useParams()
  if (!state.ready) return null // wait for localStorage check
  if (!state.tokens) return <Navigate to="/login" replace />
  if (adminOnly && !state.user?.is_super_admin) {
    return <Navigate to={slug ? `/store/${slug}/live` : '/dashboard'} replace />
  }
  return children
}
