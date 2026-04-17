const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

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

export async function fetchDefaultPr() {
  const res = await fetch(`${API_BASE}/github/default-pr`);
  if (!res.ok) {
    throw new Error(await parseError(res, "Default PR fetch failed"));
  }
  return res.json();
}

export async function fetchOpenPrs() {
  const res = await fetch(`${API_BASE}/github/open-prs`);
  if (!res.ok) {
    throw new Error(await parseError(res, "Open PR list fetch failed"));
  }
  return res.json();
}

export async function fetchPrDetails(prNumber) {
  const res = await fetch(`${API_BASE}/github/pr/${encodeURIComponent(prNumber)}`);
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
