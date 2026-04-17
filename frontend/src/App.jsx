import { useEffect, useRef, useState } from "react";
import { fetchDefaultPr, fetchResult, triggerManualReview } from "./api";
import "./App.css";

const sampleDiff = `diff --git a/example.py b/example.py
--- a/example.py
+++ b/example.py
@@ -1,2 +1,2 @@
-# TODO: improve function
+# TODO: improve function
 def run():
     return True
`;

function isNoiseIssue(issue) {
  const message = String(issue?.message || "").toLowerCase();
  return (
    message.includes("parsing failed") ||
    message.includes("invalid syntax") ||
    message.includes('"message-id": "e0001"') ||
    message.includes('"symbol": "syntax-error"')
  );
}

function buildTestFixSuggestions(testOutput) {
  const errors = Array.isArray(testOutput?.errors) ? testOutput.errors.map((e) => String(e)) : [];
  const joined = errors.join(" ").toLowerCase();
  const suggestions = [];

  if (!errors.length) {
    suggestions.push("Open CI/local logs for full trace and reproduce with the same test command.");
    return suggestions;
  }
  if (joined.includes("assert")) {
    suggestions.push("Check failing assertions and update either business logic or expected test values.");
  }
  if (joined.includes("module not found") || joined.includes("cannot import") || joined.includes("modulenotfounderror")) {
    suggestions.push("Verify imports and install missing dependencies in backend/frontend environments.");
  }
  if (joined.includes("syntaxerror") || joined.includes("invalid syntax")) {
    suggestions.push("Fix syntax issues in modified files and run formatter/linter before tests.");
  }
  if (joined.includes("connection refused") || joined.includes("timeout") || joined.includes("econnrefused")) {
    suggestions.push("Ensure required services are running and environment variables point to correct hosts/ports.");
  }
  if (joined.includes("permission denied")) {
    suggestions.push("Check file permissions and container sandbox restrictions for test execution.");
  }
  if (!suggestions.length) {
    suggestions.push("Re-run tests locally using the same command and inspect the first failing stack trace.");
  }
  return suggestions;
}

