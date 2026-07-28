// Dashboard live updates - poll /api/v1/stats every 3s
(function () {
  const fmtBytes = (b) => {
    if (b < 1024) return b + ' B';
    if (b < 1024 * 1024) return (b / 1024).toFixed(1) + ' KB';
    if (b < 1024 * 1024 * 1024) return (b / 1024 / 1024).toFixed(1) + ' MB';
    return (b / 1024 / 1024 / 1024).toFixed(2) + ' GB';
  };
  const fmtTime = (ts) => {
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString('ar', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  };

  async function refresh() {
    try {
      const r = await fetch('/api/v1/stats');
      if (!r.ok) throw new Error('stats failed');
      const j = await r.json();
      const s = j.stats;
      document.getElementById('active-count').textContent =
        s.active_clients + ' / ' + s.max_clients;
      const tbody = document.getElementById('clients-tbody');
      if (!s.clients || s.clients.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" class="muted">لا يوجد عملاء متصلون</td></tr>';
        return;
      }
      tbody.innerHTML = s.clients.map(c => {
        const [ip, port] = c.address.split(':');
        return `<tr data-ip="${ip}" data-port="${port}">
          <td>${c.username}</td>
          <td>${c.address}</td>
          <td><code>${c.virtual_ip}</code></td>
          <td>${fmtTime(c.connected_at)}</td>
          <td>${fmtTime(c.last_seen)}</td>
          <td>${fmtBytes(c.bytes_rx)}</td>
          <td>${fmtBytes(c.bytes_tx)}</td>
          <td>${c.using_accel ? '✓' : '—'}</td>
          <td><button class="btn-danger btn-sm" onclick="kickClient(this)">طرد</button></td>
        </tr>`;
      }).join('');
    } catch (e) {
      console.error('refresh failed', e);
    }
  }

  window.kickClient = async (btn) => {
    const row = btn.closest('tr');
    const ip = row.dataset.ip, port = parseInt(row.dataset.port, 10);
    if (!confirm(`طرد ${ip}:${port}؟`)) return;
    const r = await fetch('/api/v1/sessions/kick', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ip, port }),
    });
    const j = await r.json();
    if (j.ok) row.remove();
    else alert('فشل الطرد: ' + (j.error || 'unknown'));
  };

  setInterval(refresh, 3000);
})();
