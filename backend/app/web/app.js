const API = "/api/v1";
const CAPABILITY_TYPES = ["serial", "network", "ssh", "telnet", "ftp", "jlink", "power", "reset"];

const state = {
  token: localStorage.getItem("th_token") || "",
  user: null,
  targets: [],
  reservations: [],
  sessions: [],
  agents: [],
};

const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "").replace(/[&<>\"']/g, (c) => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  "\"": "&quot;",
  "'": "&#39;",
}[c]));

function isAdmin() {
  return !!state.user?.roles?.includes("admin");
}

function showMessage(text) {
  $("message").textContent = text;
  $("message").classList.remove("hidden");
}

function clearMessage() {
  $("message").classList.add("hidden");
}

function setIdentity() {
  const username = state.user?.username || "guest";
  const roleLabel = isAdmin() ? "TEAM ADMIN" : state.user ? "TEAM USER" : "NOT LOGGED IN";
  $("user-label").textContent = username;
  $("role-label").textContent = roleLabel;
  $("reservation-identity").textContent = username;
  $("logout").classList.toggle("hidden", !state.user);

  document.querySelectorAll(".admin-panel").forEach((panel) => {
    panel.classList.toggle("hidden", !isAdmin());
  });
}

function serializeFormData(data) {
  const body = new URLSearchParams();
  Object.entries(data).forEach(([key, value]) => {
    body.set(key, value);
  });
  return body;
}

async function request(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };

  if (state.token) {
    headers.Authorization = `Bearer ${state.token}`;
  }

  const response = await fetch(`${API}${path}`, {
    ...options,
    headers,
  });

  const body = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401) {
      state.user = null;
      state.token = "";
      localStorage.removeItem("th_token");
      setIdentity();
    }
    throw new Error(body?.detail || `Request failed (${response.status})`);
  }

  return body;
}

async function login(event) {
  event.preventDefault();
  clearMessage();

  const username = $("auth-username").value.trim();
  const password = $("auth-password").value;

  try {
    const body = serializeFormData({ username, password, grant_type: "" });
    const response = await fetch(`${API}/auth/token`, { method: "POST", body });
    const payload = await response.json().catch(() => null);

    if (!response.ok || !payload?.access_token) {
      throw new Error(payload?.detail || "Login failed");
    }

    state.token = payload.access_token;
    localStorage.setItem("th_token", state.token);
    await bootstrapUser();
    await load();
    $("auth-form").reset();
    showMessage(`Welcome, ${state.user.username}.`);
  } catch (error) {
    showMessage(error.message);
  }
}

function logout() {
  state.token = "";
  state.user = null;
  state.targets = [];
  state.reservations = [];
  state.sessions = [];
  state.agents = [];
  localStorage.removeItem("th_token");
  setIdentity();
  renderTargets([], []);
  renderReservations([], []);
  renderSessions([], [], []);
  renderAgents([]);
  $("serial-output").textContent = "No serial output yet.";
  showMessage("Logged out. Sign in to continue.");
}

async function bootstrapUser() {
  if (!state.token) {
    state.user = null;
    setIdentity();
    return;
  }

  try {
    state.user = await request("/auth/me", {
      headers: { "Content-Type": "application/json" },
    });
    setIdentity();
  } catch (error) {
    state.user = null;
    state.token = "";
    localStorage.removeItem("th_token");
    setIdentity();
    throw error;
  }
}

