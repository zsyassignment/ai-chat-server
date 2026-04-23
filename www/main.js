const authView = document.getElementById('auth-view');
const appView = document.getElementById('app-view');
const textarea = document.getElementById('message');
const sendBtn = document.getElementById('send');
const metaEl = document.getElementById('meta');
const chatLog = document.getElementById('chat-log');
const historyList = document.getElementById('history-list');
const usernameInput = document.getElementById('username');
const passwordInput = document.getElementById('password');
const loginBtn = document.getElementById('login');
const registerBtn = document.getElementById('register');
const logoutBtn = document.getElementById('logout');
const newConversationBtn = document.getElementById('new-conversation');
const userPill = document.getElementById('user-pill');
const accountMeta = document.getElementById('account-meta');
const loginStatus = document.getElementById('login-status');
const conversationTitleEl = document.getElementById('conversation-title');
const themeToggleButtons = document.querySelectorAll('[data-theme-toggle]');

let conversations = [];
let messages = [];
let authToken = localStorage.getItem('auth_token') || '';
let currentUser = localStorage.getItem('auth_user') || '';
let activeConversationId = 0;
let activeConversationTitle = '';
let isSending = false;
let isLoadingConversation = false;

const savedTheme = localStorage.getItem('theme') || 'light';
applyTheme(savedTheme);

