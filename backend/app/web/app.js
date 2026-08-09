const API = "/api/v1";
const USER = "developer";

const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "").replace(/[&<>\"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));

function showMessage(text) {
  $("message").textContent = text;
  $("message").classList.remove("hidden");
}
function clearMessage() { $("message").classList.add("hidden"); }

async function request(path, options = {}) {
  const response = await fetch(`${API}${path}`, { headers: { "Content-Type": "application/json" }, ...options });
  const body = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) throw new Error(body?.detail || `Request failed (${response.status})`);
  return body;
}

function statusFor(target, reservations) {
  if (target.enabled === false) return "disabled";
  const active = reservations.find(r => r.target_id === target.id && r.status === "active");
  return active ? "reserved" : "available";
}

function renderTargets(targets, reservations) {
  const available = targets.filter(t => statusFor(t, reservations) === "available").length;
  const reserved = targets.filter(t => statusFor(t, reservations) === "reserved").length;
  $("total").textContent = targets.length;
  $("available").textContent = available;
  $("reserved").textContent = reserved;
  $("targets").innerHTML = targets.map(target => {
    const status = statusFor(target, reservations);
    const reservation = reservations.find(r => r.target_id === target.id && r.status === "active");
    const label = status === "available" ? "Available" : status === "reserved" ? "Reserved" : "Disabled";
    return `<article class="target-card"><div class="target-title"><h3>${esc(target.name)}</h3><span class="badge ${status}">${label}</span></div><div class="meta"><div><b>Model:</b> ${esc(target.board_model || "—")}</div><div><b>Vendor:</b> ${esc(target.vendor || "—")}</div><div><b>Location:</b> ${esc(target.location || "—")}</div>${reservation ? `<div><b>Reserved by:</b> ${esc(reservation.user_id)}</div><div><b>Until:</b> ${esc(new Date(reservation.ends_at).toLocaleString())}</div>` : ""}</div><button class="primary" ${status !== "available" ? "disabled" : ""} data-target="${esc(target.id)}">${status === "available" ? "Reserve" : "View details"}</button></article>`;
  }).join("");
  document.querySelectorAll("button[data-target]").forEach(button => button.addEventListener("click", () => reserve(button.dataset.target)));
}

function renderReservations(reservations, targets) {
  const names = Object.fromEntries(targets.map(t => [t.id, t.name]));
  $("reservations").innerHTML = reservations.length ? reservations.map(r => `<tr><td>${esc(names[r.target_id] || r.target_id)}</td><td>${esc(r.user_id)}</td><td>${esc(new Date(r.starts_at).toLocaleString())}</td><td>${esc(new Date(r.ends_at).toLocaleString())}</td><td class="table-status">${esc(r.status)}</td></tr>`).join("") : `<tr><td colspan="5" class="empty">No reservations found.</td></tr>`;
}

async function reserve(targetId) {
  const now = new Date();
  const end = new Date(now.getTime() + 60 * 60 * 1000);
  try {
    clearMessage();
    await request("/reservations", { method: "POST", body: JSON.stringify({ target_id: targetId, user_id: USER, starts_at: now.toISOString(), ends_at: end.toISOString() }) });
    await load();
  } catch (error) { showMessage(error.message); }
}

async function load() {
  try {
    clearMessage();
    const [targets, reservations] = await Promise.all([request("/targets"), request("/reservations")]);
    renderTargets(targets, reservations);
    renderReservations(reservations, targets);
  } catch (error) {
    showMessage(`Unable to load TargetHub data: ${error.message}`);
    $("targets").innerHTML = "";
  }
}

$("refresh").addEventListener("click", load);
load();