function renderAgents(agents) {
  $("agents").innerHTML = agents.length
    ? agents
        .map((agent) => {
          const status = agent.enabled ? (agent.status || "offline") : "disabled";
          const resources = (agent.resources || []).filter((r) => r.available).length;
          const lastSeen = agent.last_seen_at ? new Date(agent.last_seen_at).toLocaleString() : "Never";
          const actions = agent.enabled
            ? `<button class="table-action" data-disable-agent="${esc(agent.id)}">Disable</button>`
            : `<button class="table-action" data-enable-agent="${esc(agent.id)}">Enable</button>`;
          const revoke = agent.credential_prefix
            ? `<button class="table-action danger-action" data-revoke-agent="${esc(agent.id)}">Revoke credential</button>`
            : "";
          return `<tr><td><strong>${esc(agent.name)}</strong><div class="muted">${esc(agent.credential_prefix || "No credential")}</div></td><td>${esc(agent.hostname || "-")}</td><td><span class="badge ${status === "online" ? "available" : status === "disabled" ? "disabled" : "reserved"}">${esc(status)}</span></td><td>${resources}</td><td>${esc(lastSeen)}</td><td><div class="agent-actions">${actions}${revoke}</div></td></tr>`;
        })
        .join("")
    : `<tr><td colspan="6" class="empty">No Agents enrolled yet.</td></tr>`;

  document.querySelectorAll("button[data-disable-agent]").forEach((button) => {
    button.onclick = () => changeAgentState(button.dataset.disableAgent, "disable");
  });
  document.querySelectorAll("button[data-enable-agent]").forEach((button) => {
    button.onclick = () => changeAgentState(button.dataset.enableAgent, "enable");
  });
  document.querySelectorAll("button[data-revoke-agent]").forEach((button) => {
    button.onclick = () => revokeAgent(button.dataset.revokeAgent);
  });
}

async function createAgentEnrollment(event) {
  event.preventDefault();
  try {
    clearMessage();
    const result = await request("/agents/enrollments", {
      method: "POST",
      body: JSON.stringify({ agent_name: $("agent-name").value.trim() }),
    });

    $("enrollment-result").innerHTML = `<div><strong>Enrollment created for ${esc(result.agent_name)}</strong><p class="muted">Run the installation command on any supported Linux machine. The token expires ${esc(new Date(result.expires_at).toLocaleString())} and can be used once.</p></div><label>One-time enrollment token<input readonly value="${esc(result.token)}" id="enrollment-token"></label><label class="wide">Installation command<textarea readonly rows="3" id="install-command">${esc(result.install_command)}</textarea></label><div class="form-actions"><button type="button" class="secondary" id="copy-install">Copy installation command</button></div>`;
    $("enrollment-result").classList.remove("hidden");
    $("agent-form").reset();
    $("copy-install").onclick = async () => {
      await navigator.clipboard.writeText(result.install_command);
      showMessage("Installation command copied to clipboard.");
    };

    await loadAgents();
  } catch (error) {
    showMessage(error.message);
  }
}

async function changeAgentState(agentId, action) {
  try {
    clearMessage();
    await request(`/agents/${agentId}/${action}`, { method: "POST" });
    await loadAgents();
    showMessage(`Agent ${action}d successfully.`);
  } catch (error) {
    showMessage(error.message);
  }
}

async function revokeAgent(agentId) {
  if (!window.confirm("Revoke this Agent credential? The Agent will stop authenticating until it is enrolled again.")) {
    return;
  }

  try {
    clearMessage();
    await request(`/agents/${agentId}/revoke-credential`, { method: "POST" });
    await loadAgents();
    showMessage("Agent credential revoked.");
  } catch (error) {
    showMessage(error.message);
  }
}

function statusFor(target, reservations) {
  if (target.enabled === false) return "disabled";
  const active = reservations.find((r) => r.target_id === target.id && r.status === "active");
  return active ? "reserved" : "available";
}

