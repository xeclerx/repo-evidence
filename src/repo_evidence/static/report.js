const root = document.querySelector('#report-root');
const analysisId = root.dataset.analysisId;
const startedAt = Date.now();
const views = ['loading', 'report', 'failure'];
const statusLabels = {
  queued: ['Ожидаем worker', 'Задача поставлена в очередь. Обычно анализ занимает меньше минуты.'],
  running: ['Анализ выполняется', 'Строим AST, запускаем правила и собираем доказательства.'],
};
let stopped = false;
let consecutiveErrors = 0;
let currentChecks = [];
let elapsedTimer;

const escapeHtml = (value) => String(value ?? '').replace(
  /[&<>'"]/g,
  (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]),
);

function setView(active) {
  views.forEach((view) => {
    document.querySelector(`#${view}`).hidden = view !== active;
  });
}

function elapsedSeconds() {
  return Math.floor((Date.now() - startedAt) / 1000);
}

function updateElapsed() {
  const seconds = elapsedSeconds();
  const minutes = String(Math.floor(seconds / 60)).padStart(2, '0');
  const remainder = String(seconds % 60).padStart(2, '0');
  document.querySelector('#elapsed-time').textContent = `${minutes}:${remainder}`;
  document.querySelector('#worker-hint').hidden = seconds < 30;
}

function updateLoading(analysis) {
  const [phase, detail] = statusLabels[analysis.status] || ['Проверяем состояние', analysis.status];
  document.querySelector('#loading-phase').textContent = phase;
  document.querySelector('#loading-status').textContent = detail;
  document.querySelector('#loading-title').textContent = analysis.repository
    ? `${analysis.repository.owner}/${analysis.repository.name}`
    : 'Готовим отчёт';
  document.querySelector('#progress-line').style.width = analysis.status === 'running' ? '68%' : '18%';
  const steps = [...document.querySelectorAll('.state-steps span')];
  steps.forEach((step, index) => step.classList.toggle('active', analysis.status === 'running' ? index <= 2 : index === 0));
}

async function fetchJson(url, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch(url, {...options, signal: controller.signal});
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
    return payload;
  } finally {
    clearTimeout(timeout);
  }
}

async function poll() {
  if (stopped) return;
  try {
    const analysis = await fetchJson(`/api/v1/analyses/${analysisId}`);
    consecutiveErrors = 0;
    if (analysis.status === 'completed') {
      stopped = true;
      clearInterval(elapsedTimer);
      await renderReport();
      return;
    }
    if (analysis.status === 'failed') {
      stopped = true;
      clearInterval(elapsedTimer);
      showFailure(analysis.error_detail || analysis.error_code || 'Worker завершил задачу с ошибкой.');
      return;
    }
    updateLoading(analysis);
    setTimeout(poll, elapsedSeconds() > 90 ? 5000 : 1800);
  } catch (error) {
    consecutiveErrors += 1;
    if (consecutiveErrors >= 3) {
      stopped = true;
      clearInterval(elapsedTimer);
      showFailure(`Не удалось получить состояние анализа: ${error.message}`);
      return;
    }
    setTimeout(poll, 2500);
  }
}

async function renderReport() {
  try {
    const report = await fetchJson(`/api/v1/analyses/${analysisId}/report`);
    const analysis = report.analysis;
    document.querySelector('#repository-name').textContent = `${analysis.repository.owner}/${analysis.repository.name}`;
    document.querySelector('#github-link').href = analysis.repository.html_url;
    document.querySelector('#framework').textContent = analysis.framework;
    document.querySelector('#commit').textContent = analysis.commit_sha.slice(0, 12);
    document.querySelector('#score').textContent = analysis.score ?? '—';
    document.querySelector('#maturity').textContent = analysis.maturity || 'Недостаточно данных';
    document.querySelector('#coverage-value').textContent = `${analysis.coverage}%`;
    document.querySelector('#checks-total').textContent = report.checks.length;
    const issues = report.checks.filter((check) => ['failed', 'partial'].includes(check.status));
    document.querySelector('#issues-total').textContent = issues.length;
    document.querySelector('#coverage').textContent = `Evidence coverage ${analysis.coverage}%`;
    renderCategories(report.categories);
    renderRecommendations(report.recommendations);
    currentChecks = report.checks;
    renderFilterButtons();
    renderChecks('all');
    setView('report');
    void loadHistory(analysis);
  } catch (error) {
    showFailure(`Отчёт готов, но не удалось отобразить данные: ${error.message}`);
  }
}

