/* Session Timer
 *
 * Time is always derived from Date.now(), never from counting ticks, so it stays
 * accurate even when the tab is throttled in the background. State lives in
 * localStorage so a reload — or a second window — shows the same session.
 */

(() => {
  const STORAGE_KEY = "session-timer:v1";
  const IS_POPUP = new URLSearchParams(location.search).has("popup");

  const widget  = document.getElementById("widget");
  const clock   = document.getElementById("clock");
  const started = document.getElementById("started");
  const status  = document.getElementById("status");
  const toggle  = document.getElementById("toggle");
  const reset   = document.getElementById("reset");
  const stage   = document.getElementById("stage");
  const dock    = document.getElementById("dock");
  const popout  = document.getElementById("popout");
  const dockNote = document.getElementById("dockNote");

  // ---- State ----------------------------------------------------------

  // startedAt: wall-clock time the session first started (for the "Started 7:54 PM" line)
  // resumedAt: Date.now() of the latest resume, or null when paused
  // banked:    milliseconds accumulated before the latest resume
  let state = { startedAt: null, resumedAt: null, banked: 0 };

  function load() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) state = { ...state, ...JSON.parse(raw) };
    } catch { /* private mode or blocked storage — run in memory only */ }
  }

  function save() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch { /* ignore */ }
  }

  const isRunning = () => state.resumedAt !== null;
  const elapsed   = () => state.banked + (isRunning() ? Date.now() - state.resumedAt : 0);

  function start() {
    if (isRunning()) return;
    const now = Date.now();
    if (state.startedAt === null) state.startedAt = now;
    state.resumedAt = now;
    save(); render();
  }

  function pause() {
    if (!isRunning()) return;
    state.banked += Date.now() - state.resumedAt;
    state.resumedAt = null;
    save(); render();
  }

  function resetTimer() {
    state = { startedAt: null, resumedAt: null, banked: 0 };
    save(); render();
  }

  // ---- Render ---------------------------------------------------------

  function formatDuration(ms) {
    const total = Math.floor(ms / 1000);
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }

  const timeFmt = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" });

  function render() {
    clock.textContent = formatDuration(elapsed());

    if (state.startedAt === null) {
      widget.dataset.state = "idle";
      status.textContent = "Ready";
      started.textContent = "Not started yet";
      toggle.textContent = "Start";
    } else if (isRunning()) {
      widget.dataset.state = "running";
      status.textContent = "Live";
      started.textContent = `Started ${timeFmt.format(state.startedAt)}`;
      toggle.textContent = "Pause";
    } else {
      widget.dataset.state = "paused";
      status.textContent = "Paused";
      started.textContent = `Started ${timeFmt.format(state.startedAt)}`;
      toggle.textContent = "Resume";
    }

    // Keep the tab title useful when the page is behind other windows.
    document.title = state.startedAt === null ? "Session Timer" : `${formatDuration(elapsed())} · Session Timer`;
  }

  // The tick runs in whichever window currently hosts the widget, because a
  // hidden tab's timers get throttled while the floating window stays visible.
  let tickHandle = null;
  let tickWindow = null;

  function startTicking(win) {
    if (tickHandle !== null) tickWindow.clearInterval(tickHandle);
    tickWindow = win;
    tickHandle = win.setInterval(render, 250);
  }

  // ---- Controls -------------------------------------------------------

  toggle.addEventListener("click", () => (isRunning() ? pause() : start()));
  reset.addEventListener("click", resetTimer);

  function onKey(event) {
    if (event.target.closest("input, textarea, select")) return;
    if (event.code === "Space") { event.preventDefault(); isRunning() ? pause() : start(); }
    else if (event.key === "r" || event.key === "R") { resetTimer(); }
  }
  document.addEventListener("keydown", onKey);

  // Another window (popup fallback or a second tab) changed the session.
  window.addEventListener("storage", (event) => {
    if (event.key === STORAGE_KEY) { load(); render(); }
  });

  // ---- Floating window ------------------------------------------------

  const PIP_WIDTH = 300;
  const PIP_HEIGHT = 240; // Chrome adds its own title bar; the content area ends up ~180px tall

  async function openDocumentPip() {
    const pip = await window.documentPictureInPicture.requestWindow({ width: PIP_WIDTH, height: PIP_HEIGHT });

    // Reuse this page's stylesheet so the widget looks identical in the floating window.
    for (const sheet of document.styleSheets) {
      if (sheet.href) {
        const link = pip.document.createElement("link");
        link.rel = "stylesheet";
        link.href = sheet.href;
        pip.document.head.append(link);
      }
    }
    pip.document.title = "Session Timer";
    pip.document.body.classList.add("pip");
    pip.document.body.append(widget);
    pip.document.addEventListener("keydown", onKey);
    startTicking(pip);

    popout.disabled = true;
    dockNote.textContent = "The timer is floating. Close that window to bring it back here.";

    pip.addEventListener("pagehide", () => {
      stage.append(widget);
      startTicking(window);
      popout.disabled = false;
      dockNote.textContent = DEFAULT_NOTE;
    });
  }

  function openPopupFallback() {
    const url = new URL(location.href);
    url.searchParams.set("popup", "1");
    const features = `popup=yes,width=${PIP_WIDTH},height=${PIP_HEIGHT},left=${screen.availWidth - PIP_WIDTH - 24},top=${screen.availHeight - PIP_HEIGHT - 80}`;
    const win = window.open(url.toString(), "session-timer", features);
    if (!win) {
      dockNote.textContent = "The browser blocked the popup. Allow popups for this page and try again.";
      return;
    }
    dockNote.textContent = "Opened in a separate window. Your browser can't pin it on top, so keep it beside your teaching app.";
  }

  const DEFAULT_NOTE = dockNote.textContent;

  popout.addEventListener("click", async () => {
    try {
      if ("documentPictureInPicture" in window) await openDocumentPip();
      else openPopupFallback();
    } catch (error) {
      console.error("Could not open the floating window:", error);
      dockNote.textContent = "Couldn't open the floating window. Try clicking again.";
    }
  });

  // ---- Boot -----------------------------------------------------------

  load();

  if (IS_POPUP) {
    // This page *is* the floating window (fallback for browsers without Document PiP).
    document.body.classList.add("pip");
    dock.hidden = true;
  } else if (!("documentPictureInPicture" in window)) {
    dockNote.textContent = "Opens the timer in a separate small window. Chrome or Edge can pin it on top of other apps.";
  }

  render();
  startTicking(window);
})();
