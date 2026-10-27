import React, { useEffect, useRef, useState } from 'react'

import { listNotifications, markNotificationsRead } from '../services/api'
import type { AppNotification } from '../services/types'
import { relativeTime } from '../utils/ui'

const POLL_MS = 30_000

export default function NotificationBell() {
  const [items, setItems] = useState<AppNotification[]>([])
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)

  async function load(): Promise<void> {
    try {
      setItems(await listNotifications())
    } catch {
      // Non-critical; try again on the next poll.
    }
  }

  useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(), POLL_MS)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  const unread = items.filter((item) => !item.read_at).length

  async function markAll(): Promise<void> {
    await markNotificationsRead().catch(() => undefined)
    await load()
  }

  return (
    <div className="bell" ref={box}>
      <button
        type="button"
        className="button ghost bell-button"
        aria-label={`Notifications (${unread} unread)`}
        onClick={() => setOpen((value) => !value)}
      >
        <span aria-hidden="true">🔔</span>
        {unread > 0 && <span className="bell-count">{unread > 99 ? '99+' : unread}</span>}
      </button>
      {open && (
        <div className="bell-panel card" role="dialog" aria-label="Notifications">
          <div className="page-head">
            <strong>Notifications</strong>
            {unread > 0 && (
              <button type="button" className="link-button" onClick={() => void markAll()}>
                Mark all read
              </button>
            )}
          </div>
          {items.length === 0 && <div className="muted">Nothing yet.</div>}
          <ul className="bell-list">
            {items.map((item) => (
              <li key={item.id} className={item.read_at ? '' : 'unread'}>
                <div>{item.message}</div>
                <div className="muted small">{relativeTime(item.created_at)}</div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
