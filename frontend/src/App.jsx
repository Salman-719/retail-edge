import React from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import StoreConfig from './pages/StoreConfig'
import LiveMonitoring from './pages/LiveMonitoring'
import Analytics from './pages/Analytics'
import AIAgent from './pages/AIAgent'
import Sidebar from './components/Sidebar'

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
      <Route path="/live-monitoring" element={<AppLayout><LiveMonitoring /></AppLayout>} />
      <Route path="/analytics" element={<AppLayout><Analytics /></AppLayout>} />
      <Route path="/ai-agent" element={<AppLayout><AIAgent /></AppLayout>} />
      <Route path="/config" element={<AppLayout><StoreConfig /></AppLayout>} />
      <Route path="*" element={<Navigate to="/config" replace />} />
    </Routes>
  )
}
