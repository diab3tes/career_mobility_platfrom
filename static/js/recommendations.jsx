/* Matches island. Loaded as text/babel (prototype choice: compiled in the browser). */
const { useState, useEffect, useCallback, useRef } = React;

const INITIAL = JSON.parse(document.getElementById("initial-data").textContent);
// "matches" (all ranked roles) or "shortlist" (saved roles only). Same cards, same details panel.
const IS_SHORTLIST = INITIAL.view === "shortlist";
const URLS = INITIAL.urls;
// URL templates from Django use 0 as the id placeholder, e.g. /api/opportunities/0/ai-assessment/
const urlFor = (template, id) => template.replace("/0/", `/${id}/`);

function csrfToken() {
  const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

async function api(url, method = "GET", jsonBody = undefined) {
  const opts = { method, headers: { Accept: "application/json" }, credentials: "same-origin" };
  if (method !== "GET") opts.headers["X-CSRFToken"] = csrfToken();
  if (jsonBody !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(jsonBody); }
  const res = await fetch(url, opts);
  let body = null;
  try { body = await res.json(); } catch (_) { /* non-JSON error page */ }
  if (!res.ok) throw new Error((body && body.error) || `Request failed (${res.status})`);
  return body;
}

const CRIT_STATUS = {
  met: { label: "Met", cls: "ok" },
  partial: { label: "Partial", cls: "warn" },
  not_met: { label: "Not met", cls: "bad" },
  unknown: { label: "Unknown", cls: "warn" },
  not_applicable: { label: "Not applicable", cls: "neutral" },
};

/* "Skills: You match 4 of 4…" -> ["Skills", "You match 4 of 4…"] */
function splitReason(s) {
  const i = s.indexOf(": ");
  return i > 0 ? [s.slice(0, i), s.slice(i + 2)] : ["", s];
}

const REDUCE_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/* Counts from 0 to target once, in step with the ring drawing in. */
function useCountUp(target, delay = 0, ms = 1000) {
  const [v, setV] = useState(REDUCE_MOTION ? target : 0);
  useEffect(() => {
    if (REDUCE_MOTION) { setV(target); return; }
    let raf, start;
    const step = (t) => {
      if (start === undefined) start = t + delay;
      const k = Math.min(Math.max((t - start) / ms, 0), 1);
      setV(Math.round(target * (1 - Math.pow(1 - k, 3))));
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target]);
  return v;
}

function Ring({ score, small, index = 0 }) {
  const cls = score >= 75 ? "hi" : score >= 50 ? "mid" : "lo";
  const shown = useCountUp(score, index * 55 + 150);
  return (
    <div className={`ring ${cls}${small ? " sm" : ""}`} style={{ "--p": score, "--i": index }} role="img" aria-label={`Score ${score} out of 100`}>
      <svg viewBox="0 0 80 80" aria-hidden="true">
        <circle className="track" cx="40" cy="40" r="34" pathLength="100" />
        <circle className="val" cx="40" cy="40" r="34" pathLength="100" />
      </svg>
      <div className="num" aria-hidden="true"><span>{shown}<small>/100</small></span></div>
    </div>
  );
}

function Eligibility({ value, label }) {
  return <span className={`status ${value}`}>{label}</span>;
}

function SaveButton({ saved, busy, onToggle }) {
  return (
    <button type="button" className="btn btn-sm" onClick={onToggle} disabled={busy} aria-pressed={saved}>
      {busy ? "Saving…" : saved ? "★ Saved" : "☆ Save"}
    </button>
  );
}

function Reasons({ items, kind }) {
  return items.map((s, i) => {
    const [name, text] = splitReason(s);
    return <li key={kind + i} className={kind}><span>{name && <b>{name}: </b>}{text}</span></li>;
  });
}

/* ---------- AI second opinion ---------- */
// Assessments saved in the database (table user_ai_assessment) come with the page and on Refresh.
function toAiState(saved) {
  const out = {};
  Object.entries(saved || {}).forEach(([id, data]) => { out[id] = { status: "done", data }; });
  return out;
}

function savedLabel(a) {
  if (!a.saved_at) return "";
  const d = new Date(a.saved_at);
  return `Saved ${d.toLocaleDateString(undefined, { day: "numeric", month: "short" })}, ${d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`;
}
function sourceLabel(a) {
  if (a.source === "live") return `Live AI${a.model_id ? ` · ${a.model_id}` : ""}${a.cached ? " · cached" : ""}`;
  if (a.source === "fallback") return "Fallback: mock output";
  return "Mock AI output";
}

function disagrees(a) {
  const s = a.rule.score;
  return (a.assessment.fit === "strong" && s < 60) || (a.assessment.fit === "weak" && s >= 75);
}

const AgentIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
    <rect x="4" y="8" width="16" height="12" rx="3" /><path d="M12 4v4M9 13h.01M15 13h.01M9.5 16.5h5" />
  </svg>
);

function AIBlock({ state, full, onRerun }) {
  if (!state) return null;
  if (state.status === "loading") return <div className="ai loading" role="status"><span className="agent"><AgentIcon /> Agent</span> is assessing this match…</div>;
  if (state.status === "error") return <div className="ai" role="alert"><span className="status bad">Failed</span> <span className="small">{state.error}</span></div>;
  const a = state.data;
  const x = a.assessment;
  return (
    <div className="ai">
      <div className="aihead">
        <span className="agent"><AgentIcon /> AI second opinion</span>
        <span className={`fit ${x.fit}`}>{x.fit} fit</span>
        <span className={`status ${a.source}`}>{sourceLabel(a)}</span>
      </div>
      {a.notice && a.source !== "mock" && <div className="note">{a.notice}</div>}
      <p>{x.summary}</p>
      {disagrees(a) && (
        <p className="small muted">The AI label and the rule-based score ({a.rule.score}) disagree. Both are shown; the ranking uses the rule-based score only.</p>
      )}
      {full && (
        <>
          {x.strengths.length > 0 && <><h4>Strengths</h4><ul>{x.strengths.map((s, i) => <li key={i}>{s}</li>)}</ul></>}
          {x.gaps.length > 0 && <><h4>Gaps</h4><ul>{x.gaps.map((s, i) => <li key={i}>{s}</li>)}</ul></>}
          {x.considerations.length > 0 && <><h4>Considerations</h4><ul>{x.considerations.map((s, i) => <li key={i}>{s}</li>)}</ul></>}
        </>
      )}
      {(full || a.source === "fallback") && onRerun && (
        <div className="rerun">
          <span className="muted small">{savedLabel(a)}</span>
          <button type="button" className="btn btn-sm btn-quiet" onClick={onRerun}>Run again</button>
        </div>
      )}
      <div className="disclaimer">
        Rule-based label: <Eligibility value={a.rule.eligibility} label={a.rule.eligibility_label} />{" "}
        The AI does not change the score, the ranking or this label, and is not a statement about your legal right to work.
      </div>
    </div>
  );
}

/* ---------- card ---------- */
function fmtSaved(iso) {
  const d = new Date(iso);
  return `Saved ${d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}`;
}

function Card({ r, rank, selected, onSelect, onToggleSave, busy, ai, onAssess, savedAt }) {
  // Clicking anywhere on the card opens its details; its own buttons and links keep their own actions,
  // and selecting text does not count as a click. Keyboard users use the "Details" button.
  const openOnClick = (e) => {
    if (e.target.closest("button, a, input, select, textarea")) return;
    if (window.getSelection && String(window.getSelection()).trim()) return;
    onSelect(r.id);
  };
  return (
    <article className={`rec tilt reveal clickable${selected ? " selected" : ""}`} data-tilt="4"
      onClick={openOnClick}
      style={{ "--i": Math.min(rank - 1, 10) }} aria-label={`${r.title}, score ${r.score}`}>
      <div>
        <Ring score={r.score} index={Math.min(rank - 1, 10)} />
        <div className="rank">#{String(rank).padStart(2, "0")}</div>
      </div>
      <div style={{ minWidth: 0 }}>
        <h2>{r.title}</h2>
        <div className="where">{r.organisation} · {r.city ? `${r.city}, ` : ""}{r.country} · {r.type_label}</div>
        <div className="labels">
          <Eligibility value={r.eligibility} label={r.eligibility_label} />
          {r.capped && <span className="small muted">Capped at 40 (raw {r.uncapped_score})</span>}
        </div>
        <ul className="reasons">
          <Reasons items={r.strengths.slice(0, 2)} kind="plus" />
          <Reasons items={r.gaps.slice(0, 2)} kind="minus" />
        </ul>
        <AIBlock state={ai} full={false} onRerun={() => onAssess(r.id, { refresh: true })} />
        <div className="actions">
          <button type="button" className="btn btn-sm" onClick={() => onSelect(r.id)}>Details</button>
          {IS_SHORTLIST ? (
            <button type="button" className="btn btn-sm btn-danger" onClick={() => onToggleSave(r.id, true)} disabled={busy}>
              {busy ? "Removing…" : "Remove"}
            </button>
          ) : (
            <SaveButton saved={r.shortlisted} busy={busy} onToggle={() => onToggleSave(r.id, r.shortlisted)} />
          )}
          {(!ai || ai.status === "error") && (
            <button type="button" className="btn btn-sm btn-quiet" onClick={() => onAssess(r.id)}>
              {ai ? "Retry AI assessment" : "AI assessment"}
            </button>
          )}
          {savedAt && <span className="muted small saved-at">{fmtSaved(savedAt)}</span>}
        </div>
      </div>
    </article>
  );
}

function fmtRange(min, max) {
  if (min == null && max == null) return "Not stated";
  if (max == null) return `${min}+ years`;
  if (min == null) return `Up to ${max} years`;
  return `${min}–${max} years`;
}

function Requirements({ o }) {
  const langs = o.language_requirements.length
    ? o.language_requirements.map((l) => `${l.language} (${l.level}${l.mandatory ? ", mandatory" : ""})`).join("; ")
    : "Not stated";
  return (
    <dl className="req">
      <dt>Required skills</dt><dd>{o.required_skills.join(", ") || "Not stated"}</dd>
      <dt>Nice to have</dt><dd>{o.nice_to_have_skills.join(", ") || "None"}</dd>
      <dt>Experience</dt><dd>{fmtRange(o.min_years_experience, o.max_years_experience)}</dd>
      <dt>Relevant experience</dt><dd>{(o.experience_areas || []).join(", ") || "Any"}</dd>
      <dt>Education</dt>
      <dd>{o.education_level_required || "Not stated"}{o.education_fields.length ? ` in ${o.education_fields.join(", ")}` : ""}</dd>
      <dt>Languages</dt><dd>{langs}</dd>
      <dt>Local work authorisation</dt><dd>{o.local_work_auth_required ? "Stated as required" : "Not stated"}</dd>
      <dt>Enrolled student</dt><dd>{o.must_be_enrolled_student ? "Required" : "Not required"}</dd>
      <dt>Visa sponsorship</dt><dd>{o.visa_sponsorship_label}</dd>
      <dt>Interest tags</dt><dd>{o.interest_tags.join(", ") || "None"}</dd>
    </dl>
  );
}

function Breakdown({ m }) {
  return (
    <div className="crit">
      {m.criteria.map((c) => {
        const st = CRIT_STATUS[c.status];
        const na = c.status === "not_applicable";
        return (
          <div className="crit-row" key={c.name}>
            <span className="name">{c.name} <span className={`status ${st.cls}`}>{st.label}</span></span>
            <span className="pts">{na ? "—" : `${c.points} / ${c.effective_weight.toFixed(1)}`}</span>
            {!na && <div className={`bar ${c.status}`}><span style={{ "--w": `${Math.round(c.score * 100)}%` }} /></div>}
            <span className="why">
              {c.reason}
              {!na && c.effective_weight !== c.weight && ` (weight ${c.weight} rescaled to ${c.effective_weight.toFixed(1)})`}
            </span>
          </div>
        );
      })}
      <div className="total">
        <span className="muted small">Weights of rules that don't apply are shared among the rest, so the total stays out of 100.</span>
        <strong>{m.capped ? `${m.uncapped_score} → ${m.score}` : m.score}</strong>
      </div>
    </div>
  );
}

/* Accessible disclosure: a button inside the heading toggles a region that animates open downwards.
   Content mounts on first open, so the bars draw in when the user actually looks at them. */
function ScoreBreakdown({ m, open, onToggle }) {
  const [everOpened, setEverOpened] = useState(open);
  useEffect(() => { if (open) setEverOpened(true); }, [open]);
  const applicable = m.criteria.filter((c) => c.status !== "not_applicable");
  const met = applicable.filter((c) => c.status === "met").length;
  return (
    <>
      <h3 className="disclosure-h">
        <button type="button" className="disclosure" aria-expanded={open} aria-controls="score-breakdown" onClick={onToggle}>
          <span className="disclosure-title">
            How the score is built
            <span className="muted small">{met} of {applicable.length} rules met · {m.score}/100</span>
          </span>
          <svg className="chev" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="m6 9 6 6 6-6" />
          </svg>
        </button>
      </h3>
      <div id="score-breakdown" role="region" aria-label="Score breakdown" className={`collapse${open ? " open" : ""}`} inert={open ? undefined : ""}>
        <div className="collapse-inner">
          <div className="collapse-pad">{everOpened && <Breakdown m={m} />}</div>
        </div>
      </div>
    </>
  );
}

function DetailPanel({ id, onClose, onToggleSave, busy, ai, onAssess, breakdownOpen, onToggleBreakdown }) {
  const [state, setState] = useState({ loading: true, error: null, data: null });

  useEffect(() => {
    let alive = true;
    setState({ loading: true, error: null, data: null });
    api(urlFor(URLS.detail, id))
      .then((data) => alive && setState({ loading: false, error: null, data }))
      .catch((e) => alive && setState({ loading: false, error: e.message, data: null }));
    return () => { alive = false; };
  }, [id]);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Sticky bar: the close button stays reachable however far the panel is scrolled.
  const bar = (label) => (
    <div className="detail-bar">
      <span className="detail-bar-title">{label}</span>
      <button type="button" className="icon-btn" onClick={onClose} aria-label="Close details" title="Close (Esc)">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
          <path d="M6 6l12 12M18 6 6 18" />
        </svg>
      </button>
    </div>
  );

  if (state.loading) return <aside className="detail">{bar("Details")}<div className="sec"><p className="muted">Loading details…</p></div></aside>;
  if (state.error) return <aside className="detail">{bar("Details")}<div className="sec"><div className="flash error" role="alert">{state.error}</div></div></aside>;

  const { opportunity: o, match: m, shortlisted } = state.data;
  return (
    <aside className="detail" aria-label={`Details for ${o.title}`}>
      {bar("Details")}
      <div className="sec">
        <h2>{o.title}</h2>
        <div className="where muted small">{o.organisation} · {o.city ? `${o.city}, ` : ""}{o.country} · {o.type_label}</div>
        <p style={{ marginTop: 12, color: "var(--ink-2)" }}>{o.description}</p>
      </div>

      {m && (
        <>
          <div className="sec">
            <div className="head">
              <Ring score={m.score} />
              <div style={{ display: "grid", gap: 8, justifyItems: "start" }}>
                <Eligibility value={m.eligibility} label={m.eligibility_label} />
                <SaveButton saved={shortlisted} busy={busy} onToggle={() => onToggleSave(o.id, shortlisted, true)} />
              </div>
            </div>
            {m.eligibility_notes.map((n, i) => (
              <div key={i} className={`note ${m.eligibility === "blocker" ? "blocker" : m.eligibility === "no_stated_constraint" ? "ok" : ""}`}>{n}</div>
            ))}
            {m.eligibility !== "no_stated_constraint" && (
              <p className="small muted" style={{ marginTop: 8 }}>Check your situation with the employer or an official source. This tool does not decide whether you may legally work anywhere.</p>
            )}
            {m.unknowns.length > 0 && (
              <>
                <h3 style={{ marginTop: 18 }}>Missing from your profile</h3>
                <ul className="reasons"><Reasons items={m.unknowns} kind="unk" /></ul>
                <p className="small muted" style={{ marginTop: 6 }}>Unknown rules score 0 until you <a href={URLS.profile}>add the details</a>.</p>
              </>
            )}
          </div>

          <div className="sec">
            <ScoreBreakdown m={m} open={breakdownOpen} onToggle={onToggleBreakdown} />
          </div>

          <div className="sec">
            <h3>AI second opinion</h3>
            {(!ai || ai.status === "error") && (
              <div className="upload-row" style={{ marginTop: 10 }}>
                <button type="button" className="btn btn-sm" onClick={() => onAssess(o.id)}>{ai ? "Retry AI assessment" : "Get AI assessment"}</button>
                <span className="muted small">{INITIAL.ai_mode === "live" ? `Uses ${INITIAL.ai_provider}.` : "Mock mode: generated from the rule-based result."}</span>
              </div>
            )}
            <AIBlock state={ai} full={true} onRerun={() => onAssess(o.id, { refresh: true })} />
          </div>
        </>
      )}

      <div className="sec">
        <h3 style={{ marginBottom: 12 }}>Full requirements</h3>
        <Requirements o={o} />
      </div>
    </aside>
  );
}

function App() {
  const [data, setData] = useState({ has_profile: INITIAL.has_profile, results: INITIAL.results });
  const initialAi = toAiState(INITIAL.assessments);
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState({});
  const [error, setError] = useState(null);
  const [panelKey, setPanelKey] = useState(0);
  const [savedAt, setSavedAt] = useState(INITIAL.saved_at || {});
  const [undo, setUndo] = useState(null); // {id, title} of the role just removed from the shortlist

  useEffect(() => {
    if (!undo) return undefined;
    const t = setTimeout(() => setUndo(null), 7000);
    return () => clearTimeout(t);
  }, [undo]);

  const refresh = useCallback(() => {
    setError(null);
    return api(IS_SHORTLIST ? `${URLS.recommendations}?only=shortlisted` : URLS.recommendations)
      .then((d) => {
        setData({ has_profile: d.has_profile, results: d.results });
        if (d.saved_at) setSavedAt(d.saved_at);
        aiRef.current = toAiState(d.assessments); // the database is the source of truth
        setAi(aiRef.current);
      })
      .catch((e) => setError(e.message));
  }, []);

  const toggleSave = useCallback(async (id, saved, fromPanel = false) => {
    setBusy((b) => ({ ...b, [id]: true }));
    setError(null);
    try {
      const res = await api(urlFor(URLS.shortlist, id), saved ? "DELETE" : "POST");
      setData((d) => ({ ...d, results: d.results.map((r) => (r.id === id ? { ...r, shortlisted: res.shortlisted } : r)) }));
      if (IS_SHORTLIST) {
        // The card stays in memory (hidden), so Undo puts it back in the same place.
        if (!res.shortlisted) {
          if (id === selected) setSelected(null);
          const title = (data.results.find((r) => r.id === id) || {}).title || "Role";
          setUndo({ id, title });
        } else {
          setUndo(null);
          setSavedAt((m) => ({ ...m, [id]: m[id] || new Date().toISOString() }));
        }
      }
      if (!IS_SHORTLIST && (fromPanel || id === selected)) setPanelKey((k) => k + 1); // reload panel so its button matches
      if (IS_SHORTLIST && res.shortlisted && id === selected) setPanelKey((k) => k + 1);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy((b) => ({ ...b, [id]: false }));
    }
  }, [selected, data.results]);

  const close = useCallback(() => setSelected(null), []);

  const visible = IS_SHORTLIST ? data.results.filter((r) => r.shortlisted) : data.results;

  // Breakdown starts closed for each opportunity; stays as the user left it while that panel reloads.
  const [breakdownOpen, setBreakdownOpen] = useState(false);
  useEffect(() => { setBreakdownOpen(false); }, [selected]);
  const toggleBreakdown = useCallback(() => setBreakdownOpen((v) => !v), []);

  const [ai, setAi] = useState(initialAi);
  const aiRef = useRef(initialAi);
  const [bulk, setBulk] = useState(null); // {done, total, running}
  const stopRef = useRef(false);

  const assess = useCallback(async (id, { refresh = false } = {}) => {
    const cur = aiRef.current[id];
    if (cur && cur.status === "loading") return;
    if (cur && cur.status === "done" && !refresh) return;
    const put = (v) => { aiRef.current = { ...aiRef.current, [id]: v }; setAi(aiRef.current); };
    put({ status: "loading" });
    try {
      put({ status: "done", data: await api(urlFor(URLS.ai, id), "POST", refresh ? { refresh: true } : undefined) });
    } catch (e) {
      put({ status: "error", error: e.message });
    }
  }, []);

  const assessAll = useCallback(async () => {
    stopRef.current = false;
    const ids = visible.map((r) => r.id);
    let done = ids.filter((id) => aiRef.current[id] && aiRef.current[id].status === "done").length;
    setBulk({ done, total: ids.length, running: true });
    for (const id of ids) {
      if (stopRef.current) break;
      const s = aiRef.current[id];
      if (s && s.status === "done") continue;
      await assess(id); // one at a time: gentle on the token quota
      if (INITIAL.ai_mode === "live") await new Promise((r) => setTimeout(r, 2500)); // free tiers limit tokens per minute
      if (aiRef.current[id] && aiRef.current[id].status === "done") done += 1;
      setBulk({ done, total: ids.length, running: true });
    }
    setBulk((b) => ({ ...b, running: false }));
  }, [visible, assess]);

  if (!data.has_profile) {
    return (
      <section className="panel empty tilt reveal" data-tilt="3">
        <span className="status neutral">No profile yet</span>
        <h2>{IS_SHORTLIST ? "Create a profile first" : "Create a profile to see your matches"}</h2>
        <p className="muted">It takes a minute, or one click with the sample candidate.</p>
        <div className="upload-row">
          <a className="btn btn-primary" href={`${URLS.profile}?sample=1`}>Load sample profile</a>
          <a className="btn" href={URLS.profile}>Create a profile</a>
        </div>
      </section>
    );
  }

  const savedCount = data.results.filter((r) => r.shortlisted).length;
  const undoBanner = undo && (
    <div className="flash undo" role="status">
      <span>Removed <b>{undo.title}</b> from your shortlist.</span>
      <button type="button" className="btn btn-sm" onClick={() => toggleSave(undo.id, false)}>Undo</button>
    </div>
  );

  if (IS_SHORTLIST && visible.length === 0) {
    return (
      <>
        {undoBanner}
        <section className="panel empty tilt reveal" data-tilt="3">
          <span className="status neutral">Empty</span>
          <h2>Nothing saved yet</h2>
          <p className="muted">Use Save on any of your matches to keep it here.</p>
          <a className="btn btn-primary" href={URLS.matches}>Go to your matches</a>
        </section>
      </>
    );
  }

  return (
    <>
      <div className="toolbar">
        {IS_SHORTLIST ? (
          <span className="small"><b>{savedCount}</b> saved · ranked by score</span>
        ) : (
          <span className="small"><b>{data.results.length}</b> opportunities · <b>{savedCount}</b> saved</span>
        )}
        <span className="grow" />
        {bulk && bulk.running ? (
          <>
            <progress max={bulk.total} value={bulk.done} aria-label="AI assessments progress" />
            <span className="muted small">AI assessed {bulk.done} / {bulk.total}</span>
            <button type="button" className="btn btn-sm" onClick={() => { stopRef.current = true; }}>Stop</button>
          </>
        ) : (
          <>
            {bulk && <span className="muted small">AI assessed {bulk.done} / {bulk.total}</span>}
            <button type="button" className="btn btn-sm" onClick={assessAll}>Assess all with AI</button>
          </>
        )}
        <button type="button" className="btn btn-sm btn-quiet" onClick={refresh}>Refresh</button>
        <a className="btn btn-sm btn-quiet" href={IS_SHORTLIST ? URLS.matches : URLS.profile}>{IS_SHORTLIST ? "All matches" : "Edit profile"}</a>
      </div>
      {undoBanner}
      {error && <div className="flash error" role="alert">{error}</div>}
      {data.results.length === 0 ? (
        <div className="card">No opportunities are loaded. Run <code>python manage.py seed_opportunities</code>.</div>
      ) : (
        <div className={`layout${selected ? " with-panel" : ""}`}>
          <div className="recs">
            {visible.map((r, i) => (
              <Card key={r.id} r={r} rank={r.rank || i + 1} selected={r.id === selected} onSelect={setSelected} onToggleSave={toggleSave}
                busy={!!busy[r.id]} ai={ai[r.id]} onAssess={assess} savedAt={IS_SHORTLIST ? savedAt[r.id] : null} />
            ))}
          </div>
          {selected && (
            <DetailPanel key={`${selected}-${panelKey}`} id={selected} onClose={close} onToggleSave={toggleSave}
              busy={!!busy[selected]} ai={ai[selected]} onAssess={assess}
              breakdownOpen={breakdownOpen} onToggleBreakdown={toggleBreakdown} />
          )}
        </div>
      )}
    </>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
