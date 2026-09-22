/* ============================================================
   QueryMind — Frontend JavaScript
   API base: https://text-to-sql-api-70892236230.us-central1.run.app
   ============================================================ */

const API = '';

// ── State ──────────────────────────────────────────────────
let token = null;
let currentUser = null;

// Role → accessible tables
const ROLE_TABLES = {
  employee: {
    customers: ['id', 'name', 'industry', 'region', 'account_tier', 'signup_date'],
    products:  ['id', 'name', 'category', 'unit_price'],
    sales:     ['id', 'product', 'monthly', 'quarterly', 'revenue', 'profit(%)'],
  },
  manager: {
    employees: ['id', 'name', 'department', 'title', 'salary', 'hire_date', 'manager_id', 'region'],
    customers: ['id', 'name', 'industry', 'region', 'account_tier', 'signup_date'],
    products:  ['id', 'name', 'category', 'unit_price'],
    sales:     ['id', 'product', 'monthly', 'quarterly', 'revenue', 'profit(%)'],
  },
  admin: {
    employees: ['id', 'name', 'department', 'title', 'salary', 'hire_date', 'manager_id', 'region'],
    customers: ['id', 'name', 'industry', 'region', 'account_tier', 'signup_date'],
    products:  ['id', 'name', 'category', 'unit_price'],
    sales:     ['id', 'product', 'monthly', 'quarterly', 'revenue', 'profit(%)'],
  },
  hr: {
    employees: ['id', 'name', 'department', 'title', 'salary', 'hire_date', 'manager_id', 'region'],
  },
};

// ── DOM refs ───────────────────────────────────────────────
const $ = id => document.getElementById(id);

const loginScreen  = $('login-screen');
const appScreen    = $('app-screen');
const loginForm    = $('login-form');
const loginBtn     = $('login-btn');
const loginError   = $('login-error');
const loginErrorTxt = $('login-error-text');
const togglePwdBtn = $('toggle-password');
const pwdInput     = $('password');
const logoutBtn    = $('logout-btn');

const navItems     = document.querySelectorAll('.nav-item');
const tabPanels    = document.querySelectorAll('.tab-panel');

const questionInput = $('question-input');
const askBtn        = $('ask-btn');
const queryResultArea = $('query-result-area');
const queryEmpty    = $('query-empty');
const queryLoading  = $('query-loading');
const queryError    = $('query-error');
const queryErrorTxt = $('query-error-text');
const sqlDisplay    = $('sql-display');
const sqlCode       = $('sql-code').querySelector('code');
const copySqlBtn    = $('copy-sql-btn');
const resultMeta    = $('result-meta');
const queryTableWrapper = $('query-table-wrapper');

const sqlInput      = $('sql-input');
const runSqlBtn     = $('run-sql-btn');
const clearSqlBtn   = $('clear-sql-btn');
const sqlResultArea = $('sql-result-area');
const sqlEmpty      = $('sql-empty');
const sqlLoading    = $('sql-loading');
const sqlError      = $('sql-error');
const sqlErrorTxt   = $('sql-error-text');
const sqlResultMeta = $('sql-result-meta');
const sqlTableWrapper = $('sql-table-wrapper');

const schemaGrid    = $('schema-grid');


