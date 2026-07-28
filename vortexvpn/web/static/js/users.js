// Users page - CRUD via API
(function () {
  const form = document.getElementById('add-user-form');
  if (form) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const fd = new FormData(form);
      const body = {
        username: fd.get('username'),
        password: fd.get('password'),
        is_admin: !!fd.get('is_admin'),
        bandwidth_quota_bytes: parseInt(fd.get('bandwidth_quota_bytes') || '0', 10),
      };
      const r = await fetch('/api/v1/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const j = await r.json();
      if (j.ok) location.reload();
      else alert('فشل: ' + (j.error || 'unknown'));
    });
  }

  window.deleteUser = async (username) => {
    if (!confirm(`حذف ${username}؟`)) return;
    const r = await fetch('/api/v1/users/' + encodeURIComponent(username), { method: 'DELETE' });
    const j = await r.json();
    if (j.ok) location.reload();
    else alert('فشل: ' + (j.error || 'unknown'));
  };

  window.toggleActive = async (username, active) => {
    const r = await fetch('/api/v1/users/' + encodeURIComponent(username) + '/active', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ active: !!active }),
    });
    const j = await r.json();
    if (j.ok) location.reload();
    else alert('فشل: ' + (j.error || 'unknown'));
  };
})();
