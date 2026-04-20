import { useCallback, useEffect, useRef, useState } from "react";
import {
  approvePr,
  createProject,
  deleteProject,
  fetchCryptoStatus,
  fetchDecisionHistoryByRun,
  fetchOnboardingStatus,
  generateAppSecret,
  fetchDefaultPr,
  fetchOpenPrs,
  fetchPrActions,
  fetchPrDetails,
  fetchPrHistory,
  fetchProjects,
  fetchResult,
  fetchWebhookInbox,
  postPrComment,
  triggerManualReview
} from "./api";
import "./App.css";

const LS_PROJECT_ID = "prReviewerProjectId";

const sampleDiff = `diff --git a/example.py b/example.py
--- a/example.py
+++ b/example.py
@@ -1,2 +1,2 @@
-# TODO: improve function
+# TODO: improve function
 def run():
     return True
 `;

function buildFormFromDefaultPr(pr) {
  const noOpenPrs = Boolean(pr?.no_open_prs);
  const prNumberRaw = pr?.pr_number;
  const diffStr = pr?.diff != null ? String(pr.diff) : "";
  return {
    form: {
      pr_id: pr?.pr_id != null ? String(pr.pr_id) : "",
      repo: pr?.repo != null ? String(pr.repo) : "",
      pr_number: prNumberRaw != null && prNumberRaw !== "" ? String(prNumberRaw) : "",
      title: pr?.title != null ? String(pr.title) : "",
      diff: noOpenPrs ? "" : diffStr.trim() ? diffStr : sampleDiff
    },
    noOpenPrs
  };
}

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
  const [info, setInfo] = useState("");
  const [bootstrapping, setBootstrapping] = useState(true);
  const [showRawJson, setShowRawJson] = useState(false);
  const [reviewProgress, setReviewProgress] = useState({ value: 0, label: "" });
  const [fetchProgress, setFetchProgress] = useState({ value: 0, label: "" });
  const [isPrModalOpen, setIsPrModalOpen] = useState(false);
  const [openPrs, setOpenPrs] = useState([]);
  const [isDecisionModalOpen, setIsDecisionModalOpen] = useState(false);
  const [decisionHistory, setDecisionHistory] = useState(null);
  const [isHistoryModalOpen, setIsHistoryModalOpen] = useState(false);
  const [prHistoryItems, setPrHistoryItems] = useState([]);
  const [prActions, setPrActions] = useState([]);
  const [decisionFlowActions, setDecisionFlowActions] = useState([]);
  const [decisionFlowActionsLoading, setDecisionFlowActionsLoading] = useState(false);
  const [projects, setProjects] = useState([]);
  const [projectId, setProjectId] = useState(null);
  const [cryptoStatus, setCryptoStatus] = useState(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [newProject, setNewProject] = useState({ full_name: "", github_token: "", webhook_secret: "" });
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [onboardingStatus, setOnboardingStatus] = useState(null);
  const [onboardingBusy, setOnboardingBusy] = useState(false);
  const [isWebhookModalOpen, setIsWebhookModalOpen] = useState(false);
  const [webhookItems, setWebhookItems] = useState([]);
  const timerRef = useRef(null);

  const loadInitialPrForProjects = useCallback(async (items) => {
    if (!Array.isArray(items) || !items.length) {
      return;
    }
    const saved = localStorage.getItem(LS_PROJECT_ID);
    let chosen = saved ? Number(saved) : NaN;
    if (!items.some((p) => p.id === chosen)) {
      chosen = items[0].id;
    }
    setProjectId(chosen);
    localStorage.setItem(LS_PROJECT_ID, String(chosen));
    const projectMeta = items.find((p) => p.id === chosen);
    const repoName = projectMeta?.full_name || "";
    try {
      const pr = await fetchDefaultPr(chosen);
      const { form: nextForm, noOpenPrs } = buildFormFromDefaultPr(pr);
      setForm(nextForm);
      if (noOpenPrs) {
        setInfo(`No open pull requests for ${repoName}. Enter a PR number or use Show Open PRs when one exists.`);
        setError("");
      } else {
        setInfo("");
        setError("");
      }
    } catch (e) {
      setForm({
        pr_id: "",
        repo: repoName,
        pr_number: "",
        title: "",
        diff: ""
      });
      setInfo("");
      setError(e.message || "Could not load the default pull request for this project.");
    }
  }, []);

  async function reloadPrActions() {
    if (!form.pr_id) {
      setPrActions([]);
      return;
    }
    try {
      const data = await fetchPrActions(form.pr_id);
      setPrActions(Array.isArray(data?.items) ? data.items : []);
    } catch {
      setPrActions([]);
    }
  }

  useEffect(() => {
    let cancelled = false;
    async function bootstrap() {
      setError("");
      try {
        const [ob, projRes] = await Promise.all([fetchOnboardingStatus(), fetchProjects()]);
        if (cancelled) {
          return;
        }
        setOnboardingStatus(ob);
        const items = Array.isArray(projRes?.items) ? projRes.items : [];
        setProjects(items);
        let cs = null;
        try {
          cs = await fetchCryptoStatus();
        } catch {
          cs = null;
        }
        if (!cancelled) {
          setCryptoStatus(cs);
        }
        if (!ob.onboarding_complete) {
          return;
        }
        await loadInitialPrForProjects(items);
      } catch (err) {
        if (!cancelled) {
          setError(err.message || "Failed to initialize session with backend services.");
          setOnboardingStatus({
            encryption_configured: false,
            project_count: 0,
            needs_encryption: true,
            needs_first_project: false,
            onboarding_complete: false
          });
        }
      } finally {
        if (!cancelled) {
          setBootstrapping(false);
        }
      }
    }
    bootstrap();
    return () => {
      cancelled = true;
    };
  }, [loadInitialPrForProjects]);

  useEffect(() => {
    if (error) {
      setInfo("");
    }
  }, [error]);

  useEffect(() => {
    if (!result || !form.pr_id) {
      setPrActions([]);
      return;
    }
    let cancelled = false;
    fetchPrActions(form.pr_id)
      .then((data) => {
        if (!cancelled) setPrActions(Array.isArray(data?.items) ? data.items : []);
      })
      .catch(() => {
        if (!cancelled) setPrActions([]);
      });
    return () => {
      cancelled = true;
    };
  }, [result, form.pr_id]);

  useEffect(() => {
    if (!isDecisionModalOpen || !decisionHistory?.run?.pr_id) {
      setDecisionFlowActions([]);
      setDecisionFlowActionsLoading(false);
      return;
    }
    const prId = decisionHistory.run.pr_id;
    let cancelled = false;
    setDecisionFlowActionsLoading(true);
    fetchPrActions(prId)
      .then((data) => {
        if (!cancelled) {
          setDecisionFlowActions(Array.isArray(data?.items) ? data.items : []);
        }
      })
      .catch(() => {
        if (!cancelled) setDecisionFlowActions([]);
      })
      .finally(() => {
        if (!cancelled) setDecisionFlowActionsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isDecisionModalOpen, decisionHistory?.run?.pr_id]);

  useEffect(() => {
    if (!settingsOpen) {
      return;
    }
    fetchCryptoStatus()
      .then((s) => setCryptoStatus(s))
      .catch(() => {});
  }, [settingsOpen]);

  function startProgress(action) {
    const profileMap = {
      review: {
        estimatedMs: 55000,
        stallWindows: [
          [0.2, 0.24],
          [0.58, 0.64]
        ],
        stages: [
          { atMs: 0, label: "Initializing orchestration..." },
          { atMs: 9000, label: "Analyzing changed files..." },
          { atMs: 24000, label: "Generating fix recommendations..." },
          { atMs: 38000, label: "Evaluating patch and tests..." },
          { atMs: 50000, label: "Compiling final report..." }
        ]
      },
      fetch: {
        estimatedMs: 10000,
        stallWindows: [[0.55, 0.68]],
        stages: [
          { atMs: 0, label: "Retrieving records..." },
          { atMs: 5000, label: "Processing response data..." },
          { atMs: 8200, label: "Finalizing results..." }
        ]
      }
    };
    const profile = profileMap[action];
    const setProgress = action === "review" ? setReviewProgress : setFetchProgress;
    const startAt = Date.now();
    let current = 1;
    setProgress({ value: current, label: `${profile.stages[0].label} • ~${Math.ceil(profile.estimatedMs / 1000)}s left` });

    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }

    timerRef.current = setInterval(() => {
      const elapsed = Date.now() - startAt;
      const normalized = Math.min(elapsed / profile.estimatedMs, 1);
      const easedTarget = 96 * (1 - Math.pow(1 - normalized, 2.25));
      const inStallWindow = profile.stallWindows.some(([s, e]) => normalized >= s && normalized <= e);
      const jitter = (Math.sin(elapsed / 1700) + Math.sin(elapsed / 900)) * 0.35;
      let target = Math.min(96, Math.max(1, easedTarget + jitter));

      if (inStallWindow) {
        target = Math.min(target, current + 0.25);
      }

      const delta = target - current;
      const step = delta > 0 ? Math.min(2.2, Math.max(0.12, delta * 0.24)) : 0;
      current = Math.min(96, current + step);

      let stageLabel = profile.stages[0].label;
      for (const stage of profile.stages) {
        if (elapsed >= stage.atMs) {
          stageLabel = stage.label;
        } else {
          break;
        }
      }

      const remainingSec = Math.max(1, Math.ceil((profile.estimatedMs - elapsed) / 1000));
      const etaText = current >= 95 ? "almost done" : `~${remainingSec}s left`;
      setProgress({ value: Math.round(current), label: `${stageLabel} • ${etaText}` });
    }, 240);
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

  async function onProjectChange(e) {
    const id = Number(e.target.value);
    if (!id) {
      return;
    }
    setProjectId(id);
    localStorage.setItem(LS_PROJECT_ID, String(id));
    setResult(null);
    setLoadingAction("switch-project");
    setError("");
    setInfo("");
    startProgress("fetch");
    const projectMeta = projects.find((p) => p.id === id);
    const repoName = projectMeta?.full_name || "";
    try {
      const pr = await fetchDefaultPr(id);
      const { form: nextForm, noOpenPrs } = buildFormFromDefaultPr(pr);
      setForm(nextForm);
      if (noOpenPrs) {
        setInfo(`No open pull requests for ${repoName}. Enter a PR number or use Show Open PRs when one exists.`);
      }
      finishProgress("fetch", "Project loaded");
    } catch (err) {
      finishProgress("fetch", "Load failed");
      setForm({
        pr_id: "",
        repo: repoName,
        pr_number: "",
        title: "",
        diff: ""
      });
      setError(err.message || "Could not load default PR for this project.");
    } finally {
      setLoadingAction("");
    }
  }

  async function onSaveNewProject(e) {
    e.preventDefault();
    if (!newProject.full_name.trim() || !newProject.github_token.trim()) {
      setError("Repository (owner/repo) and GitHub token are required.");
      return;
    }
    setSettingsBusy(true);
    setError("");
    setInfo("");
    try {
      await createProject({
        full_name: newProject.full_name.trim(),
        github_token: newProject.github_token,
        webhook_secret: newProject.webhook_secret || ""
      });
      const res = await fetchProjects();
      const items = Array.isArray(res?.items) ? res.items : [];
      setProjects(items);
      setNewProject({ full_name: "", github_token: "", webhook_secret: "" });
      if (items.length) {
        const id = items[items.length - 1].id;
        setProjectId(id);
        localStorage.setItem(LS_PROJECT_ID, String(id));
        const added = items.find((p) => p.id === id);
        const repoName = added?.full_name || "";
        try {
          const pr = await fetchDefaultPr(id);
          const { form: nextForm, noOpenPrs } = buildFormFromDefaultPr(pr);
          setForm(nextForm);
          if (noOpenPrs) {
            setInfo(`No open pull requests for ${repoName}. Enter a PR number or use Show Open PRs when one exists.`);
          }
        } catch (e) {
          setForm({
            pr_id: "",
            repo: repoName,
            pr_number: "",
            title: "",
            diff: ""
          });
          setError(e.message || "Project saved, but the repository view could not be loaded.");
        }
      }
    } catch (err) {
      setError(err.message || "Could not save project.");
    } finally {
      setSettingsBusy(false);
    }
  }

  async function onDeleteProject(id) {
    if (!window.confirm("Remove this project from the app? Stored credentials will be deleted.")) {
      return;
    }
    setSettingsBusy(true);
    setError("");
    setInfo("");
    try {
      await deleteProject(id);
      const res = await fetchProjects();
      const items = Array.isArray(res?.items) ? res.items : [];
      setProjects(items);
      if (projectId === id) {
        setProjectId(items[0]?.id ?? null);
        if (items[0]) {
          localStorage.setItem(LS_PROJECT_ID, String(items[0].id));
          const nextRepo = items[0].full_name || "";
          try {
            const pr = await fetchDefaultPr(items[0].id);
            const { form: nextForm, noOpenPrs } = buildFormFromDefaultPr(pr);
            setForm(nextForm);
            if (noOpenPrs) {
              setInfo(`No open pull requests for ${nextRepo}. Enter a PR number or use Show Open PRs when one exists.`);
            }
          } catch (e) {
            setForm({
              pr_id: "",
              repo: nextRepo,
              pr_number: "",
              title: "",
              diff: ""
            });
            setError(e.message || "Project removed, but the next repository could not be loaded.");
          }
        } else {
          localStorage.removeItem(LS_PROJECT_ID);
          setForm({ pr_id: "", repo: "", pr_number: "", title: "", diff: sampleDiff });
          setResult(null);
        }
      }
    } catch (err) {
      setError(err.message || "Could not delete project.");
    } finally {
      setSettingsBusy(false);
    }
  }

  async function onReview() {
    if (!projectId) {
      setError("Add a GitHub project in Settings first.");
      return;
    }
    if (!form.pr_id || !form.repo || !form.pr_number) {
      setError("Please complete the repository configuration before starting analysis.");
      return;
    }
    setLoadingAction("review");
    setError("");
    startProgress("review");
    try {
      const response = await triggerManualReview({
        project_id: projectId,
        ...form,
        pr_number: Number(form.pr_number)
      });
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
    if (!projectId) {
      setError("Select a GitHub project first (Settings).");
      return;
    }
    setLoadingAction("open-prs");
    setError("");
    startProgress("fetch");
    try {
      const response = await fetchOpenPrs(projectId);
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
    if (!projectId) {
      return;
    }
    setLoadingAction("select-pr");
    setError("");
    startProgress("fetch");
    try {
      const pr = await fetchPrDetails(prNumber, projectId);
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
    if (!projectId) {
      setError("Select a GitHub project in Settings.");
      return;
    }
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
        project_id: projectId,
        repo: form.repo,
        pr_number: Number(form.pr_number),
        body: finalComment
      });
      await reloadPrActions();
      finishProgress("fetch", "Comment posted");
    } catch (err) {
      finishProgress("fetch", "Post failed");
      setError(err.message || "Failed to post comment to GitHub.");
    } finally {
      setLoadingAction("");
    }
  }

  async function onApprovePr() {
    if (!projectId) {
      setError("Select a GitHub project in Settings.");
      return;
    }
    if (!form.repo || !form.pr_number) {
      setError("Select a repository and PR number before approving.");
      return;
    }
    setLoadingAction("approve-pr");
    setError("");
    startProgress("fetch");
    try {
      await approvePr({
        project_id: projectId,
        repo: form.repo,
        pr_number: Number(form.pr_number)
      });
      await reloadPrActions();
      finishProgress("fetch", "PR approved");
    } catch (err) {
      finishProgress("fetch", "Approve failed");
      setError(err.message || "Failed to approve pull request.");
    } finally {
      setLoadingAction("");
    }
  }

  async function onShowPrHistory() {
    if (!projectId) {
      setError("Select a GitHub project first.");
      return;
    }
    setLoadingAction("pr-history");
    setError("");
    startProgress("fetch");
    try {
      const response = await fetchPrHistory(300, projectId);
      const items = Array.isArray(response?.items) ? response.items : [];
      setPrHistoryItems(items);
      setIsHistoryModalOpen(true);
      finishProgress("fetch", "Analysis history loaded");
    } catch (err) {
      finishProgress("fetch", "Load failed");
      setError(err.message || "Failed to load PR history.");
    } finally {
      setLoadingAction("");
    }
  }

  async function onShowWebhookInbox() {
    setLoadingAction("webhook-inbox");
    setError("");
    startProgress("fetch");
    try {
      const response = await fetchWebhookInbox(200);
      const items = Array.isArray(response?.items) ? response.items : [];
      setWebhookItems(items);
      setIsWebhookModalOpen(true);
      finishProgress("fetch", "PR inbox loaded");
    } catch (err) {
      finishProgress("fetch", "Load failed");
      setError(err.message || "Failed to load webhook PR list.");
    } finally {
      setLoadingAction("");
    }
  }

  async function onPickWebhookItem(item) {
    const nextProjectId = item?.project_id ? Number(item.project_id) : null;
    const prNumber = item?.pr_number ? Number(item.pr_number) : null;
    if (!nextProjectId || !prNumber) {
      setError("This webhook item is missing project or PR reference.");
      return;
    }
    setLoadingAction("select-webhook-pr");
    setError("");
    startProgress("fetch");
    try {
      setProjectId(nextProjectId);
      localStorage.setItem(LS_PROJECT_ID, String(nextProjectId));
      const pr = await fetchPrDetails(prNumber, nextProjectId);
      setForm({
        pr_id: pr.pr_id || "",
        repo: pr.repo || "",
        pr_number: pr.pr_number || "",
        title: pr.title || "",
        diff: pr.diff || sampleDiff
      });
      setResult(null);
      setIsWebhookModalOpen(false);
      finishProgress("fetch", "Webhook PR loaded");
    } catch (err) {
      finishProgress("fetch", "Load failed");
      setError(err.message || "Failed to load selected webhook PR.");
    } finally {
      setLoadingAction("");
    }
  }

  function onPickHistoryItem(item) {
    if (!item?.run_id) {
      return;
    }
    setLoadingAction("decision-flow");
    setError("");
    startProgress("fetch");
    fetchDecisionHistoryByRun(item.run_id)
      .then((history) => {
        setDecisionHistory(history);
        setForm((prev) => ({
          ...prev,
          pr_id: item?.pr_id || prev.pr_id,
          repo: item?.repo || prev.repo,
          pr_number: item?.pr_number ?? prev.pr_number
        }));
        setIsHistoryModalOpen(false);
        setIsDecisionModalOpen(true);
        finishProgress("fetch", "Decision flow loaded");
      })
      .catch((err) => {
        finishProgress("fetch", "Load failed");
        setError(err.message || "Failed to load selected analysis flow.");
      })
      .finally(() => {
        setLoadingAction("");
      });
  }

  function formatRunStatus(status) {
    const normalized = String(status || "").toLowerCase();
    if (normalized === "completed") {
      return "pass";
    }
    if (normalized === "failed") {
      return "fail";
    }
    return "neutral";
  }

  function formatRunLabel(status) {
    return String(status || "unknown").toUpperCase();
  }

  function formatActionLabel(actionType) {
    const t = String(actionType || "").toLowerCase();
    if (t === "comment_added") return "Post comment";
    if (t === "pr_approved") return "Approve PR";
    return t.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) || "Action";
  }

  function renderRunTime(item) {
    const finished = item?.finished_at ? `Finished: ${item.finished_at}` : "Finished: -";
    return `Started: ${item?.started_at || "-"} | ${finished}`;
  }

  async function onGenerateEncryptionKey() {
    setOnboardingBusy(true);
    setError("");
    try {
      await generateAppSecret();
      const ob = await fetchOnboardingStatus();
      setOnboardingStatus(ob);
      setCryptoStatus(await fetchCryptoStatus());
    } catch (err) {
      setError(err.message || "Could not generate or save the encryption key.");
    } finally {
      setOnboardingBusy(false);
    }
  }

  async function onOnboardingFirstProject(e) {
    e.preventDefault();
    if (!newProject.full_name.trim() || !newProject.github_token.trim()) {
      setError("Repository (owner/repo) and GitHub token are required.");
      return;
    }
    setOnboardingBusy(true);
    setError("");
    try {
      await createProject({
        full_name: newProject.full_name.trim(),
        github_token: newProject.github_token,
        webhook_secret: newProject.webhook_secret || ""
      });
      const projRes = await fetchProjects();
      const items = Array.isArray(projRes?.items) ? projRes.items : [];
      setProjects(items);
      const ob = await fetchOnboardingStatus();
      setOnboardingStatus(ob);
      setCryptoStatus(await fetchCryptoStatus());
      setNewProject({ full_name: "", github_token: "", webhook_secret: "" });
      if (ob.onboarding_complete) {
        await loadInitialPrForProjects(items);
      }
    } catch (err) {
      setError(err.message || "Could not save the first repository.");
    } finally {
      setOnboardingBusy(false);
    }
  }

  if (bootstrapping || onboardingStatus === null) {
    return (
      <div className="onboarding-fullscreen">
        <p className="onboarding-loading">Starting application…</p>
      </div>
    );
  }

  if (!onboardingStatus.onboarding_complete) {
    return (
      <div className="onboarding-fullscreen">
        <div className="onboarding-card">
          <h1 className="onboarding-title">Welcome</h1>
          <p className="onboarding-lead">Complete setup to use AgentAI PR Reviewer with your GitHub repositories.</p>
          {error ? (
            <div className="error-banner" style={{ marginBottom: "1rem" }}>
              <strong>Error:</strong> {error}
            </div>
          ) : null}

          {onboardingStatus.needs_encryption ? (
            <section className="onboarding-step">
              <h2>Step 1 of 2 — Encryption key</h2>
              <p className="onboarding-copy">
                A server-side key encrypts stored GitHub tokens and webhook secrets. We can generate one and append{" "}
                <code>APP_SECRET_KEY</code> to your project <code>.env</code> file (repository root). You may restart the API
                afterward; it is optional if the server picks up the new variable immediately.
              </p>
              <button
                type="button"
                className="btn primary onboarding-cta"
                disabled={onboardingBusy}
                onClick={onGenerateEncryptionKey}
              >
                {onboardingBusy ? "Working…" : "Generate key and save to .env"}
              </button>
            </section>
          ) : null}

          {onboardingStatus.needs_first_project ? (
            <section className="onboarding-step">
              <h2>First GitHub repository</h2>
              <p className="onboarding-copy">
                Enter <strong>owner/repo</strong>, your <strong>GitHub token</strong>, and optionally the <strong>webhook secret</strong>{" "}
                used for <code>/webhook/github</code>. You can add or remove more repositories later under Settings.
              </p>
              <form className="onboarding-form" onSubmit={onOnboardingFirstProject}>
                <div className="form-group">
                  <label>Repository (owner/repo)</label>
                  <input
                    value={newProject.full_name}
                    onChange={(e) => setNewProject({ ...newProject, full_name: e.target.value })}
                    placeholder="organization/service"
                    autoComplete="off"
                    disabled={onboardingBusy}
                    required
                  />
                </div>
                <div className="form-group">
                  <label>GitHub personal access token</label>
                  <input
                    type="password"
                    value={newProject.github_token}
                    onChange={(e) => setNewProject({ ...newProject, github_token: e.target.value })}
                    placeholder="ghp_…"
                    autoComplete="new-password"
                    disabled={onboardingBusy}
                    required
                  />
                </div>
                <div className="form-group">
                  <label>Webhook secret (optional)</label>
                  <input
                    type="password"
                    value={newProject.webhook_secret}
                    onChange={(e) => setNewProject({ ...newProject, webhook_secret: e.target.value })}
                    placeholder="Must match GitHub webhook configuration for /webhook/github"
                    autoComplete="new-password"
                    disabled={onboardingBusy}
                  />
                </div>
                <button type="submit" className="btn primary onboarding-cta" disabled={onboardingBusy}>
                  {onboardingBusy ? "Saving…" : "Save and continue"}
                </button>
              </form>
            </section>
          ) : null}
        </div>
      </div>
    );
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
    <div className="app-page">
      <div className="hero-surface">
        <div className="hero-surface-inner">
          <header className="hero">
            <div className="hero-row">
              <div className="hero-title-block">
                <h1>AgentAI PR Reviewer</h1>
                <p>Intelligent multi-agent orchestration for autonomous pull request analysis and correction.</p>
              </div>
              <div className="hero-actions">
                <button
                  className="btn hero-btn"
                  onClick={onShowWebhookInbox}
                  disabled={Boolean(loadingAction) || bootstrapping}
                >
                  {loadingAction === "webhook-inbox" ? "Loading PR Inbox..." : "PR Inbox"}
                </button>
                <button
                  className="btn hero-btn"
                  onClick={onShowPrHistory}
                  disabled={Boolean(loadingAction) || bootstrapping || !projectId}
                >
                  {loadingAction === "pr-history" ? "Loading History..." : "Analysis History"}
                </button>
                <button
                  type="button"
                  className="btn btn-settings hero-btn"
                  aria-label="Settings"
                  title="GitHub projects and credentials"
                  onClick={() => setSettingsOpen(true)}
                  disabled={bootstrapping}
                >
                  <span aria-hidden="true" className="btn-settings-icon">⚙</span>
                  <span>Settings</span>
                </button>
              </div>
            </div>
            <div className="hero-toolbar">
              <label className="project-picker">
                <span>Project</span>
                <select
                  value={projectId ?? ""}
                  onChange={onProjectChange}
                  disabled={bootstrapping || !projects.length || Boolean(loadingAction)}
                >
                  {!projects.length ? <option value="">No projects yet</option> : null}
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.full_name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {loadingAction === "switch-project" && (
              <div className="project-switch-loader" role="status" aria-live="polite">
                <span className="project-switch-loader__spinner" />
                <span>Loading selected project details...</span>
              </div>
            )}
          </header>
        </div>
        {error ? (
          <div className="hero-alert-bar hero-alert-bar--error" role="alert">
            <strong>Error:</strong> {error}
          </div>
        ) : null}
        {!error && info ? (
          <div className="hero-alert-bar hero-alert-bar--info">
            <strong>Note:</strong> {info}
          </div>
        ) : null}
      </div>

      <div className="app-shell">
      <aside className="sidebar">
        <section className="panel">
          <div className="panel-header">
            <h3>Configuration</h3>
          </div>
          <div className="panel-body">
            {!projects.length && !bootstrapping ? (
              <p style={{ fontSize: "0.8rem", color: "var(--color-accent-fg)", marginBottom: "1rem" }}>
                Add a repository under <strong>Settings</strong> (top left). The server must have <code>APP_SECRET_KEY</code> set to store tokens securely.
              </p>
            ) : null}
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
                disabled={Boolean(loadingAction) || bootstrapping || !projectId}
              >
                {loadingAction === "review" ? "Analyzing..." : "Review Logic Flow"}
              </button>
              <button className="btn" onClick={onShowOpenPrs} disabled={Boolean(loadingAction) || bootstrapping || !projectId}>
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
                <h3>Recorded actions</h3>
              </div>
              <div className="panel-body">
                {prActions.length ? (
                  <ul className="pr-actions-list" style={{ listStyle: "none", margin: 0, padding: 0 }}>
                    {prActions.map((a) => (
                      <li
                        key={a.id}
                        style={{
                          display: "flex",
                          flexWrap: "wrap",
                          gap: "0.5rem 1rem",
                          alignItems: "baseline",
                          padding: "0.5rem 0",
                          borderBottom: "1px solid var(--color-border-default)"
                        }}
                      >
                        <span className={`status-badge ${a.action_status === "success" ? "pass" : "fail"}`}>
                          {formatActionLabel(a.action_type)}
                        </span>
                        <span style={{ fontSize: "0.82rem", color: "var(--color-fg-muted)" }}>
                          {a.created_at || ""} · {String(a.actor || "system")}
                          {a.details ? ` · ${a.details}` : ""}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p style={{ color: "var(--color-fg-muted)", fontSize: "0.875rem", margin: 0 }}>
                    No actions logged for this PR yet (e.g. post comment or approve after analysis).
                  </p>
                )}
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
                <div className="github-action-buttons" style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", marginTop: "0.75rem" }}>
                  <button
                    className="btn"
                    onClick={onPostCommentToGithub}
                    disabled={Boolean(loadingAction) || bootstrapping || !finalComment || !projectId}
                  >
                    {loadingAction === "post-comment" ? "Posting…" : "Post comment"}
                  </button>
                  <button
                    className="btn"
                    onClick={onApprovePr}
                    disabled={Boolean(loadingAction) || bootstrapping || !projectId}
                  >
                    {loadingAction === "approve-pr" ? "Approving…" : "Approve PR"}
                  </button>
                </div>
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

      {settingsOpen && (
        <div className="modal-backdrop" onClick={() => !settingsBusy && setSettingsOpen(false)}>
          <div className="modal settings-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>GitHub projects</h3>
              <button type="button" className="btn modal-close" disabled={settingsBusy} onClick={() => setSettingsOpen(false)}>
                Close
              </button>
            </div>
            <div className="modal-body">
              <p style={{ fontSize: "0.8rem", color: "var(--color-fg-muted)", marginBottom: "1rem" }}>
                Tokens and webhook secrets are stored encrypted (Fernet) when the server has{" "}
                <code>APP_SECRET_KEY</code> set. Configure the same webhook URL (<code>/webhook/github</code>) on GitHub;
                signing uses the webhook secret saved per repo.
              </p>
              {cryptoStatus && !cryptoStatus.encryption_configured ? (
                <p style={{ fontSize: "0.85rem", color: "var(--color-danger-fg)", marginBottom: "1rem" }}>
                  Encryption is off — add projects from the API cannot be persisted securely. Set{" "}
                  <code>APP_SECRET_KEY</code> on the backend, then restart. {cryptoStatus.hint}
                </p>
              ) : null}
              <h4 style={{ fontSize: "0.8rem", marginBottom: "0.5rem" }}>Registered repositories</h4>
              {projects.length === 0 ? (
                <p style={{ color: "var(--color-fg-muted)", fontSize: "0.875rem" }}>None yet. Add one below.</p>
              ) : (
                <ul className="settings-project-list">
                  {projects.map((p) => (
                    <li key={p.id} className="settings-project-row">
                      <div>
                        <strong>{p.full_name}</strong>
                        <span className="settings-project-meta">
                          {p.has_github_token ? "Token stored" : "No token"} ·{" "}
                          {p.has_webhook_secret ? "Webhook secret stored" : "No webhook secret"}
                        </span>
                      </div>
                      <button
                        type="button"
                        className="btn danger-outline"
                        disabled={settingsBusy}
                        onClick={() => onDeleteProject(p.id)}
                      >
                        Remove
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <form className="settings-add-form" onSubmit={onSaveNewProject}>
                <h4 style={{ fontSize: "0.8rem", margin: "1.25rem 0 0.5rem" }}>Add repository</h4>
                <div className="form-group">
                  <label>Repository (owner/repo)</label>
                  <input
                    value={newProject.full_name}
                    onChange={(e) => setNewProject({ ...newProject, full_name: e.target.value })}
                    placeholder="org/my-service"
                    autoComplete="off"
                    disabled={settingsBusy}
                  />
                </div>
                <div className="form-group">
                  <label>GitHub personal access token</label>
                  <input
                    type="password"
                    value={newProject.github_token}
                    onChange={(e) => setNewProject({ ...newProject, github_token: e.target.value })}
                    placeholder="ghp_…"
                    autoComplete="new-password"
                    disabled={settingsBusy}
                  />
                </div>
                <div className="form-group">
                  <label>Webhook secret (optional, for /webhook/github)</label>
                  <input
                    type="password"
                    value={newProject.webhook_secret}
                    onChange={(e) => setNewProject({ ...newProject, webhook_secret: e.target.value })}
                    placeholder="Same value as in GitHub webhook settings"
                    autoComplete="new-password"
                    disabled={settingsBusy}
                  />
                </div>
                <button type="submit" className="btn primary" disabled={settingsBusy || !cryptoStatus?.encryption_configured}>
                  {settingsBusy ? "Saving…" : "Save project"}
                </button>
                {!cryptoStatus?.encryption_configured ? (
                  <p style={{ fontSize: "0.75rem", color: "var(--color-fg-muted)", marginTop: "0.5rem" }}>
                    Save disabled until <code>APP_SECRET_KEY</code> is configured on the server.
                  </p>
                ) : null}
              </form>
            </div>
          </div>
        </div>
      )}

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

      {isDecisionModalOpen && (
        <div className="modal-backdrop" onClick={() => setIsDecisionModalOpen(false)}>
          <div className="modal decision-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Agent Decision Flow</h3>
              <button className="btn modal-close" onClick={() => setIsDecisionModalOpen(false)}>Close</button>
            </div>
            <div className="modal-body">
              {decisionHistory?.run ? (
                <>
                  <div className="decision-overview">
                    <span><strong>PR:</strong> {decisionHistory.run.pr_id}</span>
                    <span><strong>Run ID:</strong> {decisionHistory.run.id}</span>
                    <span><strong>Status:</strong> {String(decisionHistory.run.status || "").toUpperCase()}</span>
                  </div>

                  <div className="decision-user-actions" style={{ marginBottom: "1.25rem" }}>
                    <h4 style={{ fontSize: "0.9rem", margin: "0 0 0.5rem", color: "var(--color-fg-default)" }}>
                      Recorded actions (this PR)
                    </h4>
                    <p style={{ fontSize: "0.75rem", color: "var(--color-fg-muted)", margin: "0 0 0.75rem" }}>
                      GitHub actions logged for this pull request (post comment, approve, webhook comments, etc.), same as on the main analysis view.
                    </p>
                    {decisionFlowActionsLoading ? (
                      <p style={{ fontSize: "0.82rem", color: "var(--color-fg-muted)", margin: 0 }}>Loading actions…</p>
                    ) : decisionFlowActions.length ? (
                      <ul style={{ listStyle: "none", margin: 0, padding: 0, maxHeight: "200px", overflowY: "auto" }}>
                        {decisionFlowActions.map((a) => (
                          <li
                            key={`df-${a.id}`}
                            style={{
                              display: "flex",
                              flexWrap: "wrap",
                              gap: "0.35rem 0.75rem",
                              alignItems: "baseline",
                              padding: "0.45rem 0",
                              borderBottom: "1px solid var(--color-border-default)",
                              fontSize: "0.8rem"
                            }}
                          >
                            <span className={`status-badge ${a.action_status === "success" ? "pass" : "fail"}`}>
                              {formatActionLabel(a.action_type)}
                            </span>
                            <span style={{ color: "var(--color-fg-muted)" }}>
                              {a.created_at || "—"} · {String(a.actor || "system")}
                              {a.run_id != null ? ` · run #${a.run_id}` : ""}
                              {a.details ? ` · ${a.details}` : ""}
                            </span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p style={{ fontSize: "0.82rem", color: "var(--color-fg-muted)", margin: 0 }}>
                        No actions recorded for this PR yet.
                      </p>
                    )}
                  </div>

                  <div className="decision-rail">
                    {(decisionHistory.steps || []).map((step) => (
                      <article className="decision-card" key={step.id}>
                        <div className="decision-card-head">
                          <span className="decision-step-chip">Step {step.step_order}</span>
                          <span className={`status-badge ${step.severity === "high" || step.severity === "critical" ? "fail" : step.severity === "medium" ? "neutral" : "pass"}`}>
                            {String(step.agent_name || "").toUpperCase()}
                          </span>
                        </div>
                        <p className="decision-line"><strong>Decision:</strong> {step.decision_type}</p>
                        <p className="decision-line"><strong>Goal:</strong> {step.decision_goal}</p>
                        <p className="decision-line"><strong>Why:</strong> {step.selection_reason}</p>
                        <p className="decision-line"><strong>Chosen:</strong> {step.selected_option}</p>
                        {step.next_action ? <p className="decision-line"><strong>Next:</strong> {step.next_action}</p> : null}
                        <div className="decision-grid">
                          <div className="decision-cell">
                            <h4>Signals</h4>
                            {(step.signals || []).length ? (
                              step.signals.map((sig, idx) => (
                                <p key={`${step.id}-sig-${idx}`}>{sig.signal_type}: {sig.signal_value}</p>
                              ))
                            ) : <p>None</p>}
                          </div>
                          <div className="decision-cell">
                            <h4>Policies</h4>
                            {(step.policy_checks || []).length ? (
                              step.policy_checks.map((pol, idx) => (
                                <p key={`${step.id}-pol-${idx}`}>{pol.policy_name}: {pol.result}</p>
                              ))
                            ) : <p>None</p>}
                          </div>
                        </div>
                      </article>
                    ))}
                  </div>
                </>
              ) : (
                <p style={{ color: "var(--color-fg-muted)" }}>No decision history available for this PR.</p>
              )}
            </div>
          </div>
        </div>
      )}

      {isHistoryModalOpen && (
        <div className="modal-backdrop" onClick={() => setIsHistoryModalOpen(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Analysis History (All Runs)</h3>
              <button className="btn modal-close" onClick={() => setIsHistoryModalOpen(false)}>Close</button>
            </div>
            <div className="modal-body">
              {prHistoryItems.length === 0 ? (
                <p style={{ color: "var(--color-fg-muted)" }}>No analyzed PR history found yet.</p>
              ) : (
                prHistoryItems.map((item) => (
                  <button key={`${item.pr_id}-${item.run_id}`} className="pr-row" onClick={() => onPickHistoryItem(item)}>
                    <span className="pr-title">{item.pr_id} <span style={{ color: "var(--color-fg-muted)", fontWeight: 500 }}>| Run #{item.run_id}</span></span>
                    <span className="pr-meta">
                      Status: {formatRunLabel(item.status)} | {renderRunTime(item)}
                    </span>
                    <span style={{ marginTop: "0.25rem" }}>
                      <span className={`status-badge ${formatRunStatus(item.status)}`}>{formatRunLabel(item.status)}</span>
                    </span>
                  </button>
                ))
              )}
            </div>
          </div>
        </div>
      )}

      {isWebhookModalOpen && (
        <div className="modal-backdrop" onClick={() => setIsWebhookModalOpen(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>PR Inbox</h3>
              <button className="btn modal-close" onClick={() => setIsWebhookModalOpen(false)}>Close</button>
            </div>
            <div className="modal-body">
              {webhookItems.length === 0 ? (
                <p style={{ color: "var(--color-fg-muted)" }}>No webhook PR events captured yet.</p>
              ) : (
                webhookItems.map((item) => (
                  <button
                    key={`wh-${item.id}`}
                    className="pr-row"
                    onClick={() => onPickWebhookItem(item)}
                    disabled={Boolean(loadingAction)}
                  >
                    <span className="pr-title">
                      {item.pr_id} <span style={{ color: "var(--color-fg-muted)", fontWeight: 500 }}>| {item.action}</span>
                    </span>
                    <span className="pr-meta">
                      Project #{item.project_id ?? "-"} | Status: {String(item.processed_status || "").toUpperCase()} | Received: {item.received_at || "-"}
                    </span>
                    {item.title ? <span className="pr-meta">{item.title}</span> : null}
                  </button>
                ))
              )}
            </div>
          </div>
        </div>
      )}
      </div>
    </div>
  );
}



