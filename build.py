#!/usr/bin/env python3
"""
build.py — reads content/startup/*.md and content/per-request/*.md
           and generates aspnet.html

Run:    python3 build.py
Output: aspnet.html  (open in any browser, works offline)

To update content: edit any .md file, then re-run build.py.
"""

import os, json

BASE = os.path.dirname(__file__)

STARTUP_FILES = {
    "add-controllers":    "add-controllers.md",
    "add-problem-details":"add-problem-details.md",
    "add-db-context":     "add-db-context.md",
    "add-authentication": "add-authentication.md",
    "add-cors":           "add-cors.md",
    "add-health-checks":  "add-health-checks.md",
    "add-swagger-gen":    "add-swagger-gen.md",
    "add-http-client":    "add-http-client.md",
    "add-logging":        "add-logging.md",
    "service-lifetimes":  "service-lifetimes.md",
    "ordering-rules":     "ordering-rules.md",
    "the-gap":            "the-gap.md",
    "map-controllers":    "map-controllers.md",
    "istartupfilter":     "istartupfilter.md",
    "environments":       "environments.md",
}

PER_REQUEST_FILES = {
    "http-context":       "http-context.md",
    "middleware":         "middleware.md",
    "exception-handler":  "exception-handler.md",
    "status-code-pages":  "status-code-pages.md",
    "https-redirection":  "https-redirection.md",
    "static-files":       "static-files.md",
    "cors":               "cors.md",
    "authentication":     "authentication.md",
    "routing":            "routing.md",
    "rate-limiter":       "rate-limiter.md",
    "authorization":      "authorization.md",
    "health-check":       "health-check.md",
    "controller":         "controller.md",
    "filters":            "filters.md",
    "binding":            "binding.md",
    "your-action":        "your-action.md",
    "result":             "result.md",
    "response-caching":   "response-caching.md",
    "serialisation":      "serialisation.md",
}

def read(folder, filename):
    path = os.path.join(BASE, "content", folder, filename)
    with open(path, encoding="utf-8") as f:
        return f.read()

startup = {k: read("startup", v) for k, v in STARTUP_FILES.items()}
per_request = {k: read("per-request", v) for k, v in PER_REQUEST_FILES.items()}

