document.getElementById('change').addEventListener('submit', async event => {
  event.preventDefault();
  const csrf = decodeURIComponent(document.cookie.match(/(?:^|; )hexa_csrf=([^;]*)/)?.[1] || '');
  const response = await fetch('/api/account/password',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({old_password:document.getElementById('old').value,new_password:document.getElementById('new').value})});
  if (response.ok) location.assign('/login');
  else document.getElementById('message').textContent = (await response.json().catch(() => ({}))).detail || 'تعذر تغيير كلمة المرور';
});
