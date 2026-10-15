const $ = id => document.getElementById(id);
const uploadKey = 'hexa.web.upload.v1';
const pendingKey = 'hexa.web.upload.pending.v1';
const jobKey = 'hexa.web.lastJob';
let CHUNK = 256 * 1024;
let activeJob = null, activeUpload = null, files = [], polling = null, stopped = false;
let uploadBusy = false;
let preparing = false;
const say = message => { $('status').textContent = message; };
const fmt = bytes => `${(bytes / 1048576).toFixed(2)} MiB`;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
function blobStore() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('hexa-uploads', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('files');
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
async function storedFiles(id, value) {
  const db = await blobStore();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('files', value === undefined ? 'readonly' : 'readwrite');
    const request = value === undefined ? tx.objectStore('files').get(id) :
      value === null ? tx.objectStore('files').delete(id) : tx.objectStore('files').put(value, id);
    let result;
    request.onsuccess = () => { result = request.result; };
    request.onerror = () => reject(request.error);
    tx.oncomplete = () => { db.close(); resolve(result); };
    tx.onerror = () => { db.close(); reject(tx.error); };
  });
}
async function forgetFiles(id) { try { await storedFiles(id, null); } catch (_) { /* optional cache */ } }
async function sha(blob) {
  const bytes = await crypto.subtle.digest('SHA-256', await blob.arrayBuffer());
  return Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, '0')).join('');
}
async function fingerprint(file) {
  const hashes = [];
  for (let offset = 0; offset < file.size; offset += CHUNK) {
    hashes.push(await sha(file.slice(offset, offset + CHUNK)));
  }
  return sha(new Blob([hashes.join('')]));
}
async function api(url, options = {}) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) { const error = new Error(body.detail || `HTTP ${response.status}`); error.code = response.status; throw error; }
  return body;
}
function permanentInitiationError(error) {
  return [400, 409, 413, 422].includes(error.code);
}
function currentFiles() {
  const folder = Array.from($('folder').files);
  const packageFile = $('package').files[0];
  const audio = $('audio').files[0];
  if ((!folder.length && !packageFile) || !audio) throw Error('اختر ملف ZIP أو مجلد والصوت');
  return {mode: folder.length ? 'folder' : 'zip', files: [
    ...(folder.length ? folder.map((file, i) => ({id: `p${i}`, path: file.webkitRelativePath, role: 'package', file})) :
      [{id: 'p0', path: packageFile.name, role: 'package', file: packageFile}]),
    {id: 'audio', path: audio.name, role: 'audio', file: audio}
  ]};
}
function progress(snapshot, sending = 0, phase = '') {
  const total = snapshot.manifest.files.reduce((n, f) => n + f.size, 0);
  const confirmed = Object.values(snapshot.files).reduce((n, x) => n + x, 0);
  const percent = total ? Math.floor(confirmed / total * 100) : 0;
  $('progress').value = percent;
  const checkpoint = snapshot.updated ? new Date(snapshot.updated * 1000).toLocaleTimeString('ar') : '';
  say(`${phase ? `${phase}: ` : ''}تم تأكيد ${fmt(confirmed)} من ${fmt(total)} (${percent}%)${sending ? `، جارٍ إرسال ${fmt(sending)}` : ''}${checkpoint ? ` • آخر تأكيد: ${checkpoint}` : ''}`);
}
function xhrChunk(url, blob, digest, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest(); xhr.open('PUT', url);
    xhr.setRequestHeader('X-Chunk-SHA256', digest);
    xhr.upload.onprogress = event => onProgress(event.loaded);
    xhr.onload = () => xhr.status < 300 ? resolve() : reject(Object.assign(Error(`HTTP ${xhr.status}`), {code: xhr.status}));
    xhr.onerror = () => reject(Error('انقطع الاتصال'));
    xhr.send(blob);
  });
}
async function runUpload(snapshot) {
  CHUNK = snapshot.chunk_size;
  activeUpload = snapshot.id; localStorage.setItem(uploadKey, snapshot.id); stopped = false;
  $('cancel-upload').hidden = false;
  $('generate').textContent = 'استئناف الرفع';
  if (snapshot.job_id) { localStorage.removeItem(uploadKey); await forgetFiles(snapshot.id); activeUpload = null; watch(snapshot.job_id); return; }
  progress(snapshot);
  $('retry-upload').hidden = snapshot.state !== 'failed';
  if (snapshot.state === 'failed') { say(`فشل التحقق: ${snapshot.error}`); return; }
  if (snapshot.state === 'validating') { say('جارٍ التحقق من الملفات المحفوظة...'); setTimeout(reconnect, 1500); return; }
  if (snapshot.manifest.files.every(f => snapshot.files[f.id] === f.size)) {
    say('جارٍ التحقق من السلامة و Final Package...');
    const result = await api(`/api/uploads/${snapshot.id}/complete`, {method:'POST'});
    localStorage.removeItem(uploadKey); await forgetFiles(snapshot.id); activeUpload = null; watch(result.id); return;
  }
  if (!files.length) { say('الرفع محفوظ. اختر الملفات نفسها ثم اضغط استئناف.'); return; }
  const manifest = snapshot.manifest.files;
  if (files.length !== manifest.length || files.some((f, i) => f.path !== manifest[i].path || f.file.size !== manifest[i].size)) {
    say('الملفات مختلفة عن الرفع المحفوظ. اختر الملفات الأصلية.'); return;
  }
  for (let i = 0; i < files.length; i++) {
    say(`جارٍ التحقق من الملف ${i + 1} من ${files.length}...`);
    if (await fingerprint(files[i].file) !== manifest[i].fingerprint) { say('تطابق اسم الملف وحجمه، لكن محتواه مختلف.'); return; }
  }
  const started = performance.now();
  const initialConfirmed = Object.values(snapshot.files).reduce((n, x) => n + x, 0);
  let retries = 0;
  for (let i = 0; i < files.length && !stopped; i++) {
    const entry = manifest[i], file = files[i].file;
    while (snapshot.files[entry.id] < entry.size && !stopped) {
      const offset = snapshot.files[entry.id], index = Math.floor(offset / CHUNK);
      const blob = file.slice(offset, Math.min(offset + CHUNK, entry.size));
      const digest = await sha(blob);
      try {
        const phase = entry.role === 'audio' ? 'رفع التعليق الصوتي' : 'رفع Final Package';
        await xhrChunk(`/api/uploads/${snapshot.id}/files/${entry.id}/chunks/${index}`, blob, digest, sent => progress(snapshot, sent, phase));
        snapshot = await api(`/api/uploads/${snapshot.id}`);
        const confirmed = Object.values(snapshot.files).reduce((n, x) => n + x, 0);
        const total = snapshot.manifest.files.reduce((n, f) => n + f.size, 0);
        const rate = (confirmed - initialConfirmed) / Math.max(1, (performance.now() - started) / 1000);
        const remaining = rate ? Math.ceil((total - confirmed) / rate) : 0;
        progress(snapshot, 0, phase); say(`${$('status').textContent} • ${fmt(rate)}/s • المتبقي نحو ${remaining} ث • آخر نقطة: ${fmt(confirmed)} • إعادة المحاولة: ${retries}`);
        retries = 0;
      } catch (error) {
        if (stopped) return;
        if ([400, 401, 403, 413, 422].includes(error.code)) throw error;
        snapshot = await api(`/api/uploads/${snapshot.id}`);
        if (snapshot.files[entry.id] > offset) continue;
        if (++retries > 8) { say('توقف الرفع مؤقتاً. اضغط استئناف لإعادة المحاولة.'); return; }
        say(`إعادة الاتصال (${retries})...`); await pause(Math.min(30000, 500 * 2 ** retries) + Math.random() * 500);
      }
    }
  }
  if (stopped) return;
  say('جارٍ التحقق من السلامة و Final Package...');
  const result = await api(`/api/uploads/${snapshot.id}/complete`, {method:'POST'});
  localStorage.removeItem(uploadKey); await forgetFiles(snapshot.id); activeUpload = null; watch(result.id);
}
async function resume(snapshot) {
  if (uploadBusy) return;
  uploadBusy = true;
  $('generate').disabled = true;
  try { await runUpload(snapshot); }
  finally { uploadBusy = false; $('generate').disabled = false; }
}
function links(id) {
  for (const kind of ['youtube','reels','manifest','diagnostics']) $(kind).href = `/api/jobs/${id}/download/${kind}`;
  $('results').hidden = false;
}
function watch(id) {
  activeJob = id; localStorage.setItem(jobKey, id); $('cancel').disabled = false;
  $('cancel-upload').hidden = true;
  $('generate').textContent = 'توليد YouTube + Reels';
  if (polling) clearInterval(polling);
  polling = setInterval(poll, 1200); poll();
}
async function poll() {
  if (!activeJob) return;
  try {
    const id = activeJob;
    const [job, events] = await Promise.all([api(`/api/jobs/${id}`), api(`/api/jobs/${id}/events`)]);
    $('progress').value = Math.round(job.progress * 100);
    const phases = {queued:'بانتظار التوليد',running:'جارٍ التوليد',render:'التصيير',export:'إنهاء الملفات',cancelling:'جارٍ الإلغاء',completed:'اكتمل',failed:'فشل',canceled:'ألغي'};
    say(`${phases[job.stage] || phases[job.state] || job.stage || job.state}: ${job.message || ''}`);
    $('log').textContent = events.map(event => event.line).join('\n');
    if (job.state === 'completed') { links(id); $('export-path').textContent = job.export_directory || ''; }
    $('retry-job').hidden = job.state !== 'failed';
    $('retry-job').dataset.jobId = id;
    if (['completed','failed','canceled'].includes(job.state)) { clearInterval(polling); polling = null; activeJob = null; $('cancel').disabled = true; }
  } catch (error) { say(`تعذر تحديث المهمة: ${error.message}`); }
}
async function reconnect() {
  const active = await api('/api/jobs/active');
  if (active.id) { const old = localStorage.getItem(uploadKey); localStorage.removeItem(uploadKey); if (old) await forgetFiles(old); activeUpload = null; watch(active.id); return; }
  const uid = localStorage.getItem(uploadKey);
  if (uid) {
    try { files = await storedFiles(uid) || []; } catch (_) { files = []; }
    try { await resume(await api(`/api/uploads/${uid}`)); return; }
    catch (error) {
      if (error.code === 404) {
        localStorage.removeItem(uploadKey);
        await forgetFiles(uid);
        files = [];
      } else { say(error.message); return; }
    }
  }
  const pending = localStorage.getItem(pendingKey);
  if (pending) {
    try {
      const session = await api('/api/uploads', {method:'POST', headers:{'Content-Type':'application/json'}, body:pending});
      localStorage.setItem(uploadKey, session.id);
      localStorage.removeItem(pendingKey);
      files = [];
      await resume(session); return;
    } catch (error) {
      if (permanentInitiationError(error)) localStorage.removeItem(pendingKey);
      say(`تعذر استعادة بداية الرفع: ${error.message}`);
      return;
    }
  }
  const old = localStorage.getItem(jobKey);
  if (old) watch(old);
}
$('form').addEventListener('submit', async event => {
  event.preventDefault();
  if (preparing || uploadBusy || activeJob) return;
  preparing = true;
  $('generate').disabled = true;
  try {
    const chosen = currentFiles(); files = chosen.files;
    const existing = localStorage.getItem(uploadKey);
    if (existing) { await resume(await api(`/api/uploads/${existing}`)); return; }
    CHUNK = (await api('/api/uploads/config')).chunk_size;
    const manifest = {mode: chosen.mode, chunk_size: CHUNK, files: []};
    for (let i = 0; i < files.length; i++) {
      say(`تحضير الملف ${i + 1} من ${files.length}...`);
      const f = files[i]; manifest.files.push({id:f.id,path:f.path,size:f.file.size,fingerprint:await fingerprint(f.file),role:f.role});
    }
    const saved = localStorage.getItem(pendingKey);
    let pending = saved ? JSON.parse(saved) : {key:crypto.randomUUID(),manifest};
    if (JSON.stringify(pending.manifest) !== JSON.stringify(manifest)) throw Error('هناك بداية رفع محفوظة لملفات أخرى. اختر الملفات الأصلية.');
    localStorage.setItem(pendingKey, JSON.stringify(pending));
    let snapshot;
    try {
      snapshot = await api('/api/uploads', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(pending)});
    } catch (error) {
      if (permanentInitiationError(error)) localStorage.removeItem(pendingKey);
      throw error;
    }
    localStorage.setItem(uploadKey, snapshot.id);
    localStorage.removeItem(pendingKey);
    if (files.reduce((n, f) => n + f.file.size, 0) <= 100 * 1048576) {
      try { await storedFiles(snapshot.id, files); } catch (_) { /* Quota or permission: reselect after refresh. */ }
    }
    await resume(snapshot);
  } catch (error) { say(`تعذر الرفع: ${error.message}`); }
  finally { preparing = false; $('generate').disabled = false; }
});
$('retry-upload').addEventListener('click', async () => {
  if (!activeUpload) return;
  try { $('retry-upload').hidden = true; await resume(await api(`/api/uploads/${activeUpload}/retry`, {method:'POST'})); }
  catch (error) { say(error.message); $('retry-upload').hidden = false; }
});
$('cancel').addEventListener('click', async () => {
  if (!activeJob) return;
  try { await api(`/api/jobs/${activeJob}/cancel`, {method:'POST'}); say('جارٍ إلغاء التوليد...'); } catch (error) { say(error.message); }
});
$('retry-job').addEventListener('click', async () => {
  try { const result = await api(`/api/jobs/${$('retry-job').dataset.jobId}/retry`, {method:'POST'}); $('retry-job').hidden = true; watch(result.id); }
  catch (error) { say(error.message); }
});
$('cancel-upload').addEventListener('click', async () => {
  if (!activeUpload || !confirm('حذف الرفع المحفوظ؟')) return;
  stopped = true;
  try { await api(`/api/uploads/${activeUpload}`, {method:'DELETE'}); await forgetFiles(activeUpload); localStorage.removeItem(uploadKey); activeUpload = null; $('cancel-upload').hidden = true; say('حُذف الرفع.'); } catch (error) { say(error.message); }
});
$('clear').addEventListener('click', () => { $('log').textContent = ''; });
for (const id of ['package','folder','audio']) $(id).addEventListener('change', () => { $(`${id}-name`).textContent = $(id).files[0]?.webkitRelativePath || $(id).files[0]?.name || ''; });
async function ensureSession() {
  const state = await api('/api/session');
  if (!state.auth_required || state.authenticated) return true;
  const token = prompt('رمز الدخول إلى HEXA'); if (!token) return false;
  await api('/api/session', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token})}); return true;
}
ensureSession().then(ok => { if (ok) reconnect(); }).catch(error => say(error.message));