startup_json = json.dumps(startup, ensure_ascii=False)
per_request_json = json.dumps(per_request, ensure_ascii=False)

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ASP.NET Core</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 15px;
      line-height: 1.7;
      color: #111;
      background: #f7f7f6;
    }

    /* tabs */
    .tabs {
      display: flex;
      gap: 0;
      border-bottom: 1px solid #ddd;
      background: #fff;
      padding: 0 1.5rem;
      position: sticky;
      top: 0;
      z-index: 10;
    }

    .tab {
      padding: 0.75rem 1.25rem;
      font-size: 13px;
      font-weight: 500;
      color: #777;
      cursor: pointer;
      border-bottom: 2px solid transparent;
      margin-bottom: -1px;
      transition: color 0.1s;
    }

    .tab:hover { color: #111; }
    .tab.active { color: #111; border-bottom-color: #111; }

    /* split layout */
    .split {
      display: flex;
      height: calc(100vh - 41px);
    }

    .left {
      width: 300px;
      min-width: 300px;
      border-right: 1px solid #ddd;
      background: #fff;
      overflow-y: auto;
      padding: 1.25rem 1rem;
    }

    .right {
      flex: 1;
      overflow-y: auto;
      padding: 2rem 2.5rem;
      background: #f7f7f6;
    }

    .right-empty {
      color: #aaa;
      font-size: 13px;
      margin-top: 2rem;
    }

    /* tree */
    .tree { font-family: monospace; font-size: 13px; line-height: 1.7; }
    .section-label {
      font-size: 10px;
      letter-spacing: 0.08em;
      color: #666;
      font-family: monospace;
      margin: 1rem 0 0.5rem;
    }
    .section-label:first-child { margin-top: 0; }

    .flow-label { font-size: 11px; color: #666; margin-bottom: 8px; }
    .flow-end { font-size: 11px; color: #666; margin-top: 8px; }

    .row {
      display: flex; align-items: flex-start;
      padding: 2px 4px; border-radius: 4px; cursor: pointer;
    }
    .row:hover .name, .row.active .name { color: #2563eb; }

    .branch { color: #999; white-space: pre; user-select: none; }
    .name { font-weight: 500; min-width: 0; color: #111; transition: color 0.1s; flex: 1; }
    .brief { color: #555; font-size: 11px; display: block; padding-left: 4px; }

    .gap {
      margin: 3px 0 3px 16px; padding: 4px 8px;
      border: 1px solid #ddd; border-radius: 4px;
      background: #f0f0ef; font-size: 11px; color: #444;
    }
    .gap-label { font-size: 9px; letter-spacing: 0.08em; color: #777; margin-bottom: 1px; }

    .mvc-box {
      border: 1px solid #ddd; border-radius: 4px;
      padding: 6px 8px; margin-top: 2px; flex: 1;
    }
    .mvc-label { font-size: 9px; letter-spacing: 0.08em; color: #777; margin-bottom: 4px; }

    .sub {
      display: flex; align-items: flex-start;
      padding: 1px 0; cursor: pointer; border-radius: 4px;
    }
    .sub:hover .name, .sub.active .name { color: #2563eb; }

    /* detail panel */
    .detail { max-width: 740px; }
    .detail h2 { font-size: 18px; font-weight: 600; margin: 0 0 1rem; color: #111; }
    .detail h3 { font-size: 15px; font-weight: 600; margin: 1.5rem 0 0.5rem; color: #111; }
    .detail p { color: #222; margin: 0 0 0.75rem; }
    .detail p:last-child { margin-bottom: 0; }
    .detail ul { color: #222; margin: 0 0 0.75rem 1.25rem; }
    .detail li { margin-bottom: 0.25rem; }

    .detail table {
      width: 100%; border-collapse: collapse;
      font-size: 13px; margin: 0 0 0.75rem;
    }
    .detail th {
      text-align: left; font-weight: 600;
      border-bottom: 1px solid #ddd; padding: 5px 8px 5px 0;
      color: #555; font-size: 12px;
    }
    .detail td { padding: 5px 8px 5px 0; color: #333; border-bottom: 1px solid #ebebeb; }

    .detail code {
      font-family: monospace; font-size: 12px;
      background: #ebebea; border: 1px solid #ddd;
      border-radius: 3px; padding: 0 4px; color: #111;
    }

    .detail pre {
      background: #ebebea; border: 1px solid #ddd;
      border-radius: 4px; padding: 0.75rem 1rem;
      overflow-x: auto; margin: 0 0 0.75rem;
    }
    .detail pre code {
      background: none; border: none; padding: 0;
      font-size: 12px; line-height: 1.5;
    }

    .detail strong { font-weight: 500; color: #1a1a1a; }
  </style>
</head>
<body>

<div class="tabs">
  <div class="tab active" onclick="switchTab('startup')">Startup</div>
  <div class="tab" onclick="switchTab('per-request')">Per-request</div>
</div>

<div class="split">
  <div class="left">

    <!-- startup tree -->
    <div id="tree-startup" class="tree">
      <p class="section-label">── phase 1 — register services ──</p>

      <div class="row" onclick="show('service-lifetimes', this)">
        <span class="branch">· </span><span class="name">Service lifetimes<span class="brief">Singleton · Scoped · Transient</span></span>
      </div>
      <div class="row" onclick="show('add-controllers', this)">
        <span class="branch">· </span><span class="name">AddControllers<span class="brief">MVC stack — routing, binding, filters, JSON</span></span>
      </div>
      <div class="row" onclick="show('add-problem-details', this)">
        <span class="branch">· </span><span class="name">AddProblemDetails<span class="brief">{ type, title, status, traceId } error shape</span></span>
      </div>
      <div class="row" onclick="show('add-db-context', this)">
        <span class="branch">· </span><span class="name">AddDbContext<span class="brief">database context — always Scoped</span></span>
      </div>
      <div class="row" onclick="show('add-authentication', this)">
        <span class="branch">· </span><span class="name">AddAuthentication<span class="brief">JWT verification settings</span></span>
      </div>
      <div class="row" onclick="show('add-cors', this)">
        <span class="branch">· </span><span class="name">AddCors<span class="brief">cross-domain policy</span></span>
      </div>
      <div class="row" onclick="show('add-health-checks', this)">
        <span class="branch">· </span><span class="name">AddHealthChecks<span class="brief">liveness and readiness checks</span></span>
      </div>
      <div class="row" onclick="show('add-swagger-gen', this)">
        <span class="branch">· </span><span class="name">AddSwaggerGen<span class="brief">API documentation — development only</span></span>
      </div>
      <div class="row" onclick="show('add-http-client', this)">
        <span class="branch">· </span><span class="name">AddHttpClient<span class="brief">IHttpClientFactory · named · typed clients</span></span>
      </div>
      <div class="row" onclick="show('add-logging', this)">
        <span class="branch">· </span><span class="name">Logging<span class="brief">ILogger · levels · structured logging</span></span>
      </div>
      <div class="row" onclick="show('environments', this)">
        <span class="branch">· </span><span class="name">Environments<span class="brief">Development · Staging · Production</span></span>
      </div>

      <p class="section-label">── phase 2 — declare the pipeline ──</p>

      <div class="row" onclick="show('ordering-rules', this)">
        <span class="branch">· </span><span class="name">Ordering rules<span class="brief">wrong order = silent failures</span></span>
      </div>
      <div class="row" onclick="show('the-gap', this)">
        <span class="branch">· </span><span class="name">The gap<span class="brief">UseRouting → authorization gap · auto-insertion</span></span>
      </div>
      <div class="row" onclick="show('map-controllers', this)">
        <span class="branch">· </span><span class="name">MapControllers<span class="brief">builds routing table at startup</span></span>
      </div>
      <div class="row" onclick="show('istartupfilter', this)">
        <span class="branch">· </span><span class="name">IStartupFilter<span class="brief">insert middleware before user code</span></span>
      </div>
    </div>

    <!-- per-request tree -->
    <div id="tree-per-request" class="tree" style="display:none">
      <p class="flow-label">incoming request ──────────────────────►</p>

      <div class="row" onclick="show('http-context', this)">
        <span class="branch">├── </span><span class="name">HttpContext<span class="brief">Request · Response · User · Features · Items</span></span>
      </div>
      <div class="row" onclick="show('middleware', this)">
        <span class="branch">├── </span><span class="name">Middleware<span class="brief">Use · Run · Map · class-based · IMiddleware</span></span>
      </div>
      <div class="row" onclick="show('exception-handler', this)">
        <span class="branch">├── </span><span class="name">ExceptionHandler<span class="brief">wraps everything in a try/catch</span></span>
      </div>
      <div class="row" onclick="show('status-code-pages', this)">
        <span class="branch">├── </span><span class="name">StatusCodePages<span class="brief">empty 4xx/5xx responses → error body</span></span>
      </div>
      <div class="row" onclick="show('https-redirection', this)">
        <span class="branch">├── </span><span class="name">HttpsRedirection + HSTS<span class="brief">HTTP → 301 to HTTPS · HSTS header</span></span>
      </div>
      <div class="row" onclick="show('static-files', this)">
        <span class="branch">├── </span><span class="name">StaticFiles<span class="brief">file match → serve; no match → pass through</span></span>
      </div>
      <div class="row" onclick="show('cors', this)">
        <span class="branch">├── </span><span class="name">Cors<span class="brief">Access-Control-Allow-Origin; OPTIONS preflight</span></span>
      </div>
      <div class="row" onclick="show('authentication', this)">
        <span class="branch">├── </span><span class="name">Authentication<span class="brief">verifies JWT; populates HttpContext.User</span></span>
      </div>
      <div class="row" onclick="show('routing', this)">
        <span class="branch">├── </span><span class="name">Routing<span class="brief">matches request to endpoint</span></span>
      </div>

      <div class="gap">
        <div class="gap-label">── gap ──</div>
        knows destination; hasn't acted yet
      </div>

      <div class="row" onclick="show('rate-limiter', this)">
        <span class="branch">├── </span><span class="name">RateLimiter<span class="brief">429 if limit exceeded · keyed on route values</span></span>
      </div>
      <div class="row" onclick="show('authorization', this)">
        <span class="branch">├── </span><span class="name">Authorization<span class="brief">[Authorize] → 401 / 403</span></span>
      </div>
      <div class="row" onclick="show('response-caching', this)">
        <span class="branch">├── </span><span class="name">Response caching &amp; compression<span class="brief">OutputCache · ResponseCache · Compress</span></span>
      </div>

      <div style="display:flex; align-items:flex-start;">
        <span class="branch">└── </span>
        <div class="mvc-box">
          <div class="mvc-label">MVC layer — controller-matched requests only</div>
          <div class="sub" onclick="show('health-check', this)"><span class="branch" style="color:#aaa">├── </span><span class="name">Health check<span class="brief">GET /health → bypasses MVC internals</span></span></div>
          <div class="sub" onclick="show('controller', this)"><span class="branch" style="color:#aaa">├── </span><span class="name">Controller<span class="brief">created by DI</span></span></div>
          <div class="sub" onclick="show('filters', this)"><span class="branch" style="color:#aaa">├── </span><span class="name">Filters<span class="brief">before/after action</span></span></div>
          <div class="sub" onclick="show('binding', this)"><span class="branch" style="color:#aaa">├── </span><span class="name">Binding<span class="brief">route/query/body → parameters</span></span></div>
          <div class="sub" onclick="show('your-action', this)"><span class="branch" style="color:#aaa">├── </span><span class="name">Your action<span class="brief">async; thread released on await</span></span></div>
          <div class="sub" onclick="show('result', this)"><span class="branch" style="color:#aaa">├── </span><span class="name">Result<span class="brief">Ok(data), NotFound() etc.</span></span></div>
          <div class="sub" onclick="show('serialisation', this)"><span class="branch" style="color:#aaa">└── </span><span class="name">Serialisation<span class="brief">C# object → JSON bytes</span></span></div>
        </div>
      </div>

      <p class="flow-end">◄── response unwinds in reverse ─────────</p>
    </div>

  </div>

  <div class="right">
    <p class="right-empty" id="placeholder">Select a node to read about it.</p>
    <div class="detail" id="detail" style="display:none"></div>
  </div>
</div>

<script>
const STARTUP = STARTUP_PLACEHOLDER;
const PER_REQUEST = PER_REQUEST_PLACEHOLDER;

let currentTab = 'startup';
let currentNode = null;

function switchTab(tab) {
  currentTab = tab;
  currentNode = null;

  document.querySelectorAll('.tab').forEach((t, i) => {
    t.classList.toggle('active', (i === 0) === (tab === 'startup'));
  });

  document.getElementById('tree-startup').style.display = tab === 'startup' ? '' : 'none';
  document.getElementById('tree-per-request').style.display = tab === 'per-request' ? '' : 'none';

  document.querySelectorAll('.row, .sub').forEach(r => r.classList.remove('active'));
  document.getElementById('detail').style.display = 'none';
  document.getElementById('placeholder').style.display = '';
}

function show(id, row) {
  const content = currentTab === 'startup' ? STARTUP : PER_REQUEST;
  const detail = document.getElementById('detail');
  const placeholder = document.getElementById('placeholder');
  const allRows = document.querySelectorAll('.row, .sub');

  if (currentNode === id) {
    allRows.forEach(r => r.classList.remove('active'));
    detail.style.display = 'none';
    placeholder.style.display = '';
    currentNode = null;
    return;
  }

  allRows.forEach(r => r.classList.remove('active'));
  row.classList.add('active');
  detail.innerHTML = renderMd(content[id] || '(no content found for ' + id + ')');
  detail.style.display = '';
  placeholder.style.display = 'none';
  currentNode = id;
}

function renderMd(md) {
  const lines = md.split('\\n');
  let html = '';
  let inCode = false;
  let codeLines = [];
  let paraLines = [];
  let tableRows = [];

  function esc(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function inline(text) {
    return esc(text)
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  }

  function flushPara() {
    if (!paraLines.length) return;
    html += '<p>' + inline(paraLines.join(' ')) + '</p>\\n';
    paraLines = [];
  }

  function flushTable() {
    if (!tableRows.length) return;
    let t = '<table>';
    tableRows.forEach((row, i) => {
      const cells = row.split('|').map(c => c.trim()).filter(c => c);
      if (i === 1 && cells.every(c => /^-+$/.test(c))) return;
      const tag = i === 0 ? 'th' : 'td';
      t += '<tr>' + cells.map(c => '<' + tag + '>' + inline(c) + '</' + tag + '>').join('') + '</tr>';
    });
    html += t + '</table>\\n';
    tableRows = [];
  }

  for (const line of lines) {
    if (line.startsWith('```')) {
      if (inCode) {
        html += '<pre><code>' + esc(codeLines.join('\\n')) + '</code></pre>\\n';
        codeLines = []; inCode = false;
      } else {
        flushPara(); flushTable(); inCode = true;
      }
      continue;
    }
    if (inCode) { codeLines.push(line); continue; }

    if (line.includes('|')) {
      flushPara(); tableRows.push(line); continue;
    }
    if (tableRows.length && !line.includes('|')) flushTable();

    if (line.startsWith('## '))  { flushPara(); html += '<h2>' + esc(line.slice(3)) + '</h2>\\n'; continue; }
    if (line.startsWith('### ')) { flushPara(); html += '<h3>' + esc(line.slice(4)) + '</h3>\\n'; continue; }
    if (line.startsWith('- '))   { flushPara(); html += '<ul><li>' + inline(line.slice(2)) + '</li></ul>\\n'; continue; }
    if (line.trim() === '')      { flushPara(); continue; }
    paraLines.push(line);
  }

  flushPara(); flushTable();
  return html;
}
</script>
</body>
</html>
"""

HTML = HTML.replace('STARTUP_PLACEHOLDER', startup_json)
HTML = HTML.replace('PER_REQUEST_PLACEHOLDER', per_request_json)

out = os.path.join(BASE, "aspnet.html")
with open(out, "w", encoding="utf-8") as f:
    f.write(HTML)

print(f"Built: {out}")
print(f"  startup:     {len(STARTUP_FILES)} files")
print(f"  per-request: {len(PER_REQUEST_FILES)} files")
