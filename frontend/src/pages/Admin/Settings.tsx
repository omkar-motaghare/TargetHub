import React, { useEffect, useState } from 'react'

import { getPolicy, getWebhooks, saveWebhooks, testWebhook, updatePolicy } from '../../services/api'
import type { ReservationPolicy, Webhook } from '../../services/types'
import { errorMessage } from '../../utils/ui'

const POLICY_FIELDS: { key: keyof ReservationPolicy; label: string; help: string; min: number }[] = [
  { key: 'max_duration_minutes', label: 'Max reservation length (min)', help: 'Admins are exempt', min: 5 },
  { key: 'default_duration_minutes', label: 'Default length (min)', help: 'Pre-selected in the reserve dialog', min: 5 },
  { key: 'max_advance_days', label: 'Book at most N days ahead', help: '0 = only now', min: 0 },
  { key: 'max_active_reservations_per_user', label: 'Active reservations per user', help: '0 = unlimited', min: 0 },
  { key: 'expiry_warning_minutes', label: '“Ending soon” warning (min)', help: '0 = off', min: 0 },
  { key: 'waitlist_entry_ttl_hours', label: 'Waitlist entries expire after (h)', help: '', min: 1 },
  { key: 'transcript_retention_days', label: 'Keep console logs (days)', help: '', min: 1 },
  { key: 'audit_retention_days', label: 'Keep audit log (days)', help: '', min: 7 },
]

const FORMATS: Webhook['format'][] = ['slack', 'teams', 'generic']

export default function AdminSettings() {
  const [policy, setPolicy] = useState<ReservationPolicy | null>(null)
  const [hooks, setHooks] = useState<Webhook[]>([])
  const [events, setEvents] = useState<string[]>([])
  const [message, setMessage] = useState<{ kind: 'error' | 'info'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    getPolicy().then(setPolicy).catch((error) => setMessage({ kind: 'error', text: errorMessage(error) }))
    getWebhooks()
      .then((result) => {
        setHooks(result.webhooks)
        setEvents(result.events)
      })
      .catch((error) => setMessage({ kind: 'error', text: errorMessage(error) }))
  }, [])

  async function act(work: () => Promise<unknown>, success: string): Promise<void> {
    setBusy(true)
    setMessage(null)
    try {
      await work()
      setMessage({ kind: 'info', text: success })
    } catch (error) {
      setMessage({ kind: 'error', text: errorMessage(error) })
    } finally {
      setBusy(false)
    }
  }

  const patchHook = (index: number, patch: Partial<Webhook>) =>
    setHooks((current) => current.map((hook, i) => (i === index ? { ...hook, ...patch } : hook)))

  return (
    <div className="grid" style={{ gap: '1rem' }}>
      {message && <div className={`feedback ${message.kind}`} role={message.kind === 'error' ? 'alert' : 'status'}>{message.text}</div>}

      <section className="card">
        <h3 style={{ marginTop: 0 }}>Reservation policy</h3>
        {policy && (
          <form onSubmit={(event) => { event.preventDefault(); void act(async () => setPolicy(await updatePolicy(policy)), 'Policy saved.') }}>
            <div className="grid four">
              {POLICY_FIELDS.map((field) => (
                <label key={field.key}>
                  <span className="muted">{field.label}</span>
                  <input className="input" type="number" min={field.min} value={Number(policy[field.key])}
                    onChange={(e) => setPolicy({ ...policy, [field.key]: Number(e.target.value) })} />
                  {field.help && <span className="muted small">{field.help}</span>}
                </label>
              ))}
            </div>
            <label className="inline" style={{ marginTop: '0.6rem' }}>
              <input type="checkbox" checked={policy.allow_extend_when_waitlisted}
                onChange={(e) => setPolicy({ ...policy, allow_extend_when_waitlisted: e.target.checked })} />
              Allow extending a reservation while others are waiting for that target
            </label>
            <div style={{ marginTop: '0.8rem' }}>
              <button className="button" type="submit" disabled={busy}>Save policy</button>
            </div>
          </form>
        )}
      </section>

      <section className="card">
        <div className="page-head">
          <h3 style={{ margin: 0 }}>Notifications (webhooks)</h3>
          <button className="button ghost" type="button"
            onClick={() => setHooks([...hooks, { name: '', url: '', format: 'slack', events: [...events], enabled: true }])}>
            + Add webhook
          </button>
        </div>
        <p className="muted">
          Post lab events to Slack or Microsoft Teams (incoming webhook URL) or any HTTP endpoint (generic JSON, optionally
          signed with an HMAC secret in <code>X-TargetHub-Signature</code>).
        </p>
        {hooks.length === 0 && <p className="muted">No webhooks configured.</p>}
        <div className="list">
          {hooks.map((hook, index) => (
            <div key={hook.id || index} className="list-item stacked">
              <div className="grid four">
                <label><span className="muted">Name</span>
                  <input className="input" value={hook.name} onChange={(e) => patchHook(index, { name: e.target.value })} /></label>
                <label className="span2"><span className="muted">URL</span>
                  <input className="input" value={hook.url} placeholder="https://hooks.slack.com/services/…" onChange={(e) => patchHook(index, { url: e.target.value })} /></label>
                <label><span className="muted">Format</span>
                  <select className="select" value={hook.format} onChange={(e) => patchHook(index, { format: e.target.value as Webhook['format'] })}>
                    {FORMATS.map((format) => <option key={format} value={format}>{format}</option>)}
                  </select></label>
                {hook.format === 'generic' && (
                  <label><span className="muted">HMAC secret (optional)</span>
                    <input className="input" type="password" value={hook.secret || ''} placeholder={hook.secret === '********' ? 'unchanged' : ''}
                      onChange={(e) => patchHook(index, { secret: e.target.value || null })} /></label>
                )}
                <label className="inline"><input type="checkbox" checked={hook.enabled} onChange={(e) => patchHook(index, { enabled: e.target.checked })} /> Enabled</label>
              </div>
              <div className="chip-row">
                {events.map((event) => (
                  <label key={event} className="chip">
                    <input type="checkbox" checked={hook.events.includes(event)}
                      onChange={(e) => patchHook(index, { events: e.target.checked ? [...hook.events, event] : hook.events.filter((item) => item !== event) })} />
                    {event}
                  </label>
                ))}
              </div>
              <div className="toolbar">
                {hook.id && <button className="button ghost" type="button" disabled={busy} onClick={() => void act(() => testWebhook(hook.id!), `Test message sent to ${hook.name}.`)}>Send test</button>}
                <button className="button danger" type="button" onClick={() => setHooks(hooks.filter((_, i) => i !== index))}>Remove</button>
              </div>
            </div>
          ))}
        </div>
        <div style={{ marginTop: '0.8rem' }}>
          <button className="button" type="button" disabled={busy}
            onClick={() => void act(async () => setHooks((await saveWebhooks(hooks)).webhooks), 'Webhooks saved.')}>
            Save webhooks
          </button>
        </div>
      </section>
    </div>
  )
}
