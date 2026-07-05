import { useState, useRef, useEffect } from 'react'
import { CopilotKit, useCopilotReadable } from '@copilotkit/react-core'
import './App.css'

// Define the public Kong LoadBalancer gateway URL
const GATEWAY_URL = 'http://a659b32a9d28f421da4c4090c1d0b3d0-774720386.us-east-1.elb.amazonaws.com'

function DashboardContent() {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: 'Hello! I am your stateful co-assistant. I am running keylessly inside EKS and authenticated with HashiCorp Vault. Ask me anything about your infrastructure or code deployment!'
    }
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [systemPrompt, setSystemPrompt] = useState('Standard EKS Assistant Profile')
  const [temperature, setTemperature] = useState(0.7)
  const chatEndRef = useRef(null)

  // Make dashboard state readable to CopilotKit context
  useCopilotReadable({
    description: 'Active conversation history',
    value: messages,
  })
  useCopilotReadable({
    description: 'Active configuration: temperature',
    value: temperature,
  })

  // Auto-scroll chat history on new messages
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const handleSendMessage = async (e) => {
    e?.preventDefault()
    if (!input.trim() || loading) return

    const userMessage = input.trim()
    setInput('')
    setMessages((prev) => [...prev, { role: 'user', content: userMessage }])
    setLoading(true)

    try {
      const response = await fetch(`${GATEWAY_URL}/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ prompt: userMessage })
      })

      if (!response.ok) {
        throw new Error(`HTTP error ${response.status}`)
      }

      const data = await response.json()
      setMessages((prev) => [...prev, { role: 'assistant', content: data.response }])
    } catch (err) {
      console.error('Fetch error:', err)
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: `⚠️ Connection Error: Failed to communicate with the AgentCore microservice. (Reason: ${err.message})`
        }
      ])
    } finally {
      setLoading(false)
    }
  }

  const handleQuickPrompt = (promptText) => {
    setInput(promptText)
  }

  return (
    <div className="app-root-container">
      {/* Header Banner */}
      <header className="header-banner">
        <div className="logo-section">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M12 2L2 22H22L12 2Z" stroke="url(#logo-grad)" strokeWidth="2.5" strokeLinejoin="round"/>
            <defs>
              <linearGradient id="logo-grad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor="#7C3AED" />
                <stop offset="100%" stopColor="#06B6D4" />
              </linearGradient>
            </defs>
          </svg>
          <h1 style={{ fontSize: '1.5rem' }}>Antigravity <span className="text-gradient">Workspace</span></h1>
        </div>
        <div className="status-indicator">
          <div className="status-dot"></div>
          <span>Gateway Connected</span>
        </div>
      </header>

      {/* Main Dashboard Panel Grid */}
      <main className="dashboard-container">
        
        {/* Left Config Panel */}
        <section className="glass-panel sidebar-panel animate-slide-up" style={{ animationDelay: '0.1s' }}>
          <div>
            <h2 style={{ fontSize: '1.2rem', margin: '0 0 4px' }}>System Architecture</h2>
            <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>EKS + Vault Security Controls</p>
          </div>
          
          <hr style={{ border: 'none', borderTop: '1px solid var(--border-glass)', width: '100%', margin: '0' }} />

          <div className="config-item">
            <span className="config-label">Model Endpoint</span>
            <span className="badge badge-purple" style={{ alignSelf: 'flex-start' }}>us.amazon.nova-lite-v1:0</span>
          </div>

          <div className="config-item">
            <span className="config-label">AWS Bedrock Integration</span>
            <span className="badge" style={{ alignSelf: 'flex-start', color: '#10B981', borderColor: 'rgba(16, 185, 129, 0.2)' }}>Keyless IAM Role</span>
          </div>

          <div className="config-item">
            <span className="config-label">HashiCorp Vault Auth</span>
            <span className="badge" style={{ alignSelf: 'flex-start', color: '#10B981', borderColor: 'rgba(16, 185, 129, 0.2)' }}>Active ServiceAccount</span>
          </div>

          <div className="config-item">
            <span className="config-label">Rate Limiter</span>
            <span className="config-value" style={{ fontSize: '0.85rem' }}>10 requests / min</span>
          </div>

          <hr style={{ border: 'none', borderTop: '1px solid var(--border-glass)', width: '100%', margin: '0' }} />

          <div className="config-item">
            <span className="config-label">Model Temperature ({temperature})</span>
            <input 
              type="range" 
              min="0" 
              max="1" 
              step="0.1" 
              value={temperature} 
              onChange={(e) => setTemperature(parseFloat(e.target.value))} 
              style={{ width: '100%', accentColor: 'var(--accent-purple)' }}
            />
          </div>

          <div className="config-item">
            <span className="config-label">Configuration Preset</span>
            <select 
              value={systemPrompt} 
              onChange={(e) => setSystemPrompt(e.target.value)}
              style={{ 
                background: 'rgba(0,0,0,0.2)', 
                border: '1px solid var(--border-glass)', 
                color: 'var(--text-primary)',
                padding: '8px',
                borderRadius: '6px',
                outline: 'none',
                fontFamily: 'var(--font-sans)',
                fontSize: '0.85rem'
              }}
            >
              <option value="Standard EKS Assistant Profile">Standard Developer Profile</option>
              <option value="Security Governance Mode">Security Architect Mode</option>
              <option value="Detailed Infrastructure Auditor">Infrastructure Auditor Mode</option>
            </select>
          </div>

          <div style={{ marginTop: 'auto' }}>
            <span className="config-label" style={{ marginBottom: '8px', display: 'block' }}>Quick Actions</span>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <button 
                onClick={() => handleQuickPrompt("What is the current capability of our app?")}
                style={{ 
                  background: 'rgba(255,255,255,0.02)', 
                  border: '1px solid var(--border-glass)', 
                  color: 'var(--text-secondary)',
                  padding: '8px',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  textAlign: 'left',
                  fontSize: '0.8rem',
                  transition: 'background 0.2s'
                }}
                onMouseOver={(e) => e.target.style.background = 'rgba(255,255,255,0.05)'}
                onMouseOut={(e) => e.target.style.background = 'rgba(255,255,255,0.02)'}
              >
                🔍 App Capabilities
              </button>
              <button 
                onClick={() => handleQuickPrompt("Check EKS infrastructure and security health status.")}
                style={{ 
                  background: 'rgba(255,255,255,0.02)', 
                  border: '1px solid var(--border-glass)', 
                  color: 'var(--text-secondary)',
                  padding: '8px',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  textAlign: 'left',
                  fontSize: '0.8rem',
                  transition: 'background 0.2s'
                }}
                onMouseOver={(e) => e.target.style.background = 'rgba(255,255,255,0.05)'}
                onMouseOut={(e) => e.target.style.background = 'rgba(255,255,255,0.02)'}
              >
                🛡️ Check Cluster Health
              </button>
            </div>
          </div>
        </section>

        {/* Right Chat Panel */}
        <section className="glass-panel chat-panel animate-slide-up">
          {/* Scrollable Conversation */}
          <div className="chat-history">
            {messages.map((msg, index) => (
              <div 
                key={index} 
                className={`copilotKitMessage ${
                  msg.role === 'user' ? 'copilotKitMessageUser' : 'copilotKitMessageAssistant'
                }`}
                style={{ alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start', maxWidth: '75%' }}
              >
                <div style={{ fontWeight: '600', fontSize: '0.8rem', marginBottom: '6px', color: msg.role === 'user' ? 'var(--accent-purple-light)' : 'var(--accent-cyan)' }}>
                  {msg.role === 'user' ? 'DEVELOPER' : 'CO-ASSISTANT'}
                </div>
                <div style={{ fontSize: '0.95rem', lineHeight: '1.5', whiteSpace: 'pre-wrap' }}>
                  {msg.content}
                </div>
              </div>
            ))}
            
            {loading && (
              <div className="typing-indicator">
                <span className="typing-dot"></span>
                <span className="typing-dot"></span>
                <span className="typing-dot"></span>
              </div>
            )}
            <div ref={chatEndRef} />
          </div>

          {/* Form Input Area */}
          <form className="chat-input-bar" onSubmit={handleSendMessage}>
            <input
              type="text"
              className="chat-input-field"
              placeholder="Ask a question or enter a command..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={loading}
              id="chat-input-id"
            />
            <button 
              type="submit" 
              className="send-button"
              disabled={loading || !input.trim()}
              id="send-button-id"
            >
              Run Command
            </button>
          </form>
        </section>

      </main>
    </div>
  )
}

function App() {
  return (
    <CopilotKit runtimeUrl={`${GATEWAY_URL}/v1/copilotkit`}>
      <DashboardContent />
    </CopilotKit>
  )
}

export default App
