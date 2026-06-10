import { useEffect } from 'react'

const APP = 'RetailVision AI'

export function usePageTitle(title) {
  useEffect(() => {
    document.title = title ? `${title} — ${APP}` : APP
    return () => { document.title = APP }
  }, [title])
}
