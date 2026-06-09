import { useEffect, useState } from 'react'

// Generic fetch hook: runs `fetcher` whenever `deps` change, tracks loading/error,
// and ignores stale responses. Widgets stay dumb — fetching lives here.
export function useAnalyticsQuery(fetcher, deps) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    Promise.resolve()
      .then(fetcher)
      .then((d) => { if (!cancelled) setData(d) })
      .catch((e) => { if (!cancelled) { setError(e); setData(null) } })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return { data, loading, error }
}
