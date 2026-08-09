const API = "/api/v1";
const USER = "developer";
const CAPABILITY_TYPES = ["serial", "network", "ssh", "telnet", "ftp", "jlink", "power", "reset"];
let AGENTS = [];

const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "").replace(/[&<>\"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));

function showMessage(text) { $("message").textContent = text; $("message").classList.remove("hidden"); }
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
  $("total").textContent = targets.length; $("available").textContent = available; $("reserved").textContent = reserved;
  $("targets").innerHTML = targets.map(target => {
    const status = statusFor(target, reservations);
    const reservation = reservations.find(r => r.target_id === target.id && r.status === "active");
    const label = status === "available" ? "Available" : status === "reserved" ? "Reserved" : "Disabled";
    const capabilities = (target.capabilities || []).map(c => `<span class="capability-pill">${esc(c.name)}</span>`).join("");
    return `<article class="target-card"><div class="target-title"><h3>${esc(target.name)}</h3><span class="badge ${status}">${label}</span></div><div class="meta"><div><b>Model:</b> ${esc(target.board_model || "—")}</div><div><b>Vendor:</b> ${esc(target.vendor || "—")}</div><div><b>Location:</b> ${esc(target.location || "—")}</div><div class="capabilities">${capabilities || '<span class="muted">No capabilities configured</span>'}</div>${reservation ? `<div><b>Reserved by:</b> ${esc(reservation.user_id)}</div><div><b>Until:</b> ${esc(new Date(reservation.ends_at).toLocaleString())}</div>` : ""}</div><div class="card-actions"><button class="primary" ${status !== "available" ? "disabled" : ""} data-reserve="${esc(target.id)}">${status === "available" ? "Reserve" : "Reserved"}</button><button class="secondary" data-edit="${esc(target.id)}">Edit</button></div></article>`;
  }).join("");
  document.querySelectorAll("button[data-reserve]").forEach(button => button.addEventListener("click", () => reserve(button.dataset.reserve)));
  document.querySelectorAll("button[data-edit]").forEach(button => button.addEventListener("click", () => editTarget(button.dataset.edit)));
}

function renderReservations(reservations, targets) {
  const names = Object.fromEntries(targets.map(t => [t.id, t.name]));
  $("reservations").innerHTML = reservations.length ? reservations.map(r => {
    const ownActive = r.user_id === USER && r.status === "active";
    return `<tr><td>${esc(names[r.target_id] || r.target_id)}</td><td>${esc(r.user_id)}</td><td>${esc(new Date(r.starts_at).toLocaleString())}</td><td>${esc(new Date(r.ends_at).toLocaleString())}</td><td class="table-status">${esc(r.status)}</td><td>${ownActive ? `<button class="table-action" data-release="${esc(r.id)}">Release</button>` : ""}</td></tr>`;
  }).join("") : `<tr><td colspan="6" class="empty">No reservations found.</td></tr>`;
  document.querySelectorAll("button[data-release]").forEach(button => button.addEventListener("click", () => releaseReservation(button.dataset.release)));
}

function agentOptions(selectedId) {
  const options = AGENTS.filter(a => a.enabled).map(a => `<option value="${esc(a.id)}" ${a.id === selectedId ? "selected" : ""}>${esc(a.name)}${a.status === "online" ? " (online)" : " (offline)"}</option>`).join("");
  return `<option value="">Select Agent</option>${options}`;
}

function resourceOptions(agentId, selectedId) {
  const agent = AGENTS.find(a => a.id === agentId);
  const resources = (agent?.resources || []).filter(r => r.available);
  return `<option value="">Select detected resource</option>${resources.map(r => `<option value="${esc(r.id)}" ${r.id === selectedId ? "selected" : ""}>${esc(r.display_name)} (${esc(r.resource_type)})</option>`).join("")}`;
}

function capabilityRow(capability = {}) {
  const selectedAgent = capability.agent_id || "";
  return `<div class="capability-row" data-capability-row>
    <label>Name<input data-cap-name value="${esc(capability.name || "")}" placeholder="serial-console" required></label>
    <label>Type<select data-cap-type>${CAPABILITY_TYPES.map(type => `<option value="${type}" ${type === capability.capability_type ? "selected" : ""}>${type}</option>`).join("")}</select></label>
    <label>Agent<select data-cap-agent>${agentOptions(selectedAgent)}</select></label>
    <label class="wide">Detected hardware resource<select data-cap-resource>${resourceOptions(selectedAgent, capability.resource_id || "")}</select></label>
    <label class="checkbox"><input type="checkbox" data-cap-enabled ${capability.enabled !== false ? "checked" : ""}> Enabled</label>
    <button type="button" class="danger" data-remove-cap>Remove</button>
    <input type="hidden" data-cap-id value="${esc(capability.id || "")}">
  </div>`;
}

function addCapability(capability = {}) {
  $("capabilities").insertAdjacentHTML("beforeend", capabilityRow(capability));
  bindCapabilityRemoveButtons(); bindAgentResourceSelectors();
}

function bindCapabilityRemoveButtons() {
  document.querySelectorAll("button[data-remove-cap]").forEach(button => { button.onclick = () => button.closest("[data-capability-row]").remove(); });
}

function bindAgentResourceSelectors() {
  document.querySelectorAll("[data-cap-agent]").forEach(select => {
    select.onchange = () => {
      const row = select.closest("[data-capability-row]");
      row.querySelector("[data-cap-resource]").innerHTML = resourceOptions(select.value, "");
    };
  });
}

function collectCapabilities() {
  return [...document.querySelectorAll("[data-capability-row]")].map(row => {
    const agentId = row.querySelector("[data-cap-agent]").value || null;
    const resourceId = row.querySelector("[data-cap-resource]").value || null;
    return {
      id: row.querySelector("[data-cap-id]").value || undefined,
      name: row.querySelector("[data-cap-name]").value.trim(),
      capability_type: row.querySelector("[data-cap-type]").value,
      agent_id: agentId,
      resource_id: resourceId,
      provider_key: null,
      provider_config: {},
      enabled: row.querySelector("[data-cap-enabled]").checked,
    };
  });
}

async function saveTarget(event) {
  event.preventDefault();
  try {
    clearMessage();
    const targetId = $("target-id").value;
    const capabilities = collectCapabilities();
    const payload = { name: $("target-name").value.trim(), description: $("target-description").value.trim() || null, vendor: $("target-vendor").value.trim() || null, board_model: $("target-model").value.trim() || null, serial_number: $("target-serial").value.trim() || null, lab_name: $("target-lab").value.trim() || null, location: $("target-location").value.trim() || null, status: "available", enabled: true };
    let target;
    if (targetId) {
      target = await request(`/targets/${targetId}`, { method: "PUT", body: JSON.stringify(payload) });
      const existing = target.capabilities || [];
      const desiredIds = new Set(capabilities.filter(c => c.id).map(c => c.id));
      for (const oldCapability of existing) if (!desiredIds.has(oldCapability.id)) await request(`/targets/${targetId}/capabilities/${oldCapability.id}`, { method: "DELETE" });
      for (const capability of capabilities) {
        if (capability.id) {
          const { id, ...update } = capability;
          await request(`/targets/${targetId}/capabilities/${id}`, { method: "PUT", body: JSON.stringify(update) });
        } else {
          const { id, ...create } = capability;
          await request(`/targets/${targetId}/capabilities`, { method: "POST", body: JSON.stringify(create) });
        }
      }
    } else {
      target = await request("/targets", { method: "POST", body: JSON.stringify({ ...payload, capabilities: capabilities.map(({ id, ...c }) => c) }) });
    }
    resetTargetForm(); await load(); showMessage(`${target.name} saved successfully.`);
  } catch (error) { showMessage(error.message); }
}

async function editTarget(targetId) {
  try {
    clearMessage(); const target = await request(`/targets/${targetId}`);
    $("target-id").value = target.id; $("target-name").value = target.name || ""; $("target-description").value = target.description || ""; $("target-vendor").value = target.vendor || ""; $("target-model").value = target.board_model || ""; $("target-serial").value = target.serial_number || ""; $("target-lab").value = target.lab_name || ""; $("target-location").value = target.location || "";
    $("capabilities").innerHTML = (target.capabilities || []).map(capabilityRow).join(""); bindCapabilityRemoveButtons(); bindAgentResourceSelectors(); $("cancel-edit").classList.remove("hidden"); document.querySelector(".admin-panel").scrollIntoView({ behavior: "smooth" });
  } catch (error) { showMessage(error.message); }
}

function resetTargetForm() { $("target-form").reset(); $("target-id").value = ""; $("capabilities").innerHTML = ""; $("cancel-edit").classList.add("hidden"); }

async function reserve(targetId) { const now = new Date(); const end = new Date(now.getTime() + 60 * 60 * 1000); try { clearMessage(); await request("/reservations", { method: "POST", body: JSON.stringify({ target_id: targetId, user_id: USER, starts_at: now.toISOString(), ends_at: end.toISOString() }) }); await load(); } catch (error) { showMessage(error.message); } }
async function releaseReservation(reservationId) { try { clearMessage(); await request(`/reservations/${reservationId}/release?user_id=${encodeURIComponent(USER)}`, { method: "POST" }); await load(); } catch (error) { showMessage(error.message); } }

async function load() {
  try {
    clearMessage();
    const [targets, reservations, agents] = await Promise.all([request("/targets"), request("/reservations"), request("/agents")]);
    AGENTS = agents; renderTargets(targets, reservations); renderReservations(reservations, targets);
    if (!AGENTS.length) showMessage("No TargetHub Agents are registered yet. Register an Agent to configure physical resources.");
  } catch (error) { showMessage(`Unable to load TargetHub data: ${error.message}`); $("targets").innerHTML = ""; }
}

$("refresh").addEventListener("click", load);
$("target-form").addEventListener("submit", saveTarget);
$("add-capability").addEventListener("click", () => addCapability());
$("cancel-edit").addEventListener("click", resetTargetForm);
load();
