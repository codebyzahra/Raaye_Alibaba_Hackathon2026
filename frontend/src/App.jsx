import { useState, useRef, useMemo, useEffect } from 'react'
import {
  Upload, FileText, AlertTriangle, AlertCircle, BarChart3,
  MessageSquare, ChevronDown, ChevronUp, Pencil, Check,
  Zap, Send, Play, Store, Cpu, Shirt,
} from 'lucide-react'

const API_BASE = ''  // same origin via Vite proxy

const LOADING_MESSAGES = [
  'Connecting to Alibaba Cloud\u2026',
  'Running Qwen ABSA Engine\u2026',
  'Drafting Recovery Replies\u2026',
]

// ── Main App ────────────────────────────────────────────────────────────

export default function App() {
  const [uploadStatus, setUploadStatus] = useState('idle')
  const [uploadResult, setUploadResult] = useState(null)
  const [reviews, setReviews] = useState([])
  const [dragActive, setDragActive] = useState(false)
  const [error, setError] = useState('')
  const [loadingMsg, setLoadingMsg] = useState(LOADING_MESSAGES[0])
  const [toast, setToast] = useState(null)
  const [businesses, setBusinesses] = useState([])
  const [activeBusiness, setActiveBusiness] = useState(null)
  const fileRef = useRef(null)

  // Fetch available demo businesses on mount
  useEffect(() => {
    fetch(`${API_BASE}/api/demo/businesses`)
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => setBusinesses(data))
      .catch(() => setBusinesses([]))
  }, [])

  // Rotating loading messages every 1.5s
  useEffect(() => {
    if (uploadStatus !== 'uploading') return
    let idx = 0
    setLoadingMsg(LOADING_MESSAGES[0])
    const timer = setInterval(() => {
      idx = (idx + 1) % LOADING_MESSAGES.length
      setLoadingMsg(LOADING_MESSAGES[idx])
    }, 1500)
    return () => clearInterval(timer)
  }, [uploadStatus])

  // Auto-dismiss toast
  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 3000)
    return () => clearTimeout(t)
  }, [toast])

  async function handleFile(file) {
    if (!file || !file.name.endsWith('.csv')) {
      setError('Please upload a .csv file.')
      return
    }
    setError('')
    setUploadStatus('uploading')

    const form = new FormData()
    form.append('file', file)

    try {
      const res = await fetch(`${API_BASE}/api/upload`, { method: 'POST', body: form })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `Server error ${res.status}`)
      }
      const data = await res.json()
      setUploadResult(data)

      const revRes = await fetch(`${API_BASE}/api/reviews?limit=${data.reviews_saved || 100}`)
      if (revRes.ok) setReviews(await revRes.json())
      setUploadStatus('done')
    } catch (err) {
      setError(err.message)
      setUploadStatus('error')
    }
  }

  // Demo mode: load cached results for a specific business
  async function handleDemo(businessId) {
    setError('')
    setUploadStatus('uploading')
    setActiveBusiness(businessId)
    try {
      const res = await fetch(`${API_BASE}/api/demo/${businessId}`, { method: 'POST' })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `Demo mode unavailable — start backend with DEMO_MODE=true`)
      }
      const data = await res.json()
      setUploadResult(data)
      const revRes = await fetch(`${API_BASE}/api/reviews?limit=${data.reviews_saved || 100}`)
      if (revRes.ok) setReviews(await revRes.json())
      setUploadStatus('done')
    } catch (err) {
      setError(err.message)
      setUploadStatus('error')
    }
  }

  // ── Derived metrics ────────────────────────────────────────────────────

  const metrics = useMemo(() => {
    if (!reviews.length) return null
    let pos = 0, neg = 0, neu = 0
    const aspectNeg = {}

    reviews.forEach((r) => {
      const sentiments = r.aspects.map((a) => a.sentiment)
      if (sentiments.includes('negative')) neg++
      else if (sentiments.every((s) => s === 'positive')) pos++
      else neu++

      r.aspects
        .filter((a) => a.sentiment === 'negative')
        .forEach((a) => { aspectNeg[a.aspect] = (aspectNeg[a.aspect] || 0) + 1 })
    })

    const total = reviews.length
    const topAspect = Object.keys(aspectNeg).length
      ? Object.entries(aspectNeg).sort((a, b) => b[1] - a[1])[0][0]
      : null

    return {
      total,
      posPct: Math.round((pos / total) * 100),
      negPct: Math.round((neg / total) * 100),
      neuPct: Math.round((neu / total) * 100),
      topComplaint: topAspect,
      hoursSaved: Math.max(1, Math.round((total * 2) / 60 * 10) / 10),
    }
  }, [reviews])

  // ── Flagged reviews ────────────────────────────────────────────────────

  const flagged = useMemo(
    () =>
      reviews
        .map((r) => {
          const negAspects = r.aspects.filter((a) => a.sentiment === 'negative')
          if (!negAspects.length) return null
          const replies = r.actions.filter((a) => a.action_text)
          const maxConf = Math.max(...negAspects.map((a) => a.confidence))
          return {
            id: r.id,
            text: r.raw_text,
            negAspects,
            reply: replies[0]?.action_text || '',
            severity: maxConf >= 0.85 ? 'high' : 'moderate',
          }
        })
        .filter(Boolean),
    [reviews],
  )

  // ── Render ─────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-slate-50">
      <Header />

      {/* Toast notification */}
      {toast && (
        <div className="fixed top-5 right-5 z-50 animate-toast">
          <div className="bg-emerald-600 text-white px-5 py-3.5 rounded-xl shadow-xl flex items-center gap-3">
            <div className="w-6 h-6 bg-white/20 rounded-full flex items-center justify-center shrink-0">
              <Check className="w-4 h-4" />
            </div>
            <span className="font-medium text-[15px]">{toast}</span>
          </div>
        </div>
      )}

      <main className="w-full max-w-6xl mx-auto px-4 sm:px-6 lg:px-10 py-10 space-y-10">
        <UploadZone
          status={uploadStatus}
          dragActive={dragActive}
          setDragActive={setDragActive}
          onFile={handleFile}
          onDemo={handleDemo}
          businesses={businesses}
          activeBusiness={activeBusiness}
          fileRef={fileRef}
          loadingMsg={loadingMsg}
        />

        {error && (
          <p className="text-red-600 bg-red-50 rounded-lg px-4 py-3 border border-red-100 text-[15px]">
            {error}
          </p>
        )}

        {uploadStatus === 'done' && metrics && (
          <div className="space-y-10 animate-fade-up">
            <KpiRow metrics={metrics} uploadResult={uploadResult} />

            {flagged.length > 0 && (
              <FlaggedTable rows={flagged} onApprove={setToast} />
            )}

            {flagged.length === 0 && (
              <p className="text-center text-gray-400 py-8 text-lg">
                No negative reviews found — great news!
              </p>
            )}
          </div>
        )}

        {uploadStatus === 'idle' && <EmptyState />}
      </main>

      <Footer />
    </div>
  )
}

