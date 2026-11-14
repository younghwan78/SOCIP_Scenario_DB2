import { useId, useState, type ReactNode } from 'react'

/** U-05: an explanation that is not hover-only. The trigger is a button (focus, Enter / Space toggles it,
 * Escape closes it) and the text is linked by ``aria-describedby``, so keyboard, touch and screen readers
 * reach it; a screen shared in a meeting can open it. Use it instead of ``title=`` for anything that
 * carries a reason or a number. */
export function Hint({ text, children, label = '설명' }: { text: ReactNode; children?: ReactNode; label?: string }) {
  const id = useId()
  const [open, setOpen] = useState(false)
  if (text == null || text === '' || (Array.isArray(text) && text.length === 0)) return <>{children}</>
  return <span className={`hint${open ? ' open' : ''}`} onMouseLeave={() => setOpen(false)}>
    {children}
    <button type="button" className="hint-trigger" aria-label={label} aria-describedby={id} aria-expanded={open}
      onClick={(e) => { e.stopPropagation(); setOpen((o) => !o) }} onKeyDown={(e) => { if (e.key === 'Escape') setOpen(false) }}
      onBlur={() => setOpen(false)}>ⓘ</button>
    <span role="tooltip" id={id} className="hint-pop">{text}</span>
  </span>
}
