// state.js
const KEY = "orderpiqr.tour.progress";

export function loadProgress() {
  try { return JSON.parse(localStorage.getItem(KEY) || "{}"); }
  catch { return {}; }
}

export function saveProgress({ section, step }) {
  localStorage.setItem(KEY, JSON.stringify({ section, step }));
}

export function clearProgress() {
  localStorage.removeItem(KEY);
}
