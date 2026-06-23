const state = { benchmarks: [], traces: [], lastTrace: null, liveEvents: [], selectedEventIndex: null };

const $ = (id) => document.getElementById(id);

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || response.statusText);
  return payload;
}

function renderHealth(payload) {
  const lean = payload.lean ? 'Lean ready' : 'Replay ready';
  const graph = payload.langgraph_available ? 'LangGraph installed' : 'Graph fallback';
  const openai = payload.providers.openai_compatible ? 'OpenAI configured' : 'Demo provider only';
  $('health').textContent = `${lean} | ${graph} | ${openai}`;
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

function renderTraces() {
  $('trace').innerHTML = state.traces.map((trace) => `<option value="${trace.file}">${trace.theorem_id} (${trace.status})</option>`).join('');
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
      const payload = await fetchJson('/api/replay', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ trace: $('trace').value }),
      });
      renderTrace(payload.trace);
      return;
    }
    await streamRun();
  } catch (error) {
    $('summary').textContent = error.message;
  }
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
  state.traces = (await fetchJson('/api/traces')).traces;
  renderBenchmarks();
  renderTraces();
}

$('suite').addEventListener('change', renderBenchmarks);
$('theorem').addEventListener('change', renderSelectedTheorem);
$('run').addEventListener('click', run);
$('download').addEventListener('click', downloadTrace);
init().catch((error) => { $('summary').textContent = error.message; });
