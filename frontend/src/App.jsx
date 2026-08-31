import { useState, useRef, useMemo } from 'react'
import {
  Upload, FileText, AlertTriangle, CheckCircle, BarChart3,
  MessageSquare, ChevronDown, ChevronUp, Pencil, X, Check,
} from 'lucide-react'

const API_BASE = ''  // same origin via Vite proxy

// ── Main App ────────────────────────────────────────────────────────────

export default function App() {
  const [uploadStatus, setUploadStatus] = useState('idle') // idle | uploading | done | error
  const [uploadResult, setUploadResult] = useState(null)
  const [reviews, setReviews] = useState([])
  const [dragActive, setDragActive] = useState(false)
  const [error, setError] = useState('')
  const fileRef = useRef(null)

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

      // fetch processed reviews for the table
      const revRes = await fetch(`${API_BASE}/api/reviews?limit=${data.reviews_saved || 100}`)
      if (revRes.ok) {
        setReviews(await revRes.json())
      }
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
          return {
            id: r.id,
            text: r.raw_text,
            negAspects,
            reply: replies[0]?.action_text || '',
          }
        })
        .filter(Boolean),
    [reviews],
  )

  // ── Render ─────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-gray-50">
      <Header />

      <main className="max-w-5xl mx-auto px-4 sm:px-6 py-8 space-y-8">
        {/* Upload */}
        <UploadZone
          status={uploadStatus}
          dragActive={dragActive}
          setDragActive={setDragActive}
          onFile={handleFile}
          fileRef={fileRef}
        />

        {error && (
          <p className="text-red-600 text-sm bg-red-50 rounded-lg px-4 py-2">
            {error}
          </p>
        )}

        {/* Results */}
        {uploadStatus === 'done' && metrics && (
          <div className="space-y-8 animate-fade-up">
            <KpiRow metrics={metrics} uploadResult={uploadResult} />

            {flagged.length > 0 && <FlaggedTable rows={flagged} />}

            {flagged.length === 0 && (
              <p className="text-center text-gray-400 py-6">
                No negative reviews found — great news!
              </p>
            )}
          </div>
        )}

        {/* Empty state */}
        {uploadStatus === 'idle' && <EmptyState />}
      </main>
    </div>
  )
}

// ── Sub-components ────────────────────────────────────────────────────────

function Header() {
  return (
    <header className="bg-brand-900 text-white">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 py-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            Raaye
          </h1>
          <p className="text-brand-200 text-sm mt-0.5">
            Feedback-to-Action Engine for Daraz Sellers
          </p>
        </div>
        <BarChart3 className="w-7 h-7 text-brand-200" />
      </div>
    </header>
  )
}