function renderCategories(categories) {
  document.querySelector('#categories').innerHTML = categories.map((category) => {
    const percent = Math.round(category.score / category.max_score * 100);
    return `<div class="metric-row"><span>${escapeHtml(category.title)}</span><div class="metric-track"><i style="width:${percent}%"></i></div><small>${percent}%</small><strong>${category.score}/${category.max_score}</strong></div>`;
  }).join('');
}

function renderRecommendations(recommendations) {
  const sorted = [...recommendations].sort(
    (left, right) => (right.max_points - right.points) - (left.max_points - left.points),
  );
  const visible = sorted.slice(0, 8);
  document.querySelector('#recommendation-count').textContent = `${sorted.length} требуют внимания`;
  document.querySelector('#recommendations').innerHTML = visible.length
    ? visible.map((check, index) => {
      const impact = Math.round(check.max_points - check.points);
      return `<article class="recommendation"><span class="recommendation-index">${String(index + 1).padStart(2, '0')}</span><div><strong>${escapeHtml(check.title)}</strong><p>${escapeHtml(check.recommendation)}</p></div><span class="impact">−${impact} pt</span></article>`;
    }).join('')
    : '<p class="empty-copy">Приоритетных рекомендаций нет.</p>';
}

function renderFilterButtons() {
  const filters = [
    ['all', 'Все'], ['failed', 'Ошибки'], ['partial', 'Частично'], ['passed', 'Пройдено'],
  ];
  document.querySelector('#check-filters').innerHTML = filters.map(
    ([value, label], index) => `<button class="filter-button ${index === 0 ? 'active' : ''}" type="button" data-filter="${value}">${label}</button>`,
  ).join('');
  document.querySelectorAll('.filter-button').forEach((button) => {
    button.addEventListener('click', () => {
      document.querySelectorAll('.filter-button').forEach((item) => item.classList.remove('active'));
      button.classList.add('active');
      renderChecks(button.dataset.filter);
    });
  });
}

function renderChecks(filter) {
  const checks = filter === 'all' ? currentChecks : currentChecks.filter((check) => check.status === filter);
  document.querySelector('#checks').innerHTML = checks.map(renderCheck).join('') || '<p class="empty-copy">Проверок с таким статусом нет.</p>';
}

function renderCheck(check) {
  const evidence = check.evidence.map((item) => `<a href="${encodeURI(item.url)}" target="_blank" rel="noreferrer">${escapeHtml(item.path)}${item.line_start ? `:${item.line_start}` : ''}</a>`).join('');
  return `<article class="check"><i class="status ${check.status}"></i><div><h3>${escapeHtml(check.title)}</h3><p>${escapeHtml(check.explanation)}</p><div class="evidence">${evidence}</div></div><span class="check-score">${check.points}/${check.max_points}</span></article>`;
}

async function loadHistory(analysis) {
  try {
    const history = await fetchJson(`/api/v1/repositories/${encodeURIComponent(analysis.repository.owner)}/${encodeURIComponent(analysis.repository.name)}/analyses`);
    const completed = history.analyses.filter((item) => item.status === 'completed');
    document.querySelector('#history').innerHTML = completed.map((item) => {
      const action = item.id !== analysis.id
        ? `<a href="/comparisons/${item.id}/${analysis.id}">Сравнить с текущим →</a>`
        : '<small>Текущий отчёт</small>';
      return `<article class="history-item"><div><strong>${escapeHtml(item.commit_sha.slice(0, 10))}</strong><span>${item.score ?? '—'} / 100</span></div>${action}</article>`;
    }).join('') || '<p class="empty-copy">Это первый анализ.</p>';
  } catch {
    document.querySelector('#history').innerHTML = '<p class="empty-copy">История временно недоступна.</p>';
  }
}

function showFailure(detail) {
  setView('failure');
  document.querySelector('#failure-detail').textContent = detail;
}

document.querySelector('#retry-status').addEventListener('click', () => {
  stopped = false;
  consecutiveErrors = 0;
  setView('loading');
  elapsedTimer = setInterval(updateElapsed, 1000);
  void poll();
});

setView('loading');
updateElapsed();
elapsedTimer = setInterval(updateElapsed, 1000);
void poll();