function renderTargets(targets, reservations) {
  const available = targets.filter((t) => statusFor(t, reservations) === "available").length;
  const reserved = targets.filter((t) => statusFor(t, reservations) === "reserved").length;

  $("total").textContent = targets.length;
  $("available").textContent = available;
  $("reserved").textContent = reserved;

  $("targets").innerHTML = targets
    .map((target) => {
      const status = statusFor(target, reservations);
      const reservation = reservations.find((r) => r.target_id === target.id && r.status === "active");
      const label = status === "available" ? "Available" : status === "reserved" ? "Reserved" : "Disabled";
      const capabilities = (target.capabilities || []).map((c) => `<span class="capability-pill">${esc(c.name)}</span>`).join("");

      const reserveAction = state.user
        ? `<button class="primary" ${status !== "available" ? "disabled" : ""} data-reserve="${esc(target.id)}">${status === "available" ? "Reserve" : "Reserved"}</button>`
        : "";
      const editAction = isAdmin() ? `<button class="secondary" data-edit="${esc(target.id)}">Edit</button>` : "";

      return `<article class="target-card"><div class="target-title"><h3>${esc(target.name)}</h3><span class="badge ${status}">${label}</span></div><div class="meta"><div><b>Model:</b> ${esc(target.board_model || "-")}</div><div><b>Vendor:</b> ${esc(target.vendor || "-")}</div><div><b>Location:</b> ${esc(target.location || "-")}</div><div class="capabilities">${capabilities || '<span class="muted">No capabilities configured</span>'}</div>${reservation ? `<div><b>Reserved by:</b> ${esc(reservation.user_id)}</div><div><b>Until:</b> ${esc(new Date(reservation.ends_at).toLocaleString())}</div>` : ""}</div><div class="card-actions">${reserveAction}${editAction}</div></article>`;
    })
    .join("");

  document.querySelectorAll("button[data-reserve]").forEach((button) => {
    button.addEventListener("click", () => reserve(button.dataset.reserve));
  });
  document.querySelectorAll("button[data-edit]").forEach((button) => {
    button.addEventListener("click", () => editTarget(button.dataset.edit));
  });
}

function reservationActions(reservation, target) {
  if (!state.user || reservation.user_id !== state.user.username || reservation.status !== "active") {
    return "";
  }

  const hasActiveSession = state.sessions.some(
    (session) => session.reservation_id === reservation.id && session.status === "active"
  );

  const serialCap = (target.capabilities || []).find((cap) => cap.enabled && cap.capability_type === "serial");
  const openSessionButton = hasActiveSession
    ? ""
    : `<button class="table-action" data-open-session="${esc(reservation.id)}" ${serialCap ? "" : "disabled"}>Open session</button>`;

  return `${openSessionButton}<button class="table-action" data-release="${esc(reservation.id)}">Release</button>`;
}

function renderReservations(reservations, targets) {
  const targetsById = Object.fromEntries(targets.map((t) => [t.id, t]));

  $("reservations").innerHTML = reservations.length
    ? reservations
        .map((reservation) => {
          const target = targetsById[reservation.target_id] || { id: reservation.target_id, name: reservation.target_id, capabilities: [] };
          return `<tr><td>${esc(target.name)}</td><td>${esc(reservation.user_id)}</td><td>${esc(new Date(reservation.starts_at).toLocaleString())}</td><td>${esc(new Date(reservation.ends_at).toLocaleString())}</td><td class="table-status">${esc(reservation.status)}</td><td><div class="reservation-actions">${reservationActions(reservation, target)}</div></td></tr>`;
        })
        .join("")
    : `<tr><td colspan="6" class="empty">No reservations found.</td></tr>`;

  document.querySelectorAll("button[data-release]").forEach((button) => {
    button.addEventListener("click", () => releaseReservation(button.dataset.release));
  });
  document.querySelectorAll("button[data-open-session]").forEach((button) => {
    button.addEventListener("click", () => openSession(button.dataset.openSession));
  });
}

