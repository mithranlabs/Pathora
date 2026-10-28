import React, { useState, useEffect } from 'react'

const API_BASE = '/api'

export default function App() {
  const [health, setHealth] = useState(null)
  const [status, setStatus] = useState(null)
  const [profile, setProfile] = useState(null)
  const [alerts, setAlerts] = useState([])
  const [totalAlerts, setTotalAlerts] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(25)
  const [severityFilter, setSeverityFilter] = useState('all')
  const [serviceFilter, setServiceFilter] = useState('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [activeTab, setActiveTab] = useState('incidents') // 'incidents' | 'alerts' | 'scoreboard' | 'recon'
  const [loading, setLoading] = useState(false)
  const [filePathInput, setFilePathInput] = useState('')
  const [errorMsg, setErrorMsg] = useState(null)
  const [successMsg, setSuccessMsg] = useState(null)
  const [expandedAlert, setExpandedAlert] = useState(null)

  // Milestone 2 Correlation State
  const [activeRun, setActiveRun] = useState(null)
  const [incidents, setIncidents] = useState([])
  const [unattachedAlerts, setUnattachedAlerts] = useState([])
  const [selectedIncident, setSelectedIncident] = useState(null)
  const [incidentAlerts, setIncidentAlerts] = useState([])
  const [showConfigDrawer, setShowConfigDrawer] = useState(false)
  const [showUnattachedLane, setShowUnattachedLane] = useState(false)
  const [selectedEdge, setSelectedEdge] = useState(null)

  // Correlation Config Form
  const [corrAlgo, setCorrAlgo] = useState('improved')
  const [timeWindowSec, setTimeWindowSec] = useState(900)
  const [minPairScore, setMinPairScore] = useState(0.45)
  const [maxSpanSec, setMaxSpanSec] = useState(3600)

  // Fetch initial data
  useEffect(() => {
    checkHealth()
    fetchDatasetStatus()
    fetchCorrelationData()
    fetchAlerts()
  }, [])

  // Refetch alerts on filter or page change
  useEffect(() => {
    if (activeTab === 'alerts') {
      fetchAlerts()
    }
  }, [page, pageSize, severityFilter, serviceFilter, searchQuery, activeTab])

  const checkHealth = async () => {
    try {
      const res = await fetch(`${API_BASE}/health`)
      if (res.ok) {
        const data = await res.json()
        setHealth(data)
      }
    } catch (err) {
      console.error('Health check failed:', err)
      setHealth({ status: 'disconnected' })
    }
  }

  const fetchDatasetStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/dataset/status`)
      if (res.ok) {
        const data = await res.json()
        setStatus(data)
      }
    } catch (err) {
      console.error('Status fetch failed:', err)
    }
  }

  const fetchProfile = async () => {
    try {
      const res = await fetch(`${API_BASE}/dataset/profile`)
      if (res.ok) {
        const data = await res.json()
        setProfile(data)
      }
    } catch (err) {
      console.error('Profile fetch failed:', err)
    }
  }

  const fetchCorrelationData = async () => {
    try {
      const runRes = await fetch(`${API_BASE}/correlation/runs/active`)
      if (runRes.ok) {
        const runData = await runRes.json()
        setActiveRun(runData)
      }

      const incRes = await fetch(`${API_BASE}/correlation/incidents`)
      if (incRes.ok) {
        const incData = await incRes.json()
        setIncidents(incData)
        if (incData.length > 0 && !selectedIncident) {
          fetchIncidentDetail(incData[0].incident_id)
        }
      }

      const unRes = await fetch(`${API_BASE}/correlation/unattached`)
      if (unRes.ok) {
        const unData = await unRes.json()
        setUnattachedAlerts(unData)
      }
    } catch (err) {
      console.error('Failed to fetch correlation data:', err)
    }
  }

  const fetchIncidentDetail = async (incidentId) => {
    try {
      const res = await fetch(`${API_BASE}/correlation/incidents/${incidentId}`)
      if (res.ok) {
        const data = await res.json()
        setSelectedIncident(data.incident)
        setIncidentAlerts(data.alerts || [])
        setSelectedEdge(null)
      }
    } catch (err) {
      console.error('Failed to fetch incident detail:', err)
    }
  }

  const fetchAlerts = async () => {
    setLoading(true)
    setErrorMsg(null)
    try {
      const params = new URLSearchParams({
        page: page.toString(),
        page_size: pageSize.toString(),
      })
      if (severityFilter !== 'all') params.append('severity', severityFilter)
      if (serviceFilter !== 'all') params.append('service', serviceFilter)
      if (searchQuery.trim()) params.append('search', searchQuery.trim())

      const res = await fetch(`${API_BASE}/alerts?${params.toString()}`)
      if (res.ok) {
        const data = await res.json()
        setAlerts(data.alerts || [])
        setTotalAlerts(data.total || 0)
      } else {
        const err = await res.json()
        setErrorMsg(err.detail || 'Failed to fetch alerts')
      }
    } catch (err) {
      setErrorMsg(`Failed to connect to backend: ${err.message}`)
    } finally {
      setLoading(false)
    }
  }

  const runCorrelationEngine = async () => {
    setLoading(true)
    setErrorMsg(null)
    setSuccessMsg(null)
    try {
      const payload = {
        algorithm: corrAlgo,
        time_window_sec: Number(timeWindowSec),
        min_pair_score: Number(minPairScore),
        max_cluster_span_sec: Number(maxSpanSec),
      }
      const res = await fetch(`${API_BASE}/correlation/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
      if (res.ok) {
        const runData = await res.json()
        setActiveRun(runData)
        setSuccessMsg(`Correlation execution complete: ${runData.total_incidents} incident groups discovered (${runData.total_unattached_alerts} unattached).`)
        await fetchCorrelationData()
      } else {
        const err = await res.json()
        setErrorMsg(err.detail || 'Correlation execution failed')
      }
    } catch (err) {
      setErrorMsg(`Error running correlation: ${err.message}`)
    } finally {
      setLoading(false)
    }
  }

  const loadSynthetic = async (scale) => {
    setLoading(true)
    setErrorMsg(null)
    setSuccessMsg(null)
    try {
      const res = await fetch(`${API_BASE}/dataset/load-synthetic`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scale, seed: 42 })
      })
      if (res.ok) {
        const data = await res.json()
        setStatus(data)
        setSuccessMsg(`Loaded ${scale.toUpperCase()} synthetic dataset (${data.total_alerts} alerts).`)
        setPage(1)
        setSelectedIncident(null)
        await fetchCorrelationData()
        await fetchAlerts()
        await fetchProfile()
      } else {
        const err = await res.json()
        setErrorMsg(err.detail || 'Failed to load synthetic dataset')
      }
    } catch (err) {
      setErrorMsg(`Error loading synthetic dataset: ${err.message}`)
    } finally {
      setLoading(false)
    }
  }

  const loadCustomFile = async () => {
    if (!filePathInput.trim()) return
    setLoading(true)
    setErrorMsg(null)
    setSuccessMsg(null)
    try {
      const res = await fetch(`${API_BASE}/dataset/load-file`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_path: filePathInput.trim() })
      })
      if (res.ok) {
        const data = await res.json()
        setStatus(data)
        setSuccessMsg(`Successfully ingested ${filePathInput.trim()} (${data.total_alerts} records).`)
        setPage(1)
        setSelectedIncident(null)
        await fetchCorrelationData()
        await fetchAlerts()
        await fetchProfile()
      } else {
        const err = await res.json()
        setErrorMsg(err.detail || 'Failed to ingest custom file')
      }
    } catch (err) {
      setErrorMsg(`Error ingesting file: ${err.message}`)
    } finally {
      setLoading(false)
    }
  }

  const handleTabSwitch = (tab) => {
    setActiveTab(tab)
    if (tab === 'recon') fetchProfile()
    if (tab === 'incidents' || tab === 'scoreboard') fetchCorrelationData()
  }

  const totalPages = Math.max(1, Math.ceil(totalAlerts / pageSize))

  const getSeverityBadge = (sev) => {
    const s = (sev || 'unknown').toLowerCase()
    let bg = 'rgba(148, 163, 184, 0.15)'
    let text = '#94a3b8'
    let border = 'rgba(148, 163, 184, 0.4)'

    if (s === 'critical') {
      bg = 'var(--sev-critical-bg)'
      text = 'var(--sev-critical-text)'
      border = 'var(--sev-critical-border)'
    } else if (s === 'error') {
      bg = 'var(--sev-error-bg)'
      text = 'var(--sev-error-text)'
      border = 'var(--sev-error-border)'
    } else if (s === 'warning') {
      bg = 'var(--sev-warning-bg)'
      text = 'var(--sev-warning-text)'
      border = 'var(--sev-warning-border)'
    } else if (s === 'info') {
      bg = 'var(--sev-info-bg)'
      text = 'var(--sev-info-text)'
      border = 'var(--sev-info-border)'
    }

    return (
      <span style={{
        backgroundColor: bg,
        color: text,
        border: `1px solid ${border}`,
        padding: '2px 8px',
        borderRadius: '6px',
        fontSize: '11px',
        fontWeight: '700',
        textTransform: 'uppercase',
        letterSpacing: '0.05em',
        display: 'inline-block'
      }}>
        {s}
      </span>
    )
  }

  return (
    <div style={{ maxWidth: '1440px', margin: '0 auto', padding: '24px 20px 60px' }}>
      {/* Top Header */}
      <header style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: '24px',
        paddingBottom: '20px',
        borderBottom: '1px solid var(--border-color)'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{
            width: '40px',
            height: '40px',
            borderRadius: '10px',
            background: 'linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 0 18px rgba(59, 130, 246, 0.45)'
          }}>
            <span style={{ fontSize: '22px', color: '#fff' }}>⚡</span>
          </div>
          <div>
            <h1 style={{ fontSize: '24px', fontWeight: '800', letterSpacing: '-0.02em', background: 'linear-gradient(to right, #f1f5f9, #94a3b8)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
              Pathora
            </h1>
            <p style={{ fontSize: '13px', color: 'var(--text-muted)', fontWeight: '500' }}>
              From alert noise to incident clarity.
            </p>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {status && (
            <div style={{
              backgroundColor: status.is_synthetic ? 'rgba(139, 92, 246, 0.15)' : 'rgba(16, 185, 129, 0.15)',
              border: `1px solid ${status.is_synthetic ? 'rgba(139, 92, 246, 0.4)' : 'rgba(16, 185, 129, 0.4)'}`,
              padding: '6px 14px',
              borderRadius: '20px',
              display: 'flex',
              alignItems: 'center',
              gap: '8px'
            }}>
              <span style={{
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                backgroundColor: status.is_synthetic ? '#a78bfa' : '#34d399',
                boxShadow: `0 0 8px ${status.is_synthetic ? '#a78bfa' : '#34d399'}`
              }} />
              <span style={{ fontSize: '12px', fontWeight: '700', color: status.is_synthetic ? '#ddd6fe' : '#a7f3d0' }}>
                {status.is_synthetic ? 'SYNTHETIC DATA (Pre-competition Dev Mode)' : 'OFFICIAL CHALLENGE DATA'}
              </span>
            </div>
          )}

          <div style={{
            backgroundColor: health?.status === 'ok' ? 'rgba(16, 185, 129, 0.1)' : 'rgba(244, 63, 94, 0.1)',
            border: `1px solid ${health?.status === 'ok' ? 'rgba(16, 185, 129, 0.3)' : 'rgba(244, 63, 94, 0.3)'}`,
            padding: '6px 12px',
            borderRadius: '20px',
            fontSize: '12px',
            color: health?.status === 'ok' ? '#34d399' : '#f87171',
            display: 'flex',
            alignItems: 'center',
            gap: '6px'
          }}>
            <span>●</span> {health?.status === 'ok' ? 'Backend Ready (v0.1.0)' : 'Backend Offline'}
          </div>
        </div>
      </header>

      {/* Notifications */}
      {errorMsg && (
        <div style={{
          backgroundColor: 'rgba(244, 63, 94, 0.15)',
          border: '1px solid rgba(244, 63, 94, 0.4)',
          color: '#fda4af',
          padding: '12px 16px',
          borderRadius: '8px',
          marginBottom: '20px',
          fontSize: '13px'
        }}>
          ⚠️ {errorMsg}
        </div>
      )}
      {successMsg && (
        <div style={{
          backgroundColor: 'rgba(16, 185, 129, 0.15)',
          border: '1px solid rgba(16, 185, 129, 0.4)',
          color: '#6ee7b7',
          padding: '12px 16px',
          borderRadius: '8px',
          marginBottom: '20px',
          fontSize: '13px'
        }}>
          ✅ {successMsg}
        </div>
      )}

      {/* Dataset & Correlation Actions Bar */}
      <section className="glass-panel" style={{ padding: '16px 20px', marginBottom: '24px' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <button
              onClick={runCorrelationEngine}
              disabled={loading}
              style={{
                backgroundColor: 'linear-gradient(135deg, #2563eb, #7c3aed)',
                background: '#3b82f6',
                color: '#fff',
                border: 'none',
                padding: '8px 18px',
                borderRadius: '8px',
                fontSize: '13px',
                fontWeight: '700',
                boxShadow: '0 0 14px rgba(59, 130, 246, 0.4)'
              }}
            >
              🚀 Run Correlation ({corrAlgo === 'improved' ? 'Architecture B' : 'Baseline'})
            </button>

            <button
              onClick={() => setShowConfigDrawer(!showConfigDrawer)}
              style={{
                backgroundColor: showConfigDrawer ? 'var(--bg-tertiary)' : 'transparent',
                color: 'var(--text-muted)',
                border: '1px solid var(--border-color)',
                padding: '8px 12px',
                borderRadius: '8px',
                fontSize: '12px',
                fontWeight: '600'
              }}
            >
              ⚙️ Engine Tuning
            </button>

            <button
              onClick={() => loadSynthetic('small')}
              disabled={loading}
              style={{
                backgroundColor: 'rgba(59, 130, 246, 0.15)',
                color: '#93c5fd',
                border: '1px solid rgba(59, 130, 246, 0.3)',
                padding: '8px 12px',
                borderRadius: '8px',
                fontSize: '12px',
                fontWeight: '600'
              }}
            >
              Small Fixture (41)
            </button>

            <button
              onClick={() => loadSynthetic('eval')}
              disabled={loading}
              style={{
                backgroundColor: 'rgba(139, 92, 246, 0.15)',
                color: '#c4b5fd',
                border: '1px solid rgba(139, 92, 246, 0.3)',
                padding: '8px 12px',
                borderRadius: '8px',
                fontSize: '12px',
                fontWeight: '600'
              }}
            >
              Eval Fixture (~245)
            </button>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <input
              type="text"
              placeholder="Path to CSV / JSON / JSONL..."
              value={filePathInput}
              onChange={(e) => setFilePathInput(e.target.value)}
              style={{
                backgroundColor: 'var(--bg-secondary)',
                border: '1px solid var(--border-color)',
                color: '#fff',
                padding: '8px 12px',
                borderRadius: '8px',
                fontSize: '12px',
                width: '260px'
              }}
            />
            <button
              onClick={loadCustomFile}
              disabled={loading || !filePathInput.trim()}
              style={{
                backgroundColor: 'var(--bg-tertiary)',
                color: '#fff',
                border: '1px solid var(--border-color)',
                padding: '8px 12px',
                borderRadius: '8px',
                fontSize: '12px',
                fontWeight: '600'
              }}
            >
              Ingest
            </button>
          </div>
        </div>

        {/* Engine Tuning Drawer */}
        {showConfigDrawer && (
          <div style={{
            marginTop: '16px',
            paddingTop: '16px',
            borderTop: '1px solid var(--border-color)',
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: '14px'
          }}>
            <div>
              <label style={{ fontSize: '11px', textTransform: 'uppercase', color: 'var(--text-faint)', fontWeight: '700' }}>Algorithm</label>
              <select
                value={corrAlgo}
                onChange={(e) => setCorrAlgo(e.target.value)}
                style={{ width: '100%', marginTop: '4px', padding: '6px 10px', backgroundColor: 'var(--bg-secondary)', color: '#fff', border: '1px solid var(--border-color)', borderRadius: '6px', fontSize: '12px' }}
              >
                <option value="improved">Architecture B (Weighted Graph + Constrained Clustering)</option>
                <option value="baseline">Architecture A (Deterministic Fingerprint Baseline)</option>
              </select>
            </div>

            <div>
              <label style={{ fontSize: '11px', textTransform: 'uppercase', color: 'var(--text-faint)', fontWeight: '700' }}>Time Gate Window (sec)</label>
              <input
                type="number"
                value={timeWindowSec}
                onChange={(e) => setTimeWindowSec(e.target.value)}
                style={{ width: '100%', marginTop: '4px', padding: '6px 10px', backgroundColor: 'var(--bg-secondary)', color: '#fff', border: '1px solid var(--border-color)', borderRadius: '6px', fontSize: '12px' }}
              />
            </div>

            <div>
              <label style={{ fontSize: '11px', textTransform: 'uppercase', color: 'var(--text-faint)', fontWeight: '700' }}>Min Pair Score Threshold</label>
              <input
                type="number"
                step="0.05"
                min="0.1"
                max="0.9"
                value={minPairScore}
                onChange={(e) => setMinPairScore(e.target.value)}
                style={{ width: '100%', marginTop: '4px', padding: '6px 10px', backgroundColor: 'var(--bg-secondary)', color: '#fff', border: '1px solid var(--border-color)', borderRadius: '6px', fontSize: '12px' }}
              />
            </div>

            <div>
              <label style={{ fontSize: '11px', textTransform: 'uppercase', color: 'var(--text-faint)', fontWeight: '700' }}>Max Cluster Span Cap (sec)</label>
              <input
                type="number"
                value={maxSpanSec}
                onChange={(e) => setMaxSpanSec(e.target.value)}
                style={{ width: '100%', marginTop: '4px', padding: '6px 10px', backgroundColor: 'var(--bg-secondary)', color: '#fff', border: '1px solid var(--border-color)', borderRadius: '6px', fontSize: '12px' }}
              />
            </div>
          </div>
        )}
      </section>

      {/* KPI Cards Summary */}
      {activeRun && (
        <section style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
          gap: '14px',
          marginBottom: '24px'
        }}>
          {/* Card 1: Discovered Incidents */}
          <div className="glass-panel" style={{ padding: '16px' }}>
            <div style={{ fontSize: '11px', textTransform: 'uppercase', color: 'var(--text-faint)', fontWeight: '700' }}>
              Discovered Incidents
            </div>
            <div style={{ fontSize: '26px', fontWeight: '800', marginTop: '4px', color: '#60a5fa' }}>
              {activeRun.total_incidents}
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
              {activeRun.tentative_incidents_count > 0 ? `${activeRun.tentative_incidents_count} tentative` : 'High-confidence clustering'}
            </div>
          </div>

          {/* Card 2: Notification Reduction */}
          <div className="glass-panel" style={{ padding: '16px' }}>
            <div style={{ fontSize: '11px', textTransform: 'uppercase', color: 'var(--text-faint)', fontWeight: '700' }}>
              Noise Reduction
            </div>
            <div style={{ fontSize: '26px', fontWeight: '800', marginTop: '4px', color: '#34d399' }}>
              {(activeRun.notification_reduction_rate * 100).toFixed(1)}%
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
              {activeRun.total_input_alerts} alerts → {activeRun.total_incidents + activeRun.total_unattached_alerts} notifications
            </div>
          </div>

          {/* Card 3: Unattached Alerts */}
          <div className="glass-panel" style={{ padding: '16px' }}>
            <div style={{ fontSize: '11px', textTransform: 'uppercase', color: 'var(--text-faint)', fontWeight: '700' }}>
              Unattached Singletons
            </div>
            <div style={{ fontSize: '26px', fontWeight: '800', marginTop: '4px', color: '#fbbf24' }}>
              {activeRun.total_unattached_alerts}
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
              Retained in unattached lane
            </div>
          </div>

          {/* Card 4: Swallow Rate */}
          <div className="glass-panel" style={{ padding: '16px' }}>
            <div style={{ fontSize: '11px', textTransform: 'uppercase', color: 'var(--text-faint)', fontWeight: '700' }}>
              Swallow / False-Merge Rate
            </div>
            <div style={{ fontSize: '26px', fontWeight: '800', marginTop: '4px', color: (activeRun.evaluation?.swallow_rate || 0) > 0 ? '#f87171' : '#34d399' }}>
              {activeRun.evaluation?.available ? `${((activeRun.evaluation.swallow_rate || 0) * 100).toFixed(1)}%` : 'UNAVAILABLE'}
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
              {activeRun.evaluation?.available ? 'Cross-incident false merges' : 'Requires ground-truth labels'}
            </div>
          </div>

          {/* Card 5: Pairwise F1 */}
          <div className="glass-panel" style={{ padding: '16px' }}>
            <div style={{ fontSize: '11px', textTransform: 'uppercase', color: 'var(--text-faint)', fontWeight: '700' }}>
              Pairwise Clustering F1
            </div>
            <div style={{ fontSize: '26px', fontWeight: '800', marginTop: '4px', color: activeRun.evaluation?.available ? '#a78bfa' : '#94a3b8' }}>
              {activeRun.evaluation?.available && activeRun.evaluation.pairwise_f1 !== null ? `${(activeRun.evaluation.pairwise_f1 * 100).toFixed(1)}%` : 'UNAVAILABLE'}
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
              {activeRun.evaluation?.available ? `BCubed F1: ${((activeRun.evaluation.bcubed_f1 || 0) * 100).toFixed(1)}%` : 'No ground-truth labels'}
            </div>
          </div>
        </section>
      )}

      {/* Tabs Selector */}
      <div style={{ display: 'flex', gap: '8px', marginBottom: '20px', borderBottom: '1px solid var(--border-color)', paddingBottom: '8px' }}>
        <button
          onClick={() => handleTabSwitch('incidents')}
          style={{
            backgroundColor: activeTab === 'incidents' ? 'var(--bg-tertiary)' : 'transparent',
            color: activeTab === 'incidents' ? '#fff' : 'var(--text-muted)',
            border: activeTab === 'incidents' ? '1px solid var(--border-color)' : '1px solid transparent',
            padding: '8px 16px',
            borderRadius: '8px',
            fontWeight: '600',
            fontSize: '13px'
          }}
        >
          🔍 Discovered Incidents ({incidents.length})
        </button>

        <button
          onClick={() => handleTabSwitch('scoreboard')}
          style={{
            backgroundColor: activeTab === 'scoreboard' ? 'var(--bg-tertiary)' : 'transparent',
            color: activeTab === 'scoreboard' ? '#fff' : 'var(--text-muted)',
            border: activeTab === 'scoreboard' ? '1px solid var(--border-color)' : '1px solid transparent',
            padding: '8px 16px',
            borderRadius: '8px',
            fontWeight: '600',
            fontSize: '13px'
          }}
        >
          📊 Evaluation Scoreboard (B vs Baseline)
        </button>

        <button
          onClick={() => handleTabSwitch('alerts')}
          style={{
            backgroundColor: activeTab === 'alerts' ? 'var(--bg-tertiary)' : 'transparent',
            color: activeTab === 'alerts' ? '#fff' : 'var(--text-muted)',
            border: activeTab === 'alerts' ? '1px solid var(--border-color)' : '1px solid transparent',
            padding: '8px 16px',
            borderRadius: '8px',
            fontWeight: '600',
            fontSize: '13px'
          }}
        >
          📋 Raw Alert Stream
        </button>

        <button
          onClick={() => handleTabSwitch('recon')}
          style={{
            backgroundColor: activeTab === 'recon' ? 'var(--bg-tertiary)' : 'transparent',
            color: activeTab === 'recon' ? '#fff' : 'var(--text-muted)',
            border: activeTab === 'recon' ? '1px solid var(--border-color)' : '1px solid transparent',
            padding: '8px 16px',
            borderRadius: '8px',
            fontWeight: '600',
            fontSize: '13px'
          }}
        >
          🧪 Dataset Reconnaissance
        </button>
      </div>

      {/* =========================================================================
          TAB 1: Discovered Incidents & Correlation Explorer
         ========================================================================= */}
      {activeTab === 'incidents' && (
        <div style={{ display: 'grid', gridTemplateColumns: '360px 1fr', gap: '20px', alignItems: 'start' }}>
          {/* Left Column: Incidents List */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
              <span style={{ fontSize: '13px', fontWeight: '700', color: 'var(--text-muted)' }}>
                {showUnattachedLane ? `Unattached Lane (${unattachedAlerts.length})` : `Incident Groups (${incidents.length})`}
              </span>
              <button
                onClick={() => setShowUnattachedLane(!showUnattachedLane)}
                style={{
                  backgroundColor: 'transparent',
                  border: '1px solid var(--border-color)',
                  color: showUnattachedLane ? 'var(--accent-blue)' : 'var(--text-faint)',
                  fontSize: '11px',
                  padding: '4px 8px',
                  borderRadius: '6px'
                }}
              >
                {showUnattachedLane ? '← Back to Incidents' : `View Unattached (${unattachedAlerts.length})`}
              </button>
            </div>

            {/* If viewing unattached alerts lane */}
            {showUnattachedLane ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', maxHeight: '780px', overflowY: 'auto' }}>
                {unattachedAlerts.length === 0 ? (
                  <div className="glass-panel" style={{ padding: '20px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>
                    Zero unattached alerts. Every alert was correlated into an incident group.
                  </div>
                ) : (
                  unattachedAlerts.map((u) => (
                    <div
                      key={u.alert.id}
                      className="glass-panel"
                      style={{ padding: '14px', borderRadius: '8px', borderLeft: '3px solid #fbbf24' }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                        <span className="mono" style={{ fontSize: '12px', fontWeight: '700', color: '#fff' }}>{u.alert.id}</span>
                        {getSeverityBadge(u.alert.severity)}
                      </div>
                      <div style={{ fontSize: '12px', fontWeight: '600', color: '#e2e8f0', marginBottom: '4px' }}>
                        {u.alert.service || 'unknown'}
                      </div>
                      <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '8px' }}>
                        {u.alert.message}
                      </div>
                      <div style={{ fontSize: '11px', color: '#fbbf24' }}>
                        ℹ️ {u.reason}
                      </div>
                    </div>
                  ))
                )}
              </div>
            ) : (
              /* Incident Groups Cards */
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', maxHeight: '780px', overflowY: 'auto' }}>
                {incidents.length === 0 ? (
                  <div className="glass-panel" style={{ padding: '30px', textAlign: 'center', color: 'var(--text-muted)' }}>
                    No incident groups discovered. Click "Run Correlation" to execute.
                  </div>
                ) : (
                  incidents.map((inc) => {
                    const isSelected = selectedIncident?.incident_id === inc.incident_id
                    return (
                      <div
                        key={inc.incident_id}
                        onClick={() => fetchIncidentDetail(inc.incident_id)}
                        className="glass-panel"
                        style={{
                          padding: '16px',
                          borderRadius: '10px',
                          cursor: 'pointer',
                          border: isSelected ? '1px solid var(--accent-blue)' : '1px solid var(--border-color)',
                          boxShadow: isSelected ? '0 0 16px rgba(59, 130, 246, 0.25)' : 'none',
                          backgroundColor: isSelected ? 'rgba(23, 33, 54, 0.95)' : 'var(--bg-card)',
                          transition: 'all 0.15s ease'
                        }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '6px' }}>
                          <span className="mono" style={{ fontSize: '12px', fontWeight: '700', color: isSelected ? '#93c5fd' : '#cbd5e1' }}>
                            {inc.incident_id}
                          </span>
                          <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                            {inc.tentative && (
                              <span style={{ fontSize: '10px', fontWeight: '700', color: '#fcd34d', backgroundColor: 'rgba(245, 158, 11, 0.15)', border: '1px solid rgba(245, 158, 11, 0.4)', padding: '2px 6px', borderRadius: '4px' }}>
                                TENTATIVE
                              </span>
                            )}
                            {getSeverityBadge(inc.primary_severity)}
                          </div>
                        </div>

                        <div style={{ fontSize: '13px', fontWeight: '700', color: '#fff', marginBottom: '8px' }}>
                          {inc.title}
                        </div>

                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginBottom: '10px' }}>
                          {inc.services.map((s) => (
                            <span key={s} style={{ fontSize: '11px', padding: '2px 6px', borderRadius: '4px', backgroundColor: 'rgba(255, 255, 255, 0.06)', color: '#94a3b8' }}>
                              {s}
                            </span>
                          ))}
                        </div>

                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '11px', color: 'var(--text-faint)' }}>
                          <span>⏱️ {Math.round(inc.span_seconds)}s span</span>
                          <span style={{ fontWeight: '700', color: '#e2e8f0' }}>{inc.alerts_count} alerts</span>
                        </div>
                      </div>
                    )
                  })
                )}
              </div>
            )}
          </div>

          {/* Right Column: Selected Incident Detail Drawer */}
          <div>
            {!selectedIncident ? (
              <div className="glass-panel" style={{ padding: '60px', textAlign: 'center', color: 'var(--text-muted)' }}>
                Select an incident from the list to inspect its timeline, correlation evidence, and origin hypotheses.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                {/* Header Card */}
                <div className="glass-panel" style={{ padding: '22px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                        <span className="mono" style={{ fontSize: '14px', fontWeight: '700', color: 'var(--accent-blue)' }}>
                          {selectedIncident.incident_id}
                        </span>
                        {selectedIncident.tentative && (
                          <span style={{ fontSize: '11px', fontWeight: '700', color: '#fcd34d', backgroundColor: 'rgba(245, 158, 11, 0.15)', border: '1px solid rgba(245, 158, 11, 0.4)', padding: '2px 8px', borderRadius: '4px' }}>
                            TENTATIVE MERGE
                          </span>
                        )}
                        {getSeverityBadge(selectedIncident.primary_severity)}
                      </div>
                      <h2 style={{ fontSize: '18px', fontWeight: '800', marginTop: '6px', color: '#fff' }}>
                        {selectedIncident.title}
                      </h2>
                    </div>

                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontSize: '12px', color: 'var(--text-faint)' }}>Total Alerts</div>
                      <div style={{ fontSize: '24px', fontWeight: '800', color: '#fff' }}>{selectedIncident.alerts_count}</div>
                    </div>
                  </div>

                  {selectedIncident.tentative && selectedIncident.tentative_reason && (
                    <div style={{ marginTop: '12px', padding: '10px 14px', borderRadius: '6px', backgroundColor: 'rgba(245, 158, 11, 0.1)', border: '1px solid rgba(245, 158, 11, 0.3)', color: '#fde68a', fontSize: '12px' }}>
                      ⚠️ {selectedIncident.tentative_reason}
                    </div>
                  )}

                  <div style={{ display: 'flex', gap: '24px', marginTop: '16px', paddingTop: '14px', borderTop: '1px solid var(--border-color)', fontSize: '12px', color: 'var(--text-muted)' }}>
                    <div>
                      <span style={{ color: 'var(--text-faint)' }}>Start (UTC):</span>{' '}
                      <span className="mono" style={{ color: '#fff' }}>
                        {new Date(selectedIncident.start_time).toISOString().replace('.000Z', 'Z').replace('T', ' ')}
                      </span>
                    </div>
                    <div>
                      <span style={{ color: 'var(--text-faint)' }}>End (UTC):</span>{' '}
                      <span className="mono" style={{ color: '#fff' }}>
                        {new Date(selectedIncident.end_time).toISOString().replace('.000Z', 'Z').replace('T', ' ')}
                      </span>
                    </div>
                    <div>
                      <span style={{ color: 'var(--text-faint)' }}>Duration:</span>{' '}
                      <span style={{ color: '#fff', fontWeight: '600' }}>{Math.round(selectedIncident.span_seconds)} seconds</span>
                    </div>
                  </div>
                </div>

                {/* Origin Hypotheses Card */}
                <div className="glass-panel" style={{ padding: '20px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                    <h3 style={{ fontSize: '14px', fontWeight: '700', textTransform: 'uppercase', color: 'var(--accent-purple)', letterSpacing: '0.05em' }}>
                      🧭 Ranked Origin Hypotheses
                    </h3>
                    <span style={{ fontSize: '11px', color: 'var(--text-faint)' }}>
                      Evaluated from temporal precedence & topology (Never asserted as proven)
                    </span>
                  </div>

                  {selectedIncident.origin_hypotheses.length === 0 ? (
                    <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>No origin hypotheses computed.</div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                      {selectedIncident.origin_hypotheses.map((hyp, hIdx) => (
                        <div
                          key={hIdx}
                          style={{
                            backgroundColor: hyp.is_undetermined ? 'rgba(245, 158, 11, 0.08)' : 'var(--bg-secondary)',
                            border: `1px solid ${hyp.is_undetermined ? 'rgba(245, 158, 11, 0.3)' : 'var(--border-color)'}`,
                            padding: '12px 16px',
                            borderRadius: '8px'
                          }}
                        >
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                              <span style={{
                                width: '20px',
                                height: '20px',
                                borderRadius: '50%',
                                backgroundColor: hyp.is_undetermined ? '#f59e0b' : 'var(--accent-blue)',
                                color: '#fff',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                fontSize: '11px',
                                fontWeight: '700'
                              }}>
                                {hyp.rank}
                              </span>
                              <span style={{ fontSize: '14px', fontWeight: '700', color: hyp.is_undetermined ? '#fcd34d' : '#fff' }}>
                                {hyp.is_undetermined ? 'UNDETERMINED ORIGIN (Abstained)' : hyp.service}
                              </span>
                            </div>
                            <span className="mono" style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-muted)' }}>
                              Score: {hyp.score.toFixed(2)}
                            </span>
                          </div>

                          <ul style={{ paddingLeft: '20px', fontSize: '12px', color: 'var(--text-muted)', lineHeight: '1.6' }}>
                            {hyp.evidence.map((ev, eIdx) => (
                              <li key={eIdx}>{ev}</li>
                            ))}
                          </ul>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Timeline of Alerts in Incident */}
                <div className="glass-panel" style={{ padding: '20px' }}>
                  <h3 style={{ fontSize: '14px', fontWeight: '700', textTransform: 'uppercase', color: 'var(--accent-blue)', letterSpacing: '0.05em', marginBottom: '14px' }}>
                    ⏱️ Chronological Incident Timeline ({incidentAlerts.length} Alerts)
                  </h3>

                  <div style={{ overflowX: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '12px' }}>
                      <thead>
                        <tr style={{ borderBottom: '1px solid var(--border-color)', color: 'var(--text-faint)', textTransform: 'uppercase' }}>
                          <th style={{ padding: '8px 12px' }}>Time (UTC)</th>
                          <th style={{ padding: '8px 12px' }}>Severity</th>
                          <th style={{ padding: '8px 12px' }}>Service</th>
                          <th style={{ padding: '8px 12px' }}>Alert Message</th>
                          <th style={{ padding: '8px 12px' }}>Source</th>
                        </tr>
                      </thead>
                      <tbody>
                        {incidentAlerts.map((a) => (
                          <tr key={a.id} style={{ borderBottom: '1px solid rgba(36, 49, 73, 0.4)' }}>
                            <td className="mono" style={{ padding: '10px 12px', whiteSpace: 'nowrap', color: '#cbd5e1' }}>
                              {new Date(a.timestamp).toISOString().replace('.000Z', 'Z').replace('T', ' ')}
                            </td>
                            <td style={{ padding: '10px 12px' }}>
                              {getSeverityBadge(a.severity)}
                            </td>
                            <td style={{ padding: '10px 12px' }}>
                              <span style={{ backgroundColor: 'rgba(255, 255, 255, 0.08)', padding: '2px 6px', borderRadius: '4px', fontWeight: '600', color: '#e2e8f0' }}>
                                {a.service}
                              </span>
                            </td>
                            <td style={{ padding: '10px 12px', color: '#fff', fontWeight: '500' }}>
                              {a.message}
                            </td>
                            <td style={{ padding: '10px 12px', color: 'var(--text-muted)' }}>
                              {a.source}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Explainable Correlation Evidence Breakdown */}
                {selectedIncident.edges && selectedIncident.edges.length > 0 && (
                  <div className="glass-panel" style={{ padding: '20px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
                      <h3 style={{ fontSize: '14px', fontWeight: '700', textTransform: 'uppercase', color: 'var(--accent-emerald)', letterSpacing: '0.05em' }}>
                        🔗 Why Linked? Correlation Evidence Breakdown
                      </h3>
                      <span style={{ fontSize: '11px', color: 'var(--text-faint)' }}>
                        {selectedIncident.edges.length} multi-signal correlation edges
                      </span>
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '300px', overflowY: 'auto' }}>
                      {selectedIncident.edges.map((edge, eIdx) => (
                        <div
                          key={eIdx}
                          style={{
                            backgroundColor: 'var(--bg-secondary)',
                            border: '1px solid var(--border-color)',
                            padding: '10px 14px',
                            borderRadius: '8px',
                            fontSize: '12px'
                          }}
                        >
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                            <div className="mono" style={{ fontWeight: '600', color: '#93c5fd' }}>
                              {edge.alert_id_a} ↔ {edge.alert_id_b}
                            </div>
                            <span style={{
                              fontWeight: '700',
                              backgroundColor: 'rgba(16, 185, 129, 0.15)',
                              color: '#6ee7b7',
                              padding: '2px 8px',
                              borderRadius: '4px'
                            }}>
                              Score: {edge.total_score.toFixed(2)}
                            </span>
                          </div>

                          <div style={{ color: 'var(--text-muted)', marginBottom: '4px' }}>
                            {edge.rationale}
                          </div>

                          <div className="mono" style={{ display: 'flex', gap: '14px', fontSize: '11px', color: 'var(--text-faint)' }}>
                            <span>Temporal: {edge.time_score.toFixed(2)} ({edge.delta_seconds}s)</span>
                            <span>Text Sim: {edge.text_score.toFixed(2)}</span>
                            <span>Service: {edge.service_score.toFixed(2)}</span>
                            <span>Dependency: {edge.dependency_score.toFixed(2)}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* =========================================================================
          TAB 2: Evaluation Scoreboard (Baseline vs Improved Engine)
         ========================================================================= */}
      {activeTab === 'scoreboard' && (
        <section className="glass-panel" style={{ padding: '24px' }}>
          <div style={{ marginBottom: '20px' }}>
            <h2 style={{ fontSize: '18px', fontWeight: '800', color: '#fff' }}>
              📊 Algorithm Evaluation Scoreboard
            </h2>
            <p style={{ fontSize: '13px', color: 'var(--text-muted)', marginTop: '4px' }}>
              Side-by-side comparison between Architecture B (Weighted Graph + Constrained Clustering) and Architecture A (Deterministic Fingerprint Baseline).
            </p>
          </div>

          {!activeRun?.evaluation ? (
            <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
              No evaluation data available. Run correlation first.
            </div>
          ) : !activeRun.evaluation.available ? (
            <div style={{ padding: '30px', backgroundColor: 'rgba(245, 158, 11, 0.1)', border: '1px solid rgba(245, 158, 11, 0.3)', borderRadius: '8px', color: '#fde68a', fontSize: '13px' }}>
              ⚠️ <strong>Ground-Truth Labels Unavailable:</strong> This dataset does not contain separate ground-truth incident records. Pathora is operating in unsupervised mode. Pairwise F1 and incident recovery scores are explicitly marked UNAVAILABLE rather than fabricated.
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '13px' }}>
                <thead>
                  <tr style={{ borderBottom: '2px solid var(--border-color)', color: 'var(--text-faint)', textTransform: 'uppercase', fontSize: '11px', letterSpacing: '0.05em' }}>
                    <th style={{ padding: '12px 16px' }}>Evaluation Metric</th>
                    <th style={{ padding: '12px 16px', color: '#60a5fa' }}>Architecture B (Improved Engine)</th>
                    <th style={{ padding: '12px 16px', color: '#94a3b8' }}>Architecture A (Baseline)</th>
                    <th style={{ padding: '12px 16px' }}>Metric Interpretation</th>
                  </tr>
                </thead>
                <tbody>
                  <tr style={{ borderBottom: '1px solid rgba(36, 49, 73, 0.5)' }}>
                    <td style={{ padding: '14px 16px', fontWeight: '700', color: '#fff' }}>Noise Reduction Rate</td>
                    <td className="mono" style={{ padding: '14px 16px', fontWeight: '800', color: '#34d399', fontSize: '15px' }}>
                      {(activeRun.notification_reduction_rate * 100).toFixed(1)}%
                    </td>
                    <td className="mono" style={{ padding: '14px 16px', color: '#cbd5e1' }}>
                      {activeRun.baseline_evaluation ? `${(activeRun.baseline_evaluation.notification_reduction_rate * 100).toFixed(1)}%` : 'N/A'}
                    </td>
                    <td style={{ padding: '14px 16px', color: 'var(--text-muted)', fontSize: '12px' }}>
                      Alerts consolidated into incidents; higher is better when swallow rate is low.
                    </td>
                  </tr>

                  <tr style={{ borderBottom: '1px solid rgba(36, 49, 73, 0.5)' }}>
                    <td style={{ padding: '14px 16px', fontWeight: '700', color: '#fff' }}>Pairwise F1 Score</td>
                    <td className="mono" style={{ padding: '14px 16px', fontWeight: '800', color: '#a78bfa', fontSize: '15px' }}>
                      {activeRun.evaluation.pairwise_f1 !== null ? `${(activeRun.evaluation.pairwise_f1 * 100).toFixed(1)}%` : 'N/A'}
                    </td>
                    <td className="mono" style={{ padding: '14px 16px', color: '#cbd5e1' }}>
                      {activeRun.baseline_evaluation?.pairwise_f1 !== null ? `${((activeRun.baseline_evaluation?.pairwise_f1 || 0) * 100).toFixed(1)}%` : 'N/A'}
                    </td>
                    <td style={{ padding: '14px 16px', color: 'var(--text-muted)', fontSize: '12px' }}>
                      Harmonic mean of pairwise precision and recall across all alert pairs.
                    </td>
                  </tr>

                  <tr style={{ borderBottom: '1px solid rgba(36, 49, 73, 0.5)' }}>
                    <td style={{ padding: '14px 16px', fontWeight: '700', color: '#fff' }}>Pairwise Precision</td>
                    <td className="mono" style={{ padding: '14px 16px', color: '#fff' }}>
                      {activeRun.evaluation.pairwise_precision !== null ? `${(activeRun.evaluation.pairwise_precision * 100).toFixed(1)}%` : 'N/A'}
                    </td>
                    <td className="mono" style={{ padding: '14px 16px', color: '#cbd5e1' }}>
                      {activeRun.baseline_evaluation?.pairwise_precision !== null ? `${((activeRun.baseline_evaluation?.pairwise_precision || 0) * 100).toFixed(1)}%` : 'N/A'}
                    </td>
                    <td style={{ padding: '14px 16px', color: 'var(--text-muted)', fontSize: '12px' }}>
                      Measures purity: fraction of grouped pairs that truly belong together.
                    </td>
                  </tr>

                  <tr style={{ borderBottom: '1px solid rgba(36, 49, 73, 0.5)' }}>
                    <td style={{ padding: '14px 16px', fontWeight: '700', color: '#fff' }}>Pairwise Recall</td>
                    <td className="mono" style={{ padding: '14px 16px', color: '#fff' }}>
                      {activeRun.evaluation.pairwise_recall !== null ? `${(activeRun.evaluation.pairwise_recall * 100).toFixed(1)}%` : 'N/A'}
                    </td>
                    <td className="mono" style={{ padding: '14px 16px', color: '#cbd5e1' }}>
                      {activeRun.baseline_evaluation?.pairwise_recall !== null ? `${((activeRun.baseline_evaluation?.pairwise_recall || 0) * 100).toFixed(1)}%` : 'N/A'}
                    </td>
                    <td style={{ padding: '14px 16px', color: 'var(--text-muted)', fontSize: '12px' }}>
                      Measures completeness: fraction of true ground-truth pairs successfully recovered.
                    </td>
                  </tr>

                  <tr style={{ borderBottom: '1px solid rgba(36, 49, 73, 0.5)' }}>
                    <td style={{ padding: '14px 16px', fontWeight: '700', color: '#fff' }}>BCubed F1 Score</td>
                    <td className="mono" style={{ padding: '14px 16px', color: '#fff' }}>
                      {activeRun.evaluation.bcubed_f1 !== null ? `${(activeRun.evaluation.bcubed_f1 * 100).toFixed(1)}%` : 'N/A'}
                    </td>
                    <td className="mono" style={{ padding: '14px 16px', color: '#cbd5e1' }}>
                      {activeRun.baseline_evaluation?.bcubed_f1 !== null ? `${((activeRun.baseline_evaluation?.bcubed_f1 || 0) * 100).toFixed(1)}%` : 'N/A'}
                    </td>
                    <td style={{ padding: '14px 16px', color: 'var(--text-muted)', fontSize: '12px' }}>
                      Element-level clustering metric satisfying homogeneity and completeness.
                    </td>
                  </tr>

                  <tr style={{ borderBottom: '1px solid rgba(36, 49, 73, 0.5)' }}>
                    <td style={{ padding: '14px 16px', fontWeight: '700', color: '#fff' }}>Swallow / False-Merge Rate</td>
                    <td className="mono" style={{ padding: '14px 16px', color: (activeRun.evaluation.swallow_rate || 0) > 0 ? '#f87171' : '#34d399', fontWeight: '700' }}>
                      {activeRun.evaluation.swallow_rate !== null ? `${((activeRun.evaluation.swallow_rate || 0) * 100).toFixed(1)}%` : 'N/A'}
                    </td>
                    <td className="mono" style={{ padding: '14px 16px', color: '#cbd5e1' }}>
                      {activeRun.baseline_evaluation?.swallow_rate !== null ? `${((activeRun.baseline_evaluation?.swallow_rate || 0) * 100).toFixed(1)}%` : 'N/A'}
                    </td>
                    <td style={{ padding: '14px 16px', color: 'var(--text-muted)', fontSize: '12px' }}>
                      Share of independent true incidents mistakenly absorbed into another incident.
                    </td>
                  </tr>

                  <tr style={{ borderBottom: '1px solid rgba(36, 49, 73, 0.5)' }}>
                    <td style={{ padding: '14px 16px', fontWeight: '700', color: '#fff' }}>Origin Top-1 Accuracy</td>
                    <td className="mono" style={{ padding: '14px 16px', color: '#60a5fa' }}>
                      {activeRun.evaluation.origin_top1_accuracy !== null ? `${((activeRun.evaluation.origin_top1_accuracy || 0) * 100).toFixed(1)}%` : 'N/A'}
                    </td>
                    <td className="mono" style={{ padding: '14px 16px', color: '#cbd5e1' }}>
                      {activeRun.baseline_evaluation?.origin_top1_accuracy !== null ? `${((activeRun.baseline_evaluation?.origin_top1_accuracy || 0) * 100).toFixed(1)}%` : 'N/A'}
                    </td>
                    <td style={{ padding: '14px 16px', color: 'var(--text-muted)', fontSize: '12px' }}>
                      Accuracy of top-ranked origin hypothesis on non-ambiguous ground truth.
                    </td>
                  </tr>
                </tbody>
              </table>

              <div style={{ marginTop: '20px', padding: '14px 18px', backgroundColor: 'var(--bg-secondary)', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                <h4 style={{ fontSize: '12px', textTransform: 'uppercase', color: 'var(--accent-blue)', marginBottom: '6px' }}>Evaluation Audit Notes</h4>
                <ul style={{ paddingLeft: '20px', fontSize: '12px', color: 'var(--text-muted)', lineHeight: '1.6' }}>
                  {activeRun.evaluation.notes.map((n, idx) => (
                    <li key={idx}>{n}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </section>
      )}

      {/* =========================================================================
          TAB 3: Raw Alert Stream Overview
         ========================================================================= */}
      {activeTab === 'alerts' && (
        <section className="glass-panel" style={{ padding: '20px' }}>
          {/* Filters Bar */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', alignItems: 'center', marginBottom: '20px' }}>
            <input
              type="text"
              placeholder="Search alert messages, IDs, services..."
              value={searchQuery}
              onChange={(e) => { setSearchQuery(e.target.value); setPage(1); }}
              style={{
                backgroundColor: 'var(--bg-secondary)',
                border: '1px solid var(--border-color)',
                color: '#fff',
                padding: '8px 14px',
                borderRadius: '8px',
                fontSize: '13px',
                flex: '1',
                minWidth: '240px'
              }}
            />

            <select
              value={severityFilter}
              onChange={(e) => { setSeverityFilter(e.target.value); setPage(1); }}
              style={{
                backgroundColor: 'var(--bg-secondary)',
                border: '1px solid var(--border-color)',
                color: '#fff',
                padding: '8px 14px',
                borderRadius: '8px',
                fontSize: '13px'
              }}
            >
              <option value="all">All Severities</option>
              <option value="critical">Critical</option>
              <option value="error">Error</option>
              <option value="warning">Warning</option>
              <option value="info">Info</option>
            </select>

            <select
              value={pageSize}
              onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}
              style={{
                backgroundColor: 'var(--bg-secondary)',
                border: '1px solid var(--border-color)',
                color: '#fff',
                padding: '8px 14px',
                borderRadius: '8px',
                fontSize: '13px'
              }}
            >
              <option value="15">15 per page</option>
              <option value="25">25 per page</option>
              <option value="50">50 per page</option>
              <option value="100">100 per page</option>
            </select>
          </div>

          {/* Alerts Table */}
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '13px' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-color)', color: 'var(--text-faint)', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  <th style={{ padding: '10px 14px' }}>Timestamp (UTC)</th>
                  <th style={{ padding: '10px 14px' }}>Severity</th>
                  <th style={{ padding: '10px 14px' }}>Service</th>
                  <th style={{ padding: '10px 14px' }}>Message</th>
                  <th style={{ padding: '10px 14px' }}>Source / Host</th>
                  <th style={{ padding: '10px 14px' }}>Origin</th>
                  <th style={{ padding: '10px 14px' }}>Details</th>
                </tr>
              </thead>
              <tbody>
                {alerts.length === 0 ? (
                  <tr>
                    <td colSpan="7" style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
                      {loading ? 'Ingesting and parsing alerts...' : 'No alerts match current search and filter criteria.'}
                    </td>
                  </tr>
                ) : (
                  alerts.map((alert) => (
                    <React.Fragment key={alert.id}>
                      <tr style={{
                        borderBottom: '1px solid rgba(36, 49, 73, 0.5)',
                        backgroundColor: expandedAlert === alert.id ? 'rgba(59, 130, 246, 0.05)' : 'transparent',
                        transition: 'background-color 0.15s'
                      }}>
                        <td className="mono" style={{ padding: '12px 14px', whiteSpace: 'nowrap', color: '#cbd5e1' }}>
                          {new Date(alert.timestamp).toISOString().replace('.000Z', 'Z').replace('T', ' ')}
                        </td>
                        <td style={{ padding: '12px 14px' }}>
                          {getSeverityBadge(alert.severity)}
                        </td>
                        <td style={{ padding: '12px 14px' }}>
                          <span style={{
                            backgroundColor: 'rgba(255, 255, 255, 0.06)',
                            padding: '3px 8px',
                            borderRadius: '4px',
                            fontSize: '12px',
                            fontWeight: '600',
                            color: '#e2e8f0'
                          }}>
                            {alert.service || 'unknown'}
                          </span>
                        </td>
                        <td style={{ padding: '12px 14px', maxWidth: '420px', color: '#f8fafc', fontWeight: '500' }}>
                          {alert.message}
                        </td>
                        <td style={{ padding: '12px 14px', color: 'var(--text-muted)', fontSize: '12px' }}>
                          <div>{alert.source || 'generic'}</div>
                          {alert.host && <div className="mono" style={{ fontSize: '11px', color: 'var(--text-faint)' }}>{alert.host}</div>}
                        </td>
                        <td style={{ padding: '12px 14px' }}>
                          <span style={{
                            fontSize: '10px',
                            fontWeight: '700',
                            padding: '2px 6px',
                            borderRadius: '4px',
                            backgroundColor: alert.is_synthetic ? 'rgba(139, 92, 246, 0.15)' : 'rgba(16, 185, 129, 0.15)',
                            color: alert.is_synthetic ? '#c4b5fd' : '#6ee7b7'
                          }}>
                            {alert.is_synthetic ? 'SYNTHETIC' : 'OFFICIAL'}
                          </span>
                        </td>
                        <td style={{ padding: '12px 14px' }}>
                          <button
                            onClick={() => setExpandedAlert(expandedAlert === alert.id ? null : alert.id)}
                            style={{
                              backgroundColor: 'transparent',
                              border: '1px solid var(--border-color)',
                              color: 'var(--text-muted)',
                              padding: '4px 8px',
                              borderRadius: '4px',
                              fontSize: '11px'
                            }}
                          >
                            {expandedAlert === alert.id ? 'Hide' : 'Inspect'}
                          </button>
                        </td>
                      </tr>

                      {expandedAlert === alert.id && (
                        <tr style={{ backgroundColor: 'rgba(14, 21, 35, 0.95)' }}>
                          <td colSpan="7" style={{ padding: '16px 20px' }}>
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                              <div>
                                <h4 style={{ fontSize: '12px', textTransform: 'uppercase', color: 'var(--accent-blue)', marginBottom: '8px' }}>
                                  Canonical Attributes
                                </h4>
                                <div className="mono" style={{ fontSize: '12px', color: '#cbd5e1' }}>
                                  <div><strong>Canonical ID:</strong> {alert.id}</div>
                                  <div><strong>Raw Timestamp:</strong> {alert.timestamp_raw || 'N/A'}</div>
                                  <div><strong>Parsed UTC:</strong> {alert.timestamp}</div>
                                  <div><strong>Service:</strong> {alert.service}</div>
                                  <div><strong>Severity:</strong> {alert.severity}</div>
                                </div>
                              </div>
                              <div>
                                <h4 style={{ fontSize: '12px', textTransform: 'uppercase', color: 'var(--accent-purple)', marginBottom: '8px' }}>
                                  Preserved Unmapped Attributes
                                </h4>
                                <pre className="mono" style={{ fontSize: '11px', color: '#94a3b8', maxHeight: '120px', overflowY: 'auto' }}>
                                  {JSON.stringify(alert.attributes, null, 2)}
                                </pre>
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginTop: '20px',
            paddingTop: '16px',
            borderTop: '1px solid var(--border-color)'
          }}>
            <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
              Showing {alerts.length === 0 ? 0 : (page - 1) * pageSize + 1} to {Math.min(page * pageSize, totalAlerts)} of {totalAlerts} alerts
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                style={{
                  backgroundColor: 'var(--bg-secondary)',
                  border: '1px solid var(--border-color)',
                  color: page <= 1 ? 'var(--text-faint)' : '#fff',
                  padding: '6px 12px',
                  borderRadius: '6px',
                  fontSize: '12px'
                }}
              >
                ◀ Previous
              </button>
              <span className="mono" style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                Page {page} of {totalPages}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                style={{
                  backgroundColor: 'var(--bg-secondary)',
                  border: '1px solid var(--border-color)',
                  color: page >= totalPages ? 'var(--text-faint)' : '#fff',
                  padding: '6px 12px',
                  borderRadius: '6px',
                  fontSize: '12px'
                }}
              >
                Next ▶
              </button>
            </div>
          </div>
        </section>
      )}

      {/* =========================================================================
          TAB 4: Dataset Reconnaissance
         ========================================================================= */}
      {activeTab === 'recon' && (
        <section style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {!profile ? (
            <div className="glass-panel" style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
              Loading dataset reconnaissance profile...
            </div>
          ) : (
            <>
              {/* Hygiene Cards */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px' }}>
                <div className="glass-panel" style={{ padding: '16px' }}>
                  <div style={{ fontSize: '11px', color: 'var(--text-faint)', textTransform: 'uppercase', fontWeight: '700' }}>Total Ingested</div>
                  <div style={{ fontSize: '24px', fontWeight: '800', marginTop: '4px' }}>{profile.total_records}</div>
                </div>
                <div className="glass-panel" style={{ padding: '16px' }}>
                  <div style={{ fontSize: '11px', color: 'var(--text-faint)', textTransform: 'uppercase', fontWeight: '700' }}>Malformed Records</div>
                  <div style={{ fontSize: '24px', fontWeight: '800', marginTop: '4px', color: profile.malformed_records > 0 ? '#f87171' : '#34d399' }}>
                    {profile.malformed_records}
                  </div>
                </div>
                <div className="glass-panel" style={{ padding: '16px' }}>
                  <div style={{ fontSize: '11px', color: 'var(--text-faint)', textTransform: 'uppercase', fontWeight: '700' }}>Exact Duplicates</div>
                  <div style={{ fontSize: '24px', fontWeight: '800', marginTop: '4px', color: profile.duplicate_records_exact > 0 ? '#fbbf24' : '#34d399' }}>
                    {profile.duplicate_records_exact}
                  </div>
                </div>
                <div className="glass-panel" style={{ padding: '16px' }}>
                  <div style={{ fontSize: '11px', color: 'var(--text-faint)', textTransform: 'uppercase', fontWeight: '700' }}>Potential Alert Dupes</div>
                  <div style={{ fontSize: '24px', fontWeight: '800', marginTop: '4px', color: profile.potential_duplicate_alerts > 0 ? '#fbbf24' : '#34d399' }}>
                    {profile.potential_duplicate_alerts}
                  </div>
                </div>
              </div>

              {/* Inferred Mappings & Heuristics */}
              <div className="glass-panel" style={{ padding: '20px' }}>
                <h3 style={{ fontSize: '15px', fontWeight: '700', marginBottom: '14px', color: '#fff' }}>
                  Detected Canonical Field Mappings & Uncertainty
                </h3>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '12px' }}>
                  {Object.entries(profile.inferred_mappings || {}).map(([canonical, inf]) => (
                    <div key={canonical} style={{
                      backgroundColor: 'var(--bg-secondary)',
                      padding: '12px 14px',
                      borderRadius: '8px',
                      border: '1px solid var(--border-color)'
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontSize: '12px', fontWeight: '700', textTransform: 'uppercase', color: 'var(--accent-blue)' }}>
                          {canonical}
                        </span>
                        <span style={{
                          fontSize: '11px',
                          fontWeight: '700',
                          color: inf.detected_column ? '#34d399' : '#94a3b8'
                        }}>
                          {inf.detected_column ? `${Math.round(inf.confidence * 100)}% confidence` : 'Absent'}
                        </span>
                      </div>
                      <div className="mono" style={{ fontSize: '13px', fontWeight: '600', color: '#fff', marginTop: '4px' }}>
                        {inf.detected_column || 'None detected'}
                      </div>
                      <div style={{ fontSize: '11px', color: 'var(--text-faint)', marginTop: '4px' }}>
                        {inf.rationale}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Detected Schema Table */}
              <div className="glass-panel" style={{ padding: '20px' }}>
                <h3 style={{ fontSize: '15px', fontWeight: '700', marginBottom: '14px', color: '#fff' }}>
                  Raw Dataset Columns & Data Types
                </h3>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '12px' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid var(--border-color)', color: 'var(--text-faint)', textTransform: 'uppercase' }}>
                        <th style={{ padding: '8px 12px' }}>Column</th>
                        <th style={{ padding: '8px 12px' }}>Inferred Type</th>
                        <th style={{ padding: '8px 12px' }}>Non-Null</th>
                        <th style={{ padding: '8px 12px' }}>Nulls</th>
                        <th style={{ padding: '8px 12px' }}>Unique Count</th>
                        <th style={{ padding: '8px 12px' }}>Sample Values</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.values(profile.fields || {}).map((f) => (
                        <tr key={f.name} style={{ borderBottom: '1px solid rgba(36, 49, 73, 0.4)' }}>
                          <td className="mono" style={{ padding: '10px 12px', fontWeight: '600', color: '#fff' }}>{f.name}</td>
                          <td style={{ padding: '10px 12px', color: 'var(--accent-purple)' }}>{f.detected_type}</td>
                          <td style={{ padding: '10px 12px', color: '#cbd5e1' }}>{f.non_null_count}</td>
                          <td style={{ padding: '10px 12px', color: f.null_count > 0 ? '#fbbf24' : '#cbd5e1' }}>{f.null_count}</td>
                          <td style={{ padding: '10px 12px', color: '#cbd5e1' }}>{f.unique_count}</td>
                          <td className="mono" style={{ padding: '10px 12px', color: 'var(--text-muted)', fontSize: '11px' }}>
                            {f.sample_values ? f.sample_values.slice(0, 3).join(', ') : ''}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}
        </section>
      )}
    </div>
  )
}
