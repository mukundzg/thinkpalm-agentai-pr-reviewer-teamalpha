import { useEffect, useRef, useState } from "react";
import { fetchDefaultPr, fetchOpenPrs, fetchPrDetails, fetchResult, postPrComment, triggerManualReview } from "./api";
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
  const [isPrModalOpen, setIsPrModalOpen] = useState(false);
  const [openPrs, setOpenPrs] = useState([]);
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
        setError("Failed to initialize session with backend services.");
      } finally {
        setBootstrapping(false);
      }
    }
    loadDefaultPr();
  }, []);

  function startProgress(action) {
    const stageMap = {
      review: [
        { at: 15, label: "Initializing orchestration..." },
        { at: 45, label: "AI analysis in progress..." },
        { at: 75, label: "Generating fix recommendations..." },
        { at: 95, label: "Compiling final report..." }
      ],
      fetch: [
        { at: 40, label: "Retrieving records..." },
        { at: 90, label: "Processing response data..." }
      ]
    };
    const stages = stageMap[action];
    let idx = 0;
    let current = 0;
    const setProgress = action === "review" ? setReviewProgress : setFetchProgress;
    setProgress({ value: 5, label: stages[0].label });

    timerRef.current = setInterval(() => {
      const nextTarget = stages[Math.min(idx, stages.length - 1)].at;
      current = Math.min(current + Math.max(1, Math.round((nextTarget - current) / 12)), 98);
      while (idx < stages.length - 1 && current >= stages[idx + 1].at) {
        idx += 1;
      }
      setProgress({ value: current, label: stages[idx].label });
    }, 280);
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
    }, 1500);
  }

  async function onReview() {
    if (!form.pr_id || !form.repo || !form.pr_number) {
      setError("Please complete the repository configuration before starting analysis.");
      return;
    }
    setLoadingAction("review");
    setError("");
    startProgress("review");
    try {
      const response = await triggerManualReview({ ...form, pr_number: Number(form.pr_number) });
      setResult(response.result);
      setShowRawJson(false);
      finishProgress("review", "Analysis complete");
    } catch (err) {
      finishProgress("review", "Process failed");
      setError(err.message);
    } finally {
      setLoadingAction("");
    }
  }

  async function onFetchResult() {
    if (!form.pr_id) {
      setError("Identifier required to retrieve specific results.");
      return;
    }
    setLoadingAction("fetch");
    setError("");
    startProgress("fetch");
    try {
      const response = await fetchResult(form.pr_id);
      setResult(response);
      setShowRawJson(false);
      finishProgress("fetch", "Results synchronized");
    } catch (err) {
      finishProgress("fetch", "Sync failed");
      setError(err.message);
    } finally {
      setLoadingAction("");
    }
  }

  async function onShowOpenPrs() {
    setLoadingAction("open-prs");
    setError("");
    startProgress("fetch");
    try {
      const response = await fetchOpenPrs();
      const items = Array.isArray(response?.pull_requests) ? response.pull_requests : [];
      setOpenPrs(items);
      setIsPrModalOpen(true);
      finishProgress("fetch", "Open PR list loaded");
    } catch (err) {
      finishProgress("fetch", "Load failed");
      setError(err.message || "Failed to fetch open PR list.");
    } finally {
      setLoadingAction("");
    }
  }

  async function onSelectOpenPr(prNumber) {
    setLoadingAction("select-pr");
    setError("");
    startProgress("fetch");
    try {
      const pr = await fetchPrDetails(prNumber);
      setForm({
        pr_id: pr.pr_id || "",
        repo: pr.repo || "",
        pr_number: pr.pr_number || "",
        title: pr.title || "",
        diff: pr.diff || sampleDiff
      });
      setIsPrModalOpen(false);
      finishProgress("fetch", "Selected PR loaded");
    } catch (err) {
      finishProgress("fetch", "Load failed");
      setError(err.message || "Failed to load selected PR.");
    } finally {
      setLoadingAction("");
    }
  }

  async function onPostCommentToGithub() {
    if (!form.repo || !form.pr_number) {
      setError("Select a repository and PR number before posting a comment.");
      return;
    }
    if (!finalComment) {
      setError("No generated final comment available to post.");
      return;
    }
    setLoadingAction("post-comment");
    setError("");
    startProgress("fetch");
    try {
      await postPrComment({
        repo: form.repo,
        pr_number: Number(form.pr_number),
        body: finalComment
      });
      finishProgress("fetch", "Comment posted");
    } catch (err) {
      finishProgress("fetch", "Post failed");
      setError(err.message || "Failed to post comment to GitHub.");
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
      const file = issue.file ? `${issue.file}` : "kernel";
      const line = issue.line ? `:${issue.line}` : "";
      return `${sev}${issue.message} (${file}${line})`;
    });
  const testErrors = Array.isArray(testOutput?.errors) ? testOutput.errors : [];
  const testSuggestions = testOutput?.status === "fail" ? buildTestFixSuggestions(testOutput) : [];
  const analysisSummaryItems = issues
    .filter((issue) => issue?.message && !isNoiseIssue(issue))
    .map((issue) => {
      const location = issue?.file ? `${issue.file}${issue?.line ? `:${issue.line}` : ""}` : "Location unavailable";
      const severity = issue?.severity ? String(issue.severity).toUpperCase() : "INFO";
      return {
        issueText: `[${severity}] ${issue.message}`,
        location,
        resolution:
          typeof fixOutput?.changes_explained === "string" && fixOutput.changes_explained.trim()
            ? fixOutput.changes_explained
            : "Review the impacted logic at the listed location, update behavior to match expected intent, then re-run checks."
      };
    });

  return (
    <div className="app-shell">
      <header className="hero">
        <h1>AgentAI PR Reviewer</h1>
        <p>Intelligent multi-agent orchestration for autonomous pull request analysis and correction.</p>
      </header>

      <aside className="sidebar">
        <section className="panel">
          <div className="panel-header">
            <h3>Configuration</h3>
          </div>
          <div className="panel-body">
            <div className="form-group">
              <label>Project Identifier</label>
              <input value={form.pr_id} onChange={(e) => setForm({ ...form, pr_id: e.target.value })} placeholder="owner/repo#1" />
            </div>
            <div className="form-group">
              <label>Target Repository</label>
              <input value={form.repo} onChange={(e) => setForm({ ...form, repo: e.target.value })} placeholder="owner/repo" />
            </div>
            <div className="form-group">
              <label>PR Number</label>
              <input
                type="number"
                value={form.pr_number}
                onChange={(e) => setForm({ ...form, pr_number: e.target.value })}
              />
            </div>
            <div className="form-group">
              <label>Contextual Title</label>
              <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Feature label..." />
            </div>
            <div className="form-group">
              <label>Unified Diff Content</label>
              <textarea rows={8} value={form.diff} onChange={(e) => setForm({ ...form, diff: e.target.value })} placeholder="Paste raw diff..." />
            </div>

            <div className="actions">
              <button
                className="btn primary"
                onClick={onReview}
                disabled={Boolean(loadingAction) || bootstrapping}
              >
                {loadingAction === "review" ? "Analyzing..." : "Review Logic Flow"}
              </button>
              <button className="btn" onClick={onShowOpenPrs} disabled={Boolean(loadingAction) || bootstrapping}>
                {loadingAction === "open-prs" ? "Loading PRs..." : "Show Open PRs"}
              </button>
              <button className="btn" onClick={onFetchResult} disabled={Boolean(loadingAction) || bootstrapping}>
                {loadingAction === "fetch" ? "Syncing..." : "Retrieve State"}
              </button>
            </div>

            {bootstrapping ? <p style={{fontSize: "0.75rem", color: "var(--color-fg-muted)", marginTop: "1rem", textAlign: "center"}}>Connecting to agent nodes...</p> : null}

            {reviewProgress.value > 0 && (
              <div className="progress-section">
                <div className="progress-label">
                  <span>Review Pipeline</span>
                  <span>{reviewProgress.value}%</span>
                </div>
                <div className="progress-bar">
                  <div className="progress-value" style={{ width: `${reviewProgress.value}%` }} />
                </div>
                <p style={{fontSize: "0.7rem", marginTop: "0.25rem", color: "var(--color-fg-muted)"}}>{reviewProgress.label}</p>
              </div>
            )}
            {fetchProgress.value > 0 && (
              <div className="progress-section">
                <div className="progress-label">
                  <span>State Sync</span>
                  <span>{fetchProgress.value}%</span>
                </div>
                <div className="progress-bar">
                  <div className="progress-value" style={{ width: `${fetchProgress.value}%`, backgroundColor: "#af57db" }} />
                </div>
                <p style={{fontSize: "0.7rem", marginTop: "0.25rem", color: "var(--color-fg-muted)"}}>{fetchProgress.label}</p>
              </div>
            )}
          </div>
        </section>
      </aside>

      <main className="main-content">
        {error && (
          <div className="error-banner">
            <strong>Error:</strong> {error}
          </div>
        )}

        {result ? (
          <>
            <section className="panel">
              <div className="panel-header">
                <h3>Executive Summary</h3>
                <a href="#diag" className="json-link" onClick={(e) => { e.preventDefault(); setShowRawJson(p => !p); }}>
                  {showRawJson ? "Hide diagnostics" : "Show diagnostics"}
                </a>
              </div>
              <div className="panel-body">
                <div className="summary-card">
                  <div className="summary-item">
                    <label>Resource Target</label>
                    <span>{reviewInput.repo || form.repo}</span>
                  </div>
                  <div className="summary-item">
                    <label>PR Node</label>
                    <span>#{reviewInput.pr_number || form.pr_number}</span>
                  </div>
                  <div className="summary-item">
                    <label>Operational Health</label>
                    <span className={`status-badge ${testOutput.status === "pass" ? "pass" : testOutput.status === "fail" ? "fail" : "neutral"}`}>
                      {testOutput.status ? testOutput.status.toUpperCase() : "PENDING"}
                    </span>
                  </div>
                </div>
              </div>
            </section>

            <section className="panel">
              <div className="panel-header">
                <h3>Vulnerability & Style Analysis</h3>
              </div>
              <div className="panel-body">
                <div className="issues-container">
                  {actionItems.length ? actionItems.map((item, idx) => (
                    <div key={idx} className="issue-item">
                      <div className="dot" />
                      {item}
                    </div>
                  )) : <p style={{color: "var(--color-fg-muted)", textAlign: "center", fontSize: "0.875rem"}}>No critical regression or style anomalies detected.</p>}
                </div>
                <h3 style={{ fontSize: "0.875rem", marginTop: "1.25rem", marginBottom: "0.75rem" }}>Analysis Summary</h3>
                <div className="issues-container">
                  {analysisSummaryItems.length ? (
                    analysisSummaryItems.map((item, idx) => (
                      <div key={`${item.location}-${idx}`} className="issue-item" style={{ display: "block" }}>
                        <p style={{ fontSize: "0.82rem", marginBottom: "0.4rem" }}>
                          <strong>Issue:</strong> {item.issueText}
                        </p>
                        <p style={{ fontSize: "0.82rem", marginBottom: "0.4rem", color: "var(--color-fg-muted)" }}>
                          <strong>Where:</strong> {item.location}
                        </p>
                        <p style={{ fontSize: "0.82rem" }}>
                          <strong>How to solve:</strong> {item.resolution}
                        </p>
                      </div>
                    ))
                  ) : (
                    <div className="issue-item" style={{ display: "block" }}>
                      <p style={{ fontSize: "0.82rem", marginBottom: "0.4rem" }}>
                        <strong>Issue:</strong> No actionable issue was detected.
                      </p>
                      <p style={{ fontSize: "0.82rem", marginBottom: "0.4rem", color: "var(--color-fg-muted)" }}>
                        <strong>Where:</strong> Not applicable.
                      </p>
                      <p style={{ fontSize: "0.82rem" }}>
                        <strong>How to solve:</strong> Continue monitoring new PR scans for regressions or style violations.
                      </p>
                    </div>
                  )}
                </div>
                <button
                  className="btn"
                  onClick={onPostCommentToGithub}
                  disabled={Boolean(loadingAction) || bootstrapping || !finalComment}
                  style={{ marginTop: "0.75rem" }}
                >
                  {loadingAction === "post-comment" ? "Posting Comment..." : "Post Comment to GitHub PR"}
                </button>
              </div>
            </section>

            {fixOutput.changes_explained && (
              <section className="panel">
                <div className="panel-header">
                  <h3>Heuristic Reasoning</h3>
                </div>
                <div className="panel-body">
                  <p style={{fontSize: "0.875rem", color: "var(--color-fg-muted)"}}>{fixOutput.changes_explained}</p>
                </div>
              </section>
            )}

            {fixOutput.patch && (
              <section className="panel">
                <div className="panel-header">
                  <h3>Correction Patch (Diff)</h3>
                </div>
                <div className="panel-body">
                  <pre>{fixOutput.patch}</pre>
                </div>
              </section>
            )}

            {finalComment && (
              <section className="panel">
                <div className="panel-header">
                  <h3>Agent Consensus Comment</h3>
                </div>
                <div className="panel-body">
                  <pre style={{borderLeft: "4px solid var(--color-accent-fg)", backgroundColor: "rgba(9, 105, 218, 0.02)"}}>{finalComment}</pre>
                </div>
              </section>
            )}

            {testOutput?.status === "fail" && (
              <section className="panel" style={{borderColor: "var(--color-danger-fg)"}}>
                <div className="panel-header" style={{backgroundColor: "#fff8f8"}}>
                  <h3 style={{color: "var(--color-danger-fg)"}}>Regression Diagnostic</h3>
                </div>
                <div className="panel-body">
                  <div className="issues-container">
                    {testErrors.map((err, idx) => (
                      <div key={idx} className="issue-item" style={{borderColor: "#ffcfcc"}}>
                        {String(err)}
                      </div>
                    ))}
                  </div>
                  <h3 style={{fontSize: "0.875rem", marginTop: "1.5rem", marginBottom: "0.75rem"}}>Suggested Resolutions</h3>
                  <div className="issues-container">
                    {testSuggestions.map((tip, idx) => (
                      <div key={idx} className="issue-item" style={{borderColor: "var(--color-accent-fg)"}}>
                        {tip}
                      </div>
                    ))}
                  </div>
                </div>
              </section>
            )}

            {showRawJson && (
              <section className="panel" id="diag">
                <div className="panel-header">
                  <h3>System Diagnostic Dump</h3>
                </div>
                <div className="panel-body">
                  <pre>{JSON.stringify(result, null, 2)}</pre>
                </div>
              </section>
            )}
          </>
        ) : (
          <div style={{height: "100%", display: "flex", alignItems: "center", justifyContent: "center", border: "2px dashed var(--color-border-default)", borderRadius: "8px", color: "var(--color-fg-muted)"}}>
            <p>Initialize analysis or retrieve state to view data results.</p>
          </div>
        )}
      </main>

      {isPrModalOpen && (
        <div className="modal-backdrop" onClick={() => setIsPrModalOpen(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Open Pull Requests</h3>
              <button className="btn modal-close" onClick={() => setIsPrModalOpen(false)}>Close</button>
            </div>
            <div className="modal-body">
              {openPrs.length === 0 ? (
                <p style={{ color: "var(--color-fg-muted)" }}>No open pull requests found.</p>
              ) : (
                openPrs.map((pr) => (
                  <button
                    key={pr.id || pr.number}
                    className="pr-row"
                    onClick={() => onSelectOpenPr(pr.number)}
                    disabled={Boolean(loadingAction)}
                  >
                    <span className="pr-title">#{pr.number} {pr.title || "Untitled PR"}</span>
                    <span className="pr-meta">{pr.repo}</span>
                  </button>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}