export default function App() {
  const [form, setForm] = useState({
    pr_id: "",
    repo: "",
    pr_number: "",
    title: "",
    diff: ""
  });
  const [result, setResult] = useState(null);
  const [loadingAction, setLoadingAction] = useState("");
  const [error, setError] = useState("");
  const [bootstrapping, setBootstrapping] = useState(true);
  const [showRawJson, setShowRawJson] = useState(false);
  const [reviewProgress, setReviewProgress] = useState({ value: 0, label: "" });
  const [fetchProgress, setFetchProgress] = useState({ value: 0, label: "" });
  const timerRef = useRef(null);

  useEffect(() => {
    async function loadDefaultPr() {
      try {
        const pr = await fetchDefaultPr();
        setForm({
          pr_id: pr.pr_id,
          repo: pr.repo,
          pr_number: pr.pr_number,
          title: pr.title,
          diff: pr.diff || sampleDiff
        });
      } catch (err) {
        setError(err?.message || "Could not auto-load default PR.");
      } finally {
        setBootstrapping(false);
      }
    }
    loadDefaultPr();
  }, []);

  function startProgress(action) {
    const stageMap = {
      review: [
        { at: 12, label: "Sending review request..." },
        { at: 36, label: "Reviewer agent analyzing diff..." },
        { at: 58, label: "Fix generator preparing patch..." },
        { at: 78, label: "Running tests in sandbox..." },
        { at: 92, label: "Summarizing response..." }
      ],
      fetch: [
        { at: 20, label: "Looking up stored result..." },
        { at: 55, label: "Loading review payload..." },
        { at: 88, label: "Preparing dashboard output..." }
      ]
    };
    const stages = stageMap[action];
    let idx = 0;
    let current = 0;
    const setProgress = action === "review" ? setReviewProgress : setFetchProgress;
    setProgress({ value: 6, label: stages[0].label });

    timerRef.current = setInterval(() => {
      const nextTarget = stages[Math.min(idx, stages.length - 1)].at;
      current = Math.min(current + Math.max(1, Math.round((nextTarget - current) / 6)), 94);
      while (idx < stages.length - 1 && current >= stages[idx + 1].at) {
        idx += 1;
      }
      setProgress({ value: current, label: stages[idx].label });
    }, 220);
  }

  function finishProgress(action, label) {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    const setProgress = action === "review" ? setReviewProgress : setFetchProgress;
    setProgress({ value: 100, label });
    setTimeout(() => {
      setProgress({ value: 0, label: "" });
    }, 900);
  }

  async function onReview() {
    if (!form.pr_id || !form.repo || !form.pr_number) {
      setError("Load a valid PR first before running review.");
      return;
    }
    setLoadingAction("review");
    setError("");
    startProgress("review");
    try {
      const response = await triggerManualReview({ ...form, pr_number: Number(form.pr_number) });
      setResult(response.result);
      setShowRawJson(false);
      finishProgress("review", "Review completed");
    } catch (err) {
      finishProgress("review", "Review failed");
      setError(err.message);
    } finally {
      setLoadingAction("");
    }
  }

  async function onFetchResult() {
    if (!form.pr_id) {
      setError("Load a valid PR first before fetching result.");
      return;
    }
    setLoadingAction("fetch");
    setError("");
    startProgress("fetch");
    try {
      const response = await fetchResult(form.pr_id);
      setResult(response);
      setShowRawJson(false);
      finishProgress("fetch", "Result loaded");
    } catch (err) {
      finishProgress("fetch", "Fetch failed");
      setError(err.message);
    } finally {
      setLoadingAction("");
    }
  }

  const issues = Array.isArray(result?.issues) ? result.issues : [];
  const reviewInput = result?.review_input || {};
  const testOutput = result?.test_output || {};
  const fixOutput = result?.fix_output || {};
  const finalComment = typeof result?.final_comment === "string" ? result.final_comment : "";
  const actionItems = issues
    .filter((issue) => issue?.message && !isNoiseIssue(issue))
    .map((issue) => {
      const sev = issue.severity ? `[${String(issue.severity).toUpperCase()}] ` : "";
      const file = issue.file ? `${issue.file}` : "unknown file";
      const line = issue.line ? `:${issue.line}` : "";
      return `${sev}${issue.message} (${file}${line})`;
    });
  const testErrors = Array.isArray(testOutput?.errors) ? testOutput.errors : [];
  const testSuggestions = testOutput?.status === "fail" ? buildTestFixSuggestions(testOutput) : [];

  return (
    <main className="app-shell">
      <header className="hero">
        <h1>PR Review Dashboard</h1>
        <p>Analyze pull requests, generate fixes, and track status with confidence.</p>
      </header>

      <section className="panel">
        <div className="field-grid">
          <label>
            PR ID
            <input value={form.pr_id} onChange={(e) => setForm({ ...form, pr_id: e.target.value })} />
          </label>
          <label>
            Repository
            <input value={form.repo} onChange={(e) => setForm({ ...form, repo: e.target.value })} />
          </label>
          <label>
            PR Number
            <input
              type="number"
              value={form.pr_number}
              onChange={(e) => setForm({ ...form, pr_number: e.target.value })}
            />
          </label>
          <label>
            Title
            <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </label>
          <label className="field-span">
            Diff
            <textarea rows={10} value={form.diff} onChange={(e) => setForm({ ...form, diff: e.target.value })} />
          </label>
        </div>

        <div className="actions">
          <button
            className="btn primary"
            onClick={onReview}
            disabled={Boolean(loadingAction) || bootstrapping}
          >
            {loadingAction === "review" ? "Running Review..." : "Run Review"}
          </button>
          <button className="btn" onClick={onFetchResult} disabled={Boolean(loadingAction) || bootstrapping}>
            {loadingAction === "fetch" ? "Fetching..." : "Fetch Result"}
          </button>
        </div>

        {bootstrapping ? <p className="muted">Loading default PR from configured repository...</p> : null}

        {reviewProgress.value > 0 ? (
          <div className="progress-wrap">
            <div className="progress-meta">
              <span>Run Review</span>
              <span>{reviewProgress.value}%</span>
            </div>
            <div className="progress-track">
              <div className="progress-fill" style={{ width: `${reviewProgress.value}%` }} />
            </div>
            <small>{reviewProgress.label}</small>
          </div>
        ) : null}

        {fetchProgress.value > 0 ? (
          <div className="progress-wrap">
            <div className="progress-meta">
              <span>Fetch Result</span>
              <span>{fetchProgress.value}%</span>
            </div>
            <div className="progress-track">
              <div className="progress-fill secondary" style={{ width: `${fetchProgress.value}%` }} />
            </div>
            <small>{fetchProgress.label}</small>
          </div>
        ) : null}
      </section>

      {error ? <p className="error">{error}</p> : null}
      {result ? (
        <section className="panel">
          <h2>Review Results</h2>
          <a
            href="#raw-json"
            className="json-link"
            onClick={(e) => {
              e.preventDefault();
              setShowRawJson((prev) => !prev);
            }}
          >
            {showRawJson ? "Hide Raw JSON" : "View Raw JSON"}
          </a>
          <div className="result-grid">
            <div>
              <strong>PR ID:</strong> {reviewInput.pr_id || form.pr_id}
            </div>
            <div>
              <strong>Repository:</strong> {reviewInput.repo || form.repo}
            </div>
            <div>
              <strong>PR Number:</strong> {reviewInput.pr_number || form.pr_number}
            </div>
            <div>
              <strong>Title:</strong> {reviewInput.title || form.title || "N/A"}
            </div>
            <div>
              <strong>Attempts:</strong> {result?.attempts ?? "N/A"}
            </div>
            <div>
              <strong>Test Status:</strong> {testOutput.status || "not run"}
            </div>
            <div>
              <strong>Test Command:</strong> {testOutput.command || "N/A"}
            </div>
          </div>

          <h3>Action Items</h3>
          {actionItems.length ? (
            <ul className="issues-list">
              {actionItems.map((item, idx) => (
                <li key={`${item}-${idx}`}>{item}</li>
              ))}
            </ul>
          ) : (
            <p className="muted">No actionable issues were detected.</p>
          )}

          {fixOutput.changes_explained ? (
            <>
              <h3>Suggested Fix Summary</h3>
              <p className="muted">{fixOutput.changes_explained}</p>
            </>
          ) : null}

          {fixOutput.patch ? (
            <>
              <h3>Suggested Diff</h3>
              <pre>{fixOutput.patch}</pre>
            </>
          ) : null}

          {finalComment ? (
            <>
              <h3>Generated Reviewer Comment</h3>
              <pre>{finalComment}</pre>
            </>
          ) : null}

          {testOutput?.status === "fail" ? (
            <>
              <h3>Test Failure Details</h3>
              <p className="muted">Reasons reported by test runner:</p>
              {testErrors.length ? (
                <ul className="issues-list">
                  {testErrors.map((err, idx) => (
                    <li key={`${err}-${idx}`}>{String(err)}</li>
                  ))}
                </ul>
              ) : (
                <p className="muted">No explicit error lines were returned by the test runner.</p>
              )}

              <p className="muted">Suggested fixes:</p>
              <ul className="issues-list">
                {testSuggestions.map((tip, idx) => (
                  <li key={`${tip}-${idx}`}>{tip}</li>
                ))}
              </ul>
            </>
          ) : null}

          {showRawJson ? (
            <>
              <h3 id="raw-json">Raw JSON</h3>
              <pre>{JSON.stringify(result, null, 2)}</pre>
            </>
          ) : null}
        </section>
      ) : null}
    </main>
  );
}
