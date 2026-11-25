import { useEffect, useState } from 'react'
import { ask, getMeta, getProfile, getRequirements } from './api.js'

const EXAMPLES = [
  { label: 'Merawat hewan', text: 'Saya suka merawat hewan dan membantu dokter hewan.' },
  { label: 'Analisis data', text: 'Saya suka menganalisis data dan membangun model.' },
  { label: 'Mendesain bangunan', text: 'Saya suka mendesain bangunan dan menata ruang.' },
  { label: 'Mengajar anak', text: 'Saya suka mengajar anak-anak di sekolah dasar.' },
  { label: 'Tanya pendidikan', text: 'Apa pendidikan minimum pekerjaan Ilmuwan Data?' },
  { label: 'Tanya tugas', text: 'Apa 5 tugas inti pekerjaan Ilmuwan Data?' },
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

function ResultCard({ item, index, onShowRequirements, onShowProfile }) {
  const tone = TONES[index % TONES.length]
  const tier = TIERS[item.tier] || { label: item.tier, tone: 'low' }
  const scores = item.component_scores || {}
  const evidence = (item.evidence || []).slice(0, 2)
  const education = (item.evidence || []).find(
    (entry) => entry.kind === 'education'
  )

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
      {education?.detail ? (
        <p className="education">Min. pendidikan: {education.detail}</p>
      ) : null}
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

      {item.skill_gap ? (
        <span className="skill-flag skill-flag--gap">Ada skill gap</span>
      ) : item.skill_ready ? (
        <span className="skill-flag skill-flag--ok">Skill sesuai</span>
      ) : null}

      <button
        type="button"
        className="requirement-link"
        onClick={() => onShowRequirements(item)}
      >
        Lihat kebutuhan
      </button>
      <button
        type="button"
        className="requirement-link"
        onClick={() => onShowProfile(item)}
      >
        Lihat profil
      </button>

      <span className="rank">#{item.rank}</span>
    </article>
  )
}

