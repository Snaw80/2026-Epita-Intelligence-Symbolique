const state = { benchmarks: [], providers: [], lastTrace: null, liveEvents: [], selectedEventIndex: null, suiteResults: [] };

const $ = (id) => document.getElementById(id);

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || response.statusText);
  return payload;
}

function renderHealth(payload) {
  state.providers = payload.providers || [];
  renderProviders();
  const lean = payload.lean ? 'Lean ready' : 'Replay ready';
  const graph = payload.langgraph_available ? 'LangGraph installed' : 'Graph fallback';
  const configured = state.providers.filter((provider) => provider.configured);
  const providerText = configured.length
    ? configured.map((provider) => provider.label).join(', ')
    : 'No LLM provider configured';
  $('health').textContent = `${lean} | ${graph} | ${providerText}`;
}

function renderProviders() {
  $('provider').innerHTML = state.providers.map((provider) => `
    <option value="${escapeHtml(provider.name)}" ${provider.configured ? '' : 'disabled'}>
      ${escapeHtml(provider.label)}${provider.configured ? '' : ' (missing env)'}
    </option>
  `).join('');
  const selected = state.providers.find((provider) => provider.configured) || state.providers[0];
  if (selected) $('provider').value = selected.name;
}

function renderBenchmarks() {
  const suite = $('suite').value;
  const items = state.benchmarks.filter((item) => item.suite === suite);
  $('theorem').innerHTML = items.map((item) => `<option value="${item.id}">${item.title}</option>`).join('');
  renderSelectedTheorem();
}

function renderSelectedTheorem() {
  const theorem = state.benchmarks.find((item) => item.id === $('theorem').value);
  if (!theorem) return;
  $('title').textContent = theorem.title;
  $('description').textContent = theorem.description || `${theorem.source} | ${theorem.difficulty}`;
  $('statement').textContent = `${theorem.imports ? theorem.imports + '\n\n' : ''}${theorem.statement}`;
}

function renderTrace(trace) {
  state.lastTrace = trace;
  state.liveEvents = trace.events || [];
  $('download').disabled = false;
  $('summary').textContent = `${trace.status} | ${trace.provider}/${trace.model} | ${trace.elapsed_ms}ms`;
  renderTimeline();
  $('finalProof').textContent = trace.final_proof || trace.error || 'No final proof.';
  if (state.liveEvents.length) selectEvent(state.liveEvents[state.liveEvents.length - 1].index);
}

function renderTimeline() {
  $('timeline').innerHTML = state.liveEvents.map((event) => `
    <button class="event ${event.index === state.selectedEventIndex ? 'selected' : ''}" data-index="${event.index}" type="button">
      <span class="event-meta">${event.index}. ${escapeHtml(event.agent)} / ${escapeHtml(event.kind)} / ${event.payload?.elapsed_ms ?? 0}ms</span>
      <span>${escapeHtml(event.message)}</span>
    </button>
  `).join('');
  [...document.querySelectorAll('.event')].forEach((node) => {
    node.addEventListener('click', () => selectEvent(Number(node.dataset.index)));
  });
}

function selectEvent(index) {
  const event = state.liveEvents.find((item) => item.index === index);
  if (!event) return;
  state.selectedEventIndex = index;
  $('detailTitle').textContent = `Step ${event.index}: ${event.agent} / ${event.kind}`;
  $('detailPayload').textContent = JSON.stringify(event, null, 2);
  renderTimeline();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function resetLiveTrace() {
  state.lastTrace = null;
  state.liveEvents = [];
  state.selectedEventIndex = null;
  $('download').disabled = true;
  $('timeline').innerHTML = '';
  $('finalProof').textContent = '';
  $('detailTitle').textContent = 'Step Details';
  $('detailPayload').textContent = 'Streaming trace... click any step as it appears to inspect raw logs.';
}

async function run() {
  $('summary').textContent = 'Starting...';
  try {
    if ($('mode').value === 'replay') {
      await replayTrace();
      return;
    }
    await streamRun();
  } catch (error) {
    $('summary').textContent = error.message;
  }
}

async function replayTrace(theoremId = '') {
  const payload = await fetchJson('/api/replay', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(theoremId ? { theorem_id: theoremId } : {}),
  });
  renderTrace(payload.trace);
}

async function streamRun() {
  resetLiveTrace();
  const response = await fetch('/api/run-stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      theorem_id: $('theorem').value,
      suite: $('suite').value,
      provider: $('provider').value,
      max_attempts: Number($('maxAttempts').value),
    }),
  });
  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || response.statusText);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) processStreamLine(line);
  }
  if (buffer.trim()) processStreamLine(buffer);
}

