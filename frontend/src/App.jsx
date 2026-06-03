import React, { lazy, Suspense } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'

// Loaded only in dev builds — dynamic import is dead code in `vite build`.
const VisionDebugConsole = import.meta.env.DEV
  ? lazy(() => import('./pages/VisionDebugConsole'))
  : null
import { AuthProvider } from './store'
import PrivateRoute from './components/PrivateRoute'
import StoreLayout from './components/StoreLayout'

import Login from './pages/Login'
import Register from './pages/Register'
import AcceptInvite from './pages/AcceptInvite'
import ForgotPassword from './pages/ForgotPassword'
import ResetPassword from './pages/ResetPassword'
import OwnerDashboard from './pages/OwnerDashboard'

import StoreConfig from './pages/StoreConfig'
import StoreConfigEdit from './pages/StoreConfigEdit'
import LiveMonitoring from './pages/LiveMonitoring'
import Analytics from './pages/Analytics'
import Employees from './pages/Employees'
import Shifts from './pages/Shifts'
import Members from './pages/Members'
import Audit from './pages/Audit'
import AIAgent from './pages/AIAgent'
import Settings from './pages/Settings'
import LiveView from './pages/LiveView'

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        {/* Public */}
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/accept-invite" element={<AcceptInvite />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />

        {/* Owner dashboard */}
        <Route path="/dashboard" element={<PrivateRoute><OwnerDashboard /></PrivateRoute>} />

        {/* Store-scoped */}
        <Route path="/store/:slug" element={<PrivateRoute><StoreLayout /></PrivateRoute>}>
          <Route index element={<Navigate to="live" replace />} />
          <Route path="dashboard" element={<Navigate to="live" replace />} />
          <Route path="config" element={<StoreConfig />} />
          <Route path="config/edit" element={<StoreConfigEdit />} />
          <Route path="live" element={<LiveMonitoring />} />
          <Route path="live-view" element={<LiveView />} />
          <Route path="analytics" element={<Analytics />} />
          <Route path="agent" element={<AIAgent />} />
          <Route path="employees" element={<Employees />} />
          <Route path="shifts" element={<Shifts />} />
          <Route path="members" element={<Members />} />
          <Route path="audit" element={<Audit />} />
          <Route path="settings" element={<Settings />} />
        </Route>

        {/* Store invite acceptance */}
        <Route path="/store/:slug/accept-invite" element={<AcceptInvite />} />

        {/* Dev-only: Vision Debug Console. Remove route + VisionDebugConsole.jsx before shipping. */}
        {import.meta.env.DEV && VisionDebugConsole && (
          <Route
            path="/dev/vision"
            element={<Suspense fallback={null}><VisionDebugConsole /></Suspense>}
          />
        )}

        {/* Default */}
        <Route path="/" element={<Navigate to="/login" replace />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </AuthProvider>
  )
}
