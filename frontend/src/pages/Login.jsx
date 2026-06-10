import React, { useState } from 'react'
import { useNavigate, useLocation, Link } from 'react-router-dom'
import { Eye, EyeOff, Check } from 'lucide-react'
import { useAuth } from '../store'
import { login } from '../api'

const FEATURES = [
  'Real-time multi-camera tracking',
  'AI-powered insights and alerts',
  'Complete store analytics',
]

export default function Login() {
  const { dispatch } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const resetSuccess = location.state?.resetSuccess === true
  const [form, setForm] = useState({ email: '', password: '' })
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  function onChange(e) {
    setForm(f => ({ ...f, [e.target.name]: e.target.value }))
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const data = await login(form.email, form.password)
      const tokens = { access_token: data.access_token, refresh_token: data.refresh_token }
      const jwtPayload = JSON.parse(atob(data.access_token.split('.')[1]))
      const user = { user_id: jwtPayload.sub, account_type: data.account_type, is_super_admin: !!jwtPayload.is_super_admin }
      dispatch({ type: 'LOGIN', payload: { user, tokens } })
      if (data.redirect_slug) {
        navigate(`/store/${data.redirect_slug}/live`, { replace: true })
      } else if (data.account_type === 'owner') {
        navigate('/dashboard', { replace: true })
      } else {
        setError('Your account has been removed from the store. Contact the store owner.')
      }
    } catch (err) {
      const detail = err.response?.data?.detail
      setError(typeof detail === 'string' ? detail : detail?.error || 'Invalid credentials')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex">

      {/* ── Left panel (hidden on mobile) ──────────────────────────────────── */}
      <div
        className="hidden md:flex md:w-2/5 flex-col justify-between p-12 relative overflow-hidden"
        style={{ background: 'linear-gradient(160deg, #1a2744 0%, #0f1729 100%)' }}
      >
        {/* Dot-grid background pattern */}
        <div
          aria-hidden="true"
          className="absolute inset-0 pointer-events-none"
          style={{
            backgroundImage: 'radial-gradient(circle, rgba(255,255,255,0.07) 1px, transparent 1px)',
            backgroundSize: '28px 28px',
          }}
        />

        {/* Top: wordmark */}
        <div className="relative">
          <div className="flex items-center gap-2.5 mb-10">
            <div className="w-8 h-8 rounded-lg bg-blue-500 flex items-center justify-center shrink-0">
              <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                <circle cx="9" cy="9" r="3.5" fill="white" />
                <circle cx="9" cy="9" r="7" stroke="white" strokeWidth="1.5" strokeDasharray="2.5 2" />
              </svg>
            </div>
            <span className="text-white font-bold text-lg tracking-tight">RetailVision AI</span>
          </div>
        </div>

        {/* Middle: tagline + features */}
        <div className="relative space-y-8">
          <div>
            <h2 className="text-3xl font-bold text-white leading-snug">
              Intelligent retail<br />operations powered<br />by AI
            </h2>
            <p className="text-blue-300/70 text-sm mt-3 leading-relaxed max-w-xs">
              Monitor every corner of your store, predict issues before they happen, and act on real data.
            </p>
          </div>

          <ul className="space-y-3">
            {FEATURES.map(f => (
              <li key={f} className="flex items-center gap-3">
                <span className="w-5 h-5 rounded-full bg-blue-500/20 border border-blue-400/30 flex items-center justify-center shrink-0">
                  <Check size={11} className="text-blue-400" strokeWidth={3} />
                </span>
                <span className="text-blue-100/80 text-sm">{f}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* Bottom: subtle footer */}
        <p className="relative text-blue-400/40 text-xs">
          © {new Date().getFullYear()} RetailVision AI
        </p>
      </div>

      {/* ── Right panel ────────────────────────────────────────────────────── */}
      <div className="flex-1 flex items-center justify-center bg-[#f8fafc] px-6 py-12">
        <div className="w-full max-w-md">

          {/* Mobile-only wordmark */}
          <div className="md:hidden text-center mb-8">
            <span className="text-xl font-bold text-gray-900">RetailVision AI</span>
          </div>

          {/* Card */}
          <div className="bg-white rounded-2xl shadow-lg p-10">
            <div className="mb-8">
              <h1 className="text-2xl font-bold text-gray-900">Welcome back</h1>
              <p className="text-sm text-gray-500 mt-1">Sign in to your RetailVision AI account</p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-5">
              {resetSuccess && (
                <div className="bg-green-50 text-green-800 text-sm px-4 py-3 rounded-lg border border-green-200">
                  Password updated successfully. Sign in with your new password.
                </div>
              )}
              {error && (
                <div className="bg-red-50 text-red-700 text-sm px-4 py-3 rounded-lg border border-red-200">
                  {error}
                </div>
              )}

              {/* Email */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">Email address</label>
                <input
                  name="email"
                  type="email"
                  required
                  autoComplete="email"
                  value={form.email}
                  onChange={onChange}
                  placeholder="you@company.com"
                  className="w-full border border-gray-200 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 transition-shadow"
                />
              </div>

              {/* Password with show/hide */}
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label className="block text-sm font-medium text-gray-700">Password</label>
                  <Link to="/forgot-password" className="text-xs text-blue-600 hover:text-blue-700">
                    Forgot password?
                  </Link>
                </div>
                <div className="relative">
                  <input
                    name="password"
                    type={showPassword ? 'text' : 'password'}
                    required
                    autoComplete="current-password"
                    value={form.password}
                    onChange={onChange}
                    placeholder="••••••••"
                    className="w-full border border-gray-200 rounded-lg px-4 py-2.5 pr-11 text-sm focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 transition-shadow"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(v => !v)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 transition-colors"
                    tabIndex={-1}
                    aria-label={showPassword ? 'Hide password' : 'Show password'}
                  >
                    {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>

              {/* Submit */}
              <button
                type="submit"
                disabled={loading}
                className="w-full py-3 rounded-lg text-sm font-semibold text-white bg-gradient-to-r from-blue-600 to-blue-700 hover:from-blue-700 hover:to-blue-800 disabled:opacity-50 transition-all shadow-sm shadow-blue-200 mt-2"
              >
                {loading ? 'Signing in…' : 'Sign In'}
              </button>
            </form>

            <p className="text-center text-sm text-gray-400 mt-6">
              Don't have an account?{' '}
              <Link to="/register" className="text-blue-600 hover:text-blue-700 font-medium">
                Create one
              </Link>
            </p>
          </div>
        </div>
      </div>

    </div>
  )
}
