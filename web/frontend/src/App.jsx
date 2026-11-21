import { useEffect, useState } from 'react'
import { getMeta, recommend } from './api.js'

const EXAMPLES = [
  { label: 'Merawat hewan', text: 'Saya suka merawat hewan dan membantu dokter hewan.' },
  { label: 'Analisis data', text: 'Saya suka menganalisis data dan membangun model.' },
  { label: 'Mendesain bangunan', text: 'Saya suka mendesain bangunan dan menata ruang.' },
  { label: 'Mengajar anak', text: 'Saya suka mengajar anak-anak di sekolah dasar.' },
]

const TONES = ['rose', 'peach', 'sage', 'blue', 'butter']

const TIERS = {
  EligibleStrong: { label: 'Sangat cocok', tone: 'strong' },
  Eligible: { label: 'Cocok', tone: 'ok' },
  NotEligible: { label: 'Kurang cocok', tone: 'low' },
}

const COMPONENTS = {
  ontology: 'Ontology',
  element: 'Elemen',
  holland: 'Holland',
  semantic: 'Semantik',
  lexical: 'Leksikal',
}

const HOLLAND_ID = {
  Realistic: 'Realistis',
  Investigative: 'Investigatif',
  Artistic: 'Artistik',
  Social: 'Sosial',
  Enterprising: 'Wirausaha',
  Conventional: 'Konvensional',
}

function Icon({ name, size = 18 }) {
  const paths = {
    search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></>,
    user: <><circle cx="12" cy="8" r="4" /><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7" /></>,
    info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v6M12 7.5v.5" /></>,
    star: <path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1-5.4-2.9-5.4 2.9 1-6.1L3.2 9.5l6.1-.9Z" />,
    arrow: <path d="M5 12h14M13 6l6 6-6 6" />,
  }
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  )
}

function ResultCard({ item, index }) {
  const tone = TONES[index % TONES.length]
  const tier = TIERS[item.tier] || { label: item.tier, tone: 'low' }
  const scores = item.component_scores || {}
  const evidence = (item.evidence || []).slice(0, 2)

  return (
    <article className={`card card--${tone}`}>
      <div className="card-top">
        <span className={`tier tier--${tier.tone}`}>{tier.label}</span>
        <span className="score" title="Skor akhir">
          <Icon name="star" size={13} />
          {Number(item.score).toFixed(2)}
        </span>
      </div>

      <h3>{item.title}</h3>
      <p className="soc">{item.soc}</p>
      {item.description ? <p className="desc">{item.description}</p> : null}

      <div className="components">
        {Object.keys(COMPONENTS)
          .filter((key) => key in scores)
          .map((key) => (
            <div className="comp" key={key}>
              <span>{COMPONENTS[key]}</span>
              <span className="bar">
                <i style={{ width: `${Math.round(Math.min(1, scores[key]) * 100)}%` }} />
              </span>
            </div>
          ))}
      </div>

      {evidence.length > 0 ? (
        <ul className="evidence">
          {evidence.map((entry, i) => (
            <li key={i}>{entry.label}</li>
          ))}
        </ul>
      ) : null}

      <span className="rank">#{item.rank}</span>
    </article>
  )
}

