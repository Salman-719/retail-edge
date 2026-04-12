import React from 'react'
import { useNavigate, useLocation } from 'react-router-dom'

export default function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const from = location.state?.from?.pathname ?? '/'

  const handleEnter = () => {
    sessionStorage.setItem('rv_logged_in', '1')
    navigate(from, { replace: true })
  }

  return (
    <div
      className="min-h-screen flex flex-col items-center justify-center"
      style={{ background: 'linear-gradient(135deg, #0f2540 0%, #1B3A5C 60%, #2E75B6 100%)' }}
    >
      <div className="text-center px-8 py-12 rounded-2xl bg-white/10 backdrop-blur-sm shadow-2xl max-w-md w-full mx-4">
        <div className="text-6xl mb-6">🏪</div>
        <h1 className="text-4xl font-bold text-white mb-2">RetailVision AI</h1>
        <p className="text-blue-200 text-lg mb-2">Intelligent Retail Analytics</p>
        <p className="text-blue-300 text-sm mb-10">
          Multi-camera people tracking · Zone analytics · AI insights
        </p>

        <button
          onClick={handleEnter}
          className="w-full py-4 rounded-xl font-semibold text-lg transition-all duration-200 shadow-lg hover:shadow-xl hover:scale-105"
          style={{ background: '#2E75B6', color: 'white' }}
        >
          Enter Platform →
        </button>

        <p className="text-blue-400 text-xs mt-6">
          EECE503N / EECE798N · AI Engineering Final Project
        </p>
      </div>
    </div>
  )
}