// ── Login ──────────────────────────────────────────────────
loginForm.addEventListener('submit', async e => {
  e.preventDefault();
  const username = $('username').value.trim();
  const password = pwdInput.value;

  if (!username || !password) return;

  setLoginLoading(true);
  loginError.classList.add('hidden');

  try {
    const form = new URLSearchParams();
    form.append('username', username);
    form.append('password', password);

    const res = await fetch(`${API}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: form,
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || 'Invalid username or password');
    }

    const data = await res.json();
    token = data.access_token;

    // Fetch user info
    const meRes = await fetch(`${API}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    currentUser = await meRes.json();

    showApp();
  } catch (err) {
    loginErrorTxt.textContent = err.message;
    loginError.classList.remove('hidden');
  } finally {
    setLoginLoading(false);
  }
});

function setLoginLoading(loading) {
  loginBtn.disabled = loading;
  loginBtn.querySelector('.btn-text').classList.toggle('hidden', loading);
  loginBtn.querySelector('.btn-spinner').classList.toggle('hidden', !loading);
}

// ── Toggle password ────────────────────────────────────────
togglePwdBtn.addEventListener('click', () => {
  const isText = pwdInput.type === 'text';
  pwdInput.type = isText ? 'password' : 'text';
});

// ── Show app ───────────────────────────────────────────────
function showApp() {
  loginScreen.classList.remove('active');
  appScreen.classList.add('active');

  // Populate user info in sidebar
  $('sidebar-username').textContent = currentUser.username;
  $('sidebar-role').textContent     = currentUser.role;
  $('sidebar-avatar').textContent   = currentUser.username.charAt(0).toUpperCase();

  // Render schema
  renderSchema();
}

// ── Logout ─────────────────────────────────────────────────
logoutBtn.addEventListener('click', () => {
  token = null;
  currentUser = null;
  $('username').value = '';
  pwdInput.value = '';
  loginError.classList.add('hidden');
  appScreen.classList.remove('active');
  loginScreen.classList.add('active');

  // Reset query UI
  queryResultArea.classList.add('hidden');
  queryEmpty.classList.remove('hidden');
  queryLoading.classList.add('hidden');
  queryError.classList.add('hidden');
  questionInput.value = '';
});

// ── Navigation ─────────────────────────────────────────────
navItems.forEach(btn => {
  btn.addEventListener('click', () => {
    navItems.forEach(n => n.classList.remove('active'));
    tabPanels.forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    $(`tab-${btn.dataset.tab}`).classList.add('active');
  });
});

// ── Suggestion chips ───────────────────────────────────────
document.querySelectorAll('.suggestion-chip').forEach(chip => {
  chip.addEventListener('click', () => {
    questionInput.value = chip.dataset.q;
    questionInput.focus();
  });
});

// ── Ask question ───────────────────────────────────────────
askBtn.addEventListener('click', runAgentQuery);
questionInput.addEventListener('keydown', e => {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) runAgentQuery();
});

async function runAgentQuery() {
  const question = questionInput.value.trim();
  if (!question) return;

  setQueryState('loading');

  try {
    const res = await fetch(`${API}/agent/query`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ question }),
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || `Error ${res.status}`);
    }

    const data = await res.json();
    renderQueryResult(data);
  } catch (err) {
    queryErrorTxt.textContent = err.message;
    setQueryState('error');
  }
}

function renderQueryResult(data) {
  const { sql, data: result } = data;
  const { columns, rows } = result;

  // SQL block (admin only)
  if (sql) {
    sqlCode.textContent = sql;
    sqlDisplay.classList.remove('hidden');
  } else {
    sqlDisplay.classList.add('hidden');
  }

  // Meta
  resultMeta.innerHTML = `<strong>${rows.length}</strong> row${rows.length !== 1 ? 's' : ''} returned`;

  // Table
  queryTableWrapper.innerHTML = buildTable(columns, rows);

  setQueryState('result');
}

// ── Run SQL ────────────────────────────────────────────────
runSqlBtn.addEventListener('click', runSql);
clearSqlBtn.addEventListener('click', () => {
  sqlInput.value = '';
  sqlResultArea.classList.add('hidden');
  sqlEmpty.classList.remove('hidden');
});

sqlInput.addEventListener('keydown', e => {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) runSql();
});

async function runSql() {
  const sql = sqlInput.value.trim();
  if (!sql) return;

  setSqlState('loading');

  try {
    const res = await fetch(`${API}/sql/execute`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ sql }),
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || `Error ${res.status}`);
    }

    const data = await res.json();
    const { columns, rows } = data;

    sqlResultMeta.innerHTML = `<strong>${rows.length}</strong> row${rows.length !== 1 ? 's' : ''} returned`;
    sqlTableWrapper.innerHTML = buildTable(columns, rows);
    setSqlState('result');
  } catch (err) {
    sqlErrorTxt.textContent = err.message;
    setSqlState('error');
  }
}

