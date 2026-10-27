import React, { useState } from 'react'
import { useNavigate } from 'react-router'

import ChangePasswordForm from '../components/ChangePasswordForm'
import { useAuth } from '../services/auth'

export default function ChangePassword() {
  const auth = useAuth()
  const nav = useNavigate()
  const [done, setDone] = useState(false)

  if (done) {
    return (
      <div className="card" style={{ maxWidth: 520, margin: '0 auto' }}>
        <h2 className="page-title">Password updated</h2>
        <p className="muted">Your password has been changed. Please sign in again with your new password.</p>
      </div>
    )
  }

  return (
    <div className="card" style={{ maxWidth: 520, margin: '0 auto' }}>
      <h2 className="page-title">Change password</h2>
      <p className="muted">Enter your current password to set a new one.</p>
      <ChangePasswordForm
        initialUsername={auth.user?.username ?? ''}
        lockUsername
        onSuccess={() => {
          setDone(true)
          auth.logout()
          setTimeout(() => nav('/login', { replace: true }), 1200)
        }}
        onCancel={() => nav(-1)}
      />
    </div>
  )
}
