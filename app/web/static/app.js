const $ = id => document.getElementById(id);
let active = null;
let timer = null;
const rememberedKey = 'hexa.web.lastJob';

function busy(on) {
  for (const id of ['generate', 'package', 'folder', 'audio']) $(id).disabled = on;
  $('cancel').disabled = !on;
}

function status(message) { $('status').textContent = message; }

function links(id) {
  for (const kind of ['youtube', 'reels', 'manifest', 'diagnostics']) {
    $(kind).href = `/api/jobs/${id}/download/${kind}`;
  }
  $('results').hidden = false;
}

function watch(id) {
  active = id;
  localStorage.setItem(rememberedKey, id);
  busy(true);
  if (timer) clearInterval(timer);
  timer = setInterval(poll, 1200);
  poll();
}

function showJob(job, events) {
  $('progress').value = Math.round(job.progress * 100);
  status(`${job.stage || job.state}: ${job.message || ''}`);
  $('log').textContent = events.map(event => event.line).join('\n');
  if (['completed', 'failed', 'canceled'].includes(job.state)) {
    clearInterval(timer);
    timer = null;
    busy(false);
    if (job.state === 'completed') {
      links(job.id);
      $('export-path').textContent = job.export_directory || '';
    }
    active = null;
  } else {
    busy(true);
    $('cancel').disabled = job.state === 'cancelling';
  }
}

async function poll() {
  if (!active) return;
  try {
    const id = active;
    const [jobResponse, eventResponse] = await Promise.all([
      fetch(`/api/jobs/${id}`), fetch(`/api/jobs/${id}/events`)
    ]);
    if (!jobResponse.ok || !eventResponse.ok) throw Error('تعذر استعادة المهمة');
    showJob(await jobResponse.json(), await eventResponse.json());
  } catch (error) {
    status(`تعذر تحديث الحالة: ${error.message}`);
  }
}

async function reconnect() {
  busy(true);
  try {
    const response = await fetch('/api/jobs/active');
    if (!response.ok) throw Error('تعذر الاتصال بالخادم');
    const job = await response.json();
    if (job.id) { watch(job.id); return; }
    const remembered = localStorage.getItem(rememberedKey);
    if (remembered) {
      const old = await fetch(`/api/jobs/${remembered}`);
      if (old.ok) {
        const snapshot = await old.json();
        const events = await fetch(`/api/jobs/${remembered}/events`).then(r => r.json());
        showJob(snapshot, events);
        if (!['completed', 'failed', 'canceled'].includes(snapshot.state)) {
          watch(remembered);
          return;
        }
      } else {
        localStorage.removeItem(rememberedKey);
      }
    }
    busy(false);
  } catch (error) {
    busy(false);
    status(`تعذر استعادة المهمة: ${error.message}`);
  }
}

$('form').addEventListener('submit', async event => {
  event.preventDefault();
  if (active) return;
  const files = Array.from($('folder').files);
  if (!$('package').files.length && !files.length) {
    status('اختر ZIP أو مجلد Final Package');
    return;
  }
  busy(true);
  $('results').hidden = true;
  $('export-path').textContent = '';
  $('progress').value = 0;
  $('log').textContent = '';
  status('جارٍ رفع الملفات والتحقق منها...');
  const body = new FormData();
  if (files.length) {
    body.append('folder_paths', JSON.stringify(files.map(file => file.webkitRelativePath)));
    for (const file of files) body.append('folder_files', file);
  } else {
    body.append('package', $('package').files[0]);
  }
  body.append('audio', $('audio').files[0]);
  try {
    const response = await fetch('/api/jobs', {method: 'POST', body});
    const data = await response.json();
    if (!response.ok) {
      if (response.status === 409) {
        await reconnect();
        return;
      }
      throw Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
    }
    watch(data.id);
  } catch (error) {
    busy(false);
    status(`تعذر بدء التوليد: ${error.message}`);
  }
});

$('cancel').addEventListener('click', async () => {
  if (!active) return;
  $('cancel').disabled = true;
  try {
    const response = await fetch(`/api/jobs/${active}/cancel`, {method: 'POST'});
    if (!response.ok) throw Error((await response.json()).detail);
    status('جارٍ إيقاف المحرك وتنظيف الموارد...');
  } catch (error) {
    status(error.message);
    $('cancel').disabled = false;
  }
});

$('clear').addEventListener('click', () => { $('log').textContent = ''; });
for (const id of ['package', 'audio', 'folder']) {
  $(id).addEventListener('change', () => {
    $(`${id}-name`).textContent = $(id).files[0]?.webkitRelativePath ||
      $(id).files[0]?.name || '';
  });
}
reconnect();
