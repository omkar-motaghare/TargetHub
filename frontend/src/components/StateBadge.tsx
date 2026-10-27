import React from 'react'

import type { TargetState } from '../services/types'

const LABELS: Record<TargetState, string> = {
  available: 'Available',
  reserved: 'Reserved',
  maintenance: 'Maintenance',
  retired: 'Retired',
  disabled: 'Disabled',
}

export default function StateBadge({ state }: { state: TargetState }) {
  return <span className={`badge ${state}`}>{LABELS[state] || state}</span>
}
