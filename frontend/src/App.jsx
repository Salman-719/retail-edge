import React from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './store'
import PrivateRoute from './components/PrivateRoute'
import StoreLayout from './components/StoreLayout'

import Login from './pages/Login'
import Register from './pages/Register'
import AcceptInvite from './pages/AcceptInvite'
import OwnerDashboard from './pages/OwnerDashboard'

import StoreConfig from './pages/StoreConfig'
import LiveMonitoring from './pages/LiveMonitoring'
import Analytics from './pages/Analytics'
import Employees from './pages/Employees'
import Members from './pages/Members'
import Audit from './pages/Audit'
import Settings from './pages/Settings'

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        {/* Public */}
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/accept-invite" element={<AcceptInvite />} />

        {/* Owner dashboard */}
        <Route path="/dashboard" element={<PrivateRoute><OwnerDashboard /></PrivateRoute>} />

        {/* Store-scoped */}
        <Route path="/store/:slug" element={<PrivateRoute><StoreLayout /></PrivateRoute>}>
          <Route index element={<Navigate to="live" replace />} />
          <Route path="dashboard" element={<Navigate to="live" replace />} />
          <Route path="config" element={<StoreConfig />} />
          <Route path="live" element={<LiveMonitoring />} />
          <Route path="analytics" element={<Analytics />} />
          <Route path="employees" element={<Employees />} />
          <Route path="members" element={<Members />} />
          <Route path="audit" element={<Audit />} />
          <Route path="settings" element={<Settings />} />
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
