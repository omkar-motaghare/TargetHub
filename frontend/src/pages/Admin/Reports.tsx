import React, { useEffect, useState } from 'react'

import { usageReport, usageReportCsv } from '../../services/api'
import type { UsageCsvKind, UsageReport } from '../../services/types'
import { downloadText, errorMessage } from '../../utils/ui'

const PERIODS = [
  { days: 7, label: 'Last 7 days' },
  { days: 30, label: 'Last 30 days' },
  { days: 90, label: 'Last 90 days' },
  { days: 365, label: 'Last 12 months' },
]

function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="card stat">
      <div className="muted">{label}</div>
      <h3>{value}</h3>
      {hint && <div className="muted small">{hint}</div>}
    </div>
  )
}

function Section({ title, kind, days, onDownload, children }: {
  title: string
  kind: UsageCsvKind
  days: number
  onDownload: (kind: UsageCsvKind, days: number) => void
  children: React.ReactNode
}) {
  return (
    <section className="card">
      <div className="page-head">
        <h3 style={{ margin: 0 }}>{title}</h3>
        <button type="button" className="button ghost" onClick={() => onDownload(kind, days)} aria-label={`download ${kind} csv`}>
          Download CSV
        </button>
      </div>
      {children}
    </section>
  )
}

export default function AdminReports() {
  const [days, setDays] = useState(30)
  const [report, setReport] = useState<UsageReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    usageReport(days)
      .then((result) => {
        if (cancelled) return
        setReport(result)
        setMessage(null)
      })
      .catch((error) => {
        if (!cancelled) setMessage(errorMessage(error))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [days])

  async function download(kind: UsageCsvKind, period: number): Promise<void> {
    try {
      downloadText(`targethub-${kind}-${period}d.csv`, await usageReportCsv(kind, period))
    } catch (error) {
      setMessage(errorMessage(error))
    }
  }

  const triggerDownload = (kind: UsageCsvKind, period: number) => void download(kind, period)

  return (
    <div className="grid" style={{ gap: '1rem' }}>
      <div className="card">
        <div className="page-head">
          <div>
            <h3 style={{ margin: 0 }}>Usage reports</h3>
            <p className="muted" style={{ margin: '0.3rem 0 0' }}>
              How the lab is used: which boards are busy, which reservations are never used, and how long people wait.
            </p>
          </div>
          <select className="input" aria-label="report period" value={days} onChange={(event) => setDays(Number(event.target.value))}>
            {PERIODS.map((period) => <option key={period.days} value={period.days}>{period.label}</option>)}
          </select>
        </div>
      </div>

      {message && <div className="feedback error" role="alert">{message}</div>}
      {loading && !report && <div className="card">Loading…</div>}

      {report && (
        <>
          <div className="grid four">
            <Stat label="Booked time" value={`${report.totals.booked_hours} h`}
              hint={`${report.totals.reservations} reservations by ${report.totals.users} people`} />
            <Stat label="Held but unused" value={`${report.totals.idle_hours} h`}
              hint={`${report.totals.idle_share_percent}% of booked time · ${report.totals.idle_reservations} reservations`} />
            <Stat label="Waitlist entries" value={report.waitlist.entries}
              hint={`${report.waitlist.fulfilled} fulfilled · ${report.waitlist.expired} expired`} />
            <Stat label="Average wait"
              value={report.waitlist.average_wait_minutes === null ? '-' : `${report.waitlist.average_wait_minutes} min`}
              hint={report.waitlist.longest_wait_minutes === null ? undefined : `longest ${report.waitlist.longest_wait_minutes} min`} />
          </div>

          <Section title="Utilisation per target" kind="targets" days={days} onDownload={triggerDownload}>
            <div className="table-wrap">
              <table className="table" aria-label="utilisation per target">
                <thead><tr><th>Target</th><th>Tags</th><th>Reservations</th><th>Booked</th><th>Utilisation</th><th>Held unused</th></tr></thead>
                <tbody>
                  {report.targets.map((row) => (
                    <tr key={row.target_id}>
                      <td>{row.name}</td>
                      <td className="muted">{row.tags.join(', ') || '-'}</td>
                      <td>{row.reservations}</td>
                      <td>{row.booked_hours} h</td>
                      <td>{row.utilisation_percent}%</td>
                      <td>{row.idle_hours ? `${row.idle_hours} h (${row.idle_reservations})` : '-'}</td>
                    </tr>
                  ))}
                  {report.targets.length === 0 && <tr><td colSpan={6} className="muted">No targets.</td></tr>}
                </tbody>
              </table>
            </div>
          </Section>

          <Section title="Utilisation per tag" kind="tags" days={days} onDownload={triggerDownload}>
            <div className="table-wrap">
              <table className="table" aria-label="utilisation per tag">
                <thead><tr><th>Tag</th><th>Targets</th><th>Reservations</th><th>Booked</th><th>Utilisation</th></tr></thead>
                <tbody>
                  {report.tags.map((row) => (
                    <tr key={row.tag}>
                      <td>{row.tag}</td><td>{row.targets}</td><td>{row.reservations}</td>
                      <td>{row.booked_hours} h</td><td>{row.utilisation_percent}%</td>
                    </tr>
                  ))}
                  {report.tags.length === 0 && <tr><td colSpan={5} className="muted">No tagged targets.</td></tr>}
                </tbody>
              </table>
            </div>
          </Section>

          <Section title="Reservations held without using the board" kind="idle" days={days} onDownload={triggerDownload}>
            <div className="table-wrap">
              <table className="table" aria-label="idle reservations">
                <thead><tr><th>Target</th><th>User</th><th>Started</th><th>Held</th><th>Note</th></tr></thead>
                <tbody>
                  {report.idle.map((row) => (
                    <tr key={row.reservation_id}>
                      <td>{row.target}</td><td>{row.user_id}</td>
                      <td>{new Date(row.starts_at).toLocaleString()}</td>
                      <td>{row.hours_held} h</td><td className="muted">{row.note || '-'}</td>
                    </tr>
                  ))}
                  {report.idle.length === 0 && <tr><td colSpan={5} className="muted">No idle reservations in this period.</td></tr>}
                </tbody>
              </table>
            </div>
          </Section>

          <Section title="Per team" kind="teams" days={days} onDownload={triggerDownload}>
            <div className="table-wrap">
              <table className="table" aria-label="usage per team">
                <thead><tr><th>Team</th><th>Members</th><th>Active</th><th>Reservations</th><th>Booked</th><th>Held unused</th></tr></thead>
                <tbody>
                  {report.teams.map((row) => (
                    <tr key={row.team}>
                      <td>{row.team}</td><td>{row.members}</td><td>{row.active_users}</td><td>{row.reservations}</td>
                      <td>{row.booked_hours} h</td><td>{row.idle_hours ? `${row.idle_hours} h` : '-'}</td>
                    </tr>
                  ))}
                  {report.teams.length === 0 && <tr><td colSpan={6} className="muted">No teams yet. Create them under Admin → Teams.</td></tr>}
                </tbody>
              </table>
            </div>
          </Section>

          <Section title="Per user" kind="users" days={days} onDownload={triggerDownload}>
            <div className="table-wrap">
              <table className="table" aria-label="usage per user">
                <thead><tr><th>User</th><th>Reservations</th><th>Targets</th><th>Booked</th><th>Held unused</th></tr></thead>
                <tbody>
                  {report.users.map((row) => (
                    <tr key={row.user_id}>
                      <td>{row.user_id}</td><td>{row.reservations}</td><td>{row.targets}</td>
                      <td>{row.booked_hours} h</td><td>{row.idle_hours ? `${row.idle_hours} h` : '-'}</td>
                    </tr>
                  ))}
                  {report.users.length === 0 && <tr><td colSpan={5} className="muted">No reservations in this period.</td></tr>}
                </tbody>
              </table>
            </div>
          </Section>

          <div className="card">
            <div className="page-head">
              <div>
                <h3 style={{ margin: 0 }}>Waitlist</h3>
                <p className="muted small" style={{ margin: '0.3rem 0 0' }}>
                  {report.waitlist.entries} entries · {report.waitlist.waiting} waiting · {report.waitlist.cancelled} cancelled
                </p>
              </div>
              <button type="button" className="button ghost" onClick={() => triggerDownload('waitlist', days)} aria-label="download waitlist csv">
                Download CSV
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
