// ── SIDEBAR TOGGLE ──
function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  const main = document.querySelector('.main');
  if (sidebar) {
    sidebar.classList.toggle('collapsed');
    if (main) main.classList.toggle('expanded');
  }
}

// ── MODAL HELPERS ──
function openModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add('open');
}
function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove('open');
}

// Close modal on overlay click
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.modal-overlay').forEach(m => {
    m.addEventListener('click', e => {
      if (e.target === m) m.classList.remove('open');
    });
  });

  // ── LIVE UNREAD BADGE UPDATE ──
  fetchUnreadCounts();
  setInterval(fetchUnreadCounts, 30000);

  // ── HEARTBEAT PULSE ──
  setInterval(() => {
    const pill = document.querySelector('.heartbeat-pill');
    if (pill) pill.style.opacity = pill.style.opacity === '0.7' ? '1' : '0.7';
  }, 1000);

  // ── AUTO-DISMISS FLASH ──
  setTimeout(() => {
    document.querySelectorAll('.flash').forEach(f => {
      f.style.transition = 'opacity .5s';
      f.style.opacity = '0';
      setTimeout(() => f.remove(), 500);
    });
  }, 4000);
});

// ── FETCH UNREAD NOTIFICATION + BREACH COUNTS ──
async function fetchUnreadCounts() {
  try {
    const resp = await fetch('/api/unread-count');
    if (!resp.ok) return;
    const data = await resp.json();

    // Notification badge
    const notifBadge = document.querySelector('.notif-badge');
    const notifIndicator = document.querySelector('.notif-indicator');
    if (notifBadge) {
      if (data.notifications > 0) {
        notifBadge.textContent = data.notifications;
        notifBadge.style.display = 'inline';
      } else {
        notifBadge.style.display = 'none';
      }
    }
    if (notifIndicator) {
      notifIndicator.style.display = data.notifications > 0 ? 'block' : 'none';
    }

    // Breach badge
    const breachBadge = document.querySelector('.breach-badge');
    if (breachBadge) {
      if (data.breaches > 0) {
        breachBadge.textContent = data.breaches;
        breachBadge.style.display = 'inline';
      } else {
        breachBadge.style.display = 'none';
      }
    }
  } catch (e) {
    // silently fail — user may be on public page
  }
}

// ── CONFIRM DELETE ──
function confirmDelete(msg) {
  return confirm(msg || 'Are you sure you want to delete this item?');
}

// ── COPY TO CLIPBOARD ──
function copyToClipboard(text, btn) {
  navigator.clipboard.writeText(text).then(() => {
    if (btn) {
      const orig = btn.textContent;
      btn.textContent = 'Copied!';
      setTimeout(() => { btn.textContent = orig; }, 1500);
    }
  });
}

// ── PASSWORD VISIBILITY TOGGLE ──
function togglePasswordVisibility(inputId, btn) {
  const input = document.getElementById(inputId);
  if (!input) return;
  if (input.type === 'password') {
    input.type = 'text';
    if (btn) btn.textContent = 'Hide';
  } else {
    input.type = 'password';
    if (btn) btn.textContent = 'Show';
  }
}

// ── THEME SWITCHER ──
function toggleTheme() {
  const html = document.documentElement;
  const current = html.getAttribute('data-theme') || 'dark';
  const next = current === 'dark' ? 'light' : 'dark';
  html.setAttribute('data-theme', next);
  updateThemeBtn(next);
  // Persist to server session
  fetch('/api/set-theme', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ theme: next })
  });
}

function updateThemeBtn(theme) {
  const btn = document.getElementById('theme-btn');
  if (btn) btn.textContent = theme === 'dark' ? '🌙' : '☀️';
}

// Init theme button icon on page load
document.addEventListener('DOMContentLoaded', () => {
  const theme = document.documentElement.getAttribute('data-theme') || 'dark';
  updateThemeBtn(theme);
});
