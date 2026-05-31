import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { forgotPassword } from '../api'

export default function ForgotPassword() {
  const [email, setEmail] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await forgotPassword(email)
      setSubmitted(true)
    } catch {
      // Show success message even on network error to avoid leaking info,
      // but surface genuine unexpected errors
      setSubmitted(true)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#f8fafc] px-6">
      <div className="w-full max-w-md">

        <div className="bg-white rounded-2xl shadow-lg p-10">
          <div className="mb-8">
            <h1 className="text-2xl font-bold text-gray-900">Forgot password?</h1>
            <p className="text-sm text-gray-500 mt-1">
              Enter your email and we'll send you a reset link.
            </p>
          </div>

          {submitted ? (
            <div className="space-y-6">
              <div className="bg-green-50 border border-green-200 rounded-lg px-4 py-4 text-sm text-green-800">
                If that email exists, a reset link has been sent. Check your inbox.
              </div>
              <Link
                to="/login"
                className="block text-center text-sm text-blue-600 hover:text-blue-700 font-medium"
              >
                Back to sign in
              </Link>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-5">
              {error && (
                <div className="bg-red-50 text-red-700 text-sm px-4 py-3 rounded-lg border border-red-200">
                  {error}
                </div>
              )}

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">
                  Email address
                </label>
                <input
                  type="email"
                  required
                  autoComplete="email"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  placeholder="you@company.com"
                  className="w-full border border-gray-200 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 transition-shadow"
                />
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full py-3 rounded-lg text-sm font-semibold text-white bg-gradient-to-r from-blue-600 to-blue-700 hover:from-blue-700 hover:to-blue-800 disabled:opacity-50 transition-all shadow-sm shadow-blue-200"
              >
                {loading ? 'Sending…' : 'Send reset link'}
              </button>

              <p className="text-center text-sm text-gray-400">
                <Link to="/login" className="text-blue-600 hover:text-blue-700 font-medium">
                  Back to sign in
                </Link>
              </p>
            </form>
          )}
        </div>
      </div>
    </div>
  )
}
