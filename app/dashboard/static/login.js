"use strict";
const $ = (id) => document.getElementById(id);
let setupMode = false;

function fail(message) { const e = $("error"); e.textContent = message; e.hidden = false; }

async function init() {
  try {
    const info = await (await fetch("/dashboard/api/session", { cache: "no-store" })).json();
    if (info.authenticated) { location.replace("/dashboard"); return; }
    setupMode = info.setup_needed;
  } catch (e) { fail("Cannot reach the Yant Guard server."); return; }
  if (setupMode) {
    $("intro").textContent = "Welcome! Create the administrator account.";
    $("submit").textContent = "Create account and sign in";
    $("confirm-row").hidden = false; $("hint").hidden = false;
    $("confirm").required = true; $("password").autocomplete = "new-password";
  }
}

$("form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  $("error").hidden = true;
  if (setupMode && $("password").value !== $("confirm").value) { fail("The two passwords are not the same."); return; }
  $("submit").disabled = true;
  try {
    const r = await fetch(setupMode ? "/dashboard/api/setup" : "/dashboard/api/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: $("username").value, password: $("password").value }),
    });
    if (r.ok) { location.replace("/dashboard"); return; }
    let detail = "Sign-in failed.";
    try { const j = await r.json(); if (typeof j.detail === "string") detail = j.detail; } catch (e) { /* keep default */ }
    fail(detail);
  } catch (e) { fail("Cannot reach the Yant Guard server."); }
  $("submit").disabled = false; $("password").value = ""; $("confirm").value = "";
});
init();
