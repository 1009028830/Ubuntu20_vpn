import json
import socket
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen


DEFAULT_UI_HOST = "127.0.0.1"
DEFAULT_UI_PORT = 7895
DEFAULT_DELAY_URL = "https://www.gstatic.com/generate_204"


def serve_ui(
    host: str = DEFAULT_UI_HOST,
    port: int = DEFAULT_UI_PORT,
    config_path: str = "/etc/mihomo/config.yaml",
    controller: Optional[str] = None,
    secret: Optional[str] = None,
    open_browser: bool = False,
) -> None:
    config_controller, config_secret = None, ""
    if controller is None or secret is None:
        try:
            config_controller, config_secret = read_controller_config(config_path)
        except PermissionError as exc:
            raise RuntimeError(f"cannot read {config_path}; run with sudo or pass --controller and --secret") from exc

    controller_url = normalize_controller_url(controller or config_controller or "127.0.0.1:9090")
    controller_secret = secret if secret is not None else config_secret
    api = MihomoController(controller_url, controller_secret)
    handler = build_handler(api)
    server = ThreadingHTTPServer((host, int(port)), handler)
    url = f"http://{host}:{port}/"

    print(f"mihomo ui: {url}")
    print(f"controller: {controller_url}")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def read_controller_config(config_path: str) -> Tuple[Optional[str], str]:
    path = Path(config_path)
    if not path.exists():
        return None, ""

    text = path.read_text(encoding="utf-8")
    controller = extract_top_level_scalar(text, "external-controller")
    secret = extract_top_level_scalar(text, "secret") or ""
    return controller, secret


def extract_top_level_scalar(text: str, key: str) -> Optional[str]:
    prefix = f"{key}:"
    for raw_line in text.splitlines():
        if raw_line.startswith((" ", "\t", "#")):
            continue
        if not raw_line.startswith(prefix):
            continue

        value = raw_line[len(prefix) :].strip()
        if not value:
            return ""
        return parse_yaml_scalar(value)
    return None


def parse_yaml_scalar(value: str) -> str:
    if value.startswith('"'):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            pass
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value.split(" #", 1)[0].strip().strip('"')


def normalize_controller_url(value: str) -> str:
    value = value.strip()
    if not value:
        return "http://127.0.0.1:9090"
    if value.startswith(":"):
        value = f"127.0.0.1{value}"
    if "://" not in value:
        value = f"http://{value}"

    parsed = urlparse(value)
    host = parsed.hostname or "127.0.0.1"
    if host in {"0.0.0.0", "::", "*"}:
        host = "127.0.0.1"
    netloc = host
    if parsed.port:
        netloc = f"{host}:{parsed.port}"
    return urlunparse((parsed.scheme or "http", netloc, parsed.path.rstrip("/"), "", "", ""))


