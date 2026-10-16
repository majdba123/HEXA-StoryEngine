document.getElementById('login').addEventListener('submit', async event => {
  event.preventDefault();
  const button = event.target.querySelector('button');
  button.disabled = true;
  document.getElementById('message').textContent = '';
  try {
    const response = await fetch('/api/session', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:document.getElementById('email').value,password:document.getElementById('password').value})});
    if (!response.ok) throw Error('البريد الإلكتروني أو كلمة المرور غير صحيحة');
    location.assign('/');
  } catch (error) {
    document.getElementById('message').textContent = error.message;
    button.disabled = false;
  }
});
