/**
 * ZENITH DECISION LAYER - FRONTEND CONSOLE
 * Phase B: Connection status, dual link health polling, derived readiness,
 * shell layout, and Judge Mode.
 */

(function () {
  'use strict';

  // --- DOM Elements ---
  const arenaLinkPanel = document.getElementById('arenaLinkPanel');
  const arenaStatusText = document.getElementById('arenaStatusText');
  const arenaLatency = document.getElementById('arenaLatency');
  const arenaLastChecked = document.getElementById('arenaLastChecked');
  const arenaErrorBanner = document.getElementById('arenaErrorBanner');
  const arenaEndpoint = document.getElementById('arenaEndpoint');

  const layaLinkPanel = document.getElementById('layaLinkPanel');
  const layaStatusText = document.getElementById('layaStatusText');
  const layaLatency = document.getElementById('layaLatency');
  const layaLastChecked = document.getElementById('layaLastChecked');
  const layaErrorBanner = document.getElementById('layaErrorBanner');
  const layaMockBadge = document.getElementById('layaMockBadge');
  const layaModelId = document.getElementById('layaModelId');

  const decisionStatusPanel = document.getElementById('decisionStatusPanel');
  const decisionStatusValue = document.getElementById('decisionStatusValue');
  const decisionHaltReason = document.getElementById('decisionHaltReason');
  const readinessHint = document.getElementById('readinessHint');

  const btnStartSession = document.getElementById('btnStartSession');
  const btnStopSession = document.getElementById('btnStopSession');
  const btnRecheck = document.getElementById('btnRecheck');
  const judgeModeToggle = document.getElementById('judgeModeToggle');

  const checkItemArena = document.getElementById('checkItemArena');
  const checkStatusArena = document.getElementById('checkStatusArena');
  const checkItemLaya = document.getElementById('checkItemLaya');
  const checkStatusLaya = document.getElementById('checkStatusLaya');
  const checkItemReady = document.getElementById('checkItemReady');
  const checkStatusReady = document.getElementById('checkStatusReady');

  const gameSelect = document.getElementById('gameSelect');
  const sessionModeSelect = document.getElementById('sessionModeSelect');
  const modelModeSelect = document.getElementById('modelModeSelect');
  const maxMovesInput = document.getElementById('maxMovesInput');
  const modeHint = document.getElementById('modeHint');

  const activeSessionId = document.getElementById('activeSessionId');
  const activeSessionMode = document.getElementById('activeSessionMode');
  const activeSessionChain = document.getElementById('activeSessionChain');

  const tabLiveViewer = document.getElementById('tabLiveViewer');
  const tabLogs = document.getElementById('tabLogs');
  const paneLiveViewer = document.getElementById('paneLiveViewer');
  const paneLogs = document.getElementById('paneLogs');

  // --- State Variables ---
  let isPolling = false;
  let pollTimer = null;
  const POLL_INTERVAL_MS = 3000;

  // --- Formatting Helpers ---
  function formatIsoTime(isoString) {
    if (!isoString) return '--:--:--';
    try {
      const d = new Date(isoString);
      return d.toTimeString().split(' ')[0];
    } catch (_) {
      return '--:--:--';
    }
  }

  function triggerFlash(el) {
    if (!el) return;
    el.classList.remove('flash-update');
    // Force reflow
    void el.offsetWidth;
    el.classList.add('flash-update');
  }

  // --- Update UI from Health Summary ---
  function updateHealthUI(data) {
    if (!data) return;

    // 1. Arena Link
    const arena = data.arena || {};
    const arenaStatus = (arena.status || 'disconnected').toLowerCase();
    arenaLinkPanel.setAttribute('data-status', arenaStatus);
    arenaStatusText.textContent = arenaStatus.toUpperCase();
    arenaLatency.textContent = arena.latency_ms !== null && arena.latency_ms !== undefined ? `${arena.latency_ms} ms` : '-- ms';
    arenaLastChecked.textContent = formatIsoTime(arena.last_checked);
    if (arena.details && arena.details.endpoint) {
      try {
        const u = new URL(arena.details.endpoint);
        arenaEndpoint.textContent = u.hostname;
      } catch (_) {
        arenaEndpoint.textContent = arena.details.endpoint;
      }
    }
    if (arenaStatus === 'error' && arena.error) {
      arenaErrorBanner.textContent = arena.error;
      arenaErrorBanner.style.display = 'block';
      arenaErrorBanner.title = arena.error;
    } else {
      arenaErrorBanner.style.display = 'none';
    }

    // Checklist Arena
    if (checkItemArena) {
      checkItemArena.setAttribute('data-status', arenaStatus === 'connected' ? 'ok' : 'error');
      const icon = checkItemArena.querySelector('.check-icon');
      if (icon) icon.textContent = arenaStatus === 'connected' ? '✓' : '✗';
      checkStatusArena.textContent = arenaStatus === 'connected' ? `CONNECTED (${arena.latency_ms}ms)` : (arena.error || arenaStatus.toUpperCase());
    }

    // 2. Laya Link
    const laya = data.laya || {};
    const layaStatus = (laya.status || 'disconnected').toLowerCase();
    layaLinkPanel.setAttribute('data-status', layaStatus);
    layaStatusText.textContent = layaStatus.toUpperCase();
    layaLatency.textContent = laya.latency_ms !== null && laya.latency_ms !== undefined ? `${laya.latency_ms} ms` : '-- ms';
    layaLastChecked.textContent = formatIsoTime(laya.last_checked);
    if (laya.details && laya.details.model_id) {
      layaModelId.textContent = laya.details.model_id;
    }
    const isMock = Boolean(laya.details && laya.details.is_mock) || Boolean(data.mock_mode);
    layaMockBadge.style.display = isMock ? 'inline-block' : 'none';

    if (layaStatus === 'error' && laya.error) {
      layaErrorBanner.textContent = laya.error;
      layaErrorBanner.style.display = 'block';
      layaErrorBanner.title = laya.error;
    } else {
      layaErrorBanner.style.display = 'none';
    }

    // Checklist Laya
    if (checkItemLaya) {
      checkItemLaya.setAttribute('data-status', layaStatus === 'connected' ? 'ok' : 'error');
      const icon = checkItemLaya.querySelector('.check-icon');
      if (icon) icon.textContent = layaStatus === 'connected' ? '✓' : '✗';
      checkStatusLaya.textContent = layaStatus === 'connected' ? (isMock ? 'CONNECTED (MOCK DEV)' : `CONNECTED (${laya.latency_ms}ms)`) : (laya.error || layaStatus.toUpperCase());
    }

    // 3. Derived Decision Layer Status
    const dec = data.decision_layer || {};
    const decStatus = (dec.status || 'INACTIVE').toUpperCase();
    const prevStatus = decisionStatusPanel.getAttribute('data-status');
    if (prevStatus !== decStatus) {
      decisionStatusPanel.setAttribute('data-status', decStatus);
      decisionStatusValue.textContent = decStatus;
      triggerFlash(decisionStatusPanel);
    }

    if (decStatus === 'HALTED' && dec.halt_reason) {
      decisionHaltReason.textContent = dec.halt_reason;
      decisionHaltReason.style.display = 'block';
    } else {
      decisionHaltReason.style.display = 'none';
    }

    // Checklist Decision Layer
    if (checkItemReady) {
      const isReady = decStatus === 'READY' || decStatus === 'ACTIVE';
      checkItemReady.setAttribute('data-status', isReady ? 'ok' : 'error');
      const icon = checkItemReady.querySelector('.check-icon');
      if (icon) icon.textContent = isReady ? '✓' : '○';
      checkStatusReady.textContent = decStatus;
    }

    // Start / Stop Button Controls
    if (decStatus === 'READY') {
      btnStartSession.disabled = false;
      btnStartSession.title = 'Start session with current parameters';
      btnStopSession.disabled = true;
      readinessHint.textContent = 'Both links connected. Decision layer is READY to begin.';
      readinessHint.style.color = 'var(--status-connected)';
    } else if (decStatus === 'ACTIVE') {
      btnStartSession.disabled = true;
      btnStartSession.title = 'Session currently active';
      btnStopSession.disabled = false;
      readinessHint.textContent = 'Session is actively running.';
      readinessHint.style.color = 'var(--accent-amber)';
    } else if (decStatus === 'HALTED') {
      btnStartSession.disabled = true;
      btnStopSession.disabled = false;
      readinessHint.textContent = 'Session HALTED: An external link dropped mid-run.';
      readinessHint.style.color = 'var(--status-error)';
    } else {
      // INACTIVE
      btnStartSession.disabled = true;
      btnStartSession.title = 'Start disabled until BOTH Arena and Laya links are CONNECTED (status: READY)';
      btnStopSession.disabled = true;
      readinessHint.textContent = 'Waiting for Arena and Laya links to reach READY status.';
      readinessHint.style.color = 'var(--text-muted)';
    }
  }

  // --- API Calls ---
  async function fetchHealth(force = false) {
    if (isPolling && !force) return;
    isPolling = true;
    try {
      const url = force ? '/api/health/check' : '/api/health';
      const method = force ? 'POST' : 'GET';
      const resp = await fetch(url, { method });
      if (resp.ok) {
        const data = await resp.json();
        updateHealthUI(data);
      }
    } catch (err) {
      console.warn('Health fetch error:', err);
    } finally {
      isPolling = false;
    }
  }

  async function fetchCurrentSession() {
    try {
      const resp = await fetch('/api/session/current');
      if (resp.ok) {
        const res = await resp.json();
        const sess = res.session;
        if (sess) {
          activeSessionId.textContent = sess.session_id || 'NONE';
          activeSessionMode.textContent = sess.mode ? sess.mode.toUpperCase() : '--';
          activeSessionChain.textContent = sess.hash_chain_valid !== undefined ? (sess.hash_chain_valid ? 'VALID' : 'INVALID') : 'PENDING';
        } else {
          activeSessionId.textContent = 'NONE';
          activeSessionMode.textContent = '--';
          activeSessionChain.textContent = '--';
        }
      }
    } catch (err) {
      console.warn('Current session fetch error:', err);
    }
  }

  async function startSession() {
    const mode = sessionModeSelect.value;
    const modelMode = modelModeSelect.value;
    const maxMoves = parseInt(maxMovesInput.value, 10) || 10;
    const game = gameSelect.value;

    if (mode === 'live') {
      const confirmed = window.confirm(
        'LIVE COMPETITION RUN CONFIRMATION:\n\n' +
        'Team / Agent: ZENITH\n' +
        'Game: ' + game + '\n' +
        'Mode: LIVE (Official TopGameAI Arena)\n\n' +
        'Every move will be submitted to competition servers.\n' +
        'Are you sure you want to begin a real judged session?'
      );
      if (!confirmed) return;
    }

    try {
      btnStartSession.disabled = true;
      const resp = await fetch('/api/session/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          game,
          mode,
          mock_model: modelMode === 'mock',
          max_moves: maxMoves,
        }),
      });

      const res = await resp.json();
      if (!resp.ok) {
        alert('Failed to start session: ' + (res.error || 'Unknown error'));
      } else {
        await fetchHealth(true);
        await fetchCurrentSession();
      }
    } catch (err) {
      alert('Network error while starting session: ' + err.message);
    }
  }

  async function stopSession() {
    try {
      btnStopSession.disabled = true;
      const resp = await fetch('/api/session/stop', { method: 'POST' });
      if (resp.ok) {
        await fetchHealth(true);
        await fetchCurrentSession();
      }
    } catch (err) {
      console.warn('Stop session error:', err);
    }
  }

  // --- Event Listeners ---
  btnRecheck.addEventListener('click', () => {
    btnRecheck.classList.add('flash-update');
    fetchHealth(true);
  });

  btnStartSession.addEventListener('click', startSession);
  btnStopSession.addEventListener('click', stopSession);

  // Execution mode change hint
  sessionModeSelect.addEventListener('change', () => {
    if (sessionModeSelect.value === 'live') {
      modeHint.textContent = 'WARNING: Official judged Arena run. Real network calls will be made.';
      modeHint.style.color = 'var(--status-error)';
    } else {
      modeHint.textContent = 'Simulated Arena: Safe local loop, zero network calls to competition servers.';
      modeHint.style.color = 'var(--text-muted)';
    }
  });

  // Judge Mode Toggle
  judgeModeToggle.addEventListener('change', () => {
    if (judgeModeToggle.checked) {
      document.body.classList.add('judge-mode');
      localStorage.setItem('zenith_judge_mode', '1');
    } else {
      document.body.classList.remove('judge-mode');
      localStorage.removeItem('zenith_judge_mode');
    }
  });

  // Restore Judge Mode from storage
  if (localStorage.getItem('zenith_judge_mode') === '1') {
    judgeModeToggle.checked = true;
    document.body.classList.add('judge-mode');
  }

  // Tabs
  tabLiveViewer.addEventListener('click', () => {
    tabLiveViewer.classList.add('active');
    tabLiveViewer.setAttribute('aria-selected', 'true');
    tabLogs.classList.remove('active');
    tabLogs.setAttribute('aria-selected', 'false');
    paneLiveViewer.style.display = 'flex';
    paneLogs.style.display = 'none';
  });

  tabLogs.addEventListener('click', () => {
    tabLogs.classList.add('active');
    tabLogs.setAttribute('aria-selected', 'true');
    tabLiveViewer.classList.remove('active');
    tabLiveViewer.setAttribute('aria-selected', 'false');
    paneLogs.style.display = 'flex';
    paneLiveViewer.style.display = 'none';
  });

  // --- Initialization ---
  fetchHealth(false);
  fetchCurrentSession();

  pollTimer = setInterval(() => {
    fetchHealth(false);
  }, POLL_INTERVAL_MS);

  window.addEventListener('beforeunload', () => {
    if (pollTimer) clearInterval(pollTimer);
  });

})();
