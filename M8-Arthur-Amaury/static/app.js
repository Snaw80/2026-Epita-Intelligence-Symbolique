let benchmarks = [];
let lastTrace = null;

const $ = (id) => document.getElementById(id);

async function loadJson(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || response.statusText);
  }
  return payload;
}

function selectedBenchmark() {
  return benchmarks.find((item) => item.id === $("benchmark").value);
}

function fillBenchmark() {
  const item = selectedBenchmark();
  if (!item) return;
  $("imports").value = item.imports || "";
  $("statement").value = item.statement;
  $("description").textContent = item.description || "";
}

function renderHealth(payload) {
  const configuredProviders = Object.entries(payload.providers || {})
    .filter(([, ready]) => ready)
    .map(([name]) => name)
    .join(", ");
  $("health").textContent = configuredProviders || "No API key";
}

function attemptCard(attempt) {
  const success = attempt.success ? "success" : "";
  const errors = attempt.errors ? `<pre>${escapeHtml(attempt.errors)}</pre>` : "";
  return `
    <article class="attempt ${success}">
      <strong>Iteration ${attempt.iteration}, candidate ${attempt.candidate_index}: ${attempt.status}</strong>
      <pre>${escapeHtml(attempt.proof)}</pre>
      <p>${escapeHtml(attempt.rationale || "")}</p>
      ${errors}
    </article>
  `;
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function renderTrace(trace) {
  lastTrace = trace;
  $("download").disabled = false;
  $("summary").textContent =
    `${trace.status} | ${trace.attempts.length} attempts | ${trace.elapsed_ms} ms | provider ${trace.provider}`;
  $("attempts").innerHTML = trace.attempts.map(attemptCard).join("");
  $("benchmarkResults").innerHTML = "";
}

function renderBenchmarkTrace(trace) {
  lastTrace = trace;
  $("download").disabled = false;
  $("attempts").innerHTML = "";
  $("summary").textContent =
    `${trace.status} | ${trace.success}/${trace.total} solved | first try ${trace.first_try_success} | avg attempts ${trace.average_attempts}`;
  const rows = trace.sessions
    .map(
      (session) => `
        <tr>
          <td>${escapeHtml(session.theorem_id)}</td>
          <td>${escapeHtml(session.status)}</td>
          <td>${session.attempts.length}</td>
          <td>${session.elapsed_ms} ms</td>
          <td>${escapeHtml(session.error || "")}</td>
        </tr>
      `
    )
    .join("");
  $("benchmarkResults").innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Theorem</th>
          <th>Status</th>
          <th>Attempts</th>
          <th>Time</th>
          <th>Detail</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

async function runProof() {
  $("run").disabled = true;
  $("runBenchmark").disabled = true;
  $("summary").textContent = "Running...";
  $("attempts").innerHTML = "";
  $("benchmarkResults").innerHTML = "";
  try {
    const payload = {
      theorem_id: $("benchmark").value,
      provider: $("provider").value,
      model: $("model").value,
      max_iterations: Number($("maxIterations").value || 3),
      imports: $("imports").value,
      statement: $("statement").value,
    };
    renderTrace(
      await loadJson("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
    );
  } catch (error) {
    $("summary").textContent = error.message;
  } finally {
    $("run").disabled = false;
    $("runBenchmark").disabled = false;
  }
}

async function runBenchmark() {
  $("run").disabled = true;
  $("runBenchmark").disabled = true;
  $("summary").textContent = "Running benchmark...";
  $("attempts").innerHTML = "";
  $("benchmarkResults").innerHTML = "";
  try {
    const payload = {
      suite: $("suite").value,
      provider: $("provider").value,
      model: $("model").value,
      max_iterations: Number($("maxIterations").value || 3),
      limit: Number($("limit").value || 0),
    };
    renderBenchmarkTrace(
      await loadJson("/api/run-benchmark", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
    );
  } catch (error) {
    $("summary").textContent = error.message;
  } finally {
    $("run").disabled = false;
    $("runBenchmark").disabled = false;
  }
}

function downloadTrace() {
  if (!lastTrace) return;
  const blob = new Blob([JSON.stringify(lastTrace, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `m8-trace-${lastTrace.session_id}.json`;
  link.click();
  URL.revokeObjectURL(url);
}

async function init() {
  const benchmarkPayload = await loadJson("/api/benchmarks");
  benchmarks = benchmarkPayload.benchmarks;
  $("benchmark").innerHTML = benchmarks
    .map((item) => `<option value="${item.id}">${escapeHtml(item.title)}</option>`)
    .join("");
  fillBenchmark();
  $("benchmark").addEventListener("change", fillBenchmark);
  $("run").addEventListener("click", runProof);
  $("runBenchmark").addEventListener("click", runBenchmark);
  $("download").addEventListener("click", downloadTrace);
  renderHealth(await loadJson("/api/health"));
}

init().catch((error) => {
  $("summary").textContent = error.message;
});
