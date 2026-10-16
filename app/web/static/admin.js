const $ = id => document.getElementById(id);
const csrf = () => decodeURIComponent(document.cookie.match(/(?:^|; )hexa_csrf=([^;]*)/)?.[1] || '');
const message = value => { $('message').textContent = value; };
const date = value => value ? new Date(value * 1000).toLocaleString('ar') : 'غير معروف';
const mb = value => value == null ? '—' : `${(value / 1048576).toFixed(1)} MiB`;
async function api(path, options = {}) {
  options.headers = {...options.headers, 'X-CSRF-Token': csrf()};
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  if (response.status === 401) location.assign('/login');
  if (!response.ok) throw Error(body.detail || `HTTP ${response.status}`);
  return body;
}
function cell(row, value) { const item = row.insertCell(); item.textContent = value ?? '—'; return item; }
function action(row, label, handler) { const button = document.createElement('button'); button.textContent = label; button.addEventListener('click', handler); row.lastElementChild.append(button); }
let pages = {users:1,exports:1,history:1};
async function overview() {
  const data = await api('/api/admin/overview');
  const labels = {users_total:'المستخدمون',users_active:'الحسابات النشطة',users_disabled:'الحسابات المعطلة',jobs_completed:'مهام مكتملة',jobs_failed:'مهام فاشلة',jobs_active:'مهام جارية',packages:'حزم Final Package',bundles:'نسخ فيديو مكتملة',output_files:'ملفات MP4',export_bytes:'حجم ملفات الفيديو',disk_free_bytes:'مساحة القرص المتاحة'};
  $('cards').replaceChildren();
  for (const [key,label] of Object.entries(labels)) {
    const card = document.createElement('div'); card.className = 'card';
    const title = document.createElement('span'); title.textContent = label;
    const value = document.createElement('strong'); value.textContent = key.endsWith('_bytes') ? mb(data[key]) : String(data[key] ?? '—');
    card.append(title,value); $('cards').append(card);
  }
}
async function users() {
  const data = await api(`/api/admin/users?search=${encodeURIComponent($('user-search').value)}&page=${pages.users}`);
  $('user-rows').replaceChildren();
  for (const user of data.items) {
    const row = $('user-rows').insertRow(); cell(row,user.email_normalized); cell(row,user.role); cell(row,user.deleted_at ? 'محذوف' : user.is_active ? 'نشط' : 'معطل'); cell(row,date(user.last_login_at)); cell(row,'');
    if (user.deleted_at) continue;
    action(row,'تعديل البريد', async () => { const email = prompt('البريد الجديد', user.email_normalized); if (email) await updateUser(user.id,{email}); });
    action(row,user.is_active ? 'تعطيل' : 'تفعيل', async () => { if (confirm(`تأكيد تغيير حالة ${user.email_normalized}؟`)) await updateUser(user.id,{is_active:!user.is_active}); });
    action(row,'تغيير الدور', async () => { if (confirm(`تغيير دور ${user.email_normalized}؟`)) await updateUser(user.id,{role:user.role==='ADMIN'?'USER':'ADMIN'}); });
    action(row,'إعادة تعيين كلمة المرور', async () => { const password = prompt('كلمة مرور مؤقتة جديدة (12 حرفاً على الأقل)'); if (password && confirm(`إعادة تعيين كلمة مرور ${user.email_normalized}؟`)) await updateUser(user.id,{password}); });
    action(row,'حذف', async () => { if (confirm(`حذف حساب ${user.email_normalized} وتعطيل جلساته؟`)) await updateUser(user.id,{delete:true}); });
  }
  $('users-more').disabled = pages.users * 50 >= data.total;
}
async function updateUser(id, body) { try { await api(`/api/admin/users/${id}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); message('تم الحفظ'); await users(); } catch(error) { message(error.message); } }
async function exportsList() {
  const data = await api(`/api/admin/exports?search=${encodeURIComponent($('export-search').value)}&page=${pages.exports}`);
  $('export-rows').replaceChildren();
  for (const item of data.items) {
    const row = $('export-rows').insertRow();
    for (const value of [item.slug,`v${item.version}`,item.status,mb(item.outputs?.youtube),mb(item.outputs?.reels),mb(item.bytes),'']) cell(row,value);
    if (item.status === 'AVAILABLE') {
      for (const kind of ['youtube','reels']) if (item.outputs?.[kind] != null) {
        const link = document.createElement('a'); link.href = `/api/admin/exports/${encodeURIComponent(item.id)}/download/${kind}`; link.textContent = kind; row.lastElementChild.append(link,' ');
      }
      action(row,'حذف النسخة',async () => {
        if (!confirm(`حذف ملفات ${item.slug} / v${item.version} نهائياً؟`)) return;
        try { await api(`/api/admin/exports/${encodeURIComponent(item.id)}`,{method:'DELETE'}); message('حُذفت الملفات وبقي السجل'); await exportsList(); }
        catch(error) { message(error.message); }
      });
    }
  }
  $('exports-more').disabled = pages.exports * 50 >= data.total;
}
async function history() {
  const from = $('history-from').value ? new Date(`${$('history-from').value}T00:00:00`).getTime()/1000 : '';
  const to = $('history-to').value ? new Date(`${$('history-to').value}T00:00:00`).getTime()/1000 + 86400 : '';
  const data = await api(`/api/admin/history?search=${encodeURIComponent($('history-search').value)}&state=${encodeURIComponent($('history-state').value)}&page=${pages.history}&sort=${$('history-sort').value}${from ? `&from_at=${from}` : ''}${to ? `&to_at=${to}` : ''}`);
  $('history-rows').replaceChildren();
  $('history-totals').textContent = `الإجمالي ${data.total} • مكتمل ${data.completed} • فاشل ${data.failed}`;
  for (const item of data.items) { const row = $('history-rows').insertRow(); for (const value of [item.package_name,item.version,item.id,item.state,date(item.submitted_at),item.started_at && item.finished_at ? `${Math.round(item.finished_at-item.started_at)} s` : '—',item.user_email || 'قديم',item.media_status]) cell(row,value); }
  $('history-more').disabled = pages.history * 50 >= data.total;
}
const loaders = {overview,users,exports:exportsList,history};
async function tab(name) {
  for (const section of ['overview','users','exports','history','account']) $(section).hidden = section !== name;
  document.querySelectorAll('.tabs button').forEach(button => button.classList.toggle('active',button.dataset.tab === name));
  try { message('جارٍ التحميل...'); if (loaders[name]) await loaders[name](); message(''); } catch(error) { message(error.message); }
}
document.querySelectorAll('.tabs button').forEach(button => button.addEventListener('click',() => tab(button.dataset.tab)));
for (const name of ['users','exports','history']) $(`${name}-more`).addEventListener('click',() => { pages[name]++; tab(name); });
$('user-refresh').addEventListener('click',() => { pages.users=1; tab('users'); });
$('export-refresh').addEventListener('click',() => { pages.exports=1; tab('exports'); });
$('history-refresh').addEventListener('click',() => { pages.history=1; tab('history'); });
$('create-user').addEventListener('submit',async event => { event.preventDefault(); const body = Object.fromEntries(new FormData(event.target)); try { await api('/api/admin/users',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); event.target.reset(); await users(); message('أُنشئ الحساب'); } catch(error) { message(error.message); } });
$('change-password').addEventListener('submit',async event => { event.preventDefault(); const body = Object.fromEntries(new FormData(event.target)); try { await api('/api/account/password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); location.assign('/login'); } catch(error) { message(error.message); } });
$('logout').addEventListener('click',async () => { await api('/api/logout',{method:'POST'}); location.assign('/login'); });
tab('overview');
