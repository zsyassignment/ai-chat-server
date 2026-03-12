const textarea = document.getElementById('message');
const sendBtn = document.getElementById('send');
const metaEl = document.getElementById('meta');
const chatLog = document.getElementById('chat-log');
const themeToggle = document.getElementById('theme-toggle');

let history = [];

const savedTheme = localStorage.getItem('theme') || 'dark';
applyTheme(savedTheme);

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  if (themeToggle) {
    themeToggle.textContent = theme === 'dark' ? 'Switch to light' : 'Switch to dark';
  }
  localStorage.setItem('theme', theme);
}

function renderHistory() {
  chatLog.innerHTML = '';
  if (!history.length) {
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.textContent = 'No messages yet. Start the conversation.';
    chatLog.appendChild(empty);
    return;
  }

  history.forEach((msg) => {
    const row = document.createElement('div');
    row.className = `message-row ${msg.role}`;

    const avatar = document.createElement('div');
    avatar.className = 'avatar';
    avatar.textContent = msg.role === 'assistant' ? 'AI' : 'You';

    const bubble = document.createElement('div');
    bubble.className = `bubble ${msg.role}`;

    const role = document.createElement('div');
    role.className = 'role';
    role.textContent = msg.role === 'assistant' ? 'Assistant' : 'You';

    const content = document.createElement('div');
    content.className = 'content';
    content.textContent = msg.content;

    bubble.append(role, content);
    row.append(avatar, bubble);
    chatLog.appendChild(row);
  });

  chatLog.scrollTop = chatLog.scrollHeight;
}

async function sendMessage() {
  const text = textarea.value.trim();
  if (!text) {
    metaEl.textContent = 'Type something first.';
    return;
  }

  const requestHistory = [...history];
  history.push({ role: 'user', content: text });
  const assistantIndex = history.push({ role: 'assistant', content: '' }) - 1;
  renderHistory();

  textarea.value = '';
  textarea.focus();
  sendBtn.disabled = true;
  metaEl.textContent = 'Waiting for server response...';

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream'
      },
      body: JSON.stringify({ message: text, history: requestHistory })
    });
    if (!res.ok) {
      const errText = await res.text();
      throw new Error(`${res.status} ${res.statusText} ${errText}`);
    }

    const contentType = (res.headers.get('content-type') || '').toLowerCase();
    if (!contentType.includes('text/event-stream') || !res.body) {
      const data = await res.json();
      if (Array.isArray(data.history)) {
        history = data.history;
      } else if (data.answer) {
        history[assistantIndex].content = data.answer;
      }
      renderHistory();
      metaEl.textContent = data.cached ? 'Served from cache.' : 'Fresh response from model.';
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

      if (!dataLines.length) return;

      let payload = {};
      try {
        payload = JSON.parse(dataLines.join('\n'));
      } catch {
        return;
      }

      if (eventName === 'status') {
        metaEl.textContent = payload.message || 'Working...';
        return;
      }

      if (eventName === 'delta') {
        history[assistantIndex].content += payload.content || '';
        renderHistory();
        return;
      }

      if (eventName === 'done') {
        if (Array.isArray(payload.history)) {
          history = payload.history;
        }
        renderHistory();
        metaEl.textContent = payload.cached ? 'Served from cache.' : 'Fresh response from model.';
        streamDone = true;
        return;
      }

      if (eventName === 'error') {
        throw new Error(payload.message || 'Stream failed');
      }
    };

    while (!streamDone) {
      const { value, done } = await reader.read();
      if (done) break;

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
      metaEl.textContent = 'Response stream ended.';
    }
  } catch (err) {
    metaEl.textContent = 'Request failed.';
    if (history[assistantIndex]) {
      history[assistantIndex].content = `Error: ${err.message}`;
      renderHistory();
    }
  } finally {
    sendBtn.disabled = false;
  }
}

sendBtn.addEventListener('click', sendMessage);
textarea.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
    sendMessage();
  }
});

if (themeToggle) {
  themeToggle.addEventListener('click', () => {
    const current = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
    applyTheme(current === 'dark' ? 'light' : 'dark');
  });
}

renderHistory();
