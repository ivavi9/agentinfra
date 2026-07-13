import { useState, useRef, useEffect } from 'react'
import { CopilotKit, useCopilotReadable } from '@copilotkit/react-core'
import './App.css'

// Define the public Kong LoadBalancer gateway URL
const GATEWAY_URL = 'http://a90fb1d5f715a4159abc7483e774bd8d-498703573.us-east-1.elb.amazonaws.com'

// Parser for inline elements: **bold** and `code`
const parseInlineMarkdown = (text) => {
  if (!text) return '';

  // Process bold (**bold**) and inline code (`code`)
  const regex = /(\*\*.*?\*\*|`.*?`)/g;
  const parts = text.split(regex);

  return parts.map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={index} className="md-bold">{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return (
        <code key={index} className="md-inline-code">
          {part.slice(1, -1)}
        </code>
      );
    }
    return part;
  });
};

// Parser for block elements: headers, bullet lists, code blocks
const parseMarkdownText = (text) => {
  if (!text) return null;

  // Split by code blocks first
  const parts = text.split(/(```[\s\S]*?```)/g);

  return parts.map((part, partIndex) => {
    // Fenced Code Block
    if (part.startsWith('```') && part.endsWith('```')) {
      const match = part.match(/```(\w*)\n([\s\S]*?)```/);
      const language = match ? match[1] : '';
      const code = match ? match[2] : part.slice(3, -3);
      return (
        <pre key={`code-${partIndex}`} className="md-code-block">
          {language && <div className="md-code-lang">{language}</div>}
          <code className="md-code-content">{code.trim()}</code>
        </pre>
      );
    }

    // Process headers and lists line-by-line
    const lines = part.split('\n');
    let inList = false;
    let listItems = [];
    const elements = [];

    const flushList = (keySuffix) => {
      if (listItems.length > 0) {
        elements.push(
          <ul key={`ul-${keySuffix}`} className="md-unordered-list">
            {listItems}
          </ul>
        );
        listItems = [];
        inList = false;
      }
    };

    lines.forEach((line, lineIndex) => {
      const trimmed = line.trim();

      // Bullet List Match (starts with * or - followed by space)
      const listMatch = line.match(/^\s*[*+-]\s+(.*)$/);
      if (listMatch) {
        inList = true;
        listItems.push(
          <li key={`li-${lineIndex}`} className="md-list-item">
            {parseInlineMarkdown(listMatch[1])}
          </li>
        );
        return;
      }

      // Non-list line: flush any accumulated list items first
      if (inList) {
        flushList(lineIndex);
      }

      // Headers
      if (trimmed.startsWith('### ')) {
        elements.push(<h3 key={`h3-${lineIndex}`} className="md-h3">{parseInlineMarkdown(trimmed.slice(4))}</h3>);
        return;
      }
      if (trimmed.startsWith('## ')) {
        elements.push(<h2 key={`h2-${lineIndex}`} className="md-h2">{parseInlineMarkdown(trimmed.slice(3))}</h2>);
        return;
      }
      if (trimmed.startsWith('# ')) {
        elements.push(<h1 key={`h1-${lineIndex}`} className="md-h1">{parseInlineMarkdown(trimmed.slice(2))}</h1>);
        return;
      }

      // Paragraph text line
      if (trimmed) {
        elements.push(<p key={`p-${lineIndex}`} className="md-paragraph">{parseInlineMarkdown(line)}</p>);
      }
    });

    // Flush any leftover list at the end of the block
    flushList(partIndex);

    return <div key={`block-${partIndex}`} className="md-block-container">{elements}</div>;
  });
};

// Helper to render thinking blocks and markdown/clean content
const renderMessageContent = (content) => {
  if (!content) return null;
  const thinkingRegex = /<thinking>([\s\S]*?)<\/thinking>/;
  const match = content.match(thinkingRegex);
  if (match) {
    const thinkingText = match[1].trim();
    const cleanContent = content.replace(thinkingRegex, '').trim();
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
        <details className="thinking-details" style={{
          background: 'rgba(0, 0, 0, 0.25)',
          border: '1px solid rgba(124, 90, 237, 0.2)',
          borderRadius: '8px',
          padding: '10px 14px',
          transition: 'border-color 0.2s'
        }}>
          <summary className="thinking-summary" style={{
            fontSize: '0.82rem',
            color: 'var(--text-secondary)',
            cursor: 'pointer',
            fontWeight: '600',
            userSelect: 'none',
            outline: 'none',
            display: 'list-item'
          }}>
            🧠 Agent Reasoning Process
          </summary>
          <div className="thinking-content" style={{
            marginTop: '10px',
            fontSize: '0.85rem',
            color: 'rgba(243, 244, 246, 0.75)',
            fontFamily: 'var(--font-mono)',
            whiteSpace: 'pre-wrap',
            lineHeight: '1.4',
            borderLeft: '2px solid var(--accent-purple)',
            paddingLeft: '12px'
          }}>
            {thinkingText}
          </div>
        </details>
        {cleanContent && (
          <div className="md-rendered-message">
            {parseMarkdownText(cleanContent)}
          </div>
        )}
      </div>
    );
  }
  return <div className="md-rendered-message">{parseMarkdownText(content)}</div>;
};

