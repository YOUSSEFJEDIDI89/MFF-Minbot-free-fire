/**
 * VortexVPN web panel frontend — TypeScript.
 *
 * Compiled with: `npm run build` (from frontend/)
 * Output:        vortexvpn/web/static/js/bundle.js
 *
 * This module replaces the old vanilla-JS files (dashboard.js, users.js)
 * with a single typed bundle that handles:
 *   - Live stats polling (3-second interval)
 *   - User CRUD operations
 *   - Session kick
 *   - Formatters (bytes, time, IP)
 *   - Toast notifications
 */

// ----- Types -----------------------------------------------------------------

interface ClientSession {
  username: string;
  address: string;
  virtual_ip: string;
  connected_at: number;
  last_seen: number;
  bytes_rx: number;
  bytes_tx: number;
  using_accel: boolean;
}

interface StatsResponse {
  ok: boolean;
  stats: {
    listening: string;
    active_clients: number;
    max_clients: number;
    clients: ClientSession[];
  };
  ts: number;
}

interface User {
  id: number;
  username: string;
  is_admin: boolean;
  is_active: boolean;
  created_at: number;
  bandwidth_quota_bytes: number;
  bandwidth_used_bytes: number;
  expires_at: number | null;
}

interface UsersResponse {
  ok: boolean;
  users: User[];
}

interface ApiResponse {
  ok: boolean;
  error?: string;
}

// ----- Utilities -------------------------------------------------------------

class Formatter {
  static bytes(b: number): string {
    if (b < 1024) return `${b} B`;
    if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
    if (b < 1024 * 1024 * 1024) return `${(b / 1024 / 1024).toFixed(1)} MB`;
    return `${(b / 1024 / 1024 / 1024).toFixed(2)} GB`;
  }

