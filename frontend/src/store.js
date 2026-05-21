/**
 * Global auth state via React Context + useReducer.
 * Tokens are persisted to localStorage via api.js saveTokens/clearTokens.
 */
import React, { createContext, useContext, useReducer, useEffect } from 'react'
import { getTokens, saveTokens, clearTokens } from './api'

const initialState = {
  user: null,          // { user_id, account_type }
  tokens: null,        // { access_token, refresh_token }
  currentStore: null,  // { id, name, slug, status }
  currentMember: null, // { role, is_owner, permissions } — null for owners before fetch
  ready: false,        // true once localStorage has been checked
}

function reducer(state, action) {
  switch (action.type) {
    case 'INIT':
      return { ...state, ...action.payload, ready: true }
    case 'LOGIN':
      saveTokens(action.payload.tokens)
      return { ...state, user: action.payload.user, tokens: action.payload.tokens, ready: true }
    case 'SET_STORE':
      return { ...state, currentStore: action.payload }
    case 'SET_MEMBER':
      return { ...state, currentMember: action.payload }
    case 'LOGOUT':
      clearTokens()
      return { ...initialState, ready: true }
    default:
      return state
  }
}

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [state, dispatch] = useReducer(reducer, initialState)

  useEffect(() => {
    const tokens = getTokens()
    if (tokens) {
      try {
        const payload = JSON.parse(atob(tokens.access_token.split('.')[1]))
        dispatch({
          type: 'INIT',
          payload: { tokens, user: { user_id: payload.sub, account_type: payload.account_type } },
        })
      } catch {
        dispatch({ type: 'INIT', payload: {} })
      }
    } else {
      dispatch({ type: 'INIT', payload: {} })
    }
  }, [])

  return React.createElement(AuthContext.Provider, { value: { state, dispatch } }, children)
}

export function useAuth() {
  return useContext(AuthContext)
}
