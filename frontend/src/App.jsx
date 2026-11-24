import { useEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowUp, AudioLines, CircleHelp, Command, LoaderCircle, MessageSquarePlus, Sparkles, SquarePen, WandSparkles } from 'lucide-react';

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
const newSessionId = () => globalThis.crypto?.randomUUID?.() || `s-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;

function App() {
  const [sessionId] = useState(newSessionId);
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [busy, setBusy] = useState(false);
  const [serviceState, setServiceState] = useState('checking');
  const [showSettings, setShowSettings] = useState(false);
  const endRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    fetch(`${API_BASE_URL}/health`)
      .then((response) => setServiceState(response.ok ? 'online' : 'offline'))
      .catch(() => setServiceState('offline'));
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, busy]);

  async function sendMessage(event) {
    event?.preventDefault();
    const message = draft.trim();
    if (!message || busy) return;

    setDraft('');
    setBusy(true);
    setMessages((current) => [...current, { role: 'user', content: message }]);

    try {
      const response = await fetch(`${API_BASE_URL}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          message,
          ...(systemPrompt.trim() ? { system_prompt: systemPrompt.trim() } : {}),
        }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(body.detail || `The request failed (${response.status}). Please try again.`);
      }
      setServiceState('online');
      setMessages((current) => [...current, { role: 'assistant', content: body.reply, metadata: body.metadata }]);
    } catch (error) {
      setServiceState('offline');
      setMessages((current) => [...current, { role: 'error', content: error.message || 'Could not reach the chat service. Please try again.' }]);
    } finally {
      setBusy(false);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }

  function handleKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) sendMessage(event);
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <a className="brand" href="#" aria-label="Lyftr AI home">
          <span className="brand-mark"><AudioLines size={19} strokeWidth={2.5} /></span>
          <span>lyftr<span className="brand-ai">.ai</span></span>
        </a>
        <div className="topbar-center"><span className="workspace-dot" /> Personal workspace <span className="chevron">⌄</span></div>
        <div className="topbar-actions">
          <button className="icon-button help-button" aria-label="Help"><CircleHelp size={18} /></button>
          <button className="avatar" aria-label="Account">Y</button>
        </div>
      </header>

      <section className="chat-layout">
        <aside className="sidebar">
          <button className="new-chat" onClick={() => { setMessages([]); window.location.reload(); }}>
            <MessageSquarePlus size={17} /> <span>New chat</span><span className="shortcut"><Command size={11} /> K</span>
          </button>
          <div className="sidebar-section-label">RECENT</div>
          <button className="history-item active"><span className="history-indicator" /> New conversation</button>
          <div className="sidebar-bottom">
            <div className="resilience-card">
              <div className="resilience-icon"><WandSparkles size={16} /></div>
              <strong>Built to keep going</strong>
              <p>Smart provider failover and response caching are on.</p>
              <div className="status-line"><span className={`status-dot ${serviceState}`} />{serviceState === 'online' ? 'All systems operational' : serviceState === 'checking' ? 'Connecting to service…' : 'Service unavailable'}</div>
            </div>
            <button className="profile-row"><span className="avatar small">Y</span><span className="profile-label"><strong>Your workspace</strong><small>Free plan</small></span><span className="more">···</span></button>
          </div>
        </aside>

        <section className="conversation-panel">
          <div className="conversation-header">
            <div className="model-selector"><span className="model-spark"><Sparkles size={15} /></span><span>Lyftr Assistant</span><span className="chevron">⌄</span></div>
            <div className="header-tools">
              <span className="session-pill"><span className={`status-dot ${serviceState}`} />{serviceState === 'online' ? 'Connected' : serviceState === 'checking' ? 'Connecting' : 'Offline'}</span>
              <button className={`icon-button settings-toggle ${showSettings ? 'selected' : ''}`} onClick={() => setShowSettings(!showSettings)} aria-label="Toggle system prompt" title="System prompt"><SquarePen size={17} /></button>
            </div>
          </div>

          {showSettings && <div className="settings-panel"><label htmlFor="system-prompt-input">System prompt <span>Optional · saved for this session</span></label><textarea id="system-prompt-input" data-testid="system-prompt-input" value={systemPrompt} onChange={(event) => setSystemPrompt(event.target.value)} placeholder="Tell the assistant how to respond…" rows={2} /></div>}

          <div className={`messages-scroll ${messages.length ? 'has-messages' : ''}`}>
            {messages.length === 0 ? (
              <div className="welcome">
                <div className="welcome-orb"><Sparkles size={24} /></div>
                <p className="eyebrow">A LITTLE MORE RESILIENT</p>
                <h1>What’s on your mind?</h1>
                <p className="welcome-copy">Ask anything. Your conversation stays in context, while smart caching and provider failover keep things moving.</p>
                <div className="suggestion-grid">
                  <button className="suggestion" onClick={() => setDraft('Explain how response caching works in simple terms.')}><span className="suggestion-icon mint"><WandSparkles size={16} /></span><span><strong>Explain something</strong><small>Make a complex topic simple</small></span><ArrowUp size={15} /></button>
                  <button className="suggestion" onClick={() => setDraft('Help me brainstorm a thoughtful weekend project.')}><span className="suggestion-icon lavender"><Sparkles size={16} /></span><span><strong>Get creative</strong><small>Brainstorm a fresh idea</small></span><ArrowUp size={15} /></button>
                  <button className="suggestion" onClick={() => setDraft('Help me write a clear, friendly project update.')}><span className="suggestion-icon peach"><SquarePen size={16} /></span><span><strong>Write something</strong><small>Find the right words</small></span><ArrowUp size={15} /></button>
                  <button className="suggestion" onClick={() => setDraft('What are three practical ways to learn a new skill?')}><span className="suggestion-icon blue"><Command size={16} /></span><span><strong>Find a new angle</strong><small>Explore a question together</small></span><ArrowUp size={15} /></button>
                </div>
              </div>
            ) : (
              <div className="message-list">
                {messages.map((message, index) => message.role === 'assistant' ? (
                  <article className="assistant-message" data-testid="assistant-message" key={`assistant-${index}`}>
                    <div className="assistant-avatar"><AudioLines size={16} /></div>
                    <div className="assistant-body">
                      <div className="assistant-label">Lyftr Assistant <span>·</span> <time>just now</time></div>
                      <div className="reply-text">{message.content}</div>
                      <div className="metadata-row">
                        <span className={`meta-chip source-chip ${message.metadata?.resolution_source === 'LLM_CACHE' ? 'cached' : ''}`} data-testid="meta-source"><span className="chip-dot" />{message.metadata?.resolution_source}</span>
                        <span className="meta-chip" data-testid="meta-model">{message.metadata?.model}</span>
                        <span className="meta-chip" data-testid="meta-latency">{message.metadata?.latency_ms} ms</span>
                        <span className="meta-chip token-chip" data-testid="meta-input-tokens"><ArrowDown size={11} />{message.metadata?.input_tokens}</span>
                        <span className="meta-chip token-chip" data-testid="meta-output-tokens"><ArrowUp size={11} />{message.metadata?.output_tokens}</span>
                      </div>
                    </div>
                  </article>
                ) : message.role === 'user' ? (
                  <div className="user-message" key={`user-${index}`}><div className="user-bubble">{message.content}</div></div>
                ) : (
                  <div className="error-message" role="alert" key={`error-${index}`}><span className="error-mark">!</span><span>{message.content}</span></div>
                ))}
                {busy && <div className="thinking"><div className="assistant-avatar"><AudioLines size={16} /></div><div><div className="assistant-label">Lyftr Assistant <span>·</span> <time>thinking</time></div><div className="thinking-dots"><i /><i /><i /></div></div></div>}
                <div ref={endRef} />
              </div>
            )}
          </div>

          <div className="composer-area">
            <form className="composer" onSubmit={sendMessage}>
              <textarea
                ref={inputRef}
                data-testid="chat-input"
                aria-label="Message Lyftr Assistant"
                placeholder="Message Lyftr Assistant…"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={handleKeyDown}
                rows={1}
                maxLength={4000}
              />
              <div className="composer-footer">
                <div className="composer-hints"><span className="hint-pill"><WandSparkles size={13} /> Smart routing</span><span className="hint-text">Enter to send · Shift + Enter for a new line</span></div>
                <button className="send-button" data-testid="send-button" type="submit" disabled={!draft.trim() || busy} aria-label="Send message">{busy ? <LoaderCircle className="spin" size={17} /> : <ArrowUp size={18} />}</button>
              </div>
            </form>
            <p className="disclaimer">AI can make mistakes. Check important information.</p>
          </div>
        </section>
      </section>
    </main>
  );
}

export default App;