function snippet(text, maxLength = 42) {
  const normalized = (text || '').replace(/\s+/g, ' ').trim();
  if (!normalized) {
    return '新对话';
  }
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength)}...`;
}

function normalizeConversationId(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return 0;
  }
  return Math.trunc(parsed);
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  themeToggleButtons.forEach((button) => {
    button.textContent = theme === 'dark' ? '浅色模式' : '深色模式';
  });
  localStorage.setItem('theme', theme);
}

function showAuthView() {
  authView.classList.remove('is-hidden');
  appView.classList.add('is-hidden');
}

function showAppView() {
  authView.classList.add('is-hidden');
  appView.classList.remove('is-hidden');
}

function resizeComposer() {
  textarea.style.height = 'auto';
  textarea.style.height = `${Math.min(textarea.scrollHeight, 220)}px`;
}

function setLoginStatus(message) {
  loginStatus.textContent = message;
}

function activeConversationSummary() {
  return conversations.find((conversation) => conversation.id === activeConversationId) || null;
}

function syncConversationTitle() {
  const activeConversation = activeConversationSummary();
  if (activeConversation) {
    activeConversationTitle = activeConversation.title;
  }
  if (!activeConversationId) {
    activeConversationTitle = '新对话';
  }
  conversationTitleEl.textContent = activeConversationTitle || '新对话';
}

function syncUiState() {
  const enabled = Boolean(authToken && currentUser);
  textarea.disabled = !enabled;
  sendBtn.disabled = !enabled || !textarea.value.trim() || isSending || isLoadingConversation;
  logoutBtn.disabled = !enabled || isSending;
  newConversationBtn.disabled = !enabled || isSending || isLoadingConversation;
}

function setWorkspaceStatus(message) {
  userPill.textContent = currentUser || '未登录';
  accountMeta.textContent = currentUser ? '已登录' : '未登录';
  metaEl.textContent = message;
  syncConversationTitle();
  syncUiState();
}

function renderConversationList() {
  historyList.innerHTML = '';

  if (!conversations.length) {
    const empty = document.createElement('div');
    empty.className = 'history-empty';
    empty.textContent = '还没有会话';
    historyList.appendChild(empty);
    return;
  }

  conversations.forEach((conversation) => {
    const item = document.createElement('button');
    item.className = `history-item ${conversation.id === activeConversationId ? 'active' : ''}`;
    item.type = 'button';
    item.disabled = isSending || isLoadingConversation;

    const title = document.createElement('div');
    title.className = 'history-title';
    title.textContent = conversation.title || '未命名会话';

    const preview = document.createElement('div');
    preview.className = 'history-preview';
    preview.textContent = conversation.preview || '暂无内容';

    const meta = document.createElement('div');
    meta.className = 'history-meta';
    meta.textContent = conversation.updated_at || '';

    item.append(title, preview, meta);
    item.addEventListener('click', () => {
      void loadConversation(conversation.id);
    });
    historyList.appendChild(item);
  });
}

function renderMessages(scrollMode = 'bottom') {
  syncConversationTitle();
  chatLog.innerHTML = '';

  if (!messages.length) {
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.textContent = activeConversationId
      ? '这个会话暂时还没有消息'
      : authToken
        ? '发条消息开始新对话'
        : '请先登录';
    chatLog.appendChild(empty);
    return;
  }

  messages.forEach((message) => {
    const row = document.createElement('div');
    row.className = `message-row ${message.role}`;

    const avatar = document.createElement('div');
    avatar.className = 'avatar';
    avatar.textContent = message.role === 'assistant' ? 'AI' : '你';

    const bubble = document.createElement('div');
    bubble.className = `bubble ${message.role}`;

    if (message.role === 'assistant' && (message.content || '').startsWith('Error:')) {
      bubble.classList.add('error');
    }

    const role = document.createElement('div');
    role.className = 'role';
    role.textContent = message.role === 'assistant' ? 'AI' : '你';

    const content = document.createElement('div');
    content.className = 'content';
    content.textContent = message.content;

    bubble.append(role, content);
    row.append(avatar, bubble);
    chatLog.appendChild(row);
  });

  if (scrollMode === 'bottom') {
    chatLog.scrollTop = chatLog.scrollHeight;
  }
}

function storeSession(token, username) {
  authToken = token;
  currentUser = username;
  localStorage.setItem('auth_token', token);
  localStorage.setItem('auth_user', username);
}

function resetConversationState() {
  conversations = [];
  messages = [];
  activeConversationId = 0;
  activeConversationTitle = '新对话';
  renderConversationList();
  renderMessages();
}

function clearSession(message) {
  authToken = '';
  currentUser = '';
  resetConversationState();
  localStorage.removeItem('auth_token');
  localStorage.removeItem('auth_user');
  showAuthView();
  setLoginStatus(message || '登录或注册后开始对话。');
  setWorkspaceStatus('请先登录');
}

function applyConversationPayload(payload) {
  conversations = Array.isArray(payload.conversations) ? payload.conversations : [];
  messages = Array.isArray(payload.history) ? payload.history : [];
  activeConversationId = normalizeConversationId(payload.active_conversation_id);
  activeConversationTitle =
    payload.active_conversation_title ||
    activeConversationSummary()?.title ||
    (activeConversationId ? '当前会话' : '新对话');
  renderConversationList();
  renderMessages();
}

function applySessionPayload(payload, message) {
  storeSession(payload.token || authToken, payload.username || currentUser);
  applyConversationPayload(payload);
  showAppView();
  setLoginStatus(message || '登录成功。');
  setWorkspaceStatus(activeConversationId ? '已同步最近会话' : '发条消息开始新对话');
  resizeComposer();
  textarea.focus();
}

async function readJsonResponse(res) {
  const text = await res.text();
  if (!text) {
    return {};
  }
  try {
    return JSON.parse(text);
  } catch {
    return { message: text };
  }
}

async function authFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (authToken) {
    headers.set('Authorization', `Bearer ${authToken}`);
  }
  return fetch(url, { ...options, headers });
}

async function restoreSession() {
  if (!authToken) {
    clearSession('登录或注册后开始对话。');
    return;
  }

  setLoginStatus('正在同步会话...');
  try {
    const res = await authFetch('/api/me');
    const data = await readJsonResponse(res);
    if (!res.ok || !data.ok) {
      clearSession(data.message || '会话已失效，请重新登录。');
      return;
    }
    applySessionPayload(data, '会话已恢复。');
  } catch (err) {
    clearSession(`恢复会话失败：${err.message}`);
  }
}

async function submitAuth(endpoint) {
  const username = usernameInput.value.trim();
  const password = passwordInput.value;

  if (!username || !password) {
    setLoginStatus('用户名和密码不能为空。');
    return;
  }

  loginBtn.disabled = true;
  registerBtn.disabled = true;
  setLoginStatus(endpoint.endsWith('login') ? '正在登录...' : '正在创建账号...');

  try {
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ username, password })
    });

    const data = await readJsonResponse(res);
    if (!res.ok || !data.ok) {
      throw new Error(data.message || `${res.status} ${res.statusText}`);
    }

    passwordInput.value = '';
    applySessionPayload(
      data,
      endpoint.endsWith('login') ? `欢迎回来，${data.username}` : `账号已创建，${data.username}`
    );
  } catch (err) {
    setLoginStatus(err.message);
  } finally {
    loginBtn.disabled = false;
    registerBtn.disabled = false;
  }
}

async function loadConversation(conversationId) {
  const normalizedId = normalizeConversationId(conversationId);
  if (!normalizedId) {
    startNewConversation();
    return;
  }
  if (isSending) {
    setWorkspaceStatus('请等待当前回复完成');
    return;
  }
  if (normalizedId === activeConversationId && messages.length) {
    return;
  }
  if (!authToken) {
    clearSession('登录或注册后开始对话。');
    return;
  }

  isLoadingConversation = true;
  renderConversationList();
  syncUiState();
  setWorkspaceStatus('正在加载会话...');

  try {
    const params = new URLSearchParams({ conversation_id: String(normalizedId) });
    const res = await authFetch(`/api/history?${params.toString()}`);
    const data = await readJsonResponse(res);
    if (!res.ok || !data.ok) {
      if (res.status === 401) {
        clearSession(data.message || '会话已失效，请重新登录。');
        return;
      }
      throw new Error(data.message || `${res.status} ${res.statusText}`);
    }

    applyConversationPayload(data);
    setWorkspaceStatus('会话已加载');
  } catch (err) {
    setWorkspaceStatus(`加载会话失败：${err.message}`);
  } finally {
    isLoadingConversation = false;
    renderConversationList();
    syncUiState();
  }
}

function startNewConversation() {
  if (!authToken) {
    clearSession('登录或注册后开始对话。');
    return;
  }
  if (isSending) {
    setWorkspaceStatus('请等待当前回复完成');
    return;
  }

  activeConversationId = 0;
  activeConversationTitle = '新对话';
  messages = [];
  renderConversationList();
  renderMessages();
  setWorkspaceStatus('已准备新对话');
  textarea.focus();
}

async function logout() {
  if (!authToken) {
    clearSession('登录或注册后开始对话。');
    return;
  }
  if (isSending) {
    setWorkspaceStatus('请等待当前回复完成');
    return;
  }

  logoutBtn.disabled = true;
  setWorkspaceStatus('正在退出...');
  try {
    await authFetch('/api/auth/logout', { method: 'POST' });
  } finally {
    logoutBtn.disabled = false;
    clearSession('已退出登录。');
  }
}

function updateConversationStateFromDone(payload) {
  if (Array.isArray(payload.history)) {
    messages = payload.history;
  }
  if (Array.isArray(payload.conversations)) {
    conversations = payload.conversations;
  }

  const nextConversationId = normalizeConversationId(payload.conversation_id);
  if (nextConversationId) {
    activeConversationId = nextConversationId;
  }

  activeConversationTitle =
    payload.conversation_title ||
    activeConversationSummary()?.title ||
    activeConversationTitle ||
    (activeConversationId ? '当前会话' : '新对话');
}

async function sendMessage() {
  if (isSending) {
    return;
  }
  if (!authToken) {
    setWorkspaceStatus('请先登录');
    showAuthView();
    return;
  }

  const text = textarea.value.trim();
  if (!text) {
    setWorkspaceStatus('请输入内容');
    return;
  }

  const assistantIndex = messages.push({ role: 'user', content: text }, { role: 'assistant', content: '' }) - 1;
  renderMessages();

  textarea.value = '';
  resizeComposer();
  textarea.focus();
  isSending = true;
  renderConversationList();
  syncUiState();
  setWorkspaceStatus('正在生成回复...');

  try {
    const body = { message: text };
    if (activeConversationId > 0) {
      body.conversation_id = activeConversationId;
    }

    const res = await authFetch('/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream'
      },
      body: JSON.stringify(body)
    });

    if (!res.ok) {
      const data = await readJsonResponse(res);
      if (res.status === 401) {
        clearSession(data.message || '会话已失效，请重新登录。');
      }
      throw new Error(data.message || `${res.status} ${res.statusText}`);
    }

    const contentType = (res.headers.get('content-type') || '').toLowerCase();
    if (!contentType.includes('text/event-stream') || !res.body) {
      const data = await readJsonResponse(res);
      if (data && typeof data === 'object') {
        updateConversationStateFromDone(data);
        renderConversationList();
        renderMessages();
      }
      setWorkspaceStatus(data.message || '请求已完成');
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let pending = '';
    let streamDone = false;

    const applyEvent = (rawBlock) => {
      const lines = rawBlock
        .split('\n')
        .map((line) => line.trimEnd())
        .filter(Boolean);

      let eventName = 'message';
      const dataLines = [];

      lines.forEach((line) => {
        if (line.startsWith('event:')) {
          eventName = line.slice(6).trim();
          return;
        }
        if (line.startsWith('data:')) {
          dataLines.push(line.slice(5).trim());
        }
      });

      if (!dataLines.length) {
        return;
      }

      let payload = {};
      try {
        payload = JSON.parse(dataLines.join('\n'));
      } catch {
        return;
      }

      if (eventName === 'status') {
        setWorkspaceStatus(payload.message || '正在处理...');
        return;
      }

      if (eventName === 'delta') {
        if (messages[assistantIndex]) {
          messages[assistantIndex].content += payload.content || '';
          renderMessages();
        }
        return;
      }

      if (eventName === 'done') {
        updateConversationStateFromDone(payload);
        renderConversationList();
        renderMessages();

        let summary = payload.cached ? '已从缓存返回' : '回复完成';
        if (payload.persisted === false) {
          summary += payload.warning ? `，会话保存失败：${payload.warning}` : '，会话保存失败';
        }
        setWorkspaceStatus(summary);
        streamDone = true;
        return;
      }

      if (eventName === 'error') {
        throw new Error(payload.message || 'Stream failed');
      }
    };

    while (!streamDone) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }

      pending += decoder.decode(value, { stream: true });

      let sepIndex = pending.indexOf('\n\n');
      while (sepIndex !== -1) {
        const block = pending.slice(0, sepIndex).trim();
        pending = pending.slice(sepIndex + 2);
        if (block) {
          applyEvent(block);
        }
        sepIndex = pending.indexOf('\n\n');
      }
    }

    if (!streamDone) {
      setWorkspaceStatus('连接已结束');
    }
  } catch (err) {
    setWorkspaceStatus('请求失败');
    if (messages[assistantIndex]) {
      messages[assistantIndex].content = `Error: ${err.message}`;
      renderMessages();
    }
  } finally {
    isSending = false;
    renderConversationList();
    syncUiState();
  }
}

loginBtn.addEventListener('click', () => submitAuth('/api/auth/login'));
registerBtn.addEventListener('click', () => submitAuth('/api/auth/register'));
logoutBtn.addEventListener('click', logout);
newConversationBtn.addEventListener('click', startNewConversation);
sendBtn.addEventListener('click', sendMessage);

textarea.addEventListener('input', () => {
  resizeComposer();
  syncUiState();
});

textarea.addEventListener('keydown', (event) => {
  if (event.isComposing) {
    return;
  }
  if (event.key === 'Enter' && !event.shiftKey && !event.metaKey && !event.ctrlKey && !event.altKey) {
    event.preventDefault();
    sendMessage();
  }
});

passwordInput.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    submitAuth('/api/auth/login');
  }
});

themeToggleButtons.forEach((button) => {
  button.addEventListener('click', () => {
    const currentTheme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
    applyTheme(currentTheme === 'dark' ? 'light' : 'dark');
  });
});

setLoginStatus('登录或注册后开始对话。');
setWorkspaceStatus('请先登录');
renderConversationList();
renderMessages();
resizeComposer();
restoreSession();
