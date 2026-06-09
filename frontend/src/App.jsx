import React, { lazy, Suspense } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'

// DevE2E ("Main Vision Debug") ships in production but is admin-gated (A5).
// Lazy-loaded for bundle size; the backend dev routes are super-admin gated (A4).
const DevE2E = lazy(() => import('./pages/DevE2E'))
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
import Alerts from './pages/Alerts'
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
          <Route path="alerts" element={<Alerts />} />
          <Route path="agent" element={<AIAgent />} />
          <Route path="employees" element={<Employees />} />
          <Route path="shifts" element={<Shifts />} />
          <Route path="members" element={<Members />} />
          <Route path="audit" element={<Audit />} />
          <Route path="settings" element={<PrivateRoute adminOnly><Settings /></PrivateRoute>} />
          {/* End-to-end IEP1→IEP2→IEP3 tester. Ships in prod, super-admin only. */}
          <Route
            path="dev/e2e"
            element={
              <PrivateRoute adminOnly>
                <Suspense fallback={null}><DevE2E /></Suspense>
              </PrivateRoute>
            }
          />
        </Route>

        {/* Store invite acceptance */}
        <Route path="/store/:slug/accept-invite" element={<AcceptInvite />} />

        {/* Default */}
        <Route path="/" element={<Navigate to="/login" replace />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </AuthProvider>
  )
}
