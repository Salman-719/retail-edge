import React, { useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useAuth } from '../store'
import { acceptInvite } from '../api'

export default function AcceptInvite() {
  const { dispatch } = useAuth()
  const navigate = useNavigate()
  const { slug: slugFromUrl } = useParams()
  const [searchParams] = useSearchParams()

  const tokenFromUrl = searchParams.get('token') || ''

  const [form, setForm] = useState({
    slug: slugFromUrl || '',
    token: tokenFromUrl,
    name: '',
    password: '',
  })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  function onChange(e) {
    setForm(f => ({ ...f, [e.target.name]: e.target.value }))
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    if (form.password.length < 8) {
      setError('Password must be at least 8 characters')
      return
    }
    if (!form.slug || !form.token) {
      setError('Store code and invitation token are required')
      return
    }
    setLoading(true)
    try {
      const data = await acceptInvite(form.slug, form.token, form.name, form.password)
      const tokens = { access_token: data.access_token, refresh_token: data.refresh_token }
      const jwtPayload = JSON.parse(atob(data.access_token.split('.')[1]))
      const user = { user_id: jwtPayload.sub, account_type: jwtPayload.account_type }
      dispatch({ type: 'LOGIN', payload: { user, tokens } })
      navigate(`/store/${form.slug}/live`, { replace: true })
    } catch (err) {
      const detail = err.response?.data?.detail
      setError(typeof detail === 'string' ? detail : detail?.error || 'Invitation acceptance failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-gray-900">RetailVision AI</h1>
          <p className="text-gray-500 text-sm mt-1">Accept your store invitation</p>
        </div>

        <form onSubmit={handleSubmit} className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 space-y-4">
          {error && (
            <div className="bg-red-50 text-red-700 text-sm px-3 py-2 rounded-lg border border-red-200">
              {error}
            </div>
          )}

          {!slugFromUrl && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Store Code</label>
              <input
                name="slug"
                type="text"
                required
                placeholder="e.g. my-store"
                value={form.slug}
                onChange={onChange}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
          )}

          {!tokenFromUrl && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Invitation Token</label>
              <input
                name="token"
                type="text"
                required
                placeholder="Paste your invitation token"
                value={form.token}
                onChange={onChange}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Your Name</label>
            <input
              name="name"
              type="text"
              required
              autoComplete="name"
              value={form.name}
              onChange={onChange}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Create Password</label>
            <input
              name="password"
              type="password"
              required
              autoComplete="new-password"
              value={form.password}
              onChange={onChange}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
            <p className="text-xs text-gray-400 mt-1">Minimum 8 characters</p>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2 px-4 rounded-lg text-sm font-semibold text-white transition-colors disabled:opacity-50"
            style={{ backgroundColor: '#1B3A5C' }}
          >
            {loading ? 'Joining store…' : 'Join Store'}
          </button>
        </form>
      </div>
    </div>
  )
}