  static time(ts: number): string {
    if (!ts) return '—';
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString('ar', {
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
  }

  static duration(seconds: number): string {
    if (seconds < 60) return `${Math.floor(seconds)}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
    return `${Math.floor(seconds / 86400)}d`;
  }
}

class Toast {
  static show(message: string, type: 'success' | 'error' | 'info' = 'info'): void {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.classList.add('show'), 10);
    setTimeout(() => {
      toast.classList.remove('show');
      setTimeout(() => toast.remove(), 300);
    }, 3000);
  }
}

// ----- API client ------------------------------------------------------------

class ApiClient {
  static async get<T>(url: string): Promise<T> {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  }

  static async post<T>(url: string, body: object): Promise<T> {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    return r.json();
  }

  static async delete<T>(url: string): Promise<T> {
    const r = await fetch(url, { method: 'DELETE' });
    return r.json();
  }
}

// ----- Dashboard controller --------------------------------------------------

class DashboardController {
  constructor() {
    this.init();
  }

  private init(): void {
    const tbody = document.getElementById('clients-tbody');
    if (!tbody) return; // not on dashboard

    this.refresh();
    window.setInterval(() => this.refresh(), 3000);
  }

  private async refresh(): Promise<void> {
    try {
      const data = await ApiClient.get<StatsResponse>('/api/v1/stats');
      if (!data.ok) return;
      this.render(data.stats);
    } catch (e) {
      console.error('refresh failed', e);
    }
  }

  private render(stats: StatsResponse['stats']): void {
    const countEl = document.getElementById('active-count');
    if (countEl) countEl.textContent = `${stats.active_clients} / ${stats.max_clients}`;

    const tbody = document.getElementById('clients-tbody');
    if (!tbody) return;

    if (!stats.clients || stats.clients.length === 0) {
      tbody.innerHTML = '<tr><td colspan="9" class="muted">لا يوجد عملاء متصلون</td></tr>';
      return;
    }

    tbody.innerHTML = stats.clients.map((c) => {
      const [ip, port] = c.address.split(':');
      return `<tr data-ip="${ip}" data-port="${port}">
        <td>${c.username}</td>
        <td>${c.address}</td>
        <td><code>${c.virtual_ip}</code></td>
        <td>${Formatter.time(c.connected_at)}</td>
        <td>${Formatter.time(c.last_seen)}</td>
        <td>${Formatter.bytes(c.bytes_rx)}</td>
        <td>${Formatter.bytes(c.bytes_tx)}</td>
        <td>${c.using_accel ? '✓' : '—'}</td>
        <td><button class="btn-danger btn-sm" data-kick>طرد</button></td>
      </tr>`;
    }).join('');

    // Wire kick buttons
    tbody.querySelectorAll('[data-kick]').forEach((btn) => {
      btn.addEventListener('click', (e) => this.handleKick(e));
    });
  }

  private async handleKick(e: Event): Promise<void> {
    const btn = e.target as HTMLButtonElement;
    const row = btn.closest('tr') as HTMLTableRowElement;
    const ip = row.dataset.ip!;
    const port = parseInt(row.dataset.port!, 10);

    if (!confirm(`طرد ${ip}:${port}؟`)) return;

    try {
      const r = await ApiClient.post<ApiResponse>('/api/v1/sessions/kick', { ip, port });
      if (r.ok) {
        row.remove();
        Toast.show('تم طرد العميل', 'success');
      } else {
        Toast.show(`فشل: ${r.error || 'unknown'}`, 'error');
      }
    } catch (e) {
      Toast.show('خطأ في الشبكة', 'error');
    }
  }
}

// ----- Users controller ------------------------------------------------------

class UsersController {
  constructor() {
    this.init();
  }

  private init(): void {
    const form = document.getElementById('add-user-form') as HTMLFormElement | null;
    if (form) form.addEventListener('submit', (e) => this.handleAdd(e));

    // Wire delete/toggle buttons (delegation)
    document.addEventListener('click', (e) => {
      const target = e.target as HTMLElement;
      if (target.dataset.delete) this.handleDelete(target.dataset.delete);
      if (target.dataset.toggle) this.handleToggle(target.dataset.toggle, target.dataset.active === 'true');
    });
  }

  private async handleAdd(e: Event): Promise<void> {
    e.preventDefault();
    const form = e.target as HTMLFormElement;
    const fd = new FormData(form);
    const body = {
      username: fd.get('username'),
      password: fd.get('password'),
      is_admin: !!fd.get('is_admin'),
      bandwidth_quota_bytes: parseInt((fd.get('bandwidth_quota_bytes') || '0') as string, 10),
    };

    try {
      const r = await ApiClient.post<ApiResponse>('/api/v1/users', body);
      if (r.ok) {
        Toast.show('تم إنشاء المستخدم', 'success');
        setTimeout(() => location.reload(), 800);
      } else {
        Toast.show(`فشل: ${r.error || 'unknown'}`, 'error');
      }
    } catch (e) {
      Toast.show('خطأ في الشبكة', 'error');
    }
  }

  private async handleDelete(username: string): Promise<void> {
    if (!confirm(`حذف ${username}؟`)) return;
    try {
      const r = await ApiClient.delete<ApiResponse>(`/api/v1/users/${encodeURIComponent(username)}`);
      if (r.ok) {
        Toast.show('تم الحذف', 'success');
        setTimeout(() => location.reload(), 800);
      } else {
        Toast.show(`فشل: ${r.error || 'unknown'}`, 'error');
      }
    } catch (e) {
      Toast.show('خطأ في الشبكة', 'error');
    }
  }

  private async handleToggle(username: string, active: boolean): Promise<void> {
    try {
      const r = await ApiClient.post<ApiResponse>(
        `/api/v1/users/${encodeURIComponent(username)}/active`,
        { active: !active },
      );
      if (r.ok) {
        Toast.show('تم التحديث', 'success');
        setTimeout(() => location.reload(), 800);
      }
    } catch (e) {
      Toast.show('خطأ في الشبكة', 'error');
    }
  }
}

// ----- Boot ------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
  new DashboardController();
  new UsersController();
});
