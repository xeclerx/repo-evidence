const form = document.querySelector('#analysis-form');
const input = document.querySelector('#repository-url');
const errorBox = document.querySelector('#form-error');

function normalizeRepositoryUrl(value) {
  const raw = value.trim().replace(/\/$/, '');
  if (/^https:\/\/github\.com\//i.test(raw)) return raw;
  if (/^github\.com\//i.test(raw)) return `https://${raw}`;
  return `https://github.com/${raw.replace(/^\/+/, '')}`;
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  errorBox.hidden = true;
  const button = form.querySelector('button');
  button.disabled = true;
  button.textContent = 'Ставим в очередь…';
  try {
    const response = await fetch('/api/v1/analyses', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({repository_url: normalizeRepositoryUrl(input.value)}),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || 'Не удалось создать анализ.');
    window.location.assign(payload.report_url);
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
    button.disabled = false;
    button.textContent = 'Запустить анализ';
  }
});