// ── Sub-components ────────────────────────────────────────────────────────

function Header() {
  const patternSvg = [
    '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100">',
    '<g stroke="rgb(255,255,255)" fill="none" opacity="0.07">',
    '<rect x="15" y="24" width="14" height="16" rx="1.5" stroke-width="1.2"/>',
    '<path d="M18 24V19a4 4 0 018 0v5" stroke-width="1.2"/>',
    '</g>',
    '<path d="M70 15l2.5 5.1 5.6.8-4.1 4 1 5.6-5-2.6-5 2.6 1-5.6-4.1-4 5.6-.8z" fill="rgb(255,255,255)" fill-opacity="0.06"/>',
    '<g fill="rgb(255,255,255)" opacity="0.05">',
    '<rect x="40" y="70" width="4" height="12" rx="0.5"/>',
    '<rect x="46" y="65" width="4" height="17" rx="0.5"/>',
    '<rect x="52" y="60" width="4" height="22" rx="0.5"/>',
    '</g>',
    '</svg>',
  ].join('')

  return (
    <header className="bg-brand-900 text-white w-full relative overflow-hidden">
      {/* Subtle e-commerce pattern overlay */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          backgroundImage: `url("data:image/svg+xml,${encodeURIComponent(patternSvg)}")`,
          backgroundRepeat: 'repeat',
        }}
      />
      <div className="relative max-w-6xl mx-auto px-4 sm:px-6 lg:px-10 py-8 flex items-center justify-between">
        <div>
          <h1 className="text-4xl font-extrabold tracking-tight">
            Raaye
          </h1>
          <p className="text-brand-200 mt-1.5 text-[15px] font-medium">
            Turn customer reviews into action — AI-powered insights for Pakistani SMEs
          </p>
        </div>
        <BarChart3 className="w-9 h-9 text-brand-200" />
      </div>
    </header>
  )
}