function RequirementModal({ data, title, loading, error, onClose }) {
  if (!loading && !data && !error) return null
  const occupation = data?.occupation
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="requirement-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <button type="button" className="modal-close" onClick={onClose} aria-label="Tutup">
          ×
        </button>
        <p className="eyebrow">Kebutuhan okupasi</p>
        <h2 id="requirement-title">{occupation?.title || title}</h2>
        {occupation?.soc ? <p className="soc">{occupation.soc}</p> : null}

        {loading ? <p className="modal-muted">Memuat requirement…</p> : null}
        {error ? <div className="banner" role="alert">{error}</div> : null}

        {data ? (
          <>
            <div className="requirement-facts">
              <div>
                <span className="requirement-label">Pendidikan minimum</span>
                <strong>{data.education?.label || data.education?.local || '—'}</strong>
              </div>
              <div>
                <span className="requirement-label">Job zone</span>
                <strong>
                  {data.job_zone?.value ?? '—'}
                  {data.job_zone?.name ? ` · ${data.job_zone.name}` : ''}
                </strong>
              </div>
            </div>

            {(data.requirements || []).map((category) => (
              <section className="requirement-section" key={category.key}>
                <h3>{category.label}</h3>
                {category.items?.length ? (
                  <ul className="requirement-list">
                    {category.items.map((item) => (
                      <li key={item.iri}>
                        <span>{item.label}</span>
                        <span
                          className="requirement-score"
                          title={
                            item.importance != null
                              ? `Importance ${Number(item.importance).toFixed(2)}`
                              : undefined
                          }
                        >
                          {item.level != null
                            ? `Lv ${Number(item.level).toFixed(2)}`
                            : Number(item.value || item.normalized || 0).toFixed(2)}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="modal-muted">Belum ada data.</p>
                )}
              </section>
            ))}
          </>
        ) : null}
      </section>
    </div>
  )
}

function OccupationProfileModal({ data, title, loading, error, onClose }) {
  if (!loading && !data && !error) return null
  const occupation = data?.occupation
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="occupation-profile-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <button type="button" className="modal-close" onClick={onClose} aria-label="Tutup">
          ×
        </button>
        <p className="eyebrow">Profil pekerjaan</p>
        <h2 id="occupation-profile-title">{occupation?.title_id || occupation?.title_en || title}</h2>
        {occupation?.soc ? <p className="soc">{occupation.soc}</p> : null}
        {loading ? <p className="modal-muted">Memuat profil pekerjaan…</p> : null}
        {error ? <div className="banner" role="alert">{error}</div> : null}
        {data ? (
          <>
            <section className="requirement-section">
              <h3>Tugas inti</h3>
              <ul className="requirement-list">
                {(data.tasks || []).slice(0, 5).map((task) => (
                  <li key={task.iri}>
                    <span>{task.task}</span>
                    {task.frequency ? (
                      <span className="requirement-score">{task.frequency}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </section>
            {(data.context_groups || []).map((group) => (
              <section className="requirement-section" key={group.key}>
                <h3>{group.label}</h3>
                <ul className="requirement-list">
                  {(group.elements || []).map((element) => {
                    const top = (element.items || [])[0]
                    return (
                      <li key={element.iri}>
                        <span>{element.label}</span>
                        {top ? (
                          <span className="requirement-score">
                            {top.label || top.value}
                          </span>
                        ) : null}
                      </li>
                    )
                  })}
                </ul>
              </section>
            ))}
          </>
        ) : null}
      </section>
    </div>
  )
}

function AnswerPanel({ data }) {
  const answer = data?.answer
  if (!answer) return null
  return (
    <section className="answer">
      <p className="eyebrow">
        {data.label || 'Jawaban'}
        {data.occupation?.title ? ` · ${data.occupation.title}` : ''}
      </p>
      {data.match === 'similar' ? (
        <p className="modal-muted">
          Pertanyaan ditafsirkan dari kemiripan teks, bukan kata kunci persis.
        </p>
      ) : null}
      <h2>{answer.heading}</h2>
      {answer.summary ? <p className="desc">{answer.summary}</p> : null}

      {answer.facts?.length ? (
        <div className="requirement-facts">
          {answer.facts.map((fact) => (
            <div key={fact.label}>
              <span className="requirement-label">{fact.label}</span>
              <strong>{fact.value || '-'}</strong>
            </div>
          ))}
        </div>
      ) : null}

      {answer.items?.length ? (
        <ul className="requirement-list">
          {answer.items.map((item, index) => (
            <li key={`${item.title}-${index}`}>
              <span>{item.title}</span>
              {item.detail ? <span className="requirement-score">{item.detail}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}

      {(answer.groups || []).map((group) => (
        <section className="requirement-section" key={group.heading}>
          <h3>{group.heading}</h3>
          {group.items?.length ? (
            <ul className="requirement-list">
              {group.items.map((item, index) => (
                <li key={`${item.title}-${index}`}>
                  <span>{item.title}</span>
                  {item.detail ? <span className="requirement-score">{item.detail}</span> : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="modal-muted">Belum ada data.</p>
          )}
        </section>
      ))}
    </section>
  )
}

function CandidatePicker({ data, onPick }) {
  return (
    <section className="answer">
      <p className="eyebrow">{data.label || 'Pilih pekerjaan'}</p>
      <h2>Pekerjaan mana yang dimaksud?</h2>
      <p className="desc">Nama yang Anda tulis cocok dengan beberapa pekerjaan.</p>
      <ul className="requirement-list">
        {(data.items || []).map((candidate) => (
          <li key={candidate.iri}>
            <span>{candidate.title}</span>
            <button
              type="button"
              className="requirement-link"
              onClick={() => onPick(candidate)}
            >
              Pilih
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}

function ProfilePanel({ profile }) {
  const holland = profile ? Object.entries(profile.holland || {}) : []
  const elements = profile ? profile.elements || [] : []
  const skills = profile ? profile.skills || [] : []

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

          {skills.length > 0 ? (
            <>
              <h3>Skill dinyatakan</h3>
              <ul className="elements">
                {skills.map((skill) => (
                  <li key={skill.label}>
                    <span>{skill.label}</span>
                    <b>{Number(skill.level).toFixed(1)}</b>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
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
        <li>
          <b>Pertanyaan</b> tentang satu pekerjaan dijawab langsung dari index: tugas, DWA,
          pendidikan, skill, dan konteks kerja.
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
  const [answer, setAnswer] = useState(null)
  const [candidates, setCandidates] = useState(null)
  const [interestText, setInterestText] = useState('')
  const [requirement, setRequirement] = useState(null)
  const [requirementTitle, setRequirementTitle] = useState('')
  const [requirementLoading, setRequirementLoading] = useState(false)
  const [requirementError, setRequirementError] = useState('')
  const [occupationProfile, setOccupationProfile] = useState(null)
  const [occupationProfileTitle, setOccupationProfileTitle] = useState('')
  const [occupationProfileLoading, setOccupationProfileLoading] = useState(false)
  const [occupationProfileError, setOccupationProfileError] = useState('')

  useEffect(() => {
    getMeta().then(setMeta).catch(() => setMeta(null))
  }, [])

  async function run(value) {
    const query = (value ?? text).trim()
    if (!query || loading) return
    setLoading(true)
    setError('')
    setAnswer(null)
    setCandidates(null)
    try {
      const data = await ask({
        text: query,
        language: 'id',
        education: education || null,
        max_job_zone: jobZone ? Number(jobZone) : null,
        top_k: 8,
        context: interestText || null,
      })
      if (data.mode === 'recommend') {
        setResult(data)
        setInterestText(query)
      } else if (data.mode === 'answer') {
        setResult(null)
        setAnswer(data)
      } else if (data.mode === 'disambiguate') {
        setResult(null)
        setCandidates({
          question: query,
          label: data.label,
          items: data.candidates || [],
        })
      } else {
        setResult(null)
        setAnswer({
          label: data.label,
          occupation: null,
          answer: {
            heading: 'Nama pekerjaan belum dikenali',
            summary: data.message || 'Sebutkan nama pekerjaan dengan lebih jelas.',
            facts: [],
            items: [],
            groups: [],
          },
        })
      }
    } catch (err) {
      setError(err.message)
      setResult(null)
      setAnswer(null)
    } finally {
      setLoading(false)
    }
  }

  async function pickCandidate(candidate) {
    const question = candidates?.question || text
    if (loading) return
    setLoading(true)
    setError('')
    setCandidates(null)
    try {
      const data = await ask({
        text: question,
        language: 'id',
        education: education || null,
        max_job_zone: jobZone ? Number(jobZone) : null,
        top_k: 8,
        context: interestText || null,
        occupation: candidate.iri,
      })
      if (data.mode === 'answer') {
        setResult(null)
        setAnswer(data)
      } else if (data.mode === 'recommend') {
        setResult(data)
        setInterestText(question)
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  function onSubmit(event) {
    event.preventDefault()
    run()
  }

  async function showRequirements(item) {
    setRequirement(null)
    setRequirementTitle(item.title || '')
    setRequirementError('')
    setRequirementLoading(true)
    try {
      const data = await getRequirements(item.occupation_iri, 'id')
      setRequirement(data)
    } catch (err) {
      setRequirementError(err.message)
    } finally {
      setRequirementLoading(false)
    }
  }

  function closeRequirements() {
    setRequirement(null)
    setRequirementTitle('')
    setRequirementError('')
    setRequirementLoading(false)
  }

  async function showProfile(item) {
    setOccupationProfile(null)
    setOccupationProfileTitle(item.title || '')
    setOccupationProfileError('')
    setOccupationProfileLoading(true)
    try {
      const data = await getProfile(item.occupation_iri, 'id')
      setOccupationProfile(data)
    } catch (err) {
      setOccupationProfileError(err.message)
    } finally {
      setOccupationProfileLoading(false)
    }
  }

  function closeProfile() {
    setOccupationProfile(null)
    setOccupationProfileTitle('')
    setOccupationProfileError('')
    setOccupationProfileLoading(false)
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
                placeholder="Contoh: Saya suka merawat hewan dan membantu dokter hewan. Atau tanya: Apa pendidikan minimum pekerjaan Ilmuwan Data?"
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
                  {loading ? 'Memproses…' : 'Cari atau tanya'}
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
              <h2>{answer ? 'Jawaban' : candidates ? 'Pilih pekerjaan' : 'Rekomendasi'}</h2>
              {result ? (
                <span>
                  {recommendations.length} okupasi
                  {result.meta ? ` · ${result.meta.elapsed_ms} ms` : ''}
                </span>
              ) : null}
              {answer?.occupation?.soc ? <span>{answer.occupation.soc}</span> : null}
            </div>

            {loading ? <Skeletons /> : null}

            {!loading && !answer && !candidates && !result ? (
              <div className="intro">
                <p>
                  Tulis minatmu untuk mendapat rekomendasi, atau tanyakan hal spesifik tentang
                  satu pekerjaan, misalnya “Apa pendidikan minimum pekerjaan Ilmuwan Data?”.
                </p>
              </div>
            ) : null}

            {!loading && answer ? <AnswerPanel data={answer} /> : null}

            {!loading && candidates ? (
              <CandidatePicker data={candidates} onPick={pickCandidate} />
            ) : null}

            {!loading && result && recommendations.length === 0 ? (
              <div className="intro">
                <p>
                  Belum ada elemen yang dikenali. Coba sebutkan aktivitas atau bidang yang lebih
                  spesifik, misalnya “merawat hewan” atau “menganalisis data”.
                </p>
              </div>
            ) : null}

            {!loading && result && recommendations.length > 0 ? (
              <div className="cards">
                {recommendations.map((item, index) => (
                  <ResultCard
                    key={item.occupation_iri}
                    item={item}
                    index={index}
                    onShowRequirements={showRequirements}
                    onShowProfile={showProfile}
                  />
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
      <RequirementModal
        data={requirement}
        title={requirementTitle}
        loading={requirementLoading}
        error={requirementError}
        onClose={closeRequirements}
      />
      <OccupationProfileModal
        data={occupationProfile}
        title={occupationProfileTitle}
        loading={occupationProfileLoading}
        error={occupationProfileError}
        onClose={closeProfile}
      />
    </div>
  )
}