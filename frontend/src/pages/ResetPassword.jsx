import React, { useState } from 'react'
import { useNavigate, useSearchParams, Link } from 'react-router-dom'
import { Eye, EyeOff } from 'lucide-react'
import { resetPassword } from '../api'

export default function ResetPassword() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') || ''
  const navigate = useNavigate()

  const [form, setForm] = useState({ newPassword: '', confirmPassword: '' })
  const [showNew, setShowNew] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  if (!token) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#f8fafc] px-6">
        <div className="bg-white rounded-2xl shadow-lg p-10 w-full max-w-md text-center">
          <p className="text-red-600 font-medium mb-4">Invalid or missing reset token.</p>
          <Link to="/forgot-password" className="text-sm text-blue-600 hover:text-blue-700 font-medium">
            Request a new reset link
          </Link>
        </div>
      </div>
    )
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    if (form.newPassword.length < 8) {
      setError('Password must be at least 8 characters')
      return
    }
    if (form.newPassword !== form.confirmPassword) {
      setError('Passwords do not match')
      return
    }
    setLoading(true)
    try {
      await resetPassword(token, form.newPassword)
      navigate('/login', { state: { resetSuccess: true }, replace: true })
    } catch (err) {
      const detail = err.response?.data?.detail
      setError(typeof detail === 'string' ? detail : detail?.error || 'This reset link is invalid or has expired.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#f8fafc] px-6">
      <div className="w-full max-w-md">

        <div className="bg-white rounded-2xl shadow-lg p-10">
          <div className="mb-8">
            <h1 className="text-2xl font-bold text-gray-900">Set new password</h1>
            <p className="text-sm text-gray-500 mt-1">
              Choose a strong password for your account.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            {error && (
              <div className="bg-red-50 text-red-700 text-sm px-4 py-3 rounded-lg border border-red-200">
                {error}
              </div>
            )}

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">New password</label>
              <div className="relative">
                <input
                  type={showNew ? 'text' : 'password'}
                  required
                  value={form.newPassword}
                  onChange={e => setForm(f => ({ ...f, newPassword: e.target.value }))}
                  placeholder="••••••••"
                  className="w-full border border-gray-200 rounded-lg px-4 py-2.5 pr-11 text-sm focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 transition-shadow"
                />
                <button
                  type="button"
                  onClick={() => setShowNew(v => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 transition-colors"
                  tabIndex={-1}
                >
                  {showNew ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">Confirm password</label>
              <div className="relative">
                <input
                  type={showConfirm ? 'text' : 'password'}
                  required
                  value={form.confirmPassword}
                  onChange={e => setForm(f => ({ ...f, confirmPassword: e.target.value }))}
                  placeholder="••••••••"
                  className="w-full border border-gray-200 rounded-lg px-4 py-2.5 pr-11 text-sm focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 transition-shadow"
                />
                <button
                  type="button"
                  onClick={() => setShowConfirm(v => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 transition-colors"
                  tabIndex={-1}
                >
                  {showConfirm ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 rounded-lg text-sm font-semibold text-white bg-gradient-to-r from-blue-600 to-blue-700 hover:from-blue-700 hover:to-blue-800 disabled:opacity-50 transition-all shadow-sm shadow-blue-200 mt-2"
            >
              {loading ? 'Saving…' : 'Set new password'}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