// ── State helpers ──────────────────────────────────────────
function setQueryState(state) {
  queryResultArea.classList.add('hidden');
  queryEmpty.classList.add('hidden');
  queryLoading.classList.add('hidden');
  queryError.classList.add('hidden');

  if (state === 'loading')  queryLoading.classList.remove('hidden');
  else if (state === 'result') queryResultArea.classList.remove('hidden');
  else if (state === 'error')  queryError.classList.remove('hidden');
  else queryEmpty.classList.remove('hidden');
}

function setSqlState(state) {
  sqlResultArea.classList.add('hidden');
  sqlEmpty.classList.add('hidden');
  sqlLoading.classList.add('hidden');
  sqlError.classList.add('hidden');

  if (state === 'loading')  sqlLoading.classList.remove('hidden');
  else if (state === 'result') sqlResultArea.classList.remove('hidden');
  else if (state === 'error')  sqlError.classList.remove('hidden');
  else sqlEmpty.classList.remove('hidden');
}

// ── Build HTML table ───────────────────────────────────────
function buildTable(columns, rows) {
  if (!columns.length) return '<p style="padding:16px;color:#6b7280;font-size:.875rem;">No data returned.</p>';

  const ths = columns.map(c => `<th>${escHtml(c)}</th>`).join('');
  const trs = rows.map(row => {
    const tds = row.map(cell => `<td title="${escHtml(String(cell ?? ''))}">${escHtml(String(cell ?? ''))}</td>`).join('');
    return `<tr>${tds}</tr>`;
  }).join('');

  return `<table class="data-table"><thead><tr>${ths}</tr></thead><tbody>${trs}</tbody></table>`;
}

function escHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Copy SQL ───────────────────────────────────────────────
copySqlBtn.addEventListener('click', () => {
  navigator.clipboard.writeText(sqlCode.textContent).then(() => {
    copySqlBtn.innerHTML = `
      <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
        <path d="M3 8l4 4 6-6" stroke="#10b981" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
      Copied!`;
    copySqlBtn.style.color = '#10b981';
    copySqlBtn.style.borderColor = '#10b981';
    setTimeout(() => {
      copySqlBtn.innerHTML = `
        <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
          <rect x="4" y="4" width="9" height="9" rx="1.5" stroke="currentColor" stroke-width="1.5"/>
          <path d="M3 11V3a1 1 0 011-1h8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
        </svg>
        Copy`;
      copySqlBtn.style.color = '';
      copySqlBtn.style.borderColor = '';
    }, 2000);
  });
});

// ── Render schema ──────────────────────────────────────────
function renderSchema() {
  const role = currentUser?.role ?? 'employee';
  const tables = ROLE_TABLES[role] ?? ROLE_TABLES.employee;

  const tableIcons = {
    employees: `<svg width="14" height="14" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="5" r="3" stroke="white" stroke-width="1.5"/><path d="M2 13c0-2.761 2.686-5 6-5s6 2.239 6 5" stroke="white" stroke-width="1.5" stroke-linecap="round"/></svg>`,
    customers:  `<svg width="14" height="14" viewBox="0 0 16 16" fill="none"><rect x="2" y="4" width="12" height="9" rx="1.5" stroke="white" stroke-width="1.5"/><path d="M5 4V3a1 1 0 011-1h4a1 1 0 011 1v1" stroke="white" stroke-width="1.5"/></svg>`,
    products:   `<svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M2 6l6-4 6 4v6l-6 4-6-4V6z" stroke="white" stroke-width="1.5" stroke-linejoin="round"/></svg>`,
    sales:      `<svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M2 12l4-4 3 2 5-6" stroke="white" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  };

  schemaGrid.innerHTML = Object.entries(tables).map(([tableName, cols]) => `
    <div class="schema-card">
      <div class="schema-card-header">
        <div class="schema-card-icon">${tableIcons[tableName] ?? ''}</div>
        <span class="schema-table-name">${tableName}</span>
      </div>
      <div class="schema-card-body">
        ${cols.map(col => `
          <div class="schema-column">
            <span class="schema-col-name">${col}</span>
          </div>
        `).join('')}
      </div>
    </div>
  `).join('');
}
