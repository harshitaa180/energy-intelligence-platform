/** Small data-fetching hooks. No client library needed for a read-mostly dashboard. */

import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError } from '../services/api'

export interface AsyncState<T> {
  data: T | null
  loading: boolean
  error: string | null
  reload: () => void
}

/**
 * Run an async loader whenever `deps` change.
 *
 * Late responses from a superseded request are discarded, so switching site or date
 * quickly cannot leave stale data on screen.
 */
export function useAsync<T>(loader: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [nonce, setNonce] = useState(0)
  const requestId = useRef(0)

  useEffect(() => {
    const id = ++requestId.current
    let cancelled = false
    setLoading(true)
    setError(null)

    loader()
      .then((result) => {
        if (cancelled || id !== requestId.current) return
        setData(result)
      })
      .catch((cause: unknown) => {
        if (cancelled || id !== requestId.current) return
        setError(cause instanceof ApiError ? cause.message : 'Unexpected error')
      })
      .finally(() => {
        if (cancelled || id !== requestId.current) return
        setLoading(false)
      })

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce])

  const reload = useCallback(() => setNonce((value) => value + 1), [])

  return { data, loading, error, reload }
}

/** Persist a small value (the selected site, say) across reloads. */
export function useLocalStorage<T>(key: string, initial: T): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const stored = window.localStorage.getItem(key)
      return stored ? (JSON.parse(stored) as T) : initial
    } catch {
      return initial
    }
  })

  const update = useCallback(
    (next: T) => {
      setValue(next)
      try {
        window.localStorage.setItem(key, JSON.stringify(next))
      } catch {
        /* private mode or blocked storage: keep it in memory only */
      }
    },
    [key],
  )

  return [value, update]
}
