import React from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '../store'

export default function PrivateRoute({ children }) {
  const { state } = useAuth()
  if (!state.ready) return null // wait for localStorage check
  if (!state.tokens) return <Navigate to="/login" replace />
  return children
}
