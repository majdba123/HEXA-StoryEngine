const $ = id => document.getElementById(id);
const csrf = () => decodeURIComponent(document.cookie.match(/(?:^|; )hexa_csrf=([^;]*)/)?.[1] || '');
const message = value => { $('message').textContent = value; };
const date = value => { const stamp = typeof value === 'number' ? new Date(value * 1000) : new Date(value); return value && !Number.isNaN(stamp.getTime()) ? stamp.toLocaleString('ar') : 'غير معروف'; };
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
const count = value => Number(value || 0).toLocaleString('ar');
const statusLabel = value => ({AVAILABLE:'متاح',DELETED:'ملف محذوف',DELETING:'جارٍ الحذف',DELETE_FAILED:'تعذّر الحذف',completed:'مكتمل',failed:'فشل',running:'جارٍ التوليد',queued:'بالانتظار',cancelling:'جارٍ الإلغاء',canceled:'ملغى',UNKNOWN:'غير معروف'})[value] || value || 'غير معروف';
function statusCell(row, value) { const entry = cell(row,''); const badge = document.createElement('span'); badge.className = `badge ${['AVAILABLE','completed'].includes(value) ? 'good' : ['DELETED','failed','DELETE_FAILED'].includes(value) ? 'warn' : 'muted'}`; badge.textContent = statusLabel(value); entry.append(badge); return entry; }
function emptyRow(body, columns, label) { const row = body.insertRow(); const entry = row.insertCell(); entry.colSpan = columns; entry.className = 'empty'; entry.textContent = label; }
let pages = {exports:1,premiere:1,history:1};
let userListRequest = 0;
let detailsPage = 1;
let detailsUser = null;
function openEditUser(user) {
  const dialog = $('edit-user-dialog');
  dialog.dataset.userId = user.id;
  dialog.dataset.email = user.email_normalized;
  dialog.dataset.role = user.role;
  dialog.dataset.active = user.is_active ? '1' : '0';
  $('edit-user-email').value = user.email_normalized;
  $('edit-user-role').value = user.role;
  $('edit-user-active').value = user.is_active ? '1' : '0';
  dialog.showModal();
}
function openPasswordReset(user) {
  const dialog = $('reset-password-dialog');
  $('reset-password-email').textContent = user.email_normalized;
  $('reset-password-value').value = '';
  dialog.dataset.userId = user.id;
  dialog.showModal();
}
async function overview(refresh = false) {
  const data = await api(`/api/admin/overview${refresh ? '?refresh=true' : ''}`);
  const labels = {users_total:'الحسابات الحالية',users_active:'الحسابات النشطة',jobs_total:'كل مهام التوليد',jobs_completed:'مهام مكتملة',videos_historical:'فيديوهات أُنشئت',premiere_historical:'مشاريع Premiere أُنشئت',exports_deleted:'مخرجات حُذفت ملفاتها',jobs_failed:'مهام فاشلة',jobs_active:'مهام جارية',bundles:'فيديوهات متاحة',premiere_projects:'مشاريع Premiere متاحة',export_bytes:'حجم الفيديوهات المتاحة'};
  $('cards').replaceChildren();
  for (const [key,label] of Object.entries(labels)) {
    const card = document.createElement('div'); card.className = `card ${['jobs_total','videos_historical','premiere_historical'].includes(key) ? 'emphasis' : key === 'exports_deleted' ? 'warning' : key === 'jobs_completed' ? 'positive' : ''}`;
    const title = document.createElement('span'); title.textContent = label;
    const value = document.createElement('strong'); value.textContent = key.endsWith('_bytes') ? mb(data[key]) : count(data[key]);
    card.append(title,value); $('cards').append(card);
  }
  const users = await api('/api/admin/users?page=1');
  const rows = $('overview-users-rows'); rows.replaceChildren();
  for (const user of users.items.sort((a,b) => b.stats.jobs_total-a.stats.jobs_total).slice(0,8)) {
    const row = rows.insertRow();
    cell(row,user.email_normalized); cell(row,count(user.stats.jobs_total)); cell(row,count(user.stats.videos)); cell(row,count(user.stats.premiere)); cell(row,date(user.stats.last_job_at)); cell(row,'');
    action(row,'تفاصيل',() => showUserDetails(user));
  }
  if (!users.items.length) emptyRow(rows,6,'لا يوجد مستخدمون بعد');
}
async function users() {
  const request = ++userListRequest;
  const search = encodeURIComponent($('user-search').value);
  $('user-rows').replaceChildren();
  $('user-count').textContent = 'جارٍ تحميل المستخدمين...';
  let loaded = 0;
  for (let page = 1; page <= 100000; page++) {
    const data = await api(`/api/admin/users?search=${search}&page=${page}`);
    if (request !== userListRequest) return;
    for (const user of data.items) {
      const row = $('user-rows').insertRow(); cell(row,user.email_normalized); cell(row,user.role === 'ADMIN' ? 'أدمن' : 'مستخدم'); statusCell(row,user.deleted_at ? 'DELETED' : user.is_active ? 'AVAILABLE' : 'معطل');
      cell(row,count(user.stats.jobs_total)); cell(row,count(user.stats.videos)); cell(row,count(user.stats.premiere)); cell(row,count(user.stats.deleted_exports)); cell(row,date(user.stats.last_job_at)); cell(row,'');
      action(row,'تفاصيل', () => showUserDetails(user));
      if (user.deleted_at) continue;
      action(row,'تعديل', () => openEditUser(user));
      action(row,'كلمة المرور', () => openPasswordReset(user));
      action(row,'حذف', async () => { if (confirm(`حذف حساب ${user.email_normalized} وتعطيل جلساته؟`)) await updateUser(user.id,{delete:true}); });
    }
    loaded += data.items.length;
    $('user-count').textContent = `المستخدمون: ${loaded} من ${data.total}`;
    if (!data.items.length || loaded >= data.total) break;
  }
  if (!loaded) emptyRow($('user-rows'),9,'لا يوجد مستخدمون مطابقون للبحث');
}
async function showUserDetails(user) {
  detailsUser = user;
  detailsPage = 1;
  $('user-details-email').textContent = user.email_normalized;
  $('user-details-meta').textContent = `${user.role === 'ADMIN' ? 'أدمن' : 'مستخدم'} • ${user.deleted_at ? 'حساب محذوف' : user.is_active ? 'نشط' : 'معطل'} • أُنشئ ${date(user.created_at)} • آخر دخول ${date(user.last_login_at)}`;
  $('user-details-count').textContent = 'جارٍ تحميل سجل التوليد...';
  $('user-details-rows').replaceChildren();
  $('user-details-dialog').showModal();
  await loadUserDetails();
}
async function loadUserDetails() {
  if (!detailsUser) return;
  const userId = detailsUser.id;
  try {
    const data = await api(`/api/admin/users/${encodeURIComponent(userId)}/history?page=${detailsPage}`);
    if (detailsUser?.id !== userId) return;
    $('user-details-count').textContent = `إجمالي المهام: ${data.total} • مكتملة: ${data.completed} • فاشلة: ${data.failed}`;
    $('user-details-stats').replaceChildren();
    for (const [label,value] of [['المهام',data.stats.jobs_total],['فيديو',data.stats.videos],['Premiere',data.stats.premiere],['ملفات محذوفة',data.stats.deleted_exports]]) {
      const box = document.createElement('span'); box.textContent = label;
      const number = document.createElement('strong'); number.textContent = count(value); box.append(number); $('user-details-stats').append(box);
    }
    for (const item of data.items) {
      const row = $('user-details-rows').insertRow();
      cell(row,item.package_name); const id = cell(row,item.id); id.className = 'mono'; statusCell(row,item.state); cell(row,date(item.submitted_at)); cell(row,item.started_at && item.finished_at ? `${Math.round(item.finished_at-item.started_at)} ث` : '—'); cell(row,'');
      if (item.state === 'completed' && item.media_status === 'AVAILABLE' && item.bundle_id) {
        const kinds = item.media_kind === 'PREMIERE' ? ['premiere'] : ['youtube','reels'];
        for (const kind of kinds) {
          const link = document.createElement('a');
          link.href = kind === 'premiere' ? `/api/admin/premiere/${encodeURIComponent(item.bundle_id)}/download` : `/api/admin/exports/${encodeURIComponent(item.bundle_id)}/download/${kind}`;
          link.textContent = kind === 'premiere' ? 'Premiere ZIP' : kind === 'youtube' ? 'YouTube' : 'Reels';
          row.lastElementChild.append(link,' ');
        }
      } else row.lastElementChild.textContent = `${item.media_kind === 'PREMIERE' ? 'Premiere' : item.media_kind === 'VIDEO' ? 'فيديو' : 'ناتج غير معروف'} • ${item.media_status === 'DELETED' ? 'الملفات محذوفة' : statusLabel(item.media_status)}`;
    }
    if (detailsPage === 1 && !data.items.length) emptyRow($('user-details-rows'),6,'لا توجد مهام لهذا المستخدم');
    $('user-details-more').disabled = detailsPage * 50 >= data.total;
  } catch (error) { $('user-details-count').textContent = error.message; }
}
async function updateUser(id, body) { try { await api(`/api/admin/users/${id}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); message('تم الحفظ'); await users(); } catch(error) { message(error.message); } }
async function exportsList() {
  const data = await api(`/api/admin/exports?search=${encodeURIComponent($('export-search').value)}&page=${pages.exports}`);
  $('export-rows').replaceChildren();
  for (const item of data.items) {
    const row = $('export-rows').insertRow();
    for (const value of [item.slug,`v${item.version}`,date(item.created_at),item.user_email || 'غير معروف']) cell(row,value);
    statusCell(row,item.status); cell(row,mb(item.outputs?.youtube)); cell(row,mb(item.outputs?.reels)); cell(row,mb(item.bytes)); cell(row,'');
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
  if (!data.items.length) emptyRow($('export-rows'),9,'لا توجد فيديوهات مطابقة');
  $('exports-more').disabled = pages.exports * 50 >= data.total;
}
async function premiereList() {
  const data = await api(`/api/admin/premiere?search=${encodeURIComponent($('premiere-search').value)}&page=${pages.premiere}`);
  $('premiere-rows').replaceChildren();
  for (const item of data.items) {
    const row = $('premiere-rows').insertRow();
    for (const value of [item.slug,`v${item.version}`,date(item.created_at),item.user_email || 'غير معروف']) cell(row,value);
    statusCell(row,item.status); cell(row,item.outputs?.youtube != null ? 'متوفر' : '—'); cell(row,item.outputs?.reels != null ? 'متوفر' : '—'); cell(row,'');
    if (item.status === 'AVAILABLE') {
      const link = document.createElement('a');
      link.href = `/api/admin/premiere/${encodeURIComponent(item.id)}/download`;
      link.textContent = 'تحميل المشروع كاملًا ZIP';
      row.lastElementChild.append(link);
      action(row,'حذف المشروع', async () => {
        if (!confirm(`حذف مشروع Premiere ${item.slug} / v${item.version} نهائياً؟`)) return;
        try { await api(`/api/admin/exports/${encodeURIComponent(item.id)}`,{method:'DELETE'}); message('حُذف المشروع وبقي السجل'); await premiereList(); }
        catch(error) { message(error.message); }
      });
    }
  }
  if (!data.items.length) emptyRow($('premiere-rows'),8,'لا توجد مشاريع Premiere بعد');
  $('premiere-more').disabled = pages.premiere * 50 >= data.total;
}
async function history() {
  const from = $('history-from').value ? new Date(`${$('history-from').value}T00:00:00`).getTime()/1000 : '';
  const to = $('history-to').value ? new Date(`${$('history-to').value}T00:00:00`).getTime()/1000 + 86400 : '';
  const data = await api(`/api/admin/history?search=${encodeURIComponent($('history-search').value)}&state=${encodeURIComponent($('history-state').value)}&page=${pages.history}&sort=${$('history-sort').value}${from ? `&from_at=${from}` : ''}${to ? `&to_at=${to}` : ''}`);
  $('history-rows').replaceChildren();
  $('history-totals').textContent = `الإجمالي ${data.total} • مكتمل ${data.completed} • فاشل ${data.failed}`;
  for (const item of data.items) { const row = $('history-rows').insertRow(); cell(row,item.package_name); cell(row,item.version); const id=cell(row,item.id); id.className='mono'; statusCell(row,item.state); cell(row,date(item.submitted_at)); cell(row,item.started_at && item.finished_at ? `${Math.round(item.finished_at-item.started_at)} ث` : '—'); cell(row,item.user_email || 'مهمة قديمة بلا صاحب'); const media=statusCell(row,item.media_status); if(item.media_kind) media.append(` ${item.media_kind === 'PREMIERE' ? 'Premiere' : 'فيديو'}`); }
  if (!data.items.length) emptyRow($('history-rows'),8,'لا توجد مهام مطابقة');
  $('history-more').disabled = pages.history * 50 >= data.total;
}
const loaders = {overview,users,exports:exportsList,premiere:premiereList,history};
async function tab(name) {
  for (const section of ['overview','users','exports','premiere','history','account']) $(section).hidden = section !== name;
  document.querySelectorAll('.tabs button').forEach(button => button.classList.toggle('active',button.dataset.tab === name));
  try { message('جارٍ التحميل...'); if (loaders[name]) await loaders[name](); message(''); } catch(error) { message(error.message); }
}
document.querySelectorAll('.tabs button').forEach(button => button.addEventListener('click',() => tab(button.dataset.tab)));
for (const name of ['exports','premiere','history']) $(`${name}-more`).addEventListener('click',() => { pages[name]++; tab(name); });
$('user-refresh').addEventListener('click',() => tab('users'));
$('export-refresh').addEventListener('click',() => { pages.exports=1; tab('exports'); });
$('premiere-refresh').addEventListener('click',() => { pages.premiere=1; tab('premiere'); });
$('history-refresh').addEventListener('click',() => { pages.history=1; tab('history'); });
$('overview-refresh').addEventListener('click',async () => { try { message('جارٍ تحديث الأرقام...'); await overview(true); message('تحدّثت الأرقام'); } catch(error) { message(error.message); } });
$('overview-users-link').addEventListener('click',() => tab('users'));
$('create-user').addEventListener('submit',async event => { event.preventDefault(); const body = Object.fromEntries(new FormData(event.target)); try { await api('/api/admin/users',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); event.target.reset(); await users(); message('أُنشئ الحساب'); } catch(error) { message(error.message); } });
$('reset-password-form').addEventListener('submit', async event => {
  event.preventDefault();
  const dialog = $('reset-password-dialog');
  const target = dialog.dataset.userId;
  const input = $('reset-password-value');
  if (!target) return;
  const submit = event.target.querySelector('[type="submit"]');
  submit.disabled = true;
  try {
    await api(`/api/admin/users/${encodeURIComponent(target)}`, {
      method:'PATCH', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({password:input.value})
    });
    dialog.close();
    message('تم تعيين كلمة المرور المؤقتة وإبطال جلسات الحساب');
    await users();
  } catch (error) {
    message(error.message);
  } finally {
    submit.disabled = false;
  }
});
$('reset-password-cancel').addEventListener('click', () => $('reset-password-dialog').close());
$('reset-password-dialog').addEventListener('close', () => {
  $('reset-password-value').value = '';
  delete $('reset-password-dialog').dataset.userId;
});
$('edit-user-form').addEventListener('submit', async event => {
  event.preventDefault();
  const dialog = $('edit-user-dialog');
  const id = dialog.dataset.userId;
  if (!id) return;
  const button = event.target.querySelector('[type="submit"]');
  button.disabled = true;
  try {
    const changes = {};
    if ($('edit-user-email').value !== dialog.dataset.email) changes.email = $('edit-user-email').value;
    if ($('edit-user-role').value !== dialog.dataset.role) changes.role = $('edit-user-role').value;
    if ($('edit-user-active').value !== dialog.dataset.active) changes.is_active = $('edit-user-active').value === '1';
    if (!Object.keys(changes).length) { dialog.close(); return; }
    await api(`/api/admin/users/${encodeURIComponent(id)}`, {method:'PATCH',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(changes)});
    dialog.close();
    message('تم تحديث الحساب والصلاحية');
    await users();
  } catch (error) { message(error.message); }
  finally { button.disabled = false; }
});
$('edit-user-cancel').addEventListener('click', () => $('edit-user-dialog').close());
$('edit-user-dialog').addEventListener('close', () => { for (const key of ['userId','email','role','active']) delete $('edit-user-dialog').dataset[key]; });
$('user-details-more').addEventListener('click', () => { detailsPage++; loadUserDetails(); });
$('user-details-close').addEventListener('click', () => $('user-details-dialog').close());
$('user-details-dialog').addEventListener('close', () => { detailsUser = null; });
$('change-password').addEventListener('submit',async event => { event.preventDefault(); const body = Object.fromEntries(new FormData(event.target)); try { await api('/api/account/password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); location.assign('/login'); } catch(error) { message(error.message); } });
$('logout').addEventListener('click',async () => { await api('/api/logout',{method:'POST'}); location.assign('/login'); });
tab('overview');