async function runSuite() {
  resetLiveTrace();
  $('summary').textContent = 'Running suite...';
  state.suiteResults = [];
  $('scorePanel').hidden = false;
  $('scoreSummary').textContent = `${$('suite').value}: starting...`;
  renderScoreRows();
  try {
    const response = await fetch('/api/run-suite-stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        suite: $('suite').value,
        provider: $('provider').value,
        max_attempts: Number($('maxAttempts').value),
      }),
    });
    if (!response.ok || !response.body) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || response.statusText);
    }
    await processSuiteStream(response);
  } catch (error) {
    $('summary').textContent = error.message;
  }
}

async function processSuiteStream(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) processSuiteLine(line);
  }
  if (buffer.trim()) processSuiteLine(buffer);
}

function processSuiteLine(line) {
  if (!line.trim()) return;
  const payload = JSON.parse(line);
  if (payload.type === 'error') throw new Error(payload.error);
  if (payload.type === 'result') {
    state.suiteResults.push(payload.result);
    renderScoreRows();
    $('summary').textContent = `${payload.result.index}/${payload.result.total} ${payload.result.theorem_id} -> ${payload.result.status}`;
    $('scoreSummary').textContent = `${$('suite').value}: ${state.suiteResults.length}/${payload.result.total} completed`;
    return;
  }
  if (payload.type === 'score') {
    $('scoreSummary').textContent = `${payload.score.suite}: ${payload.score.solved}/${payload.score.attempted} solved`;
    $('summary').textContent = `${payload.score.solved}/${payload.score.attempted} solved (${Math.round(payload.score.accuracy * 100)}%)`;
  }
}

function renderScore(payload) {
  state.suiteResults = payload.results || [];
  $('scorePanel').hidden = false;
  $('scoreSummary').textContent = `${payload.score.suite}: ${payload.score.solved}/${payload.score.attempted} solved`;
  renderScoreRows();
}

function renderScoreRows() {
  $('scoreTable').innerHTML = `
    <div class="score-row score-header">
      <span>Problem</span>
      <span>Status</span>
      <span>Trace</span>
    </div>
    ${state.suiteResults.map((item) => `
      <div class="score-row">
        <span>${escapeHtml(item.title || item.theorem_id)}</span>
        <span class="status ${escapeHtml(item.status)}">${escapeHtml(item.status)}</span>
        <button class="trace-open" type="button" data-theorem="${escapeHtml(item.theorem_id)}">Open</button>
      </div>
    `).join('')}
  `;
  [...document.querySelectorAll('.trace-open')].forEach((node) => {
    node.addEventListener('click', () => replayTrace(node.dataset.theorem));
  });
}

function processStreamLine(line) {
  if (!line.trim()) return;
  const payload = JSON.parse(line);
  if (payload.type === 'error') throw new Error(payload.error);
  if (payload.type === 'event') {
    state.liveEvents.push(payload.event);
    $('summary').textContent = `${payload.event.agent} / ${payload.event.kind} / ${payload.event.payload?.elapsed_ms ?? 0}ms`;
    renderTimeline();
    selectEvent(payload.event.index);
    return;
  }
  if (payload.type === 'trace') {
    state.lastTrace = payload.trace;
    $('download').disabled = false;
    $('summary').textContent = `${payload.trace.status} | ${payload.trace.provider}/${payload.trace.model} | ${payload.trace.elapsed_ms}ms`;
    $('finalProof').textContent = payload.trace.final_proof || payload.trace.error || 'No final proof.';
  }
}

async function runWithoutStreaming() {
  const payload = await fetchJson('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        theorem_id: $('theorem').value,
        suite: $('suite').value,
        provider: $('provider').value,
        max_attempts: Number($('maxAttempts').value),
      }),
    });
  renderTrace(payload.trace);
}

function downloadTrace() {
  if (!state.lastTrace) return;
  const blob = new Blob([JSON.stringify(state.lastTrace, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${state.lastTrace.run_id}.json`;
  link.click();
  URL.revokeObjectURL(url);
}

async function init() {
  renderHealth(await fetchJson('/api/health'));
  state.benchmarks = (await fetchJson('/api/benchmarks')).benchmarks;
  renderBenchmarks();
}

$('suite').addEventListener('change', renderBenchmarks);
$('theorem').addEventListener('change', renderSelectedTheorem);
$('run').addEventListener('click', run);
$('runSuite').addEventListener('click', runSuite);
$('download').addEventListener('click', downloadTrace);
init().catch((error) => { $('summary').textContent = error.message; });
