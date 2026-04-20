const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

function qProject(projectId) {
  if (projectId == null || projectId === "") {
    return "";
  }
  return `?project_id=${encodeURIComponent(projectId)}`;
}

async function parseError(res, fallbackPrefix) {
  const body = await res.text();
  if (!body) {
    return `${fallbackPrefix}: ${res.status}`;
  }

  try {
    const parsed = JSON.parse(body);
    const detail = parsed?.detail || parsed?.message;
    if (detail) {
      return `${fallbackPrefix}: ${res.status} - ${detail}`;
    }
  } catch (_err) {
    // Non-JSON error bodies are still useful for debugging.
  }

  return `${fallbackPrefix}: ${res.status} - ${body.slice(0, 240)}`;
}

export async function fetchCryptoStatus() {
  const res = await fetch(`${API_BASE}/settings/crypto-status`);
  if (!res.ok) {
    throw new Error(await parseError(res, "Crypto status failed"));
  }
  return res.json();
}

export async function fetchOnboardingStatus() {
  const res = await fetch(`${API_BASE}/settings/onboarding-status`);
  if (!res.ok) {
    throw new Error(await parseError(res, "Onboarding status failed"));
  }
  return res.json();
}

export async function generateAppSecret() {
  const res = await fetch(`${API_BASE}/settings/generate-app-secret`, { method: "POST" });
  if (!res.ok) {
    throw new Error(await parseError(res, "Generate key failed"));
  }
  return res.json();
}

export async function fetchProjects() {
  const res = await fetch(`${API_BASE}/projects`);
  if (!res.ok) {
    throw new Error(await parseError(res, "Projects list failed"));
  }
  return res.json();
}

export async function createProject(payload) {
  const res = await fetch(`${API_BASE}/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!res.ok) {
    throw new Error(await parseError(res, "Create project failed"));
  }
  return res.json();
}

export async function deleteProject(projectId) {
  const res = await fetch(`${API_BASE}/projects/${encodeURIComponent(projectId)}`, { method: "DELETE" });
  if (!res.ok) {
    throw new Error(await parseError(res, "Delete project failed"));
  }
  return res.json();
}

export async function triggerManualReview(payload) {
  const res = await fetch(`${API_BASE}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!res.ok) {
    throw new Error(await parseError(res, "Review failed"));
  }
  return res.json();
}

export async function fetchResult(prId) {
  const res = await fetch(`${API_BASE}/results/${encodeURIComponent(prId)}`);
  if (!res.ok) {
    throw new Error(await parseError(res, "Result fetch failed"));
  }
  return res.json();
}

export async function fetchPrHistory(limit = 100, projectId) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (projectId != null && projectId !== "") {
    params.set("project_id", String(projectId));
  }
  const res = await fetch(`${API_BASE}/decisions/history/runs?${params.toString()}`);
  if (!res.ok) {
    throw new Error(await parseError(res, "PR history fetch failed"));
  }
  return res.json();
}

export async function fetchDecisionHistoryByRun(runId) {
  const res = await fetch(`${API_BASE}/decisions/run/${encodeURIComponent(runId)}`);
  if (!res.ok) {
    throw new Error(await parseError(res, "Decision flow fetch failed"));
  }
  return res.json();
}

export async function fetchDefaultPr(projectId) {
  const res = await fetch(`${API_BASE}/github/default-pr${qProject(projectId)}`);
  if (!res.ok) {
    throw new Error(await parseError(res, "Default PR fetch failed"));
  }
  return res.json();
}

export async function fetchOpenPrs(projectId) {
  const res = await fetch(`${API_BASE}/github/open-prs${qProject(projectId)}`);
  if (!res.ok) {
    throw new Error(await parseError(res, "Open PR list fetch failed"));
  }
  return res.json();
}

export async function fetchPrDetails(prNumber, projectId) {
  const res = await fetch(`${API_BASE}/github/pr/${encodeURIComponent(prNumber)}${qProject(projectId)}`);
  if (!res.ok) {
    throw new Error(await parseError(res, "PR details fetch failed"));
  }
  return res.json();
}

export async function postPrComment(payload) {
  const res = await fetch(`${API_BASE}/github/post-comment`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!res.ok) {
    throw new Error(await parseError(res, "PR comment post failed"));
  }
  return res.json();
}

export async function approvePr(payload) {
  const res = await fetch(`${API_BASE}/github/approve-pr`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!res.ok) {
    throw new Error(await parseError(res, "PR approve failed"));
  }
  return res.json();
}

export async function fetchPrActions(prId) {
  const res = await fetch(`${API_BASE}/actions/${encodeURIComponent(prId)}`);
  if (!res.ok) {
    throw new Error(await parseError(res, "Actions fetch failed"));
  }
  return res.json();
}
