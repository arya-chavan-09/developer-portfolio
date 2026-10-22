(() => {
  "use strict";

  const $ = (s) => document.querySelector(s);
  const term = $("#term"), screen = $("#screen"), input = $("#cmd"), ps1 = $("#ps1");
  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let token = null;
  try { token = sessionStorage.getItem("admin_token"); } catch { /* storage may be blocked */ }
  const defaultPs1 = () => (token ? "admin@portfolio:~#" : "guest@portfolio:~$");
  function setToken(t) {
    token = t;
    try { t ? sessionStorage.setItem("admin_token", t) : sessionStorage.removeItem("admin_token"); } catch { /* ignore */ }
    ps1.textContent = defaultPs1();
    const who = document.getElementById("who");
    if (who) who.textContent = token ? "admin@portfolio" : "guest@portfolio";
  }
  const history = [];
  let hIdx = 0, busy = false, reader = null, readerSecret = false, slugs = [];

  /* ---------------- output helpers ---------------- */
  const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const toBottom = () => { term.scrollTop = term.scrollHeight; };

  function line(html = "", cls = "") {
    const d = document.createElement("div");
    d.className = ("ln " + cls).trim();
    d.innerHTML = html;
    screen.appendChild(d);
    toBottom();
    return d;
  }
  const text = (t, cls) => line(esc(t), cls);
  const dim = (t) => line(esc(t), "dim");
  const err = (t) => line(esc(t), "err");

  function highlight(obj) {
    const json = esc(JSON.stringify(obj, null, 2));
    return json.replace(
      /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d+)?/g,
      (m, str, colon, lit) => {
        if (str) return colon ? `<span class="j-key">${str}</span>${colon}` : `<span class="j-str">${str}</span>`;
        if (lit) return `<span class="j-lit">${m}</span>`;
        return `<span class="j-num">${m}</span>`;
      }
    );
  }

  /* ---------------- API client ---------------- */
  async function api(method, path, body) {
    const t0 = performance.now();
    let res;
    try {
      res = await fetch(path, {
        method,
        headers: {
          ...(body ? { "Content-Type": "application/json" } : {}),
          ...(token ? { Authorization: "Bearer " + token } : {}),
        },
        body: body ? JSON.stringify(body) : undefined,
      });
    } catch {
      err("Network error: the API is not reachable. Is the server running?");
      return null;
    }
    const ms = Math.round(performance.now() - t0);
    let data = null;
    try { data = await res.json(); } catch { /* non-JSON body */ }
    line(
      `<span class="req"><span class="m">${method}</span> ${esc(path)}  ` +
      `<span class="s${String(res.status)[0]}">${res.status} ${esc(res.statusText || "")}</span>  ${ms}ms</span>`,
      "gap"
    );
    return { ok: res.ok, status: res.status, data };
  }

  function showApiError(r) {
    if (!r) return;
    if (r.status === 401 && token) setToken(null);
    let d = r.data && (r.data.detail ?? r.data.error);
    if (Array.isArray(d)) d = d.map((x) => `${(x.loc || []).slice(1).join(".")}: ${x.msg}`).join("\n");
    err(d || `Request failed with status ${r.status}`);
  }

  /* ---------------- input reading (for prompts like `contact`) ---------------- */
  function ask(label, secret = false) {
    return new Promise((resolve) => {
      ps1.textContent = label + ">";
      input.type = secret ? "password" : "text";
      readerSecret = secret;
      reader = resolve;
      input.focus();
    });
  }

  /* ---------------- formatters ---------------- */
  async function askAll(labels) {
    const out = [];
    for (const l of labels) { const v = await ask(l); if (v === null) return null; out.push(v); }
    return out;
  }

  const bar = (n) => `<span class="bar-l">${"█".repeat(n)}</span><span class="bar-e">${"█".repeat(5 - n)}</span>`;
  const pad = (s, n) => String(s).padEnd(n, " ");

  function table(columns, rows) {
    const cell = (v) => { const s = v === null ? "NULL" : String(v); return s.length > 38 ? s.slice(0, 37) + "…" : s; };
    const w = columns.map((c, i) => Math.max(c.length, ...rows.map((r) => cell(r[i]).length)));
    const head = columns.map((c, i) => pad(c, w[i])).join("  ");
    line(`<span class="head">${esc(head)}</span>`);
    line(`<span class="dim">${w.map((n) => "─".repeat(n)).join("  ")}</span>`);
    rows.forEach((r) => line(esc(r.map((v, i) => pad(cell(v), w[i])).join("  "))));
  }

  /* ---------------- commands ---------------- */
  const HELP = [
    ["whoami", "who I am (GET /api/profile)"],
    ["about", "short bio"],
    ["projects", "list projects (GET /api/projects)"],
    ["cat projects/<name>", "one project in detail"],
    ["skills", "skills by category"],
    ["experience", "work history"],
    ["sql <SELECT …>", "query the portfolio database (read-only)"],
    ["curl [-X M] [-d JSON] <path>", "call the API directly; raw JSON"],
    ["contact", "send me a message (POST /api/contact)"],
    ["status", "live API stats: latency, traffic, recent requests"],
    ["docs", "open the Swagger docs"],
    ["login · logout", "admin: sign in to manage experience"],
    ["exp add · exp rm <id>", "admin: add or delete a work experience"],
    ["theme", "switch colour theme"],
    ["gui", "switch to the visual page"],
    ["history · clear", "shell basics. Tab completes, ↑ ↓ recall"],
  ];

  const commands = {
    async help() {
      line(`<span class="head">Commands</span>`, "gap");
      HELP.forEach(([c, d]) => line(`  <span class="tag">${esc(pad(c, 30))}</span><span class="dim">${esc(d)}</span>`));
      dim("Tip: try  sql SELECT name FROM skills WHERE category = 'database'");
    },

    async whoami() {
      const r = await api("GET", "/api/profile");
      if (!r || !r.ok) return showApiError(r);
      const p = r.data;
      line(`<span class="head">${esc(p.name)}</span>  ${esc(p.title)}  <span class="dim">${esc(p.location)}</span>`);
      line(esc(p.bio));
      line(`<span class="dim">${esc(p.email)} · ${esc(p.github)}</span>`);
      if (p.open_to_work) line(`<span class="s2">● open to work</span>`);
    },

    async about() {
      const r = await api("GET", "/api/profile");
      if (!r || !r.ok) return showApiError(r);
      text(r.data.bio);
    },

    async ls(args) {
      const t = (args[0] || "").replace(/\/$/, "");
      if (!t) {
        line(`<span class="tag">projects/  skills/  experience/</span>  about.md`);
        return;
      }
      if (t === "projects") {
        const r = await api("GET", "/api/projects");
        if (!r || !r.ok) return showApiError(r);
        slugs = r.data.map((p) => p.slug);
        r.data.forEach((p) => line(`<span class="tag">${esc(pad(p.slug, 20))}</span><span class="dim">${p.year}  ${esc(p.status)}</span>`));
      } else if (t === "skills") await commands.skills([]);
      else if (t === "experience") await commands.experience([]);
      else err(`ls: cannot access '${t}': no such directory`);
    },

    async cat(args) {
      const t = args[0] || "";
      if (t === "about.md") return commands.about();
      const m = t.match(/^projects\/([\w-]+)$/);
      if (!m) return err("usage: cat about.md | cat projects/<name>   (try: ls projects)");
      const r = await api("GET", `/api/projects/${m[1]}`);
      if (!r || !r.ok) return showApiError(r);
      renderProject(r.data, true);
    },

    async projects(args) {
      const r = await api("GET", "/api/projects");
      if (!r || !r.ok) return showApiError(r);
      slugs = r.data.map((p) => p.slug);
      r.data.forEach((p) => renderProject(p, false));
      dim("Run  cat projects/<name>  for details.");
    },

    async skills() {
      const r = await api("GET", "/api/skills");
      if (!r || !r.ok) return showApiError(r);
      const groups = {};
      r.data.forEach((s) => (groups[s.category] = groups[s.category] || []).push(s));
      Object.entries(groups).forEach(([cat, items]) => {
        line(`<span class="head">${esc(cat)}</span>`, "gap");
        items.forEach((s) => line(`  ${esc(pad(s.name, 18))}${bar(s.level)}`));
      });
    },

    async experience() {
      const r = await api("GET", "/api/experience");
      if (!r || !r.ok) return showApiError(r);
      r.data.forEach((e) => {
        const id = token ? `<span class="tag">#${e.id}</span> ` : "";
        line(`${id}<span class="dim">${esc(e.start)} → ${esc(e.end || "now")}</span>  <span class="head">${esc(e.role)}</span> @ ${esc(e.company)}`, "gap");
        line("  " + esc(e.summary));
      });
    },

    async sql(args, raw) {
      const q = raw.replace(/^\s*sql\s*/i, "").trim();
      if (!q) {
        line(`<span class="head">Tables</span>`, "gap");
        line("  projects    slug, title, summary, stack, year, status, repo");
        line("  skills      name, category, level");
        line('  experience  id, company, role, start, "end", summary');
        dim("Read-only. One SELECT at a time.");
        return;
      }
      const r = await api("POST", "/api/query", { sql: q });
      if (!r || !r.ok) return showApiError(r);
      if (!r.data.rows.length) return dim("(0 rows)");
      table(r.data.columns, r.data.rows);
      dim(`(${r.data.row_count} row${r.data.row_count === 1 ? "" : "s"}${r.data.truncated ? ", truncated" : ""})`);
    },

    async curl(args) {
      let method = "GET", body, path;
      for (let i = 0; i < args.length; i++) {
        if (args[i] === "-X") method = (args[++i] || "GET").toUpperCase();
        else if (args[i] === "-d") { body = args[++i]; if (method === "GET") method = "POST"; }
        else if (!args[i].startsWith("-")) path = args[i];
      }
      if (!path) return err("usage: curl [-X METHOD] [-d '{\"json\":1}'] /projects");
      if (!/^\/(api|health)/.test(path)) path = "/api" + (path.startsWith("/") ? path : "/" + path);
      let parsed;
      if (body) { try { parsed = JSON.parse(body); } catch { return err("curl: -d must be valid JSON, wrapped in single quotes"); } }
      const r = await api(method, path, parsed);
      if (r && r.data !== null) line(highlight(r.data));
    },

    async contact() {
      dim("Leave a message. Press Ctrl+C at any prompt to cancel.");
      const name = await ask("name"); if (name === null) return dim("cancelled");
      const email = await ask("email"); if (email === null) return dim("cancelled");
      const message = await ask("message"); if (message === null) return dim("cancelled");
      const r = await api("POST", "/api/contact", { name, email, message });
      if (!r) return;
      if (r.ok) { line(`<span class="s2">${esc(r.data.detail)}</span>`); line(highlight(r.data)); }
      else showApiError(r);
    },

    async status() {
      const r = await api("GET", "/api/status");
      if (!r || !r.ok) return showApiError(r);
      const s = r.data;
      const up = s.uptime_seconds, fmt = `${Math.floor(up / 3600)}h ${Math.floor((up % 3600) / 60)}m ${up % 60}s`;
      line(`<span class="head">uptime</span>        ${fmt}`, "gap");
      line(`<span class="head">requests</span>      ${s.requests}   <span class="dim">errors ${s.errors} · rate-limited ${s.rate_limited}</span>`);
      line(`<span class="head">latency</span>       p50 ${s.latency_ms.p50}ms   p95 ${s.latency_ms.p95}ms`);
      if (s.top_routes.length) {
        line(`<span class="head">top routes</span>`, "gap");
        s.top_routes.forEach(([route, n]) => line(`  ${esc(pad(route, 28))}${n}`));
      }
      if (s.recent.length) {
        line(`<span class="head">recent</span>`, "gap");
        s.recent.forEach((e) => line(`  <span class="dim">${e.time}</span>  <span class="s${String(e.status)[0]}">${e.status}</span>  ${esc(pad(e.method, 5))}${esc(pad(e.path, 26))}<span class="dim">${e.ms}ms</span>`));
      }
    },

    async login() {
      if (token) return dim("Already logged in as admin. Run logout to leave.");
      const pw = await ask("password", true);
      if (!pw) return dim("cancelled");
      const r = await api("POST", "/api/admin/login", { password: pw });
      if (!r) return;
      if (!r.ok) return showApiError(r);
      setToken(r.data.token);
      line(`<span class="s2">Logged in. Session lasts ${Math.round(r.data.expires_in / 3600)}h. Try: exp add, or experience then exp rm &lt;id&gt;</span>`);
    },

    async logout() {
      if (!token) return dim("Not logged in.");
      setToken(null);
      dim("Logged out.");
    },

    async exp(args) {
      if (args[0] === "add") return expAdd();
      if (args[0] === "rm") return expRemove(args[1]);
      err("usage: exp add | exp rm <id>   (admin only, run login first)");
    },

    async docs() {
      dim("Opening /docs in a new tab…");
      window.open("/docs", "_blank", "noopener");
    },

    async theme() { toggleTheme(); dim(`theme: ${document.documentElement.dataset.theme}`); },
    async gui() { setMode("gui"); },
    async history() { history.forEach((h, i) => dim(`${String(i + 1).padStart(3)}  ${h}`)); },
    async clear() { screen.innerHTML = ""; },
  };

  async function expAdd() {
    if (!token) return err("Admin only. Run login first.");
    dim("Add an experience. Leave end blank for a current role. Ctrl+C cancels.");
    const v = await askAll(["company", "role", "start (YYYY-MM)", "end (YYYY-MM, blank = present)", "summary"]);
    if (!v) return dim("cancelled");
    const [company, role, start, end, summary] = v;
    const r = await api("POST", "/api/experience", { company, role, start, end: end || null, summary });
    if (!r) return;
    if (!r.ok) return showApiError(r);
    guiBuilt = false;
    line(`<span class="s2">Added experience #${r.data.id}: ${esc(r.data.role)} @ ${esc(r.data.company)}</span>`);
  }

  async function expRemove(id) {
    if (!token) return err("Admin only. Run login first.");
    if (!/^\d+$/.test(id || "")) return err("usage: exp rm <id>   (run experience to see ids)");
    const ok = await ask(`delete experience #${id}? type yes`);
    if (ok !== "yes") return dim("cancelled");
    const r = await api("DELETE", `/api/experience/${id}`);
    if (!r) return;
    if (!r.ok) return showApiError(r);
    guiBuilt = false;
    line(`<span class="s2">Deleted experience #${id}.</span>`);
  }

  function renderProject(p, detailed) {
    line(`<span class="head">${esc(p.title)}</span>  <span class="dim">${p.year} · ${esc(p.status)}</span>`, "gap");
    line("  " + esc(p.summary));
    line(`  <span class="tag">${esc(p.stack.join(", "))}</span>`);
    if (detailed) {
      p.highlights.forEach((h) => line("  • " + esc(h)));
      line(`  <span class="dim">${esc(p.repo)}</span>`);
    } else {
      line(`  <span class="dim">cat projects/${esc(p.slug)}</span>`);
    }
  }

  /* ---------------- tokenizer + runner ---------------- */
  function tokenize(s) {
    const out = [];
    s.replace(/'([^']*)'|"([^"]*)"|(\S+)/g, (_, a, b, c) => out.push(a ?? b ?? c));
    return out;
  }

  async function run(raw) {
    const trimmed = raw.trim();
    line(`<span class="p">${esc(ps1.textContent)}</span> ${esc(raw)}`, "echo gap");
    if (!trimmed) return;
    if (history[history.length - 1] !== trimmed) history.push(trimmed);
    hIdx = history.length;

    const [cmd, ...args] = tokenize(trimmed);
    const fn = commands[cmd.toLowerCase()];
    if (!fn) return err(`command not found: ${cmd}. Type help to list commands.`);
    busy = true;
    try { await fn(args, trimmed); }
    catch (e) { err("Something went wrong: " + e.message); }
    finally { busy = false; }
  }

  /* ---------------- keyboard ---------------- */
  const NAMES = Object.keys(commands);

  function commonPrefix(list) {
    return list.reduce((a, b) => { let i = 0; while (i < a.length && a[i] === b[i]) i++; return a.slice(0, i); });
  }

  function complete() {
    const parts = input.value.split(/\s+/);
    let pool, prefix = "", cur;
    if (parts.length === 1) { pool = NAMES; cur = parts[0]; }
    else {
      const c = parts[0]; cur = parts[1]; prefix = c + " ";
      pool = c === "ls" ? ["projects", "skills", "experience"]
        : c === "cat" ? ["about.md", ...slugs.map((s) => "projects/" + s)] : [];
    }
    const m = pool.filter((p) => p.startsWith(cur));
    if (!m.length) return;
    if (m.length === 1) { input.value = prefix + m[0] + (parts.length === 1 ? " " : ""); return; }
    const cp = commonPrefix(m);
    if (cp.length > cur.length) input.value = prefix + cp;
    else dim(m.join("   "));
  }

  input.addEventListener("keydown", async (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      const v = input.value;
      if (reader) {
        const r = reader; reader = null;
        line(`<span class="p">${esc(ps1.textContent)}</span> ${esc(readerSecret ? "•".repeat(v.length) : v)}`, "echo");
        input.type = "text"; readerSecret = false;
        ps1.textContent = defaultPs1(); input.value = "";
        r(v.trim());
        return;
      }
      if (busy) return;
      input.value = "";
      await run(v);
    } else if (e.key === "c" && e.ctrlKey) {
      e.preventDefault();
      line(`<span class="p">${esc(ps1.textContent)}</span> ${esc(readerSecret ? "•".repeat(input.value.length) : input.value)}^C`, "echo");
      input.value = "";
      if (reader) { const r = reader; reader = null; input.type = "text"; readerSecret = false; ps1.textContent = defaultPs1(); r(null); }
    } else if (e.key === "l" && e.ctrlKey) {
      e.preventDefault(); screen.innerHTML = "";
    } else if (e.key === "Tab") {
      e.preventDefault(); if (!reader) complete();
    } else if (e.key === "ArrowUp" && !reader) {
      e.preventDefault();
      if (hIdx > 0) input.value = history[--hIdx];
    } else if (e.key === "ArrowDown" && !reader) {
      e.preventDefault();
      input.value = hIdx < history.length - 1 ? history[++hIdx] : ((hIdx = history.length), "");
    }
  });

  term.addEventListener("click", () => { if (!getSelection().toString()) input.focus(); });

  $("#chips").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-cmd]");
    if (!b || busy || reader) return;
    run(b.dataset.cmd);
    input.focus();
  });

  /* ---------------- theme + mode ---------------- */
  function toggleTheme() {
    const next = document.documentElement.dataset.theme === "ink" ? "paper" : "ink";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch { /* storage may be blocked */ }
  }
  try { const t = localStorage.getItem("theme"); if (t) document.documentElement.dataset.theme = t; } catch { /* ignore */ }
  $("#theme-btn").addEventListener("click", toggleTheme);

  let guiBuilt = false;
  function setMode(mode) {
    document.body.dataset.mode = mode;
    $("#gui").hidden = mode !== "gui";
    $("#m-term").setAttribute("aria-pressed", String(mode === "terminal"));
    $("#m-gui").setAttribute("aria-pressed", String(mode === "gui"));
    if (mode === "gui" && !guiBuilt) buildGui();
    if (mode === "terminal") input.focus();
  }
  $("#m-term").addEventListener("click", () => setMode("terminal"));
  $("#m-gui").addEventListener("click", () => setMode("gui"));

  async function buildGui() {
    const root = $("#gui");
    root.innerHTML = '<p class="dim">Loading from the API…</p>';
    try {
      const [p, projs, skills, exp] = await Promise.all(
        ["/api/profile", "/api/projects", "/api/skills", "/api/experience"].map((u) => fetch(u).then((r) => r.json()))
      );
      const byCat = {};
      skills.forEach((s) => (byCat[s.category] = byCat[s.category] || []).push(s));
      root.innerHTML = `
        <h1>${esc(p.name)}</h1>
        <div class="dim">${esc(p.title)} · ${esc(p.location)}</div>
        <p>${esc(p.bio)}</p>
        <div class="links">
          <a href="mailto:${esc(p.email)}">${esc(p.email)}</a>
          <a href="${esc(p.github)}" rel="noopener" target="_blank">GitHub</a>
          <a href="${esc(p.linkedin)}" rel="noopener" target="_blank">LinkedIn</a>
          <a href="/docs" rel="noopener" target="_blank">API docs</a>
        </div>
        <h2>Projects</h2>
        ${projs.map((x) => `
          <div class="proj">
            <h3>${esc(x.title)}</h3>
            <div class="meta">${x.year} · ${esc(x.status)}</div>
            <p>${esc(x.summary)}</p>
            <div class="chip-tags">${x.stack.map((s) => `<span>${esc(s)}</span>`).join("")}</div>
            <ul>${x.highlights.map((h) => `<li>${esc(h)}</li>`).join("")}</ul>
            <a href="${esc(x.repo)}" rel="noopener" target="_blank">Source</a>
          </div>`).join("")}
        <h2>Skills</h2>
        <div class="skillgrid">
          ${Object.entries(byCat).map(([c, items]) => `
            <div><h3>${esc(c)}</h3>${items.map((s) => `
              <div class="row"><span>${esc(s.name)}</span><span class="lv" aria-label="${s.level} of 5">${"●".repeat(s.level)}${"○".repeat(5 - s.level)}</span></div>`).join("")}
            </div>`).join("")}
        </div>
        <h2>Experience</h2>
        <div class="timeline">
          ${exp.map((e) => `
            <div class="job">
              <div class="when">${esc(e.start)} → ${esc(e.end || "now")}</div>
              <div><strong>${esc(e.role)}</strong> @ ${esc(e.company)}</div>
              <p>${esc(e.summary)}</p>
            </div>`).join("")}
        </div>
        <h2>Contact</h2>
        <form id="gui-form">
          <label>Name<input name="name" required maxlength="80"></label>
          <label>Email<input name="email" type="email" required maxlength="120"></label>
          <label>Message<textarea name="message" rows="4" required minlength="5" maxlength="2000"></textarea></label>
          <button class="send" type="submit">Send message</button>
          <div id="form-msg" class="form-msg" role="status"></div>
        </form>`;
      $("#gui-form").addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const f = Object.fromEntries(new FormData(ev.target));
        const msg = $("#form-msg");
        msg.textContent = "Sending…";
        try {
          const res = await fetch("/api/contact", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(f) });
          const d = await res.json();
          msg.className = "form-msg " + (res.ok ? "s2" : "err");
          msg.textContent = res.ok ? d.detail : (Array.isArray(d.detail) ? d.detail.map((x) => x.msg).join(", ") : d.detail);
          if (res.ok) ev.target.reset();
        } catch { msg.className = "form-msg err"; msg.textContent = "Could not reach the API."; }
      });
      guiBuilt = true;
    } catch {
      root.innerHTML = '<p class="err">Could not load data from the API.</p>';
    }
  }

  /* ---------------- boot ---------------- */
  async function typeAndRun(cmd) {
    busy = true;
    input.readOnly = true;
    for (const ch of cmd) { input.value += ch; if (!reduceMotion) await sleep(38); }
    if (!reduceMotion) await sleep(260);
    input.value = "";
    input.readOnly = false;
    busy = false;
    await run(cmd);
  }

  async function health() {
    try {
      const r = await fetch("/health");
      if (!r.ok) throw 0;
      $("#dot").className = "dot on";
      $("#api-state").textContent = "API online";
    } catch {
      $("#dot").className = "dot off";
      $("#api-state").textContent = "API unreachable";
    }
  }

  (async () => {
    health();
    ps1.textContent = defaultPs1();
    $("#who").textContent = token ? "admin@portfolio" : "guest@portfolio";
    dim("Portfolio API v1.0. Every answer below comes from a real request.");
    dim("Type help, press Tab to complete, or use the buttons underneath.");
    input.focus();
    await typeAndRun("curl /api/profile");
    input.focus();
  })();
})();
