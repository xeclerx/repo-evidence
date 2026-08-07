const root = document.querySelector('#comparison-root');
const escapeHtml = (value) => String(value ?? '').replace(
  /[&<>'"]/g,
  (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]),
);

async function loadComparison() {
  const response = await fetch(`/api/v1/comparisons?base=${root.dataset.base}&head=${root.dataset.head}`);
  const data = await response.json();
  if (!response.ok) {
    document.querySelector('#comparison-loading').innerHTML = `<p>${escapeHtml(data.detail || 'Ошибка сравнения.')}</p>`;
    return;
  }
  document.querySelector('#comparison-loading').hidden = true;
  document.querySelector('#comparison').hidden = false;
  const delta = data.score_delta;
  const score = document.querySelector('#score-delta');
  score.textContent = delta === null ? '—' : `${delta > 0 ? '+' : ''}${delta}`;
  score.className = delta > 0 ? 'delta-positive' : delta < 0 ? 'delta-negative' : '';
  document.querySelector('#category-deltas').innerHTML = Object.entries(data.category_deltas).map(
    ([name, value]) => `<div class="metric-row"><span>${escapeHtml(name)}</span><div class="metric-track"><i style="width:${Math.min(100, Math.abs(value) * 5)}%"></i></div><small>delta</small><strong>${value > 0 ? '+' : ''}${value}</strong></div>`,
  ).join('');
  document.querySelector('#improved').innerHTML = renderChanges(data.improved, 'Улучшений пока нет.');
  document.querySelector('#regressed').innerHTML = renderChanges(data.regressed, 'Регрессий нет.');
}

function renderChanges(changes, empty) {
  return changes.length
    ? changes.map((item) => `<article class="check"><i class="status ${item.after_status}"></i><div><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.before_status)} → ${escapeHtml(item.after_status)}</p></div><span class="check-score">${item.points_delta > 0 ? '+' : ''}${item.points_delta}</span></article>`).join('')
    : `<p class="empty-copy">${empty}</p>`;
}

void loadComparison();