function Footer() {
  const patternSvg = [
    '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100">',
    '<g stroke="rgb(255,255,255)" fill="none" opacity="0.07">',
    '<rect x="15" y="24" width="14" height="16" rx="1.5" stroke-width="1.2"/>',
    '<path d="M18 24V19a4 4 0 018 0v5" stroke-width="1.2"/>',
    '</g>',
    '<path d="M70 15l2.5 5.1 5.6.8-4.1 4 1 5.6-5-2.6-5 2.6 1-5.6-4.1-4 5.6-.8z" fill="rgb(255,255,255)" fill-opacity="0.06"/>',
    '<g fill="rgb(255,255,255)" opacity="0.05">',
    '<rect x="40" y="70" width="4" height="12" rx="0.5"/>',
    '<rect x="46" y="65" width="4" height="17" rx="0.5"/>',
    '<rect x="52" y="60" width="4" height="22" rx="0.5"/>',
    '</g>',
    '</svg>',
  ].join('')

  return (
    <footer className="bg-brand-900 text-white w-full relative overflow-hidden mt-10">
      {/* Subtle e-commerce pattern overlay — matches header */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          backgroundImage: `url("data:image/svg+xml,${encodeURIComponent(patternSvg)}")`,
          backgroundRepeat: 'repeat',
        }}
      />
      <div className="relative text-center py-8">
        <p className="text-white font-medium text-[15px]">
          Raaye — Built for the Alibaba Cloud AI Hackathon 2026
        </p>
        <p className="text-brand-200 text-[13px] mt-1.5">
          Powered by Qwen (Alibaba Cloud Model Studio)
        </p>
      </div>
    </footer>
  )
}