function renderSessions(sessions, targets, reservations) {
  const targetNames = Object.fromEntries(targets.map((target) => [target.id, target.name]));
  const reservationOwners = Object.fromEntries(reservations.map((reservation) => [reservation.id, reservation.user_id]));

  $("sessions").innerHTML = sessions.length
    ? sessions
        .map((session) => {
          const ownSession = state.user && session.user_id === state.user.username;
          const provider = session.provider_key || "-";
          const sessionStatus = esc(session.status);

          const controls = ownSession && session.status === "active"
            ? `<div class="reservation-actions"><button class="table-action" data-session-read="${esc(session.id)}">Read serial</button><button class="table-action" data-session-close="${esc(session.id)}">Close</button></div>`
            : "";

          return `<tr><td>${esc(session.capability_type)}</td><td>${esc(reservationOwners[session.reservation_id] || session.user_id)}</td><td>${esc(targetNames[session.target_id] || session.target_id)}</td><td>${esc(provider)}</td><td>${esc(new Date(session.expires_at).toLocaleString())}</td><td class="table-status">${sessionStatus}</td><td>${controls}</td></tr>`;
        })
        .join("")
    : `<tr><td colspan="7" class="empty">No sessions found.</td></tr>`;

  document.querySelectorAll("button[data-session-read]").forEach((button) => {
    button.addEventListener("click", () => readSerial(button.dataset.sessionRead));
  });
  document.querySelectorAll("button[data-session-close]").forEach((button) => {
    button.addEventListener("click", () => closeSession(button.dataset.sessionClose));
  });
}

function agentOptions(selectedId) {
  const options = state.agents
    .filter((agent) => agent.enabled)
    .map((agent) => `<option value="${esc(agent.id)}" ${agent.id === selectedId ? "selected" : ""}>${esc(agent.name)}${agent.status === "online" ? " (online)" : " (offline)"}</option>`)
    .join("");
  return `<option value="">Select Agent</option>${options}`;
}

function resourceOptions(agentId, selectedId) {
  const agent = state.agents.find((item) => item.id === agentId);
  const resources = (agent?.resources || []).filter((resource) => resource.available);
  return `<option value="">Select detected resource</option>${resources
    .map((resource) => `<option value="${esc(resource.id)}" ${resource.id === selectedId ? "selected" : ""}>${esc(resource.display_name)} (${esc(resource.resource_type)})</option>`)
    .join("")}`;
}

function capabilityRow(capability = {}) {
  const selectedAgent = capability.agent_id || "";
  return `<div class="capability-row" data-capability-row>
    <label>Name<input data-cap-name value="${esc(capability.name || "")}" placeholder="serial-console" required></label>
    <label>Type<select data-cap-type>${CAPABILITY_TYPES.map((type) => `<option value="${type}" ${type === capability.capability_type ? "selected" : ""}>${type}</option>`).join("")}</select></label>
    <label>Provider key<input data-cap-provider-key value="${esc(capability.provider_key || "")}" placeholder="serial-demo"></label>
    <label>Agent<select data-cap-agent>${agentOptions(selectedAgent)}</select></label>
    <label class="wide">Detected hardware resource<select data-cap-resource>${resourceOptions(selectedAgent, capability.resource_id || "")}</select></label>
    <label class="checkbox"><input type="checkbox" data-cap-enabled ${capability.enabled !== false ? "checked" : ""}> Enabled</label>
    <button type="button" class="danger" data-remove-cap>Remove</button>
    <input type="hidden" data-cap-id value="${esc(capability.id || "")}">
  </div>`;
}

function addCapability(capability = {}) {
  $("capabilities").insertAdjacentHTML("beforeend", capabilityRow(capability));
  bindCapabilityRemoveButtons();
  bindAgentResourceSelectors();
}

function bindCapabilityRemoveButtons() {
  document.querySelectorAll("button[data-remove-cap]").forEach((button) => {
    button.onclick = () => button.closest("[data-capability-row]").remove();
  });
}

function bindAgentResourceSelectors() {
  document.querySelectorAll("[data-cap-agent]").forEach((select) => {
    select.onchange = () => {
      const row = select.closest("[data-capability-row]");
      row.querySelector("[data-cap-resource]").innerHTML = resourceOptions(select.value, "");
    };
  });
}