function UploadZone({ status, dragActive, setDragActive, onFile, fileRef }) {
  return (
    <section
      className={`
        relative border-2 border-dashed rounded-2xl p-8 text-center transition-all
        ${dragActive ? 'border-brand-500 bg-brand-50' : 'border-gray-300 bg-white hover:border-brand-400'}
      `}
      onDragOver={(e) => { e.preventDefault(); setDragActive(true) }}
      onDragLeave={() => setDragActive(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragActive(false)
        if (e.dataTransfer.files[0]) onFile(e.dataTransfer.files[0])
      }}
    >
      {status === 'uploading' ? (
        <div className="flex flex-col items-center gap-3">
          <div className="w-10 h-10 border-4 border-brand-500 border-t-transparent rounded-full animate-spin" />
          <p className="text-gray-600 font-medium">Analyzing reviews&hellip;</p>
          <p className="text-gray-400 text-sm">Running aspect-level sentiment analysis</p>
        </div>
      ) : (
        <>
          <Upload className="w-10 h-10 text-gray-400 mx-auto mb-3" />
          <p className="text-gray-700 font-medium">
            Drop your Daraz review CSV here, or{' '}
            <button
              className="text-brand-600 hover:text-brand-700 underline underline-offset-2"
              onClick={() => fileRef.current?.click()}
            >
              browse files
            </button>
          </p>
          <p className="text-gray-400 text-sm mt-1">
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
  )
}

function KpiRow({ metrics, uploadResult }) {
  return (
    <section className="grid grid-cols-1 sm:grid-cols-3 gap-4">
      <KpiCard
        icon={<FileText className="w-5 h-5 text-brand-600" />}
        label="Reviews Analyzed"
        value={metrics.total}
      />
      <KpiCard
        icon={<AlertTriangle className="w-5 h-5 text-orange-500" />}
        label="Negative Reviews"
        value={`${metrics.negPct}%`}
        sub={`${metrics.posPct}% positive \u00b7 ${metrics.neuPct}% neutral`}
        accent={metrics.negPct > 25}
      />
      <KpiCard
        icon={<MessageSquare className="w-5 h-5 text-red-500" />}
        label="Top Complaint"
        value={metrics.topComplaint ? capitalize(metrics.topComplaint) : 'None'}
        sub={
          uploadResult?.actions_saved != null
            ? `${uploadResult.actions_saved} auto-replies drafted`
            : undefined
        }
      />
    </section>
  )
}

function KpiCard({ icon, label, value, sub, accent }) {
  return (
    <div
      className={`
        rounded-xl p-5 shadow-sm border transition-shadow
        ${accent ? 'bg-orange-50 border-orange-200' : 'bg-white border-gray-100'}
      `}
    >
      <div className="flex items-center gap-2 mb-2">
        {icon}
        <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">
          {label}
        </span>
      </div>
      <p className={`text-2xl font-bold ${accent ? 'text-orange-700' : 'text-gray-900'}`}>
        {value}
      </p>
      {sub && <p className="text-sm text-gray-500 mt-1">{sub}</p>}
    </div>
  )
}

function FlaggedTable({ rows }) {
  const [expanded, setExpanded] = useState(null)
  const [editing, setEditing] = useState(null)
  const [drafts, setDrafts] = useState({})

  return (
    <section>
      <h2 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
        <AlertTriangle className="w-5 h-5 text-orange-500" />
        Flagged Negative Reviews
        <span className="text-sm font-normal text-gray-400">({rows.length})</span>
      </h2>

      <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden divide-y divide-gray-100">
        {rows.map((r) => {
          const isOpen = expanded === r.id
          const isEditing = editing === r.id
          const currentDraft = drafts[r.id] ?? r.reply

          return (
            <div key={r.id} className="px-5 py-4">
              {/* Row header */}
              <div className="flex items-start justify-between gap-4">
                <p className="text-gray-800 text-sm leading-relaxed flex-1 line-clamp-2">
                  {r.text}
                </p>
                <button
                  className="text-gray-400 hover:text-gray-600 shrink-0 mt-0.5"
                  onClick={() => setExpanded(isOpen ? null : r.id)}
                >
                  {isOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                </button>
              </div>

              {/* Aspect badges */}
              <div className="flex flex-wrap gap-1.5 mt-2">
                {r.negAspects.map((a, i) => (
                  <span
                    key={i}
                    className="inline-flex items-center gap-1 text-xs font-medium bg-red-50 text-red-700 rounded-full px-2.5 py-0.5"
                  >
                    {capitalize(a.aspect)}
                    <span className="text-red-400">
                      {Math.round(a.confidence * 100)}%
                    </span>
                  </span>
                ))}
              </div>

              {/* Expanded reply */}
              {isOpen && (
                <div className="mt-4 bg-blue-50 rounded-lg p-4 animate-fade-up">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-semibold text-brand-700 uppercase tracking-wide">
                      Auto-Reply Draft
                    </span>
                    <button
                      className="text-gray-400 hover:text-gray-600"
                      onClick={() => {
                        if (isEditing) {
                          setDrafts((d) => ({ ...d, [r.id]: currentDraft }))
                        }
                        setEditing(isEditing ? null : r.id)
                      }}
                    >
                      {isEditing ? (
                        <Check className="w-4 h-4 text-green-600" />
                      ) : (
                        <Pencil className="w-3.5 h-3.5" />
                      )}
                    </button>
                  </div>

                  {isEditing ? (
                    <textarea
                      className="w-full text-sm bg-white border border-blue-200 rounded-lg p-3 focus:outline-none focus:ring-2 focus:ring-brand-500 resize-y"
                      rows={3}
                      defaultValue={currentDraft || ''}
                      onChange={(e) =>
                        setDrafts((d) => ({ ...d, [r.id]: e.target.value }))
                      }
                    />
                  ) : (
                    <p className="text-sm text-gray-700 leading-relaxed">
                      {currentDraft || (
                        <span className="italic text-gray-400">
                          No reply generated — confidence may be below threshold.
                        </span>
                      )}
                    </p>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}

function EmptyState() {
  return (
    <section className="text-center py-20 animate-fade-up">
      <FileText className="w-14 h-14 text-gray-300 mx-auto mb-4" />
      <h2 className="text-xl font-semibold text-gray-700">
        Upload your reviews to get started
      </h2>
      <p className="text-gray-400 mt-2 max-w-md mx-auto">
        Export your Daraz reviews as a CSV file and drop it above.
        Raaye will analyze every review aspect-by-aspect and generate
        recovery replies for negative feedback.
      </p>
    </section>
  )
}

// ── Helpers ──────────────────────────────────────────────────────────────

function capitalize(s) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s
}
