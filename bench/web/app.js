import { createProfileUI } from "./profiles.js";
const $ = (id) => document.getElementById(id);
let token, socket;
function notice(message, error = true) {
  $("message").textContent = message;
  $("message").hidden = !message;
  $("message").className = error ? "warning" : "mode-note";
}
async function api(action, body = {}) {
  const response = await fetch(`/api/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Bench-Token": token },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed");
  return data;
}
async function action(fn) {
  try {
    notice("");
    await fn();
  } catch (err) {
    notice(err.message);
  }
}
const profileUI = createProfileUI({ api, action, notice });
function update(next) {
  profileUI.update(next.profile_sessions, next.profile_app);
}
function connect() {
  socket = new WebSocket(
    `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`,
    ["ambi-bench", token],
  );
  socket.onopen = () => {
    $("connection").textContent = "Live · connected";
    $("connection").className = "connection connected";
  };
  socket.onmessage = (e) => update(JSON.parse(e.data));
  socket.onclose = () => {
    $("connection").textContent = "Disconnected · retrying";
    $("connection").className = "connection";
    setTimeout(bootstrap, 2000);
  };
}
async function bootstrap() {
  try {
    const response = await fetch("/api/bootstrap");
    if (!response.ok) throw new Error("Dashboard unavailable");
    const data = await response.json();
    token = data.token;
    profileUI.setCatalog(data.profiles);
    update(data);
    connect();
  } catch (err) {
    notice(err.message);
    setTimeout(bootstrap, 3000);
  }
}
for (const tab of document.querySelectorAll("[data-tab]"))
  tab.onclick = () => {
    for (const other of document.querySelectorAll("[data-tab]"))
      other.classList.toggle("selected", other === tab);
    for (const section of document.querySelectorAll(".view"))
      section.hidden = section.id !== `${tab.dataset.tab}-view`;
  };
bootstrap();