function ProfilePanel({ profile }) {
  const holland = profile ? Object.entries(profile.holland || {}) : []
  const elements = profile ? profile.elements || [] : []

  return (
    <section className="panel" aria-live="polite">
      <div className="panel-head">
        <span className="avatar">OR</span>
        <div>
          <h2>Profil terdeteksi</h2>
          <p className="muted">Dari teks yang kamu tulis</p>
        </div>
      </div>

      {profile ? (
        <>
          <div className="facts">
            <span>{profile.education_level || 'Pendidikan —'}</span>
            <span>Job zone {profile.max_job_zone ?? '—'}</span>
          </div>

          <h3>Holland</h3>
          {holland.length > 0 ? (
            <div className="chips">
              {holland.map(([code, weight]) => (
                <span className="chip" key={code}>
                  {HOLLAND_ID[code] || code}
                  <b>{Number(weight).toFixed(2)}</b>
                </span>
              ))}
            </div>
          ) : (
            <p className="muted">Belum terdeteksi.</p>
          )}

          <h3>Elemen O*NET</h3>
          {elements.length > 0 ? (
            <ul className="elements">
              {elements.map((element) => (
                <li key={element.label}>
                  <span>{element.label}</span>
                  <span className="bar">
                    <i
                      style={{
                        width: `${Math.round(Math.min(1, element.weight) * 100)}%`,
                      }}
                    />
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">Belum terdeteksi.</p>
          )}
        </>
      ) : (
        <p className="muted">
          Tulis minatmu lalu cari. Elemen dan kode Holland yang terbaca akan muncul di sini.
        </p>
      )}
    </section>
  )
}

function HowItWorks() {
  return (
    <section className="panel panel--plain" id="tentang">
      <h2>Cara kerjanya</h2>
      <ol className="steps">
        <li>
          <b>Teks bebas</b> diekstrak menjadi profil: Holland, pendidikan, dan elemen O*NET.
        </li>
        <li>
          <b>Ontology traversal</b> mencocokkan elemen ke okupasi lewat SPARQL, plus satu hop
          okupasi terkait.
        </li>
        <li>
          <b>Peringkat</b> menggabungkan Holland, elemen, dan kecocokan ontology.
        </li>
      </ol>
    </section>
  )
}

function Skeletons() {
  return (
    <div className="cards" aria-hidden="true">
      {[0, 1, 2, 3].map((i) => (
        <div className="card skeleton" key={i} />
      ))}
    </div>
  )
}

export default function App() {
  const [meta, setMeta] = useState(null)
  const [text, setText] = useState('')
  const [education, setEducation] = useState('')
  const [jobZone, setJobZone] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)

  useEffect(() => {
    getMeta().then(setMeta).catch(() => setMeta(null))
  }, [])

  async function run(value) {
    const query = (value ?? text).trim()
    if (!query || loading) return
    setLoading(true)
    setError('')
    try {
      const data = await recommend({
        text: query,
        language: 'id',
        education: education || null,
        max_job_zone: jobZone ? Number(jobZone) : null,
        top_k: 8,
      })
      setResult(data)
    } catch (err) {
      setError(err.message)
      setResult(null)
    } finally {
      setLoading(false)
    }
  }

  function onSubmit(event) {
    event.preventDefault()
    run()
  }

  const levels = meta?.education_levels || []
  const recommendations = result?.recommendations || []

  return (
    <div className="page">
      <div className="shell">
        <aside className="rail" aria-label="Navigasi">
          <span className="rail-logo">OR</span>
          <nav className="rail-nav">
            <a className="rail-btn is-active" href="#cari" aria-label="Cari karier">
              <Icon name="search" />
            </a>
            <a className="rail-btn" href="#profil" aria-label="Profil terdeteksi">
              <Icon name="user" />
            </a>
            <a className="rail-btn" href="#tentang" aria-label="Cara kerja">
              <Icon name="info" />
            </a>
          </nav>
          <span className="rail-dot" title="Ontology aktif" />
        </aside>

        <main className="main">
          <header className="hero">
            <p className="eyebrow">OntoRAG · O*NET + SPARQL</p>
            <h1>
              Temukan karier
              <br />
              yang cocok untukmu.
            </h1>
            <p className="lede">
              Ceritakan minat, aktivitas, atau pengalamanmu. Sistem mencari lewat ontologi
              okupasi, bukan sekadar kemiripan kata.
            </p>
          </header>

          <section className="search" id="cari">
            <form onSubmit={onSubmit}>
              <label className="sr-only" htmlFor="profil-teks">
                Ceritakan minatmu
              </label>
              <textarea
                id="profil-teks"
                value={text}
                onChange={(event) => setText(event.target.value)}
                rows={4}
                maxLength={2000}
                placeholder="Contoh: Saya suka merawat hewan dan membantu dokter hewan. Saya lulusan S1."
              />

              <div className="controls">
                <label className="ctrl">
                  Pendidikan
                  <select value={education} onChange={(event) => setEducation(event.target.value)}>
                    <option value="">Otomatis</option>
                    {levels.map((level) => (
                      <option key={level.value} value={level.value}>
                        {level.label} ({level.value})
                      </option>
                    ))}
                  </select>
                </label>

                <label className="ctrl">
                  Job zone
                  <select value={jobZone} onChange={(event) => setJobZone(event.target.value)}>
                    <option value="">Otomatis</option>
                    {[1, 2, 3, 4, 5].map((zone) => (
                      <option key={zone} value={zone}>
                        {zone}
                      </option>
                    ))}
                  </select>
                </label>

                <span className="ctrl ctrl--static">
                  Retrieval
                  <strong>{meta?.retrieval || 'memuat…'}</strong>
                </span>

                <button className="go" type="submit" disabled={loading || !text.trim()}>
                  {loading ? 'Mencari…' : 'Cari karier'}
                  {!loading ? <Icon name="arrow" size={16} /> : null}
                </button>
              </div>
            </form>

            <div className="examples">
              <span>Contoh:</span>
              {EXAMPLES.map((example) => (
                <button
                  type="button"
                  key={example.label}
                  onClick={() => {
                    setText(example.text)
                    run(example.text)
                  }}
                >
                  {example.label}
                </button>
              ))}
            </div>
          </section>

          {error ? (
            <div className="banner" role="alert">
              {error}
            </div>
          ) : null}

          <section className="results" aria-live="polite">
            <div className="section-head">
              <h2>Rekomendasi</h2>
              {result ? (
                <span>
                  {recommendations.length} okupasi
                  {result.meta ? ` · ${result.meta.elapsed_ms} ms` : ''}
                </span>
              ) : null}
            </div>

            {loading ? <Skeletons /> : null}

            {!loading && !result ? (
              <div className="intro">
                <p>
                  Tulis minatmu di atas, atau pilih salah satu contoh. Hasil akan muncul sebagai
                  kartu berisi skor dan elemen ontology yang cocok.
                </p>
              </div>
            ) : null}

            {!loading && result && recommendations.length === 0 ? (
              <div className="intro">
                <p>
                  Belum ada elemen yang dikenali. Coba sebutkan aktivitas atau bidang yang lebih
                  spesifik, misalnya “merawat hewan” atau “menganalisis data”.
                </p>
              </div>
            ) : null}

            {!loading && recommendations.length > 0 ? (
              <div className="cards">
                {recommendations.map((item, index) => (
                  <ResultCard key={item.occupation_iri} item={item} index={index} />
                ))}
              </div>
            ) : null}
          </section>
        </main>

        <aside className="side">
          <div id="profil">
            <ProfilePanel profile={result?.profile} />
          </div>
          <HowItWorks />
        </aside>
      </div>
    </div>
  )
}