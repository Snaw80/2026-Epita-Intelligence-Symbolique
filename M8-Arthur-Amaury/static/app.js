const state = { benchmarks: [], traces: [], lastTrace: null };

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
  $('download').disabled = false;
  $('summary').textContent = `${trace.status} | ${trace.provider}/${trace.model} | ${trace.elapsed_ms}ms`;
  $('timeline').innerHTML = trace.events.map((event) => `
    <article class="event">
      <div class="event-meta">${event.index}. ${event.agent} / ${event.kind}</div>
      <div>${event.message}</div>
    </article>
  `).join('');
  $('finalProof').textContent = trace.final_proof || trace.error || 'No final proof.';
}

async function run() {
  $('summary').textContent = 'Running...';
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
  } catch (error) {
    $('summary').textContent = error.message;
  }
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