function UploadZone({ status, dragActive, setDragActive, onFile, onDemo, businesses, activeBusiness, fileRef, loadingMsg }) {
  const isIdle = status !== 'uploading'

  const BUSINESS_ICONS = {
    electronics: <Cpu className="w-7 h-7" />,
    fashion: <Shirt className="w-7 h-7" />,
  }

  const BUSINESS_COLORS = {
    electronics: {
      active: 'bg-blue-50 border-blue-200 ring-2 ring-blue-300 shadow-md',
      idle: 'bg-white border-gray-200 hover:bg-blue-100 hover:border-blue-200 hover:shadow-md',
      text: 'text-blue-700',
      icon: 'text-blue-500',
      dot: 'bg-blue-500',
    },
    fashion: {
      active: 'bg-pink-50 border-pink-200 ring-2 ring-pink-300 shadow-md',
      idle: 'bg-white border-gray-200 hover:bg-pink-100 hover:border-pink-200 hover:shadow-md',
      text: 'text-pink-700',
      icon: 'text-pink-500',
      dot: 'bg-pink-500',
    },
  }

  const DEFAULT_COLORS = {
    active: 'bg-indigo-50 border-indigo-200 ring-2 ring-indigo-300 shadow-md',
    idle: 'bg-white border-gray-200 hover:bg-indigo-100 hover:border-indigo-200 hover:shadow-md',
    text: 'text-indigo-700',
    icon: 'text-indigo-500',
    dot: 'bg-indigo-500',
  }

  return (
    <div className="space-y-4">
      <section
        role="button"
        tabIndex={0}
        className={`
          relative border-2 border-dashed rounded-2xl p-14 text-center transition-all duration-200
          cursor-pointer select-none
          ${dragActive
            ? 'border-indigo-500 bg-indigo-50 scale-[1.01] shadow-lg shadow-indigo-100'
            : isIdle
              ? 'border-gray-300 bg-white hover:border-indigo-400 hover:bg-indigo-50/40 hover:shadow-md'
              : 'border-gray-200 bg-white cursor-wait'}
        `}
        onDragOver={(e) => { e.preventDefault(); setDragActive(true) }}
        onDragLeave={() => setDragActive(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragActive(false)
          if (e.dataTransfer.files[0]) onFile(e.dataTransfer.files[0])
        }}
        onClick={() => isIdle && fileRef.current?.click()}
        onKeyDown={(e) => isIdle && (e.key === 'Enter' || e.key === ' ') && fileRef.current?.click()}
      >
        {status === 'uploading' ? (
          <div className="flex flex-col items-center gap-5">
            <div className="w-14 h-14 border-4 border-indigo-500 border-t-transparent rounded-full animate-spin" />
            <p className="text-indigo-700 font-bold text-xl transition-all duration-300">
              {loadingMsg}
            </p>
            <p className="text-gray-400 text-[15px]">This may take a moment for large datasets</p>
          </div>
        ) : (
          <>
            <Upload className="w-14 h-14 text-gray-300 mx-auto mb-5" />
            <p className="text-gray-700 font-bold text-xl">
              Drop your customer reviews CSV here, or{' '}
              <span className="text-indigo-600 underline underline-offset-2">browse files</span>
            </p>
            <p className="text-gray-400 mt-2.5 text-[15px]">
              Supports CSV with a &ldquo;review&rdquo; or &ldquo;Reviews&rdquo; column
            </p>
            <input
              ref={fileRef}
              type="file"
              accept=".csv"
              className="hidden"
              onChange={(e) => e.target.files[0] && onFile(e.target.files[0])}
            />
          </>
        )}
      </section>

      {/* Demo business selector */}
      {businesses.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <Play className="w-4 h-4 text-indigo-500" />
            <span className="text-sm font-semibold text-gray-500 uppercase tracking-wider">
              Or try a demo business
            </span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {businesses.map((biz) => {
              const colors = BUSINESS_COLORS[biz.id] || DEFAULT_COLORS
              const isActive = activeBusiness === biz.id && status === 'done'
              return (
                <button
                  key={biz.id}
                  className={`
                    group relative text-left rounded-xl p-5 border-2 transition-all duration-200
                    ${isActive ? colors.active : colors.idle}
                    ${status === 'uploading' ? 'opacity-50 cursor-wait' : 'cursor-pointer'}
                  `}
                  onClick={() => status !== 'uploading' && onDemo(biz.id)}
                  disabled={status === 'uploading'}
                >
                  <div className="flex items-start gap-3.5">
                    <div className={`${colors.icon} shrink-0 mt-0.5`}>
                      {BUSINESS_ICONS[biz.id] || <Store className="w-7 h-7" />}
                    </div>
                    <div className="min-w-0">
                      <h3 className={`font-bold text-[16px] leading-tight ${colors.text}`}>
                        {biz.name}
                      </h3>
                      <p className="text-gray-500 text-[13px] mt-1 leading-snug">
                        {biz.description}
                      </p>
                      <span className="inline-block mt-2.5 text-xs font-semibold bg-gray-100 text-gray-500 rounded-full px-2.5 py-1">
                        {biz.review_count} reviews
                      </span>
                    </div>
                  </div>
                  {isActive && (
                    <div className={`absolute top-3 right-3 w-2.5 h-2.5 rounded-full ${colors.dot}`} />
                  )}
                </button>
              )
            })}
          </div>
          <p className="text-gray-400 text-xs mt-2">
            Instantly loads cached results &mdash; no API calls needed
          </p>
        </div>
      )}
    </div>
  )
}

function KpiRow({ metrics, uploadResult }) {
  return (
    <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
      <KpiCard
        icon={<FileText className="w-6 h-6 text-indigo-600" />}
        label="Reviews Analyzed"
        value={metrics.total}
      />
      <KpiCard
        icon={<AlertTriangle className="w-6 h-6 text-orange-500" />}
        label="Negative Reviews"
        value={`${metrics.negPct}%`}
        sub={`${metrics.posPct}% positive \u00b7 ${metrics.neuPct}% neutral`}
        accent={metrics.negPct > 25}
      />
      <KpiCard
        icon={<MessageSquare className="w-6 h-6 text-red-500" />}
        label="Top Complaint"
        value={metrics.topComplaint ? capitalize(metrics.topComplaint) : 'None'}
        sub={
          uploadResult?.actions_saved != null
            ? `${uploadResult.actions_saved} auto-replies drafted`
            : undefined
        }
      />
      <KpiCard
        icon={<Zap className="w-6 h-6 text-amber-500" />}
        label="Work Saved"
        value={`${metrics.hoursSaved}h`}
        sub={`~${metrics.total * 2} min of manual review`}
        highlight
      />
    </section>
  )
}

