import { useEffect, useState } from 'react'

export function useCatalogSearch() {
  const [input, setInput] = useState('')
  const [search, setSearch] = useState('')
  useEffect(() => {
    const timer = setTimeout(() => setSearch(input), 250)
    return () => clearTimeout(timer)
  }, [input])
  return { input, setInput, search }
}
