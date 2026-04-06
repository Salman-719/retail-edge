import React from 'react'
import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import LoginPage from './pages/LoginPage'
import StoreOnboarding from './pages/StoreOnboarding'
import LiveMonitoring from './pages/LiveMonitoring'
import Analytics from './pages/Analytics'
import AIAgent from './pages/AIAgent'
import Sidebar from './components/Sidebar'

function useIsLoggedIn() {
  return sessionStorage.getItem('rv_logged_in') === '1'
}

function RequireAuth({ children }) {
  const loggedIn = useIsLoggedIn()
  const location = useLocation()
  if (!loggedIn) return <Navigate to="/login" state={{ from: location }} replace />
  return children
}

function AppLayout({ children }) {
  return (
    <div className="flex min-h-screen bg-gray-50">
      <Sidebar />
      <main className="flex-1 flex flex-col overflow-hidden">
        {children}
      </main>
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />

      <Route path="/" element={
        <RequireAuth>
          <AppLayout><StoreOnboarding /></AppLayout>
        </RequireAuth>
      } />

      <Route path="/live-monitoring" element={
        <RequireAuth>
          <AppLayout><LiveMonitoring /></AppLayout>
        </RequireAuth>
      } />

      <Route path="/analytics" element={
        <RequireAuth>
          <AppLayout><Analytics /></AppLayout>
        </RequireAuth>
      } />

      <Route path="/ai-agent" element={
        <RequireAuth>
          <AppLayout><AIAgent /></AppLayout>
        </RequireAuth>
      } />

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