function KpiCard({ icon, label, value, sub, accent, highlight }) {
  return (
    <div
      className={`
        rounded-xl p-6 shadow-md border transition-shadow hover:shadow-lg
        ${accent
          ? 'bg-orange-50 border-orange-200'
          : highlight
            ? 'bg-amber-50 border-amber-200'
            : 'bg-white border-gray-100'}
      `}
    >
      <div className="flex items-center gap-2.5 mb-3">
        {icon}
        <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
          {label}
        </span>
      </div>
      <p className={`text-3xl font-extrabold tracking-tight leading-none ${
        accent ? 'text-orange-700' : highlight ? 'text-amber-700' : 'text-gray-900'
      }`}>
        {value}
      </p>
      {sub && <p className="text-gray-500 mt-2 text-sm">{sub}</p>}
    </div>
  )
}

function FlaggedTable({ rows, onApprove }) {
  const [expanded, setExpanded] = useState({})
  const [editing, setEditing] = useState(null)
  const [drafts, setDrafts] = useState({})
  const [approved, setApproved] = useState({})

  function handleApprove(id) {
    setApproved((a) => ({ ...a, [id]: true }))
    onApprove('Reply approved and queued for sending!')
    setTimeout(() => setApproved((a) => ({ ...a, [id]: false })), 2500)
  }

  return (
    <section>
      <h2 className="text-2xl font-bold text-gray-900 mb-6 flex items-center gap-3">
        <AlertTriangle className="w-7 h-7 text-orange-500" />
        Flagged Negative Reviews
        <span className="text-lg font-normal text-gray-400">({rows.length})</span>
      </h2>

      <div className="space-y-5">
        {rows.map((r) => {
          const isOpen = expanded[r.id]
          const isEditing = editing === r.id
          const currentDraft = drafts[r.id] ?? r.reply
          const isApproved = approved[r.id]
          const borderColor = r.severity === 'high' ? 'border-l-red-500' : 'border-l-orange-400'

          return (
            <div
              key={r.id}
              className={`bg-white rounded-xl shadow-md border border-gray-100 border-l-[5px] ${borderColor} overflow-hidden transition-shadow hover:shadow-lg`}
            >
              <div className="px-7 py-6">
                {/* Review text */}
                <p className="text-gray-800 leading-relaxed text-[16px]">
                  {r.text}
                </p>

                {/* Aspect badges */}
                <div className="flex flex-wrap gap-2.5 mt-4">
                  {r.negAspects.map((a, i) => (
                    <span
                      key={i}
                      className={`
                        inline-flex items-center gap-1.5 font-semibold rounded-full px-3.5 py-1 text-[13px]
                        ${a.confidence >= 0.85
                          ? 'bg-red-100 text-red-800 ring-1 ring-red-200'
                          : 'bg-orange-100 text-orange-800 ring-1 ring-orange-200'}
                      `}
                    >
                      <AlertCircle className={`w-3.5 h-3.5 ${a.confidence >= 0.85 ? 'text-red-500' : 'text-orange-500'}`} />
                      {capitalize(a.aspect)}
                      <span className={`font-extrabold ${a.confidence >= 0.85 ? 'text-red-600' : 'text-orange-600'}`}>
                        {Math.round(a.confidence * 100)}%
                      </span>
                    </span>
                  ))}
                </div>

                {/* Reply preview (collapsed) */}
                {currentDraft && !isOpen && (
                  <div className="mt-5 bg-indigo-50/50 rounded-xl px-5 py-4 border border-indigo-100">
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-xs font-bold text-indigo-700 uppercase tracking-wider flex items-center gap-1.5">
                        <MessageSquare className="w-3.5 h-3.5" />
                        AI Auto-Reply Draft
                      </span>
                      <span className="text-[10px] font-semibold bg-indigo-100 text-indigo-600 rounded-full px-2 py-0.5 uppercase tracking-wide">
                        AI Generated
                      </span>
                    </div>
                    <p className="text-gray-600 line-clamp-2 text-[15px] leading-relaxed">
                      {currentDraft}
                    </p>
                    <button
                      className="text-indigo-600 hover:text-indigo-700 text-sm font-semibold mt-2 flex items-center gap-1"
                      onClick={() => setExpanded((e) => ({ ...e, [r.id]: true }))}
                    >
                      View full reply <ChevronDown className="w-4 h-4" />
                    </button>
                  </div>
                )}

                {/* Reply expanded */}
                {currentDraft && isOpen && (
                  <div className="mt-5 bg-indigo-50/50 rounded-xl p-6 border border-indigo-100 animate-fade-up">
                    <div className="flex items-center justify-between mb-3">
                      <span className="text-sm font-bold text-indigo-700 uppercase tracking-wider flex items-center gap-1.5">
                        <MessageSquare className="w-4 h-4" />
                        AI Auto-Reply Draft
                      </span>
                      <div className="flex items-center gap-3">
                        <span className="text-[10px] font-semibold bg-indigo-100 text-indigo-600 rounded-full px-2 py-0.5 uppercase tracking-wide">
                          AI Generated
                        </span>
                        <button
                          className="text-gray-400 hover:text-gray-600 transition-colors"
                          onClick={() => {
                            if (isEditing) {
                              setDrafts((d) => ({ ...d, [r.id]: currentDraft }))
                            }
                            setEditing(isEditing ? null : r.id)
                          }}
                        >
                          {isEditing ? (
                            <Check className="w-5 h-5 text-emerald-600" />
                          ) : (
                            <Pencil className="w-5 h-5" />
                          )}
                        </button>
                        <button
                          className="text-gray-400 hover:text-gray-600 transition-colors"
                          onClick={() => setExpanded((e) => ({ ...e, [r.id]: false }))}
                        >
                          <ChevronUp className="w-5 h-5" />
                        </button>
                      </div>
                    </div>

                    {isEditing ? (
                      <textarea
                        className="w-full bg-white border border-indigo-200 rounded-lg p-4 text-[15px] focus:outline-none focus:ring-2 focus:ring-indigo-400 resize-y"
                        rows={3}
                        defaultValue={currentDraft || ''}
                        onChange={(e) =>
                          setDrafts((d) => ({ ...d, [r.id]: e.target.value }))
                        }
                      />
                    ) : (
                      <p className="text-gray-700 leading-relaxed text-[16px]">
                        {currentDraft}
                      </p>
                    )}

                    {/* Approve & Send button */}
                    <div className="mt-4 pt-4 border-t border-indigo-100 flex items-center gap-3">
                      <button
                        className={`
                          inline-flex items-center gap-2 px-5 py-2.5 rounded-lg font-semibold text-sm
                          transition-all duration-200
                          ${isApproved
                            ? 'bg-emerald-600 text-white cursor-default'
                            : 'bg-indigo-600 text-white hover:bg-indigo-700 active:scale-[0.97]'}
                        `}
                        onClick={() => !isApproved && handleApprove(r.id)}
                        disabled={isApproved}
                      >
                        {isApproved ? (
                          <>
                            <Check className="w-4 h-4" />
                            Approved!
                          </>
                        ) : (
                          <>
                            <Send className="w-4 h-4" />
                            Approve &amp; Send
                          </>
                        )}
                      </button>
                      {!isApproved && (
                        <span className="text-xs text-gray-400">
                          Sends via configured channel
                        </span>
                      )}
                    </div>
                  </div>
                )}

                {/* No reply generated */}
                {!currentDraft && (
                  <p className="mt-5 text-gray-400 italic text-[15px]">
                    No reply generated — confidence may be below threshold.
                  </p>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}

function EmptyState() {
  return (
    <section className="text-center py-28 animate-fade-up">
      <FileText className="w-16 h-16 text-gray-200 mx-auto mb-6" />
      <h2 className="text-2xl font-bold text-gray-700">
        Upload your reviews to get started
      </h2>
      <p className="text-gray-400 mt-3 max-w-lg mx-auto text-lg leading-relaxed">
        Export your customer reviews as a CSV file and drop it above,
        or select a <strong className="text-indigo-500">demo business</strong> below to see
        Raaye in action instantly.
      </p>
    </section>
  )
}

// ── Helpers ──────────────────────────────────────────────────────────────

function capitalize(s) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s
}