function collectCapabilities() {
  return [...document.querySelectorAll("[data-capability-row]")].map((row) => {
    const providerKeyValue = row.querySelector("[data-cap-provider-key]").value.trim();
    const capabilityType = row.querySelector("[data-cap-type]").value;

    return {
      id: row.querySelector("[data-cap-id]").value || undefined,
      name: row.querySelector("[data-cap-name]").value.trim(),
      capability_type: capabilityType,
      agent_id: row.querySelector("[data-cap-agent]").value || null,
      resource_id: row.querySelector("[data-cap-resource]").value || null,
      provider_key: providerKeyValue || `${capabilityType}-demo`,
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
    const payload = {
      name: $("target-name").value.trim(),
      description: $("target-description").value.trim() || null,
      vendor: $("target-vendor").value.trim() || null,
      board_model: $("target-model").value.trim() || null,
      serial_number: $("target-serial").value.trim() || null,
      lab_name: $("target-lab").value.trim() || null,
      location: $("target-location").value.trim() || null,
      status: "available",
      enabled: true,
    };

    let target;
    if (targetId) {
      target = await request(`/targets/${targetId}`, { method: "PUT", body: JSON.stringify(payload) });
      const existing = target.capabilities || [];
      const desiredIds = new Set(capabilities.filter((capability) => capability.id).map((capability) => capability.id));

      for (const oldCapability of existing) {
        if (!desiredIds.has(oldCapability.id)) {
          await request(`/targets/${targetId}/capabilities/${oldCapability.id}`, { method: "DELETE" });
        }
      }

      for (const capability of capabilities) {
        if (capability.id) {
          const { id, ...update } = capability;
          await request(`/targets/${targetId}/capabilities/${id}`, {
            method: "PUT",
            body: JSON.stringify(update),
          });
        } else {
          const { id, ...create } = capability;
          await request(`/targets/${targetId}/capabilities`, {
            method: "POST",
            body: JSON.stringify(create),
          });
        }
      }
    } else {
      target = await request("/targets", {
        method: "POST",
        body: JSON.stringify({
          ...payload,
          capabilities: capabilities.map(({ id, ...capability }) => capability),
        }),
      });
    }

    resetTargetForm();
    await load();
    showMessage(`${target.name} saved successfully.`);
  } catch (error) {
    showMessage(error.message);
  }
}

async function editTarget(targetId) {
  try {
    clearMessage();
    const target = await request(`/targets/${targetId}`);

    $("target-id").value = target.id;
    $("target-name").value = target.name || "";
    $("target-description").value = target.description || "";
    $("target-vendor").value = target.vendor || "";
    $("target-model").value = target.board_model || "";
    $("target-serial").value = target.serial_number || "";
    $("target-lab").value = target.lab_name || "";
    $("target-location").value = target.location || "";

    $("capabilities").innerHTML = (target.capabilities || []).map(capabilityRow).join("");
    bindCapabilityRemoveButtons();
    bindAgentResourceSelectors();
    $("cancel-edit").classList.remove("hidden");
    document.querySelector(".admin-panel").scrollIntoView({ behavior: "smooth" });
  } catch (error) {
    showMessage(error.message);
  }
}

function resetTargetForm() {
  $("target-form").reset();
  $("target-id").value = "";
  $("capabilities").innerHTML = "";
  $("cancel-edit").classList.add("hidden");
}

async function reserve(targetId) {
  const now = new Date();
  const end = new Date(now.getTime() + 60 * 60 * 1000);

  try {
    clearMessage();
    await request("/reservations", {
      method: "POST",
      body: JSON.stringify({
        target_id: targetId,
        user_id: state.user.username,
        starts_at: now.toISOString(),
        ends_at: end.toISOString(),
      }),
    });
    await load();
  } catch (error) {
    showMessage(error.message);
  }
}

async function releaseReservation(reservationId) {
  try {
    clearMessage();
    await request(`/reservations/${reservationId}/release?user_id=${encodeURIComponent(state.user.username)}`, {
      method: "POST",
    });
    await load();
  } catch (error) {
    showMessage(error.message);
  }
}

async function openSession(reservationId) {
  try {
    clearMessage();

    const reservation = state.reservations.find((item) => item.id === reservationId);
    const target = state.targets.find((item) => item.id === reservation?.target_id);
    if (!reservation || !target) {
      throw new Error("Reservation target context not found");
    }

    const availableCapabilities = (target.capabilities || []).filter((capability) => capability.enabled);
    if (!availableCapabilities.length) {
      throw new Error("No enabled capabilities are configured on this target");
    }

    const preferred = availableCapabilities.find((capability) => capability.capability_type === "serial");
    const selectedType = preferred ? preferred.capability_type : availableCapabilities[0].capability_type;

    await request("/sessions", {
      method: "POST",
      body: JSON.stringify({
        reservation_id: reservationId,
        user_id: state.user.username,
        capability_type: selectedType,
      }),
    });

    await load();
    showMessage(`Session opened with capability '${selectedType}'.`);
  } catch (error) {
    showMessage(error.message);
  }
}

async function closeSession(sessionId) {
  try {
    clearMessage();
    await request(`/sessions/${sessionId}/close?user_id=${encodeURIComponent(state.user.username)}`, {
      method: "POST",
    });
    await load();
    showMessage("Session closed.");
  } catch (error) {
    showMessage(error.message);
  }
}

async function readSerial(sessionId) {
  try {
    clearMessage();
    const result = await request(`/sessions/${sessionId}/serial/read`);
    const content = result?.data?.data_text || result?.data?.data || "<empty>";
    const timestamp = new Date().toLocaleTimeString();
    const current = $("serial-output").textContent;
    const header = `[${timestamp}] ${result?.provider_key || "serial"}`;
    $("serial-output").textContent = `${current === "No serial output yet." ? "" : `${current}\n`}\n${header}\n${content}`.trim();
  } catch (error) {
    showMessage(error.message);
  }
}

async function loadAgents() {
  state.agents = await request("/agents");
  renderAgents(state.agents);
}

async function load() {
  try {
    clearMessage();
    if (!state.user) {
      showMessage("Sign in to load dashboard data.");
      return;
    }

    const [targets, reservations, agents, sessions] = await Promise.all([
      request("/targets"),
      request("/reservations"),
      request("/agents"),
      request("/sessions"),
    ]);

    state.targets = targets;
    state.reservations = reservations;
    state.agents = agents;
    state.sessions = sessions;

    renderAgents(agents);
    renderTargets(targets, reservations);
    renderReservations(reservations, targets);
    renderSessions(sessions, targets, reservations);

    if (!agents.length && isAdmin()) {
      showMessage("No TargetHub Agents are registered yet. Create an enrollment above to install one.");
    }
  } catch (error) {
    showMessage(`Unable to load TargetHub data: ${error.message}`);
    $("targets").innerHTML = "";
    $("reservations").innerHTML = `<tr><td colspan="6" class="empty">Unable to load reservations.</td></tr>`;
    $("sessions").innerHTML = `<tr><td colspan="7" class="empty">Unable to load sessions.</td></tr>`;
  }
}

$("refresh").addEventListener("click", load);
$("agent-form").addEventListener("submit", createAgentEnrollment);
$("target-form").addEventListener("submit", saveTarget);
$("add-capability").addEventListener("click", () => addCapability());
$("cancel-edit").addEventListener("click", resetTargetForm);
$("auth-form").addEventListener("submit", login);
$("logout").addEventListener("click", logout);
$("clear-serial").addEventListener("click", () => {
  $("serial-output").textContent = "No serial output yet.";
});

(async function init() {
  setIdentity();
  try {
    await bootstrapUser();
  } catch (error) {
    showMessage("Please sign in to continue.");
  }
  await load();
})();
