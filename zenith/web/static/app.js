/**
 * ZENITH DECISION LAYER - FRONTEND CONSOLE
 * Phase B & C & Requested Extensions:
 * - Real-time SSE streaming for live decision viewer
 * - Dark minimalist styling
 * - Full Snake 12x12 and 2048 4x4 state grid rendering
 * - Export as .CSV, download .JSONL, verify cryptographic hash chain
 * - Tabular log viewer with filtering, search, and row drawer
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
  const promptVersionSelect = document.getElementById('promptVersionSelect');
  const promptVersionGroup = document.getElementById('promptVersionGroup');
  const maxMovesInput = document.getElementById('maxMovesInput');
  const modeHint = document.getElementById('modeHint');
  const currentStageBadge = document.getElementById('currentStageBadge');

  const activeSessionId = document.getElementById('activeSessionId');
  const activeSessionMode = document.getElementById('activeSessionMode');
  const activeSessionChain = document.getElementById('activeSessionChain');

  // Tabs
  const tabLiveViewer = document.getElementById('tabLiveViewer');
  const tabLogs = document.getElementById('tabLogs');
  const paneLiveViewer = document.getElementById('paneLiveViewer');
  const paneLogs = document.getElementById('paneLogs');

  // Live Viewer Elements
  const emptyStateViewer = document.getElementById('emptyStateViewer');
  const liveActiveContainer = document.getElementById('liveActiveContainer');
  const liveGameBadge = document.getElementById('liveGameBadge');
  const liveSessionIdTag = document.getElementById('liveSessionIdTag');
  const liveModeBadge = document.getElementById('liveModeBadge');
  const liveStepCounter = document.getElementById('liveStepCounter');
  const liveScoreCounter = document.getElementById('liveScoreCounter');
  const liveMoveResultBadge = document.getElementById('liveMoveResultBadge');

  const snakeBoardWrapper = document.getElementById('snakeBoardWrapper');
  const game2048BoardWrapper = document.getElementById('game2048BoardWrapper');
  const snakeGrid = document.getElementById('snakeGrid');
  const grid2048 = document.getElementById('grid2048');
  const boardMeta = document.getElementById('boardMeta');
  const boardMetric1 = document.getElementById('boardMetric1');
  const boardMetric2 = document.getElementById('boardMetric2');
  const boardMetric3 = document.getElementById('boardMetric3');

  const liveQuestionText = document.getElementById('liveQuestionText');
  const decisionSourceTag = document.getElementById('decisionSourceTag');
  const liveChosenAction = document.getElementById('liveChosenAction');
  const liveConfidence = document.getElementById('liveConfidence');
  const liveSourceBadge = document.getElementById('liveSourceBadge');
  const liveDecideMs = document.getElementById('liveDecideMs');
  const liveApiMs = document.getElementById('liveApiMs');
  const liveTurnMs = document.getElementById('liveTurnMs');

  const probRowUp = document.getElementById('probRowUp');
  const probBarUp = document.getElementById('probBarUp');
  const probValUp = document.getElementById('probValUp');
  const probRowDown = document.getElementById('probRowDown');
  const probBarDown = document.getElementById('probBarDown');
  const probValDown = document.getElementById('probValDown');
  const probRowLeft = document.getElementById('probRowLeft');
  const probBarLeft = document.getElementById('probBarLeft');
  const probValLeft = document.getElementById('probValLeft');
  const probRowRight = document.getElementById('probRowRight');
  const probBarRight = document.getElementById('probBarRight');
  const probValRight = document.getElementById('probValRight');

  const fallbackMeterText = document.getElementById('fallbackMeterText');
  const fallbackMeterFill = document.getElementById('fallbackMeterFill');

  const liveAuditCard = document.getElementById('liveAuditCard');
  const auditScore = document.getElementById('auditScore');
  const auditOutcome = document.getElementById('auditOutcome');
  const auditHashStatus = document.getElementById('auditHashStatus');

  // Export Buttons
  const btnExportCsv = document.getElementById('btnExportCsv');
  const btnExportPdf = document.getElementById('btnExportPdf');
  const btnDownloadJsonl = document.getElementById('btnDownloadJsonl');
  const btnVerifyChain = document.getElementById('btnVerifyChain');
  const btnLiveExportCsv = document.getElementById('btnLiveExportCsv');
  const btnLiveExportPdf = document.getElementById('btnLiveExportPdf');
  const btnLiveDownloadJsonl = document.getElementById('btnLiveDownloadJsonl');
  const btnLiveVerify = document.getElementById('btnLiveVerify');
  const btnLogsExportCsv = document.getElementById('btnLogsExportCsv');
  const btnLogsExportPdf = document.getElementById('btnLogsExportPdf');
  const btnLogsDownload = document.getElementById('btnLogsDownload');
  const btnLogsVerify = document.getElementById('btnLogsVerify');

  // Logs Elements
  const sessionPickerSelect = document.getElementById('sessionPickerSelect');
  const logsRowCount = document.getElementById('logsRowCount');
  const logSearchInput = document.getElementById('logSearchInput');
  const logsTableBody = document.getElementById('logsTableBody');
  const verifyStatusBar = document.getElementById('verifyStatusBar');
  const filterButtons = document.querySelectorAll('.btn-filter');

  // Drawer Elements
  const drawerOverlay = document.getElementById('drawerOverlay');
  const btnDrawerClose = document.getElementById('btnDrawerClose');
  const drawerTitle = document.getElementById('drawerTitle');
  const drawerHash = document.getElementById('drawerHash');
  const drawerPrevHash = document.getElementById('drawerPrevHash');
  const drawerDecisionJson = document.getElementById('drawerDecisionJson');
  const drawerStateBeforeJson = document.getElementById('drawerStateBeforeJson');
  const drawerStateAfterJson = document.getElementById('drawerStateAfterJson');
  const btnCopyHash = document.getElementById('btnCopyHash');
  const btnCopyPrevHash = document.getElementById('btnCopyPrevHash');

  // --- State Variables ---
  let currentSession = null;
  let moveRecords = [];
  let activeFilter = 'all';
  let searchTerm = '';
  let eventSource = null;
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
    void el.offsetWidth;
    el.classList.add('flash-update');
  }

  // --- Board Renderers ---
  function initSnakeGrid() {
    snakeGrid.innerHTML = '';
    for (let r = 0; r < 12; r++) {
      for (let c = 0; c < 12; c++) {
        const cell = document.createElement('div');
        cell.className = 'snake-cell';
        cell.dataset.x = String(c);
        cell.dataset.y = String(r);
        snakeGrid.appendChild(cell);
      }
    }
  }

  function renderSnakeState(state) {
    if (!state) return;
    snakeBoardWrapper.style.display = 'flex';
    game2048BoardWrapper.style.display = 'none';
    boardMeta.textContent = '12x12 SNAKE GRID';

    // Reset cells
    const cells = snakeGrid.querySelectorAll('.snake-cell');
    cells.forEach(c => {
      c.className = 'snake-cell';
    });

    const snake = state.snake || [];
    const food = state.food || {};
    const dir = (state.direction || 'up').toUpperCase();
    const foodEaten = state.foodEaten !== undefined ? state.foodEaten : 0;

    // Food
    if (food.x !== undefined && food.y !== undefined) {
      const foodCell = snakeGrid.querySelector(`.snake-cell[data-x="${food.x}"][data-y="${food.y}"]`);
      if (foodCell) foodCell.classList.add('food');
    }

    // Body
    if (Array.isArray(snake)) {
      snake.forEach((seg, idx) => {
        const cell = snakeGrid.querySelector(`.snake-cell[data-x="${seg.x}"][data-y="${seg.y}"]`);
        if (cell) {
          if (idx === 0) {
            cell.classList.add('head');
          } else {
            cell.classList.add('body');
          }
        }
      });

      if (snake.length > 0) {
        boardMetric1.textContent = `HEAD: (${snake[0].x}, ${snake[0].y})`;
      }
    }

    boardMetric2.textContent = `DIR: ${dir}`;
    boardMetric3.textContent = `FOOD: ${foodEaten}`;
  }

  function render2048State(state) {
    if (!state) return;
    snakeBoardWrapper.style.display = 'none';
    game2048BoardWrapper.style.display = 'flex';
    boardMeta.textContent = '4x4 2048 GRID';

    grid2048.innerHTML = '';
    const grid = state.grid || [
      [0, 0, 0, 0],
      [0, 0, 0, 0],
      [0, 0, 0, 0],
      [0, 0, 0, 0]
    ];

    let maxTile = 0;
    for (let r = 0; r < 4; r++) {
      for (let c = 0; c < 4; c++) {
        const val = grid[r] && grid[r][c] !== undefined ? grid[r][c] : 0;
        if (val > maxTile) maxTile = val;
        const tile = document.createElement('div');
        tile.className = 'tile-2048';
        tile.dataset.val = String(val);
        tile.textContent = val > 0 ? String(val) : '';
        grid2048.appendChild(tile);
      }
    }

    boardMetric1.textContent = `BEST TILE: ${maxTile}`;
    boardMetric2.textContent = `SCORE: ${state.score || 0}`;
    boardMetric3.textContent = `MOVES: ${state.moves || 0}`;
  }

  function renderGameState(game, state) {
    if (game === '2048') {
      render2048State(state);
    } else {
      renderSnakeState(state);
    }
  }

  // --- Render Single Move into Decision Viewer ---
  function renderLiveMove(moveData) {
    if (!moveData) return;

    emptyStateViewer.style.display = 'none';
    liveActiveContainer.style.display = 'flex';

    const game = moveData.game || 'snake';
    liveGameBadge.textContent = game.toUpperCase();
    liveSessionIdTag.textContent = moveData.session_id || 'session';
    liveStepCounter.textContent = moveData.step !== undefined ? String(moveData.step) : '0';
    liveScoreCounter.textContent = moveData.score !== undefined ? String(moveData.score) : '0';

    const res = (moveData.result || 'applied').toLowerCase();
    liveMoveResultBadge.textContent = res.toUpperCase();
    liveMoveResultBadge.className = 'kpi-value ' + (res === 'applied' ? 'badge-applied' : 'badge-rejected');

    // Board View
    const stateToRender = moveData.state_after || moveData.state_before;
    renderGameState(game, stateToRender);

    // Decision block
    const dec = moveData.decision || {};
    const questions = dec.questions || [];
    liveQuestionText.textContent = questions.length > 0 ? questions[0] : '(No question text provided)';

    const source = (dec.source || 'laya').toUpperCase();
    decisionSourceTag.textContent = `SOURCE: ${source}`;
    liveSourceBadge.textContent = source;
    liveSourceBadge.style.color = source === 'LAYA' ? 'var(--status-connected)' : 'var(--accent-amber)';

    const chosen = (dec.chosen || moveData.action || '').toUpperCase();
    liveChosenAction.textContent = chosen;
    const conf = dec.confidence !== undefined ? (Number(dec.confidence) * 100).toFixed(1) + '%' : '--';
    liveConfidence.textContent = conf;

    // Probabilities
    const probs = dec.probabilities || {};
    const pUp = (Number(probs.up || 0) * 100);
    const pDown = (Number(probs.down || 0) * 100);
    const pLeft = (Number(probs.left || 0) * 100);
    const pRight = (Number(probs.right || 0) * 100);

    probBarUp.style.width = `${Math.min(100, pUp)}%`;
    probValUp.textContent = `${pUp.toFixed(2)}%`;
    probRowUp.classList.toggle('chosen', chosen === 'UP');

    probBarDown.style.width = `${Math.min(100, pDown)}%`;
    probValDown.textContent = `${pDown.toFixed(2)}%`;
    probRowDown.classList.toggle('chosen', chosen === 'DOWN');

    probBarLeft.style.width = `${Math.min(100, pLeft)}%`;
    probValLeft.textContent = `${pLeft.toFixed(2)}%`;
    probRowLeft.classList.toggle('chosen', chosen === 'LEFT');

    probBarRight.style.width = `${Math.min(100, pRight)}%`;
    probValRight.textContent = `${pRight.toFixed(2)}%`;
    probRowRight.classList.toggle('chosen', chosen === 'RIGHT');

    // Timings
    const timing = moveData.timing || {};
    liveDecideMs.textContent = `${timing.decide_ms || 0}ms`;
    liveApiMs.textContent = `${timing.api_ms || 0}ms`;
    liveTurnMs.textContent = `${timing.turn_ms || 0}ms`;

    // Fallback Meter
    const totalMoves = moveData.total_moves || 0;
    const fbMoves = moveData.fallback_moves || 0;
    const fbPct = totalMoves > 0 ? (fbMoves / totalMoves * 100) : 0.0;
    const limitOk = fbPct <= 10.0;

    fallbackMeterText.textContent = `${fbMoves}/${totalMoves} (${fbPct.toFixed(1)}%) [${limitOk ? 'OK' : 'EXCEEDED'}]`;
    fallbackMeterFill.style.width = `${Math.min(100, fbPct * 5)}%`; // Scaled for visibility up to 20%
    fallbackMeterFill.className = 'fallback-fill ' + (fbPct > 10.0 ? 'exceeded' : (fbPct > 7.0 ? 'warning' : ''));

    // Append to move records and table
    addRecordToTable(moveData);
  }

  // --- Table & Drawer Management ---
  function addRecordToTable(record) {
    // Avoid duplicates by step
    const existingIdx = moveRecords.findIndex(r => r.step === record.step && r.session_id === record.session_id);
    if (existingIdx >= 0) {
      moveRecords[existingIdx] = record;
    } else {
      moveRecords.push(record);
    }
    renderLogsTable();
  }

  function renderLogsTable() {
    logsRowCount.textContent = `${moveRecords.length} rows`;
    if (moveRecords.length === 0) {
      logsTableBody.innerHTML = '<tr class="empty-row"><td colspan="10" style="text-align: center; color: var(--text-muted); padding: 30px;">No session logs loaded. Start a session to view real-time audit records.</td></tr>';
      return;
    }

    const filtered = moveRecords.filter(rec => {
      // Step search
      if (searchTerm && !String(rec.step).includes(searchTerm)) {
        return false;
      }
      // Button filter
      if (activeFilter === 'applied' && rec.result !== 'applied') return false;
      if (activeFilter === 'rejected' && rec.result !== 'rejected') return false;
      if (activeFilter === 'fallback') {
        const src = (rec.decision && rec.decision.source) || '';
        if (src !== 'fallback') return false;
      }
      return true;
    });

    const fragment = document.createDocumentFragment();
    filtered.forEach(rec => {
      const tr = document.createElement('tr');
      const dec = rec.decision || {};
      const timing = rec.timing || {};
      const shortHash = rec.hash ? rec.hash.slice(0, 12) + '...' : '--';
      const confStr = dec.confidence !== undefined ? (Number(dec.confidence) * 100).toFixed(1) + '%' : '--';

      tr.innerHTML = `
        <td class="mono">${rec.step}</td>
        <td class="mono">${(rec.action || '').toUpperCase()}</td>
        <td class="mono ${rec.result === 'applied' ? 'badge-applied' : 'badge-rejected'}">${(rec.result || '').toUpperCase()}</td>
        <td class="mono">${(dec.chosen || '').toUpperCase()}</td>
        <td class="mono">${confStr}</td>
        <td class="mono" style="color: ${dec.source === 'laya' ? 'var(--status-connected)' : 'var(--accent-amber)'}">${(dec.source || 'laya').toUpperCase()}</td>
        <td class="mono">${timing.decide_ms || 0}ms</td>
        <td class="mono">${timing.api_ms || 0}ms</td>
        <td class="mono">${timing.turn_ms || 0}ms</td>
        <td class="mono" title="${rec.hash || ''}">${shortHash}</td>
      `;

      tr.addEventListener('click', () => openRowDrawer(rec));
      fragment.appendChild(tr);
    });

    logsTableBody.innerHTML = '';
    logsTableBody.appendChild(fragment);
  }

  function openRowDrawer(rec) {
    drawerTitle.textContent = `MOVE STEP #${rec.step} // AUDIT RECORD`;
    drawerHash.textContent = rec.hash || '--';
    drawerPrevHash.textContent = rec.prev_hash || '--';
    drawerDecisionJson.textContent = JSON.stringify(rec.decision || {}, null, 2);
    drawerStateBeforeJson.textContent = JSON.stringify(rec.state_before || {}, null, 2);
    drawerStateAfterJson.textContent = JSON.stringify(rec.state_after || {}, null, 2);
    drawerOverlay.style.display = 'flex';
  }

  btnDrawerClose.addEventListener('click', () => {
    drawerOverlay.style.display = 'none';
  });

  drawerOverlay.addEventListener('click', (e) => {
    if (e.target === drawerOverlay) {
      drawerOverlay.style.display = 'none';
    }
  });

  btnCopyHash.addEventListener('click', () => {
    navigator.clipboard.writeText(drawerHash.textContent);
    btnCopyHash.textContent = 'COPIED';
    setTimeout(() => { btnCopyHash.textContent = 'COPY'; }, 1200);
  });

  btnCopyPrevHash.addEventListener('click', () => {
    navigator.clipboard.writeText(drawerPrevHash.textContent);
    btnCopyPrevHash.textContent = 'COPIED';
    setTimeout(() => { btnCopyPrevHash.textContent = 'COPY'; }, 1200);
  });

  // Filters
  filterButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      filterButtons.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeFilter = btn.dataset.filter;
      renderLogsTable();
    });
  });

  logSearchInput.addEventListener('input', (e) => {
    searchTerm = e.target.value.trim();
    renderLogsTable();
  });

  // --- Real-Time SSE Stream ---
  function connectEventSource() {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }

    eventSource = new EventSource('/api/session/events');

    eventSource.addEventListener('session_sync', (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.session) {
          currentSession = data.session;
          activeSessionId.textContent = currentSession.session_id || 'NONE';
          activeSessionMode.textContent = `${(currentSession.game || '').toUpperCase()} / ${(currentSession.mode || '').toUpperCase()}`;
        }
        if (data.latest_move) {
          renderLiveMove(data.latest_move);
        }
      } catch (err) {
        console.warn('Sync parse error:', err);
      }
    });

    eventSource.addEventListener('session_started', (e) => {
      try {
        const sess = JSON.parse(e.data);
        currentSession = sess;
        moveRecords = [];
        renderLogsTable();
        liveAuditCard.style.display = 'none';
        emptyStateViewer.style.display = 'none';
        liveActiveContainer.style.display = 'flex';
        liveGameBadge.textContent = (sess.game || 'snake').toUpperCase();
        liveSessionIdTag.textContent = sess.session_id;
        liveModeBadge.textContent = (sess.mode || 'dry-run').toUpperCase();
        activeSessionId.textContent = sess.session_id;
        activeSessionMode.textContent = `${(sess.game || '').toUpperCase()} / ${(sess.mode || '').toUpperCase()}`;
        activeSessionChain.textContent = 'BUILDING';
      } catch (err) {
        console.warn('Start parse error:', err);
      }
    });

    eventSource.addEventListener('move', (e) => {
      try {
        const moveData = JSON.parse(e.data);
        renderLiveMove(moveData);
      } catch (err) {
        console.warn('Move parse error:', err);
      }
    });

    eventSource.addEventListener('session_finished', (e) => {
      try {
        const fin = JSON.parse(e.data);
        currentSession = fin;
        liveAuditCard.style.display = 'flex';
        auditScore.textContent = fin.final_score !== undefined ? String(fin.final_score) : '0';
        auditOutcome.textContent = fin.won ? 'WON' : (fin.won === false ? 'TERMINATED' : 'FINISHED');
        const valid = fin.hash_chain_valid;
        auditHashStatus.textContent = valid ? 'VERIFIED VALID (SHA-256)' : (valid === false ? 'FAILED' : 'COMPLETE');
        auditHashStatus.style.color = valid ? 'var(--status-connected)' : 'var(--status-error)';
        activeSessionChain.textContent = valid ? 'VERIFIED VALID' : (valid === false ? 'INVALID' : 'COMPLETE');
        fetchHealth(true);
        fetchSessionList();
      } catch (err) {
        console.warn('Finish parse error:', err);
      }
    });

    eventSource.addEventListener('session_error', (e) => {
      try {
        const errData = JSON.parse(e.data);
        alert('Session Error: ' + (errData.error || 'Unknown error'));
        fetchHealth(true);
      } catch (err) {
        console.warn('Error parse error:', err);
      }
    });

    eventSource.onerror = () => {
      // Reconnection handled automatically by browser EventSource
    };
  }

  // --- Export Actions ---
  function getActiveSessionId() {
    if (currentSession && currentSession.session_id) {
      return currentSession.session_id;
    }
    const txt = activeSessionId.textContent.trim();
    return txt !== 'NONE' && txt !== '--' ? txt : null;
  }

  function exportCsv() {
    const sId = getActiveSessionId();
    if (!sId) {
      alert('No active or previous session selected to export.');
      return;
    }
    window.location.href = `/api/logs/export-csv?session_id=${encodeURIComponent(sId)}`;
  }

  function downloadJsonl() {
    const sId = getActiveSessionId();
    if (!sId) {
      alert('No active or previous session selected to download.');
      return;
    }
    window.location.href = `/api/logs/download?session_id=${encodeURIComponent(sId)}`;
  }

  async function verifyChain() {
    const sId = getActiveSessionId();
    if (!sId) {
      alert('No active or previous session selected to verify.');
      return;
    }
    try {
      verifyStatusBar.style.display = 'block';
      verifyStatusBar.className = 'verify-status-bar';
      verifyStatusBar.textContent = `Verifying hash chain for ${sId}...`;

      const resp = await fetch(`/api/logs/verify?session_id=${encodeURIComponent(sId)}`);
      const data = await resp.json();
      if (data.is_valid) {
        verifyStatusBar.className = 'verify-status-bar valid';
        verifyStatusBar.textContent = `✓ SHA-256 HASH CHAIN INTACT: Verified ${data.record_count} moves with zero tampering.`;
        activeSessionChain.textContent = 'VERIFIED VALID';
      } else {
        verifyStatusBar.className = 'verify-status-bar invalid';
        verifyStatusBar.textContent = `✗ HASH CHAIN AUDIT FAILURE: ${data.error_message || 'Hash mismatch'} at step #${data.failing_step || 'unknown'}.`;
        activeSessionChain.textContent = 'INVALID';
      }
    } catch (err) {
      verifyStatusBar.className = 'verify-status-bar invalid';
      verifyStatusBar.textContent = `Verification error: ${err.message}`;
    }
  }

  function exportPdf() {
    const sId = getActiveSessionId();
    if (!sId) {
      alert('No active or previous session selected to export.');
      return;
    }
    window.location.href = `/api/logs/export-pdf?session_id=${encodeURIComponent(sId)}`;
  }

  btnExportCsv.addEventListener('click', exportCsv);
  if (btnExportPdf) btnExportPdf.addEventListener('click', exportPdf);
  btnDownloadJsonl.addEventListener('click', downloadJsonl);
  btnVerifyChain.addEventListener('click', verifyChain);
  btnLiveExportCsv.addEventListener('click', exportCsv);
  if (btnLiveExportPdf) btnLiveExportPdf.addEventListener('click', exportPdf);
  btnLiveDownloadJsonl.addEventListener('click', downloadJsonl);
  btnLiveVerify.addEventListener('click', verifyChain);
  btnLogsExportCsv.addEventListener('click', exportCsv);
  if (btnLogsExportPdf) btnLogsExportPdf.addEventListener('click', exportPdf);
  btnLogsDownload.addEventListener('click', downloadJsonl);
  btnLogsVerify.addEventListener('click', verifyChain);

  // --- Health UI Updates ---
  function updateHealthUI(data) {
    if (!data) return;

    // Arena Link
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

    if (checkItemArena) {
      checkItemArena.setAttribute('data-status', arenaStatus === 'connected' ? 'ok' : 'error');
      const icon = checkItemArena.querySelector('.check-icon');
      if (icon) icon.textContent = arenaStatus === 'connected' ? '✓' : '✗';
      checkStatusArena.textContent = arenaStatus === 'connected' ? `CONNECTED (${arena.latency_ms}ms)` : (arena.error || arenaStatus.toUpperCase());
    }

    // Laya Link
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

    if (checkItemLaya) {
      checkItemLaya.setAttribute('data-status', layaStatus === 'connected' ? 'ok' : 'error');
      const icon = checkItemLaya.querySelector('.check-icon');
      if (icon) icon.textContent = layaStatus === 'connected' ? '✓' : '✗';
      checkStatusLaya.textContent = layaStatus === 'connected' ? (isMock ? 'CONNECTED (MOCK DEV)' : `CONNECTED (${laya.latency_ms}ms)`) : (laya.error || layaStatus.toUpperCase());
    }

    // Derived Decision Layer Status
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

    if (checkItemReady) {
      const isReady = decStatus === 'READY' || decStatus === 'ACTIVE';
      checkItemReady.setAttribute('data-status', isReady ? 'ok' : 'error');
      const icon = checkItemReady.querySelector('.check-icon');
      if (icon) icon.textContent = isReady ? '✓' : '○';
      checkStatusReady.textContent = decStatus;
    }

    // Button controls
    if (decStatus === 'READY') {
      btnStartSession.disabled = false;
      btnStartSession.title = 'Start session with current parameters';
      btnStopSession.disabled = true;
      readinessHint.textContent = 'Both links connected. Decision layer is READY to begin.';
      readinessHint.style.color = 'var(--status-connected)';
    } else if (decStatus === 'ACTIVE') {
      btnStartSession.disabled = true;
      btnStopSession.disabled = false;
      readinessHint.textContent = 'Session is actively running.';
      readinessHint.style.color = 'var(--accent-amber)';
    } else if (decStatus === 'HALTED') {
      btnStartSession.disabled = true;
      btnStopSession.disabled = false;
      readinessHint.textContent = 'Session HALTED: An external link dropped mid-run.';
      readinessHint.style.color = 'var(--status-error)';
    } else {
      btnStartSession.disabled = true;
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
          currentSession = sess;
          activeSessionId.textContent = sess.session_id || 'NONE';
          activeSessionMode.textContent = `${(sess.game || '').toUpperCase()} / ${(sess.mode || '').toUpperCase()}`;
          activeSessionChain.textContent = sess.hash_chain_valid !== undefined ? (sess.hash_chain_valid ? 'VALID' : 'INVALID') : 'PENDING';
          if (res.latest_move) {
            renderLiveMove(res.latest_move);
          }
        }
      }
    } catch (err) {
      console.warn('Current session fetch error:', err);
    }
  }

  async function startSession() {
    const game = gameSelect.value;
    const mode = sessionModeSelect.value;
    const modelMode = modelModeSelect.value;
    const promptVersion = promptVersionSelect ? promptVersionSelect.value : 'v1';
    const maxMoves = parseInt(maxMovesInput.value, 10) || 15;

    if (mode === 'live') {
      const confirmed = window.confirm(
        'LIVE COMPETITION RUN CONFIRMATION:\n\n' +
        'Team / Agent: ZENITH\n' +
        'Game: ' + game.toUpperCase() + '\n' +
        'Mode: LIVE (Official TopGameAI Arena)\n\n' +
        'Every move will be submitted to competition servers.\n' +
        'Are you sure you want to begin an official judged session?'
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
          prompt_version: promptVersion,
          max_moves: maxMoves,
        }),
      });

      const res = await resp.json();
      if (!resp.ok) {
        alert('Failed to start session: ' + (res.error || 'Unknown error'));
        btnStartSession.disabled = false;
      } else {
        await fetchHealth(true);
        await fetchCurrentSession();
      }
    } catch (err) {
      alert('Network error while starting session: ' + err.message);
      btnStartSession.disabled = false;
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

  gameSelect.addEventListener('change', () => {
    const g = gameSelect.value;
    currentStageBadge.textContent = g === '2048' ? 'STAGE 2: 2048' : 'STAGE 1: SNAKE';
    if (g === '2048') {
      promptVersionGroup.style.display = 'flex';
      boardMeta.textContent = '4x4 2048 GRID';
    } else {
      promptVersionGroup.style.display = 'none';
      boardMeta.textContent = '12x12 SNAKE GRID';
    }
  });

  sessionModeSelect.addEventListener('change', () => {
    if (sessionModeSelect.value === 'live') {
      modeHint.textContent = 'WARNING: Official judged Arena run. Real network calls will be made.';
      modeHint.style.color = 'var(--status-error)';
    } else {
      modeHint.textContent = 'Simulated Arena: Safe local loop, zero network calls to competition servers.';
      modeHint.style.color = 'var(--text-muted)';
    }
  });

  judgeModeToggle.addEventListener('change', () => {
    if (judgeModeToggle.checked) {
      document.body.classList.add('judge-mode');
      localStorage.setItem('zenith_judge_mode', '1');
    } else {
      document.body.classList.remove('judge-mode');
      localStorage.removeItem('zenith_judge_mode');
    }
  });

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

  // --- Session Picker and Past Runs ---
  async function fetchSessionList() {
    if (!sessionPickerSelect) return;
    try {
      const resp = await fetch('/api/sessions');
      if (resp.ok) {
        const data = await resp.json();
        const currentVal = sessionPickerSelect.value;
        sessionPickerSelect.innerHTML = '<option value="__active__">Active Session</option>';
        (data.sessions || []).forEach(s => {
          const opt = document.createElement('option');
          opt.value = s.session_id;
          opt.textContent = `${s.session_id} (${s.game.toUpperCase()})`;
          sessionPickerSelect.appendChild(opt);
        });
        if (currentVal && Array.from(sessionPickerSelect.options).some(o => o.value === currentVal)) {
          sessionPickerSelect.value = currentVal;
        }
      }
    } catch (err) {
      console.warn('Session list fetch error:', err);
    }
  }

  if (sessionPickerSelect) {
    sessionPickerSelect.addEventListener('change', async () => {
      const selected = sessionPickerSelect.value;
      if (selected === '__active__') {
        if (currentSession) {
          activeSessionId.textContent = currentSession.session_id || 'NONE';
        }
        await fetchCurrentSession();
      } else {
        try {
          const resp = await fetch(`/api/logs/session?session_id=${encodeURIComponent(selected)}`);
          if (resp.ok) {
            const data = await resp.json();
            moveRecords = data.records || [];
            activeSessionId.textContent = selected;
            activeSessionMode.textContent = selected.includes('2048') ? '2048' : 'SNAKE';
            renderLogsTable();
            verifyChain();
          }
        } catch (err) {
          console.warn('Load session error:', err);
        }
      }
    });
  }

  // --- Initialization ---
  initSnakeGrid();
  fetchHealth(false);
  fetchCurrentSession();
  fetchSessionList();
  connectEventSource();

  pollTimer = setInterval(() => {
    fetchHealth(false);
  }, POLL_INTERVAL_MS);

  window.addEventListener('beforeunload', () => {
    if (pollTimer) clearInterval(pollTimer);
    if (eventSource) eventSource.close();
  });

})();