function DashboardContent({ token, onLogout }) {
  const [sessionId] = useState(() => {
    let id = sessionStorage.getItem('agent_session_id')
    if (!id) {
      id = 'session-' + Math.random().toString(36).substring(2, 15)
      sessionStorage.setItem('agent_session_id', id)
    }
    return id
  })
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
  const [metrics, setMetrics] = useState({ infra: 0, code: 0, research: 0, tokens: 0 })
  const chatEndRef = useRef(null)

  // Pipeline Ingestion Automation states
  const [activeTab, setActiveTab] = useState('chat') // 'chat', 'pipeline'
  const [brdText, setBrdText] = useState(`# Value Stream: Retail Bank Transaction Ingestion
Source System: CORE_BANK_DB
SLA Latency: Hourly
Estimated Volume: 150000 events/day

Entities:
- Customer:
  * customer_id (PK)
  * first_name
  * last_name
  * email
  * date_of_birth
- Transaction:
  * transaction_id (PK)
  * account_id
  * amount
  * transaction_date
`)
  const [pipelineLoading, setPipelineLoading] = useState(false)
  const [pipelineStatus, setPipelineStatus] = useState('')
  const [pipelineError, setPipelineError] = useState('')
  const [mappingMatrix, setMappingMatrix] = useState([])
  const [generatedFiles, setGeneratedFiles] = useState({})
  const [selectedFileTab, setSelectedFileTab] = useState('')
  const [pipelineStateStep, setPipelineStateStep] = useState(0) // 0: input, 1: mapping approval, 2: bundle generated
  const [pipelineRunLoading, setPipelineRunLoading] = useState(false)
  const [pipelineRunResult, setPipelineRunResult] = useState(null)
  const [activePipelineRunStatus, setActivePipelineRunStatus] = useState('') // '', 'bronze', 'silver', 'complete'

  const handleAnalysePipeline = async () => {
    setPipelineLoading(true)
    setPipelineError('')
    setPipelineStateStep(1)
    setPipelineStatus('Parsing BRD Value Stream & Mapping Schemas...')
    
    try {
      const response = await fetch(`${GATEWAY_URL}/pipeline/analyse`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ brd_document: brdText, session_id: sessionId })
      })
      
      const data = await response.json()
      if (!response.ok) {
        throw new Error(data.detail || 'Analysis request failed.')
      }
      
      if (data.error) {
        throw new Error(data.error)
      }
      
      setMappingMatrix(data.mapping_matrix)
      setPipelineStatus('Awaiting Source-to-Target mapping approval...')
    } catch (err) {
      setPipelineError(err.message)
      setPipelineStateStep(0)
    } finally {
      setPipelineLoading(false)
    }
  }

  const handleApprovePipeline = async () => {
    setPipelineLoading(true)
    setPipelineError('')
    setPipelineStatus('Compiling Databricks Asset Bundle (DAB) files...')
    
    try {
      const response = await fetch(`${GATEWAY_URL}/pipeline/approve`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ session_id: sessionId, mapping_matrix: mappingMatrix })
      })
      
      const data = await response.json()
      if (!response.ok) {
        throw new Error(data.detail || 'Approve request failed.')
      }
      
      if (data.error) {
        throw new Error(data.error)
      }
      
      setGeneratedFiles(data.generated_bundle_files)
      const fileNames = Object.keys(data.generated_bundle_files)
      if (fileNames.length > 0) {
        setSelectedFileTab(fileNames[0])
      }
      setPipelineStateStep(2)
      setPipelineStatus('Databricks Asset Bundle successfully generated!')
    } catch (err) {
      setPipelineError(err.message)
    } finally {
      setPipelineLoading(false)
    }
  }

  const handleRejectPipeline = () => {
    setMappingMatrix([])
    setGeneratedFiles({})
    setPipelineStateStep(0)
    setPipelineError('Pipeline mapping rejected by user.')
  }

  const handleRunPipeline = async (entityName) => {
    setPipelineRunLoading(true)
    setPipelineRunResult(null)
    setActivePipelineRunStatus('bronze')
    try {
      // Small artificial delay for visual state progress in UX
      await new Promise((r) => setTimeout(r, 1000));
      setActivePipelineRunStatus('silver')
      
      const response = await fetch(`${GATEWAY_URL}/pipeline/run`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          session_id: sessionId,
          entity_name: entityName
        })
      })
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `Execution failed with status: ${response.status}`);
      }
      const data = await response.json()
      setPipelineRunResult(data)
      setActivePipelineRunStatus('complete')
    } catch (err) {
      console.error(err)
      setPipelineError(`Pipeline execution failed: ${err.message}`)
      setActivePipelineRunStatus('')
    } finally {
      setPipelineRunLoading(false)
    }
  }

  const handleMappingCellChange = (index, field, value) => {
    setMappingMatrix((prev) => {
      const updated = [...prev]
      updated[index] = {
        ...updated[index],
        [field]: value
      }
      return updated
    })
  }

  const fetchMetrics = async () => {
    try {
      const response = await fetch(`${GATEWAY_URL}/metrics`)
      if (response.ok) {
        const text = await response.text()
        
        // Parse simple prometheus metrics
        const infraMatch = text.match(/agent_routes_total\{specialist="infra"\} (\d+)/)
        const codeMatch = text.match(/agent_routes_total\{specialist="code"\} (\d+)/)
        const researchMatch = text.match(/agent_routes_total\{specialist="research"\} (\d+)/)
        const tokensMatch = text.match(/llm_token_chunks_total (\d+)/)
        
        setMetrics({
          infra: infraMatch ? parseInt(infraMatch[1], 10) : 0,
          code: codeMatch ? parseInt(codeMatch[1], 10) : 0,
          research: researchMatch ? parseInt(researchMatch[1], 10) : 0,
          tokens: tokensMatch ? parseInt(tokensMatch[1], 10) : 0
        })
      }
    } catch (err) {
      console.warn('Failed to fetch metrics:', err)
    }
  }

  // Fetch stateful chat history on mount
  useEffect(() => {
    const loadHistory = async () => {
      try {
        const response = await fetch(`${GATEWAY_URL}/chat/history?session_id=${sessionId}`, {
          headers: {
            'Authorization': `Bearer ${token}`
          }
        })
        if (response.ok) {
          const data = await response.json()
          if (data.history && data.history.length > 0) {
            setMessages(data.history)
          }
        }
      } catch (err) {
        console.warn('Failed to load chat history:', err)
      }
    }
    loadHistory()
    fetchMetrics()
  }, [sessionId, token])

  // Refresh metrics every 8 seconds
  useEffect(() => {
    const timer = setInterval(fetchMetrics, 8000)
    return () => clearInterval(timer)
  }, [])

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
    
    // Add user message and temporary empty assistant message immediately
    setMessages((prev) => [
      ...prev, 
      { role: 'user', content: userMessage },
      { role: 'assistant', content: '', specialist: null }
    ])
    setLoading(true)

    try {
      const response = await fetch(`${GATEWAY_URL}/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ prompt: userMessage, session_id: sessionId })
      })

      if (!response.ok) {
        throw new Error(`HTTP error ${response.status}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let done = false
      let accumulatedText = ''
      let resolvedSpecialist = null

      while (!done) {
        const { value, done: readerDone } = await reader.read()
        done = readerDone
        if (value) {
          const chunkStr = decoder.decode(value, { stream: !done })
          const lines = chunkStr.split('\n')
          
          for (const line of lines) {
            const trimmed = line.trim()
            if (trimmed.startsWith('data: ')) {
              try {
                const parsed = JSON.parse(trimmed.slice(6))
                if (parsed.type === 'token') {
                  accumulatedText += parsed.data
                  setMessages((prev) => {
                    const updated = [...prev]
                    if (updated.length > 0) {
                      updated[updated.length - 1] = {
                        ...updated[updated.length - 1],
                        content: accumulatedText
                      }
                    }
                    return updated
                  })
                } else if (parsed.type === 'specialist') {
                  resolvedSpecialist = parsed.data
                  setMessages((prev) => {
                    const updated = [...prev]
                    if (updated.length > 0) {
                      updated[updated.length - 1] = {
                        ...updated[updated.length - 1],
                        specialist: resolvedSpecialist
                      }
                    }
                    return updated
                  })
                } else if (parsed.type === 'approval_required') {
                  setMessages((prev) => [
                    ...prev,
                    {
                      role: 'assistant',
                      type: 'approval_request',
                      specialist: 'infra',
                      next_nodes: parsed.next_nodes
                    }
                  ])
                } else if (parsed.type === 'error') {
                  throw new Error(parsed.data)
                }
              } catch (jsonErr) {
                console.warn('Failed to parse SSE line JSON:', trimmed, jsonErr)
              }
            }
          }
        }
      }
    } catch (err) {
      console.error('Fetch stream error:', err)
      setMessages((prev) => {
        const updated = [...prev]
        if (updated.length > 0) {
          updated[updated.length - 1] = {
            role: 'assistant',
            content: `⚠️ Connection Error: Failed to communicate with the AgentCore microservice. (Reason: ${err.message})`,
            specialist: null
          }
        }
        return updated
      })
    } finally {
      setLoading(false)
      fetchMetrics()
    }
  }

  const handleApprovalDecision = async (action) => {
    setLoading(true)
    // Remove the approval card from messages to transition cleanly
    setMessages((prev) => {
      const updated = [...prev]
      if (updated.length > 0 && updated[updated.length - 1].type === 'approval_request') {
        updated.pop()
      }
      return updated
    })

    try {
      // Add status message showing user decision
      setMessages((prev) => [
        ...prev,
        { role: 'user', content: `[User Approved Action Execution]` },
        { role: 'assistant', content: '', specialist: 'infra' }
      ])

      const response = await fetch(`${GATEWAY_URL}/chat/approve`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ session_id: sessionId, action: action })
      })

      if (!response.ok) {
        throw new Error(`HTTP error ${response.status}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let done = false
      let accumulatedText = ''

      while (!done) {
        const { value, done: readerDone } = await reader.read()
        done = readerDone
        if (value) {
          const chunkStr = decoder.decode(value, { stream: !done })
          const lines = chunkStr.split('\n')
          
          for (const line of lines) {
            const trimmed = line.trim()
            if (trimmed.startsWith('data: ')) {
              try {
                const parsed = JSON.parse(trimmed.slice(6))
                if (parsed.type === 'token' || parsed.type === 'status') {
                  accumulatedText += parsed.data
                  setMessages((prev) => {
                    const updated = [...prev]
                    if (updated.length > 0) {
                      updated[updated.length - 1] = {
                        ...updated[updated.length - 1],
                        content: accumulatedText
                      }
                    }
                    return updated
                  })
                } else if (parsed.type === 'approval_required') {
                  setMessages((prev) => [
                    ...prev,
                    {
                      role: 'assistant',
                      type: 'approval_request',
                      specialist: 'infra',
                      next_nodes: parsed.next_nodes
                    }
                  ])
                } else if (parsed.type === 'error') {
                  throw new Error(parsed.data)
                }
              } catch (jsonErr) {
                console.warn('Failed to parse approval chunk JSON:', trimmed, jsonErr)
              }
            }
          }
        }
      }
    } catch (err) {
      console.error('Approval stream error:', err)
      setMessages((prev) => {
        const updated = [...prev]
        if (updated.length > 0) {
          updated[updated.length - 1] = {
            role: 'assistant',
            content: `⚠️ Connection Error: Failed to execute approval response. (Reason: ${err.message})`,
            specialist: null
          }
        }
        return updated
      })
    } finally {
      setLoading(false)
      fetchMetrics()
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
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          {/* Tab selector */}
          <div style={{ display: 'flex', gap: '8px', background: 'rgba(0,0,0,0.3)', padding: '4px', borderRadius: '8px', border: '1px solid var(--border-glass)', marginRight: '16px' }}>
            <button 
              onClick={() => setActiveTab('chat')}
              style={{
                background: activeTab === 'chat' ? 'var(--accent-purple)' : 'transparent',
                border: 'none',
                color: '#fff',
                padding: '6px 12px',
                borderRadius: '6px',
                cursor: 'pointer',
                fontSize: '0.8rem',
                fontWeight: '600',
                transition: 'background 0.2s'
              }}
            >
              💬 Chat Console
            </button>
            <button 
              onClick={() => setActiveTab('pipeline')}
              style={{
                background: activeTab === 'pipeline' ? 'var(--accent-purple)' : 'transparent',
                border: 'none',
                color: '#fff',
                padding: '6px 12px',
                borderRadius: '6px',
                cursor: 'pointer',
                fontSize: '0.8rem',
                fontWeight: '600',
                transition: 'background 0.2s'
              }}
              id="pipeline-tab-id"
            >
              📦 Databricks Ingest
            </button>
          </div>
          <div className="status-indicator">
            <div className="status-dot"></div>
            <span>EKS Multi-Tenant Secure</span>
          </div>
          <button 
            onClick={onLogout}
            style={{
              background: 'rgba(239, 68, 68, 0.1)',
              border: '1px solid rgba(239, 68, 68, 0.3)',
              color: '#F87171',
              padding: '6px 12px',
              borderRadius: '6px',
              cursor: 'pointer',
              fontSize: '0.8rem',
              fontWeight: '600',
              transition: 'background 0.2s'
            }}
            onMouseOver={(e) => e.target.style.background = 'rgba(239, 68, 68, 0.2)'}
            onMouseOut={(e) => e.target.style.background = 'rgba(239, 68, 68, 0.1)'}
          >
            Sign Out
          </button>
        </div>
      </header>

      {/* Main Dashboard Panel Grid */}
      {activeTab === 'chat' ? (
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
              <span className="config-label">State Checkpointer</span>
              <span className="badge" style={{ alignSelf: 'flex-start', color: '#34D399', borderColor: 'rgba(52, 211, 153, 0.2)' }}>RDS PostgreSQL</span>
            </div>

            <div className="config-item">
              <span className="config-label">HashiCorp Vault Auth</span>
              <span className="badge" style={{ alignSelf: 'flex-start', color: '#10B981', borderColor: 'rgba(16, 185, 129, 0.2)' }}>Active ServiceAccount</span>
            </div>

            {/* Real-time Prometheus Metrics widget */}
            <div style={{ padding: '12px 0' }}>
              <span className="config-label" style={{ marginBottom: '8px', display: 'block' }}>Prometheus Router Metrics</span>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '0.8rem' }}>
                <div style={{ background: 'rgba(0,0,0,0.2)', padding: '6px 10px', borderRadius: '6px', border: '1px solid var(--border-glass)' }}>
                  <div style={{ color: 'var(--text-secondary)', fontSize: '0.72rem' }}>INFRA ROUTE</div>
                  <div style={{ fontWeight: '700', fontSize: '1.1rem', color: 'var(--accent-cyan)' }}>{metrics.infra}</div>
                </div>
                <div style={{ background: 'rgba(0,0,0,0.2)', padding: '6px 10px', borderRadius: '6px', border: '1px solid var(--border-glass)' }}>
                  <div style={{ color: 'var(--text-secondary)', fontSize: '0.72rem' }}>CODE ROUTE</div>
                  <div style={{ fontWeight: '700', fontSize: '1.1rem', color: 'var(--accent-purple-light)' }}>{metrics.code}</div>
                </div>
                <div style={{ background: 'rgba(0,0,0,0.2)', padding: '6px 10px', borderRadius: '6px', border: '1px solid var(--border-glass)' }}>
                  <div style={{ color: 'var(--text-secondary)', fontSize: '0.72rem' }}>RESEARCH</div>
                  <div style={{ fontWeight: '700', fontSize: '1.1rem', color: '#F472B6' }}>{metrics.research}</div>
                </div>
                <div style={{ background: 'rgba(0,0,0,0.2)', padding: '6px 10px', borderRadius: '6px', border: '1px solid var(--border-glass)' }}>
                  <div style={{ color: 'var(--text-secondary)', fontSize: '0.72rem' }}>TOTAL TOKENS</div>
                  <div style={{ fontWeight: '700', fontSize: '1.1rem', color: '#FBBF24' }}>{metrics.tokens}</div>
                </div>
              </div>
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
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', justifyContent: 'space-between', fontWeight: '600', fontSize: '0.8rem', marginBottom: '6px', color: msg.role === 'user' ? 'var(--accent-purple-light)' : 'var(--accent-cyan)' }}>
                    <span>{msg.role === 'user' ? 'DEVELOPER' : 'CO-ASSISTANT'}</span>
                    {msg.specialist && (
                      <span className="badge badge-purple" style={{ fontSize: '0.65rem', padding: '2px 6px', textTransform: 'uppercase' }}>
                        ⚙️ {msg.specialist} Specialist
                      </span>
                    )}
                  </div>

                  {msg.type === 'approval_request' ? (
                    // Custom Human-in-the-loop interactive card
                    <div style={{
                      background: 'rgba(245, 158, 11, 0.1)',
                      border: '1px solid rgba(245, 158, 11, 0.3)',
                      borderRadius: '8px',
                      padding: '14px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '12px'
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                        <span style={{ fontSize: '1.4rem' }}>🛡️</span>
                        <div>
                          <div style={{ fontWeight: '700', fontSize: '0.9rem', color: '#FBBF24' }}>Infrastructure Security Interrupt</div>
                          <div style={{ fontSize: '0.78rem', color: 'rgba(243, 244, 246, 0.7)' }}>Execution paused before: <code>{msg.next_nodes?.join(', ')}</code></div>
                        </div>
                      </div>
                      <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', lineHeight: '1.4' }}>
                        An infrastructure-modifying action was routed to the <strong>EKS Specialist</strong>. Please verify the target cluster changes before approving execution.
                      </div>
                      <div style={{ display: 'flex', gap: '10px', marginTop: '4px' }}>
                        <button 
                          onClick={() => handleApprovalDecision('approve')}
                          style={{
                            flex: 1,
                            background: 'rgba(16, 185, 129, 0.25)',
                            border: '1px solid #10B981',
                            color: '#34D399',
                            padding: '8px',
                            borderRadius: '6px',
                            cursor: 'pointer',
                            fontWeight: '600',
                            fontSize: '0.82rem',
                            transition: 'background 0.2s'
                          }}
                          onMouseOver={(e) => e.target.style.background = 'rgba(16, 185, 129, 0.4)'}
                          onMouseOut={(e) => e.target.style.background = 'rgba(16, 185, 129, 0.25)'}
                        >
                          Approve Action
                        </button>
                        <button 
                          onClick={() => handleApprovalDecision('reject')}
                          style={{
                            flex: 1,
                            background: 'rgba(239, 68, 68, 0.2)',
                            border: '1px solid #EF4444',
                            color: '#F87171',
                            padding: '8px',
                            borderRadius: '6px',
                            cursor: 'pointer',
                            fontWeight: '600',
                            fontSize: '0.82rem',
                            transition: 'background 0.2s'
                          }}
                          onMouseOver={(e) => e.target.style.background = 'rgba(239, 68, 68, 0.35)'}
                          onMouseOut={(e) => e.target.style.background = 'rgba(239, 68, 68, 0.2)'}
                        >
                          Reject & Terminate
                        </button>
                      </div>
                    </div>
                  ) : msg.role === 'user' ? (
                    <div style={{ fontSize: '0.95rem', lineHeight: '1.5', whiteSpace: 'pre-wrap' }}>
                      {msg.content}
                    </div>
                  ) : (
                    renderMessageContent(msg.content)
                  )}
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
      ) : (
        <main className="dashboard-container" style={{ display: 'grid', gridTemplateColumns: '40% 60%', gap: '20px', height: 'calc(100vh - 100px)', padding: '0 20px 20px', boxSizing: 'border-box' }}>
          {/* Left BRD Ingestion Panel */}
          <section className="glass-panel" style={{ display: 'flex', flexDirection: 'column', gap: '16px', padding: '20px', overflow: 'hidden' }}>
            <div>
              <h2 style={{ fontSize: '1.2rem', margin: '0 0 4px', color: 'var(--text-primary)' }}>1. Business Value Stream BRD</h2>
              <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Input the Value Stream document detailing source schemas</p>
            </div>
            
            <textarea
              value={brdText}
              onChange={(e) => setBrdText(e.target.value)}
              disabled={pipelineLoading}
              style={{
                flex: 1,
                background: 'rgba(0,0,0,0.3)',
                border: '1px solid var(--border-glass)',
                borderRadius: '8px',
                padding: '16px',
                color: '#fff',
                fontFamily: 'var(--font-mono)',
                fontSize: '0.85rem',
                lineHeight: '1.5',
                outline: 'none',
                resize: 'none'
              }}
              placeholder="Paste or write Business Requirement Document (BRD) Value Stream specs here..."
              id="brd-input-id"
            />
            
            <button
              onClick={handleAnalysePipeline}
              disabled={pipelineLoading || !brdText.trim()}
              className="send-button"
              style={{ padding: '12px', borderRadius: '6px', fontWeight: '700', fontSize: '0.9rem', cursor: 'pointer' }}
              id="analyse-pipeline-button"
            >
              {pipelineLoading ? 'Analyzing Ingest Elements...' : 'Generate Source-to-Target Mapping'}
            </button>
          </section>

          {/* Right STM / DAB Bundle Explorer Panel */}
          <section className="glass-panel" style={{ display: 'flex', flexDirection: 'column', gap: '16px', padding: '20px', overflow: 'hidden' }}>
            <div>
              <h2 style={{ fontSize: '1.2rem', margin: '0 0 4px', color: 'var(--text-primary)' }}>2. Target Mapping & Databricks Bundle</h2>
              <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                {pipelineStateStep === 0 && 'Awaiting BRD Ingestion...'}
                {pipelineStateStep === 1 && 'Confirm conformed IBM model alignments before bundle compilation.'}
                {pipelineStateStep === 2 && 'Databricks Asset Bundle (DAB) ready for execution.'}
              </p>
            </div>

            {pipelineError && (
              <div style={{ background: 'rgba(239, 68, 68, 0.1)', border: '1px solid rgba(239, 68, 68, 0.3)', color: '#F87171', padding: '10px 14px', borderRadius: '6px', fontSize: '0.8rem' }}>
                ⚠️ Error: {pipelineError}
              </div>
            )}

            {pipelineLoading && (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', flex: 1, gap: '16px' }}>
                <div className="typing-indicator" style={{ transform: 'scale(1.5)' }}>
                  <span className="typing-dot"></span>
                  <span className="typing-dot"></span>
                  <span className="typing-dot"></span>
                </div>
                <div style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', fontWeight: '600' }} id="pipeline-loading-status">
                  {pipelineStatus}
                </div>
              </div>
            )}

            {!pipelineLoading && pipelineStateStep === 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', flex: 1, color: 'var(--text-secondary)', gap: '12px' }}>
                <span style={{ fontSize: '3rem' }}>📦</span>
                <span>Enter Business Requirements on the left to start pipeline generation.</span>
              </div>
            )}

            {!pipelineLoading && pipelineStateStep === 1 && (
              <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden', gap: '16px' }}>
                {/* Modern Side-by-Side Schema Conformance Preview Card Grid */}
                <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '12px', paddingRight: '4px' }}>
                  {mappingMatrix.map((row, idx) => {
                    const isDirectMatch = (row.source_column === row.target_column) && !row.transformation_rule.includes('HASH');
                    const isTransform = row.transformation_rule.includes('HASH') || row.transformation_rule.includes('CAST');
                    const confidenceColor = isDirectMatch ? '#10B981' : isTransform ? '#F59E0B' : '#EF4444';
                    const confidenceText = isDirectMatch ? 'Direct Pass' : isTransform ? 'Auto-Casted' : 'Override Needed';

                    return (
                      <div 
                        key={idx} 
                        style={{ 
                          display: 'grid', 
                          gridTemplateColumns: '1fr 120px 1fr', 
                          alignItems: 'center', 
                          gap: '12px', 
                          padding: '12px', 
                          border: '1px solid var(--border-glass)',
                          borderRadius: '8px',
                          background: 'rgba(255, 255, 255, 0.02)'
                        }}
                        className="mapping-row-item"
                      >
                        {/* Bronze Source Column */}
                        <div style={{ background: 'rgba(239, 68, 68, 0.04)', border: '1px solid rgba(239, 68, 68, 0.1)', padding: '8px 10px', borderRadius: '6px' }}>
                          <div style={{ fontSize: '0.62rem', color: '#F87171', fontWeight: '700', textTransform: 'uppercase', marginBottom: '2px' }}>Bronze Column</div>
                          <div style={{ fontSize: '0.85rem', fontWeight: '700', color: '#fff' }}>{row.source_column}</div>
                          <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>{row.source_table}</div>
                        </div>

                        {/* Transition Logic Indicator */}
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center', gap: '2px' }}>
                          <div style={{ fontSize: '1rem', color: confidenceColor, fontWeight: '700' }}>➔</div>
                          <span style={{ fontSize: '0.62rem', padding: '1px 6px', borderRadius: '10px', background: `${confidenceColor}22`, color: confidenceColor, fontWeight: '700', whiteSpace: 'nowrap' }}>
                            {confidenceText}
                          </span>
                          <span style={{ fontSize: '0.65rem', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', maxWidth: '110px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {row.transformation_rule || 'Direct Pass'}
                          </span>
                        </div>

                        {/* Silver Conformed Target Column */}
                        <div style={{ background: 'rgba(6, 182, 212, 0.04)', border: '1px solid rgba(6, 182, 212, 0.1)', padding: '8px 10px', borderRadius: '6px' }}>
                          <div style={{ fontSize: '0.62rem', color: 'var(--accent-cyan)', fontWeight: '700', textTransform: 'uppercase', marginBottom: '2px' }}>Silver Target Attribute</div>
                          <div style={{ fontSize: '0.85rem', fontWeight: '700', color: '#fff' }}>
                            <input 
                              type="text" 
                              value={row.target_column || ''} 
                              onChange={(e) => handleMappingCellChange(idx, 'target_column', e.target.value)}
                              style={{ background: 'transparent', border: 'none', borderBottom: '1px solid var(--border-glass)', color: '#fff', width: '100%', outline: 'none', fontSize: '0.85rem', fontWeight: '700' }}
                            />
                          </div>
                          <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>{row.target_table}</div>
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* HITL Buttons */}
                <div style={{ display: 'flex', gap: '12px' }}>
                  <button
                    onClick={handleApprovePipeline}
                    className="send-button"
                    style={{ flex: 1, padding: '12px', borderRadius: '6px', fontWeight: '700', cursor: 'pointer' }}
                    id="approve-pipeline-id"
                  >
                    Approve & Compile Bundle
                  </button>
                  <button
                    onClick={handleRejectPipeline}
                    style={{
                      flex: 1,
                      background: 'rgba(239, 68, 68, 0.1)',
                      border: '1px solid rgba(239, 68, 68, 0.3)',
                      color: '#F87171',
                      padding: '12px',
                      borderRadius: '6px',
                      fontWeight: '700',
                      cursor: 'pointer',
                      transition: 'background 0.2s'
                    }}
                    onMouseOver={(e) => e.target.style.background = 'rgba(239, 68, 68, 0.2)'}
                    onMouseOut={(e) => e.target.style.background = 'rgba(239, 68, 68, 0.1)'}
                  >
                    Reject Mapping
                  </button>
                </div>
              </div>
            )}

            {!pipelineLoading && pipelineStateStep === 2 && (
              <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden', gap: '16px' }}>
                {/* File selectors */}
                <div style={{ display: 'flex', gap: '6px', overflowX: 'auto', borderBottom: '1px solid var(--border-glass)', paddingBottom: '8px' }}>
                  {Object.keys(generatedFiles).map((filename) => (
                    <button
                      key={filename}
                      onClick={() => setSelectedFileTab(filename)}
                      style={{
                        background: selectedFileTab === filename ? 'var(--accent-purple)' : 'rgba(255,255,255,0.02)',
                        border: '1px solid var(--border-glass)',
                        color: '#fff',
                        padding: '6px 12px',
                        borderRadius: '6px',
                        cursor: 'pointer',
                        fontSize: '0.78rem',
                        fontWeight: '600',
                        whiteSpace: 'nowrap'
                      }}
                      className="bundle-file-tab"
                    >
                      📄 {filename}
                    </button>
                  ))}
                </div>

                {/* File Editor View */}
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', position: 'relative' }}>
                  <textarea
                    readOnly
                    value={generatedFiles[selectedFileTab] || ''}
                    style={{
                      flex: 1,
                      background: 'rgba(0,0,0,0.4)',
                      border: '1px solid var(--border-glass)',
                      borderRadius: '8px',
                      padding: '16px',
                      color: 'var(--accent-cyan)',
                      fontFamily: 'var(--font-mono)',
                      fontSize: '0.82rem',
                      lineHeight: '1.5',
                      outline: 'none',
                      resize: 'none',
                      overflowY: 'auto'
                    }}
                    id="bundle-editor-id"
                  />
                  <button
                    onClick={() => navigator.clipboard.writeText(generatedFiles[selectedFileTab] || '')}
                    style={{
                      position: 'absolute',
                      right: '12px',
                      top: '12px',
                      background: 'rgba(0,0,0,0.6)',
                      border: '1px solid var(--border-glass)',
                      color: '#fff',
                      padding: '6px 10px',
                      borderRadius: '4px',
                      cursor: 'pointer',
                      fontSize: '0.75rem',
                      fontWeight: '600'
                    }}
                  >
                    Copy Code
                  </button>
                </div>

                {/* Pipeline Run Execution Controls */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border-glass)', padding: '12px', borderRadius: '8px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: '0.85rem', fontWeight: '600' }}>🚀 Medallion Pipeline Ingest Execution</span>
                    
                    <button
                      onClick={() => {
                        // Extract target table base entity name dynamically (e.g. bronze_customer -> customer)
                        const rawTarget = mappingMatrix[0]?.target_table || 'customer';
                        const entityName = rawTarget.toLowerCase().includes('customer') ? 'customer' : 'transaction';
                        handleRunPipeline(entityName);
                      }}
                      disabled={pipelineRunLoading || activePipelineRunStatus === 'complete'}
                      className="send-button"
                      style={{ padding: '8px 16px', borderRadius: '4px', fontSize: '0.8rem', fontWeight: '700', cursor: 'pointer' }}
                      id="run-pipeline-id"
                    >
                      {pipelineRunLoading ? 'Running Conformance...' : activePipelineRunStatus === 'complete' ? 'Run Complete' : 'Run Ingestion Pipeline'}
                    </button>
                  </div>

                  {/* Execution Progress Timeline */}
                  {activePipelineRunStatus && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', borderTop: '1px solid var(--border-glass)', paddingTop: '8px', marginTop: '4px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.78rem' }}>
                        <span style={{ color: activePipelineRunStatus === 'bronze' || activePipelineRunStatus === 'silver' || activePipelineRunStatus === 'complete' ? 'var(--accent-cyan)' : 'var(--text-secondary)' }}>
                          {activePipelineRunStatus === 'bronze' ? '● ' : '✓ '} 📥 Ingestion (S3)
                        </span>
                        <span style={{ color: activePipelineRunStatus === 'silver' || activePipelineRunStatus === 'complete' ? 'var(--accent-purple-light)' : 'var(--text-secondary)' }}>
                          {activePipelineRunStatus === 'silver' ? '● ' : activePipelineRunStatus === 'complete' ? '✓ ' : '○ '} ⚙️ Conformance
                        </span>
                        <span style={{ color: activePipelineRunStatus === 'complete' ? '#10B981' : 'var(--text-secondary)' }}>
                          {activePipelineRunStatus === 'complete' ? '✓ ' : '○ '} 💎 DB Load
                        </span>
                      </div>

                      {pipelineRunResult && (
                        <div style={{ background: 'rgba(16, 185, 129, 0.05)', border: '1px solid rgba(16, 185, 129, 0.2)', padding: '8px', borderRadius: '6px', fontSize: '0.75rem', color: '#6EE7B7' }} id="pipeline-run-result-id">
                          🎉 Ingested <strong>{pipelineRunResult.records_processed}</strong> records successfully into <strong>{pipelineRunResult.silver_table}</strong> table!
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* Reset button */}
                <button
                  onClick={() => {
                    setPipelineStateStep(0);
                    setActivePipelineRunStatus('');
                    setPipelineRunResult(null);
                  }}
                  style={{
                    background: 'rgba(255,255,255,0.05)',
                    border: '1px solid var(--border-glass)',
                    color: '#fff',
                    padding: '12px',
                    borderRadius: '6px',
                    fontWeight: '700',
                    cursor: 'pointer',
                    transition: 'background 0.2s'
                  }}
                  onMouseOver={(e) => e.target.style.background = 'rgba(255,255,255,0.1)'}
                  onMouseOut={(e) => e.target.style.background = 'rgba(255,255,255,0.05)'}
                >
                  Create Another Pipeline
                </button>
              </div>
            )}
          </section>
        </main>
      )}
    </div>
  )
}

function AuthScreen({ onLoginSuccess }) {
  const [authMode, setAuthMode] = useState('login') // 'login', 'signup', 'verify'
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [verifyCode, setVerifyCode] = useState('')
  const [errorMsg, setErrorMsg] = useState('')
  const [loading, setLoading] = useState(false)
  const [verifyEmail, setVerifyEmail] = useState('')

  const handleCognitoRequest = async (target, payload) => {
    const response = await fetch('https://cognito-idp.us-east-1.amazonaws.com/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-amz-json-1.1',
        'X-Amz-Target': `AWSCognitoIdentityProviderService.${target}`
      },
      body: JSON.stringify(payload)
    })
    const data = await response.json()
    if (!response.ok) {
      throw new Error(data.message || 'Operation failed')
    }
    return data
  }

  const onSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setErrorMsg('')

    try {
      if (authMode === 'login') {
        const data = await handleCognitoRequest('InitiateAuth', {
          ClientId: '5f6s8b6ur4bokfnucs98ieds3p',
          AuthFlow: 'USER_PASSWORD_AUTH',
          AuthParameters: {
            USERNAME: email,
            PASSWORD: password
          }
        })
        const token = data.AuthenticationResult.IdToken
        onLoginSuccess(token)
      } else if (authMode === 'signup') {
        await handleCognitoRequest('SignUp', {
          ClientId: '5f6s8b6ur4bokfnucs98ieds3p',
          Username: email,
          Password: password,
          UserAttributes: [{ Name: 'email', Value: email }]
        })
        setVerifyEmail(email)
        setAuthMode('verify')
        setErrorMsg('Sign up successful! Please check your email for a verification code.')
      } else if (authMode === 'verify') {
        await handleCognitoRequest('ConfirmSignUp', {
          ClientId: '5f6s8b6ur4bokfnucs98ieds3p',
          Username: verifyEmail,
          ConfirmationCode: verifyCode
        })
        setAuthMode('login')
        setErrorMsg('Email verified! You can now sign in with your password.')
      }
    } catch (err) {
      setErrorMsg(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: 'radial-gradient(circle at top left, #1e1b4b 0%, #030712 100%)',
      fontFamily: 'var(--font-sans)',
      padding: '20px'
    }}>
      <div className="glass-panel animate-slide-up" style={{
        maxWidth: '420px',
        width: '100%',
        padding: '30px',
        display: 'flex',
        flexDirection: 'column',
        gap: '24px',
        border: '1px solid rgba(255, 255, 255, 0.08)'
      }}>
        {/* Logo */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px' }}>
          <svg width="36" height="36" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M12 2L2 22H22L12 2Z" stroke="url(#auth-grad)" strokeWidth="2.5" strokeLinejoin="round"/>
            <defs>
              <linearGradient id="auth-grad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor="#7C3AED" />
                <stop offset="100%" stopColor="#06B6D4" />
              </linearGradient>
            </defs>
          </svg>
          <h2 style={{ margin: '8px 0 2px', fontSize: '1.6rem', fontWeight: '700' }}>
            Antigravity <span className="text-gradient">Console</span>
          </h2>
          <p style={{ margin: 0, fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
            {authMode === 'login' && 'Sign in to access secure EKS workspace'}
            {authMode === 'signup' && 'Create developer account'}
            {authMode === 'verify' && `Verify email code for ${verifyEmail}`}
          </p>
        </div>

        {errorMsg && (
          <div style={{
            background: errorMsg.includes('successful') || errorMsg.includes('verified') ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)',
            border: errorMsg.includes('successful') || errorMsg.includes('verified') ? '1px solid rgba(16, 185, 129, 0.3)' : '1px solid rgba(239, 68, 68, 0.3)',
            color: errorMsg.includes('successful') || errorMsg.includes('verified') ? '#34D399' : '#F87171',
            padding: '10px 14px',
            borderRadius: '6px',
            fontSize: '0.8rem',
            lineHeight: '1.4'
          }}>
            {errorMsg}
          </div>
        )}

        <form onSubmit={onSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {authMode !== 'verify' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label style={{ fontSize: '0.75rem', fontWeight: '600', color: 'var(--text-secondary)' }}>EMAIL ADDRESS</label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                style={{
                  background: 'rgba(255, 255, 255, 0.05)',
                  border: '1px solid var(--border-glass)',
                  borderRadius: '6px',
                  padding: '10px 12px',
                  color: '#fff',
                  outline: 'none',
                  fontSize: '0.9rem'
                }}
              />
            </div>
          )}

          {authMode === 'verify' ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label style={{ fontSize: '0.75rem', fontWeight: '600', color: 'var(--text-secondary)' }}>VERIFICATION CODE</label>
              <input
                type="text"
                required
                placeholder="Enter 6-digit code"
                value={verifyCode}
                onChange={(e) => setVerifyCode(e.target.value)}
                style={{
                  background: 'rgba(255, 255, 255, 0.05)',
                  border: '1px solid var(--border-glass)',
                  borderRadius: '6px',
                  padding: '10px 12px',
                  color: '#fff',
                  outline: 'none',
                  fontSize: '0.9rem',
                  textAlign: 'center',
                  letterSpacing: '4px'
                }}
              />
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label style={{ fontSize: '0.75rem', fontWeight: '600', color: 'var(--text-secondary)' }}>PASSWORD</label>
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                style={{
                  background: 'rgba(255, 255, 255, 0.05)',
                  border: '1px solid var(--border-glass)',
                  borderRadius: '6px',
                  padding: '10px 12px',
                  color: '#fff',
                  outline: 'none',
                  fontSize: '0.9rem'
                }}
              />
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="send-button"
            style={{
              padding: '12px',
              borderRadius: '6px',
              fontWeight: '700',
              cursor: 'pointer',
              marginTop: '8px'
            }}
          >
            {loading ? 'Processing...' : authMode === 'login' ? 'Sign In' : authMode === 'signup' ? 'Create Account' : 'Verify Email'}
          </button>
        </form>

        <div style={{ textAlign: 'center', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
          {authMode === 'login' ? (
            <span>
              Don't have an account?{' '}
              <a href="#" onClick={() => { setAuthMode('signup'); setErrorMsg(''); }} style={{ color: 'var(--accent-cyan)', textDecoration: 'none', fontWeight: '600' }}>
                Sign Up
              </a>
            </span>
          ) : (
            <span>
              Already have an account?{' '}
              <a href="#" onClick={() => { setAuthMode('login'); setErrorMsg(''); }} style={{ color: 'var(--accent-purple-light)', textDecoration: 'none', fontWeight: '600' }}>
                Sign In
              </a>
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

function App() {
  const [token, setToken] = useState(() => localStorage.getItem('agent_jwt_token') || null)

  const handleLoginSuccess = (newToken) => {
    localStorage.setItem('agent_jwt_token', newToken)
    setToken(newToken)
  }

  const handleLogout = () => {
    localStorage.removeItem('agent_jwt_token')
    setToken(null)
  }

  if (!token) {
    return <AuthScreen onLoginSuccess={handleLoginSuccess} />
  }

  return (
    <CopilotKit 
      runtimeUrl={`${GATEWAY_URL}/v1/copilotkit`}
      agents__unsafe_dev_only={{
        default: {
          subscribe: () => ({ unsubscribe: () => {} }),
          messages: [],
          setState: () => {},
          isRunning: false,
          state: {}
        }
      }}
    >
      <DashboardContent token={token} onLogout={handleLogout} />
    </CopilotKit>
  )
}

export default App
