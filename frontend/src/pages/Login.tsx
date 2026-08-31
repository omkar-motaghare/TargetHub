import React, {useState} from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../services/auth'

export default function Login(){
  const auth = useAuth()
  const nav = useNavigate()
  const [name,setName] = useState('')
  const [password,setPassword] = useState('')
  const [role,setRole] = useState<'user'|'admin'>('user')
  const submit = async (e:React.FormEvent)=>{ e.preventDefault(); try{ await auth.login(name||'guest', password); nav('/') }catch(err:any){ alert(err.message) } }
  return (
    <div className="card">
      <h2>Login</h2>
      <form onSubmit={submit}>
        <div className="form-row">
          <input className="input" placeholder="Username" value={name} onChange={e=>setName(e.target.value)} />
        </div>
        <div className="form-row">
          <input className="input" placeholder="Password" type="password" value={password} onChange={e=>setPassword(e.target.value)} />
        </div>
        <div>
          <button className="button" type="submit">Login</button>
        </div>
      </form>
    </div>
  )
}
