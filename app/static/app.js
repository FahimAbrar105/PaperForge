/* Paper Forge front end: plain JavaScript, no framework, no external downloads. */
(function () {
  "use strict";

  const STEPS = ["Upload Handler", "Venue Analyst", "Content Structurer", "LaTeX Formatter", "Compiler", "QA & Repair", "Report Generator"];
  const TERMINAL = ["completed", "failed", "cancelled"];
  const STATUS_LABEL = { compliant: "layout checks passed", needs_attention: "needs attention", failed: "checks failed" };

  function $(id) { return document.getElementById(id); }
  function el(tag, attrs, text) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => node.setAttribute(k, v));
    if (text !== undefined) node.textContent = text;
    return node;
  }
  // The server's error message: a string, or FastAPI's list of field errors.
  function errorText(body, fallback) {
    const detail = body && body.detail;
    if (!detail) return fallback;
    if (Array.isArray(detail)) return detail.map(d => (d.loc ? d.loc.slice(-1)[0] + ": " : "") + d.msg).join("\n");
    return detail;
  }
  async function api(url, options) {
    const res = await fetch(url, options);
    let body = null;
    try { body = await res.json(); } catch (e) { body = null; }
    if (!res.ok) throw new Error(errorText(body, res.statusText));
    return body;
  }
  function putSettings(payload) {
    return api("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  }
  function checkedValue(root, name, fallback) {
    const input = root.querySelector('input[name="' + name + '"]:checked');
    return input ? input.value : fallback;
  }
  function paperName(j) {
    const manuscript = j.files.find(f => f.kind === "manuscript");
    return j.title || (manuscript && manuscript.original_name) || "Job " + j.job_id;
  }
  function fmtTime(iso) {
    try { return new Date(iso).toLocaleTimeString(); } catch (e) { return ""; }
  }
  function fmtDate(iso) {
    try {
      return new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
    } catch (e) { return iso; }
  }
  function sizeMB(n) { return (n / 1048576).toFixed(n < 104858 ? 2 : 1) + " MB"; }
  function cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : ""; }

  /* ------------------------------------------------------------------ theme */
  // The page's <head> sets data-theme before the first paint; this keeps the toggle in step.
  function initTheme() {
    const root = document.documentElement, button = $("theme-toggle");
    const media = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
    function chosen() { try { return localStorage.getItem("pf-theme"); } catch (e) { return null; } }
    function apply(theme) {
      root.setAttribute("data-theme", theme);
      if (button) button.setAttribute("aria-pressed", String(theme === "dark"));
    }
    apply(root.getAttribute("data-theme") === "dark" ? "dark" : "light");
    if (button) button.addEventListener("click", () => {
      const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      apply(next);
      try { localStorage.setItem("pf-theme", next); } catch (e) { /* not remembered */ }
    });
    if (media && media.addEventListener) media.addEventListener("change", e => { if (!chosen()) apply(e.matches ? "dark" : "light"); });
  }

  const LEVEL_LABEL = { off: "Off", partial: "Partial", full: "Full" };
  // Why a job did less with the AI than asked, from the report's ai_usage once it is loaded.
  function lessAI(usage, got) {
    if (!usage) return "";
    if (usage.limit_hit) return " (AI limit reached)";
    if (got === "partial") return " (rules took over some steps)";
    return usage.calls ? " (no usable AI answer)" : " (no AI provider answered)";
  }
  function agenticText(j, usage) {
    const asked = LEVEL_LABEL[j.agentic_level] || j.agentic_level;
    const got = j.agentic_achieved;
    if (!got) return "Agentic: " + asked;
    if (j.agentic_level === "full" && got === "partial") return "Agentic: Full → partly" + lessAI(usage, got);
    if (got === "off" && j.agentic_level !== "off") return "Agentic: " + asked + " → rules only" + lessAI(usage, got);
    if (got === "partial" && usage && !usage.steps.some(s => s.actor === "ai")) return "Agentic: Partial (no step needed the AI)";
    return "Agentic: " + (LEVEL_LABEL[got] || got);
  }

  /* ------------------------------------------------------------------ index */
  function initIndex() {
    const files = [];
    const input = $("file-input"), drop = $("drop"), list = $("file-list"), submit = $("submit-btn");

    const anonymous = new Set();
    api("/api/venues").then(venues => {
      const sel = $("venue");
      sel.innerHTML = "";
      venues.forEach(v => {
        const opt = el("option", { value: v.venue_id }, v.display_name + (v.available ? "" : " (unavailable)"));
        if (!v.available) opt.disabled = true;
        if (v.anonymous_submission) anonymous.add(v.venue_id);
        sel.appendChild(opt);
      });
      if (!venues.length) sel.appendChild(el("option", { value: "" }, "No venues installed"));
      refresh();
    }).catch(err => { $("upload-error").textContent = "Could not load venues: " + err.message; });

    function setMode(value) {
      document.querySelectorAll('input[name="agentic_level"]').forEach(r => { r.checked = r.value === value; });
    }
    setMode("off");
    api("/api/settings").then(s => {
      const ready = s.ai_ready;
      document.querySelectorAll('input[name="agentic_level"]').forEach(r => {
        if (r.value !== "off" && !ready) {
          r.disabled = true;
          r.closest(".mode").classList.add("disabled");
        }
      });
      setMode(ready ? s.agentic_level : "off");
      $("ai-note").textContent = ready
        ? "(AI provider: " + s.ai_provider + ")"
        : "(Full and Partial need an AI provider: add a free Gemini key in Settings)";
      if (!s.tectonic_found) $("upload-error").textContent = "Tectonic (the LaTeX compiler) was not found. Start Paper Forge with run.bat or run.sh so it can be set up.";
    }).catch(() => {});

    function refresh() {
      list.innerHTML = "";
      files.forEach((f, i) => {
        const li = el("li");
        li.appendChild(el("span", { class: "name" }, f.name));
        li.appendChild(el("span", { class: "size" }, sizeMB(f.size)));
        const rm = el("button", { type: "button", "aria-label": "Remove " + f.name, title: "Remove" }, "×");
        rm.addEventListener("click", () => { files.splice(i, 1); refresh(); });
        li.appendChild(rm);
        list.appendChild(li);
      });
      submit.disabled = !files.length || !$("venue").value;
      $("version-row").hidden = !anonymous.has($("venue").value);
    }
    function addFiles(fileList) {
      Array.from(fileList).forEach(f => {
        if (!files.some(x => x.name === f.name && x.size === f.size)) files.push(f);
      });
      refresh();
    }
    drop.addEventListener("click", () => input.click());
    drop.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
    input.addEventListener("change", () => { addFiles(input.files); input.value = ""; });
    ["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
    drop.addEventListener("drop", e => addFiles(e.dataTransfer.files));
    $("venue").addEventListener("change", refresh);

    $("upload-form").addEventListener("submit", e => {
      e.preventDefault();
      $("upload-error").textContent = "";
      const data = new FormData();
      data.append("venue_id", $("venue").value);
      data.append("agentic_level", checkedValue(document, "agentic_level", "off"));
      if (!$("version-row").hidden) data.append("camera_ready", $("version").value === "camera_ready");
      files.forEach(f => data.append("files", f, f.name));
      const xhr = new XMLHttpRequest();
      const bar = $("progress");
      bar.hidden = false; bar.value = 0; submit.disabled = true;
      xhr.upload.addEventListener("progress", ev => { if (ev.lengthComputable) bar.value = Math.round(ev.loaded / ev.total * 100); });
      xhr.addEventListener("load", () => {
        let body = {};
        try { body = JSON.parse(xhr.responseText); } catch (err) { body = {}; }
        if (xhr.status >= 200 && xhr.status < 300 && body.job_id) {
          window.location.href = "/jobs/" + body.job_id;
        } else {
          bar.hidden = true; submit.disabled = false;
          $("upload-error").textContent = errorText(body, "Upload failed (HTTP " + xhr.status + ").");
        }
      });
      xhr.addEventListener("error", () => { bar.hidden = true; submit.disabled = false; $("upload-error").textContent = "Upload failed: Paper Forge is not reachable."; });
      xhr.open("POST", "/api/jobs");
      xhr.send(data);
    });

    loadHistory();
    setInterval(loadHistory, 5000);
  }

  async function loadHistory() {
    let jobs;
    try { jobs = await api("/api/jobs"); } catch (e) { return; }
    const box = $("history");
    if (!jobs.length) { box.innerHTML = '<p class="empty">No jobs yet.</p>'; return; }
    const table = el("table");
    const head = el("tr");
    ["Paper", "Started", "Status", "Downloads", ""].forEach(h => head.appendChild(el("th", {}, h)));
    table.appendChild(head);
    jobs.forEach(j => {
      const tr = el("tr");
      const name = el("td");
      name.appendChild(el("a", { href: "/jobs/" + j.job_id }, paperName(j)));
      tr.appendChild(name);
      tr.appendChild(el("td", {}, fmtDate(j.created_at)));
      const st = el("td");
      const markers = el("div", { class: "markers" });
      markers.appendChild(el("span", { class: "status s-" + j.status }, cap(j.status)));
      if (j.overall_status) markers.appendChild(el("span", { class: "status s-" + j.overall_status }, cap(STATUS_LABEL[j.overall_status] || j.overall_status)));
      if (j.agentic_level && j.agentic_level !== "off") markers.appendChild(el("span", { class: "hint" }, agenticText(j)));
      st.appendChild(markers);
      tr.appendChild(st);
      const dl = el("td");
      const links = el("div", { class: "dl-links" });
      dl.appendChild(links);
      [["pdf", "PDF"], ["zip", "ZIP"], ["report", "Report"]].forEach(([k, label]) => {
        if (j.downloads && j.downloads[k]) {
          const a = el("a", { href: `/api/jobs/${j.job_id}/download/${k}` }, label);
          if (k === "report") a.target = "_blank";
          links.appendChild(a);
        }
      });
      tr.appendChild(dl);
      const act = el("td");
      if (TERMINAL.includes(j.status)) {
        const del = el("button", { class: "danger", type: "button" }, "Delete");
        del.addEventListener("click", async () => {
          if (!confirm("Delete this job and its files?")) return;
          try { await api("/api/jobs/" + j.job_id, { method: "DELETE" }); loadHistory(); } catch (err) { alert(err.message); }
        });
        act.appendChild(del);
      }
      tr.appendChild(act);
      table.appendChild(tr);
    });
    box.innerHTML = "";
    box.appendChild(table);
  }

  const AI_WAIT = "Waiting for the AI's answer. Free Gemini keys are often slow when Google's servers are busy. If the model does not answer, Paper Forge tries other models, and if none answers, this step uses its built-in rules.";
  function waitingHint(step, usesAI) {
    if (step === "Compiler") return "Compiling the PDF with LaTeX. This takes longer when LaTeX first has to download the files a template needs.";
    if (step === "QA & Repair") return "Recompiling and checking the PDF." + (usesAI ? " " + AI_WAIT : "");
    if (usesAI && ["Content Structurer", "LaTeX Formatter", "Report Generator"].includes(step)) return AI_WAIT;
    return "";
  }

  /* -------------------------------------------------------------------- job */
  function initJob() {
    const jobId = window.location.pathname.split("/").filter(Boolean).pop();
    const log = $("log");
    let lastSeq = 0;
    let assistantStarted = false;
    let usage = null, usageRequested = false;  // the report's ai_usage
    let job = null, lastLineAt = Date.now();
    const seen = new Set();

    function renderSteps(current, status) {
      const ul = $("steps");
      ul.innerHTML = "";
      const curBase = (current || "").replace(/ \(.*\)$/, "");
      const idx = STEPS.indexOf(curBase);
      STEPS.forEach((s, i) => {
        let cls = "", state = "";
        if (status === "completed" || current === "Done" || (idx >= 0 && i < idx)) { cls = "done"; state = "Done"; }
        else if (i === idx && !TERMINAL.includes(status)) { cls = "now"; state = "In progress"; }
        const li = el("li", { class: cls }, s);
        if (state) li.appendChild(el("span", { class: "state" }, state));
        if (cls === "now") li.setAttribute("aria-current", "step");
        ul.appendChild(li);
      });
    }
    function addEvent(e) {
      if (seen.has(e.seq)) return;
      seen.add(e.seq);
      lastSeq = Math.max(lastSeq, e.seq);
      lastLineAt = Date.now();
      const line = el("div", { class: e.level });
      line.appendChild(el("span", { class: "t" }, fmtTime(e.timestamp) + "  "));
      line.appendChild(el("span", { class: "step" }, e.step + ": "));
      line.appendChild(document.createTextNode(e.message));
      const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 30;
      log.appendChild(line);
      if (atBottom) log.scrollTop = log.scrollHeight;
    }
    function setLink(id, enabled, href) {
      const a = $(id);
      a.classList.toggle("disabled", !enabled);
      a.setAttribute("href", enabled ? href : "#");
    }
    function showProgress() {
      const live = $("log-live");
      live.hidden = !job || TERMINAL.includes(job.status);
      if (live.hidden) return;
      const step = (job.current_step || "").replace(/ \(.*\)$/, "");
      const quiet = Math.round((Date.now() - lastLineAt) / 1000);
      $("log-live-text").textContent = (step ? "Working on " + step : "Starting") + "... " + quiet + " s since the last update";
      $("log-live-hint").textContent = quiet >= 15 ? waitingHint(step, job.agentic_level && job.agentic_level !== "off") : "";
    }
    setInterval(showProgress, 1000);
    function renderJob(j) {
      job = j;
      $("job-title").textContent = paperName(j);
      const st = $("job-status");
      st.textContent = cap(j.status) + (j.overall_status ? " · " + (STATUS_LABEL[j.overall_status] || j.overall_status) : "");
      st.className = "status s-" + (j.overall_status && j.status === "completed" ? j.overall_status : j.status);
      $("job-step").textContent = TERMINAL.includes(j.status) ? "" : (j.current_step || "Waiting to start...");
      const pill = $("job-agentic");
      pill.textContent = agenticText(j, usage);
      pill.className = "pill " + (j.agentic_achieved || j.agentic_level || "off");
      $("job-error").textContent = j.error || "";
      setLink("dl-pdf", j.downloads.pdf, `/api/jobs/${jobId}/download/pdf`);
      setLink("dl-zip", j.downloads.zip, `/api/jobs/${jobId}/download/zip`);
      setLink("dl-report", j.downloads.report, `/api/jobs/${jobId}/download/report`);
      $("cancel-btn").hidden = TERMINAL.includes(j.status);
      renderSteps(j.current_step, j.status);
      if (j.agentic_achieved && j.agentic_level !== "off" && !usageRequested) {
        usageRequested = true;
        api(`/api/jobs/${jobId}/download/report-json`).then(r => {
          usage = r.ai_usage;
          pill.textContent = agenticText(j, usage);
          $("job-models").textContent = usage.models.length ? (usage.models.length > 1 ? "Models used: " : "Model used: ") + usage.models.join(", ") : "";
        }).catch(() => {});
      }
      if (TERMINAL.includes(j.status) && !assistantStarted) {
        assistantStarted = true;
        initAssistant(jobId);
      }
      document.title = paperName(j) + " · " + cap(j.status) + " · Paper Forge";
      showProgress();
    }

    $("cancel-btn").addEventListener("click", async () => {
      $("cancel-btn").disabled = true;
      try { await api(`/api/jobs/${jobId}/cancel`, { method: "POST" }); } catch (e) { $("job-error").textContent = e.message; }
    });

    api("/api/jobs/" + jobId).then(j => {
      j.events.forEach(addEvent);
      renderJob(j);
      if (!TERMINAL.includes(j.status)) stream();
    }).catch(err => { $("job-error").textContent = err.message; });

    function stream() {
      if (!window.EventSource) { poll(); return; }
      const es = new EventSource(`/api/jobs/${jobId}/events?after=${lastSeq}`);
      es.addEventListener("log", ev => addEvent(JSON.parse(ev.data)));
      es.addEventListener("status", ev => renderJob(JSON.parse(ev.data)));
      es.addEventListener("done", () => es.close());
      es.onerror = () => { es.close(); setTimeout(poll, 1500); };
    }
    async function poll() {
      try {
        const j = await api("/api/jobs/" + jobId);
        j.events.forEach(addEvent);
        renderJob(j);
        if (!TERMINAL.includes(j.status)) setTimeout(poll, 1500);
      } catch (e) { setTimeout(poll, 3000); }
    }
  }

  /* -------------------------------------------------------------- assistant */
  const ANSWER_SOURCE = { rules: "Paper Forge (built-in answer)", gemini: "Gemini", ollama: "Ollama" };

  function initAssistant(jobId) {
    const url = `/api/jobs/${jobId}/assistant`;
    const chat = $("chat"), question = $("question");
    let about = null;  // the issue that follow-up questions are about

    function setAbout(issue) {
      about = issue;
      $("ask-about").hidden = !issue;
      $("ask-about-text").textContent = issue ? issue.message : "";
    }
    function copy(pre, button) {
      const done = () => { button.textContent = "Copied"; setTimeout(() => { button.textContent = "Copy"; }, 1500); };
      const select = () => {
        const range = document.createRange();
        range.selectNodeContents(pre);
        window.getSelection().removeAllRanges();
        window.getSelection().addRange(range);
      };
      if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(pre.textContent).then(done, select);
      else select();
    }
    function addMessage(m) {
      const box = el("div", { class: "msg " + (m.role === "user" ? "user" : "bot") });
      if (m.role !== "user") box.appendChild(el("div", { class: "who" }, (ANSWER_SOURCE[m.source] || m.source) + (m.model ? " · " + m.model : "")));
      box.appendChild(el("div", { class: "text" }, m.text));
      if (m.suggested_text) {
        const wrap = el("div", { class: "suggest" });
        const head = el("div", { class: "suggest-head" });
        head.appendChild(el("span", {}, "Suggested text (check it, then paste it into your source)"));
        const pre = el("pre", {}, m.suggested_text);
        const button = el("button", { type: "button", class: "secondary" }, "Copy");
        button.addEventListener("click", () => copy(pre, button));
        head.appendChild(button);
        wrap.appendChild(head);
        wrap.appendChild(pre);
        box.appendChild(wrap);
      }
      if (m.note) box.appendChild(el("div", { class: "note" }, m.note));
      chat.appendChild(box);
      chat.scrollTop = chat.scrollHeight;
    }
    function setBusy(busy) {
      document.querySelectorAll("#assistant button").forEach(b => { b.disabled = busy; });
      $("ask-btn").textContent = busy ? "Thinking..." : "Ask";
    }
    async function ask(payload) {
      $("assistant-error").textContent = "";
      setBusy(true);
      const waiting = el("div", { class: "msg bot waiting" }, "Thinking...");
      chat.appendChild(waiting);
      chat.scrollTop = chat.scrollHeight;
      const started = Date.now();
      const ticker = setInterval(() => {
        waiting.textContent = "Thinking... " + Math.round((Date.now() - started) / 1000) + " s";
      }, 1000);
      try {
        const r = await api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        r.messages.forEach(addMessage);
        return true;
      } catch (err) {
        $("assistant-error").textContent = err.message;
        return false;
      } finally {
        clearInterval(ticker);
        waiting.remove();
        setBusy(false);
      }
    }
    function renderIssues(issues) {
      const list = $("issues");
      list.innerHTML = "";
      $("issue-count").textContent = "(" + issues.length + ")";
      if (!issues.length) list.appendChild(el("li", { class: "empty" }, "No open issues: every check passed. You can still ask about the venue's guidelines."));
      issues.forEach(issue => {
        const li = el("li", { class: "k-" + issue.status });
        const text = el("div");
        text.appendChild(el("span", { class: "kind" }, issue.label));
        text.appendChild(el("span", {}, issue.message));
        li.appendChild(text);
        const help = el("button", { type: "button", class: "secondary" }, "Help me fix this");
        help.addEventListener("click", () => { setAbout(issue); ask({ issue_id: issue.id }); });
        li.appendChild(help);
        list.appendChild(li);
      });
    }

    $("ask-form").addEventListener("submit", async e => {
      e.preventDefault();
      const text = question.value.trim();
      if (!text) { question.focus(); return; }
      if (await ask({ question: text, issue_id: about ? about.id : null })) question.value = "";
    });
    question.addEventListener("keydown", e => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("ask-form").requestSubmit(); }
    });
    $("ask-about-clear").addEventListener("click", () => setAbout(null));
    $("chat-clear").addEventListener("click", async () => {
      if (!confirm("Clear this conversation?")) return;
      try { await api(url, { method: "DELETE" }); chat.innerHTML = ""; setAbout(null); } catch (err) { $("assistant-error").textContent = err.message; }
    });

    api(url).then(data => {
      $("assistant").hidden = false;
      $("assistant-privacy").textContent = data.privacy;
      renderIssues(data.issues);
      data.messages.forEach(addMessage);
    }).catch(() => {});  // no report (cancelled, or stopped before the report): no assistant
  }

  /* --------------------------------------------------------------- settings */
  function initSettings() {
    const form = $("settings-form");
    function fill(s) {
      form.querySelectorAll('input[name="agentic_level"]').forEach(r => { r.checked = r.value === s.agentic_level; });
      form.querySelectorAll('input[name="ai_provider"]').forEach(r => { r.checked = r.value === s.ai_provider; });
      $("max_agent_calls").value = s.max_agent_calls;
      showModels(s);
      $("ollama_enabled").checked = s.ollama_enabled;
      $("ollama_base_url").value = s.ollama_base_url;
      $("ollama_model").value = s.ollama_model;
      $("gemini_api_key").value = "";
      $("key-state").textContent = s.gemini_key_set ? "(saved: " + s.gemini_key_masked + ")" : "(not set)";
      if (s.effective_retention_days !== undefined) $("retention_days").value = s.effective_retention_days;
      if (s.tectonic_found !== undefined) $("tectonic-state").textContent = s.tectonic_found ? "LaTeX compiler (Tectonic): found." : "LaTeX compiler (Tectonic): NOT found. Start Paper Forge with run.bat or run.sh.";
    }
    function load() { api("/api/settings").then(fill).catch(err => { $("settings-error").textContent = err.message; }); }
    function setModels(models, chosen) {
      const select = $("gemini_model");
      select.innerHTML = "";
      if (!models.some(m => m.name === chosen)) {
        models = [{ name: chosen, label: models.length ? chosen + ": not offered to your key now" : chosen }].concat(models);
      }
      models.forEach(m => select.appendChild(el("option", { value: m.name }, m.label.startsWith(m.name) ? m.label : m.label + " (" + m.name + ")")));
      select.value = chosen;
    }
    function showModels(s) {
      setModels([], s.gemini_model);
      $("model-error").textContent = "";
      if (!s.gemini_key_set) { $("model-error").textContent = "Save your API key to choose from the models it can use."; return; }
      api("/api/settings/gemini-models")
        .then(r => setModels(r.models, s.gemini_model))
        .catch(err => { $("model-error").textContent = "Could not get the model list from Google: " + err.message + ". The saved model is still used."; });
    }
    load();

    form.addEventListener("submit", async e => {
      e.preventDefault();
      $("settings-error").textContent = ""; $("save-msg").textContent = "";
      const level = checkedValue(form, "agentic_level", "off");
      const provider = checkedValue(form, "ai_provider", "gemini");
      const payload = {
        agentic_level: level,
        ai_provider: provider,
        max_agent_calls: Math.min(30, Math.max(1, parseInt($("max_agent_calls").value || "12", 10))),
        gemini_model: $("gemini_model").value.trim(),
        ollama_enabled: $("ollama_enabled").checked,
        ollama_base_url: $("ollama_base_url").value.trim(),
        ollama_model: $("ollama_model").value.trim(),
        retention_days: parseInt($("retention_days").value || "0", 10),
      };
      const key = $("gemini_api_key").value.trim();
      if (key) payload.gemini_api_key = key;
      const noKey = !key && $("key-state").textContent.indexOf("not set") >= 0;
      if (level !== "off" && provider === "gemini" && noKey && !$("ollama_enabled").checked) {
        $("settings-error").textContent = "Full and Partial modes with Gemini need an API key. Paste one above, or choose Off.";
        return;
      }
      try {
        await putSettings(payload);
        $("save-msg").innerHTML = '<span class="ok">Saved.</span>';
        load();
      } catch (err) { $("settings-error").textContent = err.message; }
    });
    $("clear-key").addEventListener("click", async () => {
      if (!confirm("Remove the saved Gemini API key?")) return;
      try {
        await putSettings({ clear_gemini_key: true, agentic_level: "off" });
        load();
      } catch (err) { $("settings-error").textContent = err.message; }
    });
    async function test(provider) {
      $("settings-error").textContent = ""; $("save-msg").textContent = "Testing " + provider + "...";
      try {
        const model = provider === "gemini" ? "&model=" + encodeURIComponent($("gemini_model").value) : "";
        const r = await api("/api/settings/test-ai?provider=" + provider + model, { method: "POST" });
        $("save-msg").innerHTML = "";
        $("save-msg").appendChild(el("span", { class: r.ok ? "ok" : "error" }, r.message));
      } catch (err) { $("save-msg").textContent = ""; $("settings-error").textContent = err.message; }
      $("save-msg").parentNode.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
    $("test-gemini").addEventListener("click", () => test("gemini"));
    $("test-ollama").addEventListener("click", () => test("ollama"));
  }

  initTheme();
  window.PF = { initIndex, initJob, initSettings };
})();
