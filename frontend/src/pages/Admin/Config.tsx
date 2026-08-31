import React, {useState} from 'react'

export default function AdminConfig(){
  const [reservationTimeout,setReservationTimeout] = useState(30)
  function save(){ localStorage.setItem('th_config_v1', JSON.stringify({reservationTimeout})); alert('Saved (mock)') }
  return (
    <div>
      <h3>Configuration</h3>
      <div className="card">
        <div className="form-row">
          <input className="input" type="number" value={reservationTimeout} onChange={e=>setReservationTimeout(parseInt(e.target.value||'0'))} />
          <div style={{alignSelf:'center'}}>minutes default reservation</div>
        </div>
        <div>
          <button className="button" onClick={save}>Save</button>
        </div>
      </div>
    </div>
  )
}
