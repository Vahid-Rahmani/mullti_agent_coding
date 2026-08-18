/* Shared Agent console.  Runtime selection is a backend concern; this module
   only buffers raw user input and submits it with the owning session id. */
(function () {
  "use strict";
  class AgentTerminal {
    constructor(host, sessionId, onInput) {
      this.host = host; this.sessionId = sessionId; this.onInput = onInput;
      this.rawPty = String(sessionId || "").includes("freebuff");
      this.inputBuffer = "";
      if (window.Terminal) {
        this.term = new window.Terminal({convertEol: !this.rawPty, cursorBlink: true, scrollback: 2000,
          // Keep the embedded TUI legible while leaving room for a useful
          // number of columns/rows in the resizable Agent panel.
          fontSize: 12,
          fontFamily: 'Cascadia Mono, Consolas, "SF Mono", Menlo, monospace',
          theme: {background: "#111214", foreground: "#e7e7e7"}});
        this.term.open(host);
        this.fitAddon = null;
        if (window.FitAddon && window.FitAddon.FitAddon) {
          this.fitAddon = new window.FitAddon.FitAddon();
          this.term.loadAddon(this.fitAddon);
        }
        // The host is often constructed before its panel is attached to the
        // workflow canvas.  Fit once now and again on the first real layout
        // notification; the fallback below keeps the terminal usable even if
        // a bundled FitAddon failed to load.
        this.fit();
        if (window.ResizeObserver) {
          this._resizeObserver = new window.ResizeObserver(() => this.fit());
          this._resizeObserver.observe(host);
        }
        this.term.onData((data) => this._input(data));
        this.term.onResize(({cols, rows}) => {
          // Keep the real ConPTY grid equal to xterm's character grid.  TUI
          // apps such as FreeBuff redraw based on this signal.
          fetch(`/api/console/${encodeURIComponent(this.sessionId)}/resize`, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({cols, rows}),
          }).catch(() => {});
        });
        // Clicking anywhere in the embedded terminal must transfer keyboard
        // ownership from the dashboard prompt to this PTY terminal.
        host.addEventListener("pointerdown", (event) => {
          event.stopPropagation();
          this.focus();
        });
        host.addEventListener("click", (event) => {
          event.stopPropagation();
          this.focus();
        });
      } else {
        this.term = null;
        host.tabIndex = 0;
        this.pre = document.createElement("pre");
        this.pre.className = "freebuff-terminal-fallback";
        host.appendChild(this.pre);
        host.addEventListener("keydown", (event) => {
          if (this.onInput) { event.preventDefault(); this._input(event.key === "Enter" ? "\r" : event.key); }
        });
        host.addEventListener("pointerdown", (event) => {
          event.stopPropagation();
          host.focus();
        });
      }
    }
    fit() {
      if (this.fitAddon) {
        try { this.fitAddon.fit(); } catch (_) { /* host not laid out yet */ }
      }
      // Keep the mount/resize barrier deterministic when the optional addon
      // is unavailable or cannot measure a just-attached host.  This uses the
      // same local xterm cell metrics and never fabricates a grid size.
      if (!this.term || !this.host || !this.term.element) return;
      const width = this.host.clientWidth;
      const height = this.host.clientHeight;
      const measure = this.term.element.querySelector(".xterm-char-measure-element");
      if (!width || !height || !measure) return;
      const rect = measure.getBoundingClientRect();
      const cellWidth = rect.width / 32;
      const cellHeight = rect.height || parseFloat(window.getComputedStyle(measure).lineHeight);
      if (!Number.isFinite(cellWidth) || !Number.isFinite(cellHeight) ||
          cellWidth <= 0 || cellHeight <= 0) return;
      const cols = Math.max(2, Math.floor(width / cellWidth));
      const rows = Math.max(1, Math.floor(height / cellHeight));
      if (this.term.cols !== cols || this.term.rows !== rows) {
        this.term.resize(cols, rows);
      }
    }
    _input(data) {
      if (this.rawPty) {
        // FreeBuff is an interactive TUI: arrows, escape, backspace and
        // control keys must reach the PTY immediately, without line buffering.
        if (this.onInput && data) this.onInput(String(data));
        return;
      }
      for (const ch of String(data || "")) {
        if (ch === "\r" || ch === "\n") {
          const line = this.inputBuffer;
          this.inputBuffer = "";
          if (line.trim()) this.onInput(line);
        } else if (ch === "\b" || ch === "\x7f") {
          this.inputBuffer = this.inputBuffer.slice(0, -1);
        } else if (ch >= " " || ch === "\t") {
          this.inputBuffer += ch;
        }
      }
    }
    write(data) { if (this.term) this.term.write(data); else this.pre.textContent += data; }
    focus() { if (this.term) this.term.focus(); }
    dispose() {
      if (this._resizeObserver) this._resizeObserver.disconnect();
      if (this.term) this.term.dispose();
    }
  }
  window.AgentTerminal = AgentTerminal;
}());