class MihomoController:
    def __init__(self, base_url: str, secret: str = "", timeout: int = 10) -> None:
        self.base_url = base_url.rstrip("/")
        self.secret = secret
        self.timeout = timeout

    def version(self) -> Dict[str, Any]:
        return self.request_json("GET", "/version")

    def proxies(self) -> Dict[str, Any]:
        data = self.request_json("GET", "/proxies")
        proxies = data.get("proxies", {})
        groups = []
        for name, item in proxies.items():
            if isinstance(item, dict) and isinstance(item.get("all"), list):
                groups.append(
                    {
                        "name": name,
                        "type": item.get("type", ""),
                        "now": item.get("now", ""),
                        "all": item.get("all", []),
                    }
                )
        groups.sort(key=lambda group: (group["type"] != "Selector", group["name"].lower()))
        return {"groups": groups, "proxies": proxies}

    def select_proxy(self, group: str, name: str) -> Dict[str, Any]:
        return self.request_json("PUT", f"/proxies/{quote(group, safe='')}", {"name": name})

    def delay(self, name: str, timeout_ms: int = 5000, url: str = DEFAULT_DELAY_URL) -> Dict[str, Any]:
        query = urlencode({"timeout": int(timeout_ms), "url": url})
        return self.request_json("GET", f"/proxies/{quote(name, safe='')}/delay?{query}")

    def request_json(self, method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = None
        headers = {"Accept": "application/json"}
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.secret:
            headers["Authorization"] = f"Bearer {self.secret}"

        request = Request(f"{self.base_url}{path}", data=payload, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                if not raw:
                    return {"ok": True}
                return json.loads(raw.decode("utf-8"))
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(raw or f"controller returned HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(f"cannot reach mihomo controller at {self.base_url}: {exc.reason}") from exc


def build_handler(api: MihomoController):
    class MihomoUiHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            try:
                parsed = urlparse(self.path)
                if parsed.path == "/":
                    self.send_html(UI_HTML)
                    return
                if parsed.path == "/api/status":
                    self.send_json({"version": safe_call(api.version), "controller": api.base_url})
                    return
                if parsed.path == "/api/proxies":
                    self.send_json(api.proxies())
                    return
                if parsed.path == "/api/delay":
                    query = parse_qs(parsed.query)
                    name = query.get("name", [""])[0]
                    if not name:
                        self.send_error_json(400, "missing node name")
                        return
                    self.send_json(api.delay(name))
                    return

                self.send_error_json(404, "not found")
            except CLIENT_DISCONNECT_ERRORS:
                return
            except Exception as exc:
                self.send_error_json(502, str(exc))

        def do_PUT(self) -> None:
            try:
                parsed = urlparse(self.path)
                prefix = "/api/groups/"
                if parsed.path.startswith(prefix):
                    group = unquote(parsed.path[len(prefix) :])
                    body = self.read_json_body()
                    name = str(body.get("name", ""))
                    if not group or not name:
                        self.send_error_json(400, "missing group or node name")
                        return
                    self.send_json(api.select_proxy(group, name))
                    return

                self.send_error_json(404, "not found")
            except CLIENT_DISCONNECT_ERRORS:
                return
            except Exception as exc:
                self.send_error_json(502, str(exc))

        def read_json_body(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length == 0:
                return {}
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8"))

        def send_html(self, html: str) -> None:
            raw = html.encode("utf-8")
            self.send_response_bytes(200, "text/html; charset=utf-8", raw)

        def send_json(self, data: Dict[str, Any]) -> None:
            raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response_bytes(200, "application/json; charset=utf-8", raw, cache_control="no-store")

        def send_error_json(self, status: int, message: str) -> None:
            raw = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
            self.send_response_bytes(status, "application/json; charset=utf-8", raw)

        def send_response_bytes(
            self,
            status: int,
            content_type: str,
            raw: bytes,
            cache_control: Optional[str] = None,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            if cache_control:
                self.send_header("Cache-Control", cache_control)
            self.send_header("Content-Length", str(len(raw)))
            try:
                self.end_headers()
                self.wfile.write(raw)
            except CLIENT_DISCONNECT_ERRORS:
                return

        def log_message(self, _format: str, *_args: Any) -> None:
            return

    return MihomoUiHandler


CLIENT_DISCONNECT_ERRORS = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, socket.timeout)


def safe_call(func) -> Dict[str, Any]:
    try:
        return func()
    except Exception as exc:
        return {"error": str(exc)}


UI_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>mihomo 控制台</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --line: #d9dee7;
      --text: #18202d;
      --muted: #667085;
      --accent: #176b5f;
      --accent-weak: #e6f4ef;
      --warn: #a15c00;
      --bad: #b42318;
      --shadow: 0 10px 28px rgba(17, 24, 39, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      min-height: 64px;
      padding: 0 24px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }
    h1, h2 {
      margin: 0;
      font-weight: 650;
      letter-spacing: 0;
    }
    h1 { font-size: 18px; }
    h2 { font-size: 15px; }
    button {
      min-height: 34px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      padding: 0 12px;
      font: inherit;
      cursor: pointer;
      white-space: nowrap;
    }
    button:hover { border-color: #99a4b5; }
    button.primary {
      border-color: var(--accent);
      background: var(--accent);
      color: #fff;
    }
    button.ghost {
      border-color: transparent;
      background: transparent;
    }
    button:disabled {
      cursor: default;
      opacity: .55;
    }
    main {
      display: grid;
      grid-template-columns: minmax(220px, 280px) 1fr;
      min-height: calc(100vh - 64px);
    }
    aside {
      border-right: 1px solid var(--line);
      background: #fbfcfe;
      padding: 18px;
      overflow: auto;
    }
    section {
      padding: 18px 22px 28px;
      overflow: auto;
    }
    .topbar, .section-head, .status {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .topbar, .section-head {
      justify-content: space-between;
      margin-bottom: 14px;
    }
    .status {
      color: var(--muted);
      font-size: 13px;
      min-width: 0;
    }
    .status span {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      max-width: 46vw;
    }
    .groups {
      display: grid;
      gap: 8px;
      margin-top: 14px;
    }
    .group {
      width: 100%;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      align-items: center;
      min-height: 46px;
      text-align: left;
      border-radius: 6px;
      padding: 8px 10px;
    }
    .group.active {
      border-color: var(--accent);
      background: var(--accent-weak);
    }
    .name, .node-name {
      min-width: 0;
      overflow-wrap: anywhere;
    }
    .meta, .delay {
      color: var(--muted);
      font-size: 12px;
    }
    .nodes {
      display: grid;
      gap: 8px;
    }
    .node {
      display: grid;
      grid-template-columns: minmax(160px, 1fr) 92px 84px 86px;
      align-items: center;
      gap: 12px;
      min-height: 50px;
      padding: 8px 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel);
      box-shadow: var(--shadow);
    }
    .node.current {
      border-color: var(--accent);
      box-shadow: 0 0 0 1px var(--accent-weak);
    }
    .type {
      color: var(--muted);
      font-size: 12px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .delay.good { color: var(--accent); }
    .delay.warn { color: var(--warn); }
    .delay.bad { color: var(--bad); }
    .empty {
      padding: 34px 0;
      color: var(--muted);
      text-align: center;
    }
    .toast {
      position: fixed;
      right: 18px;
      bottom: 18px;
      max-width: min(420px, calc(100vw - 36px));
      padding: 10px 12px;
      border-radius: 6px;
      background: #111827;
      color: #fff;
      opacity: 0;
      transform: translateY(8px);
      transition: opacity .16s ease, transform .16s ease;
      overflow-wrap: anywhere;
    }
    .toast.show {
      opacity: 1;
      transform: translateY(0);
    }
    @media (max-width: 780px) {
      header {
        align-items: flex-start;
        flex-direction: column;
        padding: 14px 16px;
      }
      main {
        grid-template-columns: 1fr;
      }
      aside {
        border-right: 0;
        border-bottom: 1px solid var(--line);
      }
      .groups {
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      }
      section {
        padding: 16px;
      }
      .node {
        grid-template-columns: 1fr 72px;
      }
      .node .type, .node .delay {
        grid-column: 1;
      }
      .node button {
        grid-column: 2;
        grid-row: 1 / span 3;
      }
    }
  </style>
</head>
<body>
  <header>
    <h1>mihomo 控制台</h1>
    <div class="status">
      <span id="status">连接中</span>
      <button id="refresh" type="button">刷新</button>
    </div>
  </header>
  <main>
    <aside>
      <div class="section-head">
        <h2>代理组</h2>
      </div>
      <div id="groups" class="groups"></div>
    </aside>
    <section>
      <div class="topbar">
        <h2 id="group-title">节点</h2>
        <button id="test-all" type="button">测速</button>
      </div>
      <div id="nodes" class="nodes"></div>
    </section>
  </main>
  <div id="toast" class="toast"></div>
  <script>
    let state = { groups: [], proxies: {}, selectedGroup: "" };
    const el = (id) => document.getElementById(id);

    async function api(path, options = {}) {
      const response = await fetch(path, {
        ...options,
        headers: { "Content-Type": "application/json", ...(options.headers || {}) }
      });
      const text = await response.text();
      const data = text ? JSON.parse(text) : {};
      if (!response.ok) throw new Error(data.error || text || response.statusText);
      return data;
    }

    function toast(message) {
      const box = el("toast");
      box.textContent = message;
      box.classList.add("show");
      clearTimeout(box.timer);
      box.timer = setTimeout(() => box.classList.remove("show"), 2600);
    }

    async function load() {
      try {
        const [status, proxies] = await Promise.all([api("/api/status"), api("/api/proxies")]);
        state.groups = proxies.groups || [];
        state.proxies = proxies.proxies || {};
        if (!state.groups.find((group) => group.name === state.selectedGroup)) {
          const preferred = state.groups.find((group) => group.name === "PROXY") || state.groups[0];
          state.selectedGroup = preferred ? preferred.name : "";
        }
        const version = status.version && (status.version.version || status.version.meta);
        el("status").textContent = version ? `${status.controller} · ${version}` : status.controller;
        render();
      } catch (error) {
        el("status").textContent = "连接失败";
        el("groups").innerHTML = "";
        el("nodes").innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
      }
    }

    function render() {
      renderGroups();
      renderNodes();
    }

    function renderGroups() {
      const groups = el("groups");
      if (!state.groups.length) {
        groups.innerHTML = `<div class="empty">暂无代理组</div>`;
        return;
      }
      groups.innerHTML = state.groups.map((group) => `
        <button class="group ${group.name === state.selectedGroup ? "active" : ""}" type="button" data-group="${escapeAttr(group.name)}">
          <span class="name">${escapeHtml(group.name)}</span>
          <span class="meta">${escapeHtml(group.now || group.type || "")}</span>
        </button>
      `).join("");
      groups.querySelectorAll("[data-group]").forEach((button) => {
        button.addEventListener("click", () => {
          state.selectedGroup = button.dataset.group;
          render();
        });
      });
    }

    function renderNodes() {
      const group = state.groups.find((item) => item.name === state.selectedGroup);
      el("group-title").textContent = group ? `${group.name} · ${group.now || ""}` : "节点";
      const nodes = el("nodes");
      if (!group) {
        nodes.innerHTML = `<div class="empty">暂无节点</div>`;
        return;
      }
      nodes.innerHTML = group.all.map((name) => {
        const proxy = state.proxies[name] || {};
        const delay = latestDelay(proxy);
        return `
          <div class="node ${group.now === name ? "current" : ""}" data-node="${escapeAttr(name)}">
            <div class="node-name">${escapeHtml(name)}</div>
            <div class="type">${escapeHtml(proxy.type || "")}</div>
            <div class="delay ${delayClass(delay)}" data-delay="${escapeAttr(name)}">${formatDelay(delay)}</div>
            <button class="${group.now === name ? "primary" : ""}" type="button" data-select="${escapeAttr(name)}">${group.now === name ? "当前" : "选用"}</button>
          </div>
        `;
      }).join("");
      nodes.querySelectorAll("[data-select]").forEach((button) => {
        button.addEventListener("click", () => selectNode(button.dataset.select));
      });
      nodes.querySelectorAll(".node").forEach((row) => {
        row.addEventListener("dblclick", () => selectNode(row.dataset.node));
      });
    }

    async function selectNode(name) {
      const group = state.selectedGroup;
      try {
        await api(`/api/groups/${encodeURIComponent(group)}`, {
          method: "PUT",
          body: JSON.stringify({ name })
        });
        toast(`已切换到 ${name}`);
        await load();
      } catch (error) {
        toast(error.message);
      }
    }

    async function testVisibleNodes() {
      const group = state.groups.find((item) => item.name === state.selectedGroup);
      if (!group) return;
      el("test-all").disabled = true;
      try {
        const queue = [...group.all];
        const workers = Array.from({ length: Math.min(4, queue.length) }, async () => {
          while (queue.length) {
            const name = queue.shift();
            await testNode(name);
          }
        });
        await Promise.all(workers);
      } finally {
        el("test-all").disabled = false;
      }
    }

    async function testNode(name) {
      const target = delayElement(name);
      if (target) target.textContent = "测试中";
      try {
        const result = await api(`/api/delay?name=${encodeURIComponent(name)}`);
        if (target) {
          target.textContent = formatDelay(result.delay);
          target.className = `delay ${delayClass(result.delay)}`;
        }
      } catch {
        if (target) {
          target.textContent = "失败";
          target.className = "delay bad";
        }
      }
    }

    function latestDelay(proxy) {
      const history = proxy.history;
      if (!Array.isArray(history) || !history.length) return null;
      const last = history[history.length - 1];
      return typeof last.delay === "number" ? last.delay : null;
    }

    function formatDelay(delay) {
      return typeof delay === "number" && delay >= 0 ? `${delay} ms` : "-";
    }

    function delayClass(delay) {
      if (typeof delay !== "number" || delay < 0) return "";
      if (delay < 220) return "good";
      if (delay < 600) return "warn";
      return "bad";
    }

    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, (char) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }[char]));
    }

    function escapeAttr(value) {
      return escapeHtml(value);
    }

    function delayElement(name) {
      return Array.from(document.querySelectorAll("[data-delay]")).find((item) => item.dataset.delay === name);
    }

    el("refresh").addEventListener("click", load);
    el("test-all").addEventListener("click", testVisibleNodes);
    load();
  </script>
</body>
</html>
"""
