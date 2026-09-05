import { useState, useMemo, useEffect, useRef } from "react";
import { GTM_STAGES, GTM_BRAINS, GTM_PRINCIPLES, GTM_DECISION_TRANSPARENCY, searchStages, type GtmStage } from "../gtm/canonical";
import { ABC_HVAC_SIMULATION, ABC_HVAC_PROFILE, SIMULATION_VARIANTS, type SimulationStep } from "../gtm/simulation";

export default function GtmExplorer() {
  const [activeId, setActiveId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [learnMode, setLearnMode] = useState(false);
  const [learnIdx, setLearnIdx] = useState(0);
  const [storyMode, setStoryMode] = useState(false);
  const [showSimulation, setShowSimulation] = useState(false);
  const [depth, setDepth] = useState(1); // 0..4
  const [activeSimulationStep, setActiveSimulationStep] = useState<SimulationStep | null>(null);
  const detailRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  const activeStage: GtmStage | undefined = useMemo(() => GTM_STAGES.find((s) => s.id === activeId), [activeId]);
  const activeBrain = useMemo(() => GTM_BRAINS.find((b) => b.id === activeId), [activeId]);

  const filteredIds = useMemo(() => {
    if (!query.trim()) return new Set(GTM_STAGES.map((s) => s.id));
    return new Set(searchStages(query).map((s) => s.id));
  }, [query]);

  const progressPct = learnMode ? ((learnIdx + 1) / GTM_STAGES.length) * 100 : activeId ? ((GTM_STAGES.findIndex((s) => s.id === activeId) + 1) / GTM_STAGES.length) * 100 : 0;
  const progressText = learnMode ? `Learn Mode — ${GTM_STAGES[learnIdx].title} — ${learnIdx + 1} / ${GTM_STAGES.length}` : activeId ? `${activeStage?.title ?? ""} — ${(GTM_STAGES.findIndex((s) => s.id === activeId) + 1)} / ${GTM_STAGES.length}` : `GTM Overview — ${GTM_STAGES.length} stages`;

  // Keyboard shortcuts: / to focus search, Esc to close
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === "/" && document.activeElement !== searchInputRef.current) {
        e.preventDefault();
        searchInputRef.current?.focus();
      }
      if (e.key === "Escape") {
        setActiveId(null);
        setActiveSimulationStep(null);
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  function openStage(id: string) {
    setActiveId(id);
    setDepth(1);
    const sim = ABC_HVAC_SIMULATION.find((s) => s.stage === id);
    setActiveSimulationStep(sim ?? null);
    setTimeout(() => detailRef.current?.scrollTo({ top: 0, behavior: "smooth" }), 50);
  }
  function closeDetail() {
    setActiveId(null);
    setActiveSimulationStep(null);
  }

  // Learn mode controls
  function startLearn() {
    setLearnMode(true);
    setLearnIdx(0);
    openStage(GTM_STAGES[0].id);
  }
  function learnNext() {
    if (learnIdx < GTM_STAGES.length - 1) {
      const n = learnIdx + 1;
      setLearnIdx(n);
      openStage(GTM_STAGES[n].id);
    } else {
      // Completed
      setLearnMode(false);
    }
  }
  function learnPrev() {
    if (learnIdx > 0) {
      const n = learnIdx - 1;
      setLearnIdx(n);
      openStage(GTM_STAGES[n].id);
    }
  }
  function exitLearn() {
    setLearnMode(false);
  }

  // Story follow
  function followStory() {
    if (!activeId) {
      openStage(GTM_STAGES[0].id);
      setStoryMode(true);
      return;
    }
    const idx = GTM_STAGES.findIndex((s) => s.id === activeId);
    if (idx < GTM_STAGES.length - 1) openStage(GTM_STAGES[idx + 1].id);
  }

  return (
    <div className="w-full max-w-[1280px] mx-auto space-y-4">
      {/* Header + Search + Learn */}
      <div className="sticky top-0 z-20 bg-slate-100/90 backdrop-blur -mx-6 px-6 pt-2 pb-3 border-b border-slate-200">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-sky-500 to-violet-600 text-white grid place-items-center font-extrabold">◉</div>
            <div>
              <div className="font-semibold text-slate-900 leading-none">Learn How Orbit Thinks</div>
              <div className="text-xs text-slate-500">Click any stage • Search • Learn Mode • Follow ABC HVAC through the entire GTM</div>
            </div>
          </div>
          <div className="ml-auto flex items-center gap-2 flex-wrap">
            <div className="relative">
              <input
                ref={searchInputRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search: qualification, intent, contacts, gate, suppression… (press /)"
                className="w-[320px] max-w-[42vw] bg-white border border-slate-300 rounded-full px-4 py-2 text-sm placeholder:text-slate-400 focus:outline-none focus:border-sky-400 focus:ring-2 focus:ring-sky-100"
              />
              {query && (
                <button onClick={() => setQuery("")} className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 text-sm px-2">✕</button>
              )}
            </div>
            <button onClick={startLearn} className="btn text-sm">▶ Start Learning</button>
            <button onClick={() => { setStoryMode((s) => !s); if (!storyMode) openStage("find"); }} className={`btn text-sm ${storyMode ? "!bg-sky-600 !text-white" : "btn-ghost"}`}>ABC HVAC story</button>
            <button onClick={() => setShowSimulation((s) => !s)} className={`btn text-sm ${showSimulation ? "!bg-violet-600 !text-white" : "btn-ghost"}`}>Simulation</button>
          </div>
        </div>
        <div className="mt-3 flex items-center gap-3 text-xs text-slate-500">
          <span className="font-medium text-slate-600">{progressText}</span>
          <div className="flex-1 h-1.5 bg-slate-200 rounded-full overflow-hidden max-w-md">
            <div className="h-full bg-gradient-to-r from-sky-500 to-violet-600 transition-all duration-500" style={{ width: `${progressPct}%` }} />
          </div>
          <span>{learnMode ? `Step ${learnIdx + 1}/${GTM_STAGES.length}` : activeId ? "Exploring" : "Explore freely"}</span>
        </div>
      </div>

      {/* Hero */}
      <div className="card p-5 flex flex-wrap gap-4 items-start">
        <div className="flex-1 min-w-[280px]">
          <h2 className="text-[18px] font-semibold text-slate-900 leading-tight">See the whole system, then click anything to understand how it works</h2>
          <p className="text-sm text-slate-500 mt-1">The map is the table of contents. Each node is a chapter. Learn Mode is the guided course. ABC HVAC is the worked example.</p>
          <div className="flex flex-wrap gap-2 mt-3">
            <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full bg-slate-100 border border-slate-200 text-xs"> {GTM_STAGES.length} stages • left → right</span>
            <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full bg-slate-100 border border-slate-200 text-xs">2 brains: Leads + Intent → Opportunity</span>
            <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full bg-slate-100 border border-slate-200 text-xs">Human in the loop • Learning loop</span>
            <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full bg-slate-100 border border-slate-200 text-xs">7 principles • Decision transparency</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-4 text-xs text-slate-500">
          <span className="inline-flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-sky-500" /> Main path</span>
          <span className="inline-flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-amber-500" /> Gate / decision</span>
          <span className="inline-flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-emerald-500" /> Feedback</span>
        </div>
      </div>

      {/* Engines — 2 brains */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {GTM_BRAINS.map((b) => (
          <button
            key={b.id}
            onClick={() => setActiveId(b.id)}
            className={`text-left card p-4 hover:shadow-md hover:border-slate-300 transition relative overflow-hidden ${activeId === b.id ? "ring-2 ring-sky-300 border-sky-300" : ""}`}
          >
            <div className="absolute top-3 right-3 text-[11px] px-2 py-1 rounded-full bg-slate-100 border border-slate-200 text-slate-500">{b.id === "leads" ? "Does not send" : "Why now?"}</div>
            <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">{b.title} — {b.subtitle}</div>
            <div className="font-semibold text-slate-900 mt-1">{b.whatItIs}</div>
            <div className="text-sm text-slate-500 mt-1 leading-snug">{b.whatItDoes.slice(0, 140)}…</div>
            <div className="mt-2 text-xs font-medium text-sky-700">Output: {b.output} →</div>
          </button>
        ))}
      </div>

      {/* Main flow map */}
      <div className="card p-4 overflow-auto">
        <div className="flex gap-2 items-stretch min-w-[980px] py-1">
          {GTM_STAGES.map((stage, i) => {
            const isActive = activeId === stage.id;
            const isDimmed = query.trim() && !filteredIds.has(stage.id);
            const isStoryHighlight = storyMode && ABC_HVAC_SIMULATION.some((s) => s.stage === stage.id);
            return (
              <div key={stage.id} className="flex items-stretch gap-2 flex-1">
                <button
                  onClick={() => openStage(stage.id)}
                  className={`flex-1 min-w-[110px] max-w-[170px] bg-white border rounded-xl p-3 text-left flex flex-col gap-1.5 hover:shadow-md hover:-translate-y-[1px] transition relative
                    ${isActive ? "border-sky-400 shadow-md ring-2 ring-sky-100" : isStoryHighlight ? "border-violet-300" : "border-slate-200"}
                    ${isDimmed ? "opacity-35" : ""} ${query && filteredIds.has(stage.id) ? "outline outline-2 outline-sky-400 outline-offset-1" : ""}`}
                >
                  <div className="text-[11px] font-bold tracking-widest uppercase text-slate-400">{String(stage.index).padStart(2, "0")} · {stage.id.toUpperCase()}</div>
                  <div className="font-extrabold text-sm leading-tight text-slate-900">{stage.title}</div>
                  <div className="text-xs leading-snug text-slate-500 line-clamp-3">{stage.short}</div>
                  <div className="mt-auto flex flex-wrap gap-1">
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-slate-50 border border-slate-200 text-slate-500">{stage.icon} {stage.title}</span>
                  </div>
                  {storyMode && isStoryHighlight && <span className="absolute -top-1.5 -right-1.5 w-2.5 h-2.5 bg-violet-600 rounded-full animate-pulse" />}
                </button>
                {i < GTM_STAGES.length - 1 && <div className="shrink-0 w-[22px] grid place-items-center text-slate-300 font-bold">→</div>}
              </div>
            );
          })}
        </div>

        <div className="h-px bg-slate-200 my-3" />
        {/* Story strip */}
        <div className={`border rounded-xl p-3 flex flex-wrap gap-3 items-center ${storyMode ? "border-sky-300 bg-sky-50" : "border-dashed border-slate-300 bg-slate-50"}`}>
          <div className="flex-1 min-w-[300px]">
            <div className="font-semibold text-sm text-slate-900">{ABC_HVAC_PROFILE.name} — worked example</div>
            <div className="text-xs text-slate-500">{ABC_HVAC_PROFILE.tagline} • {ABC_HVAC_PROFILE.hiring.split("—")[0]} • {ABC_HVAC_PROFILE.website} • {ABC_HVAC_PROFILE.decisionMaker.split("(")[0]} • {ABC_HVAC_PROFILE.operationalPressure.split("(")[0]}</div>
            {activeSimulationStep && (
              <div className="mt-2 text-xs bg-white border border-slate-200 rounded-lg p-2">
                <div className="font-medium text-slate-700">At {activeSimulationStep.stageTitle}: {activeSimulationStep.decision}</div>
                <div className="text-slate-500">{activeSimulationStep.whyDecision}</div>
              </div>
            )}
          </div>
          <button onClick={followStory} className="btn btn-green text-sm shrink-0">Follow ABC HVAC →</button>
        </div>
        <div className="mt-2 text-xs text-slate-400">Tip: Press <b>/</b> to search • <b>Click</b> a stage • <b>Start Learning</b> walks 1→{GTM_STAGES.length} • Detail keeps map visible</div>
      </div>

      {/* Simulation panel (toggle) */}
      {showSimulation && (
        <div className="card p-5 space-y-3">
          <div className="flex items-center justify-between">
            <div className="font-semibold text-slate-900">Prospect Simulation — {ABC_HVAC_PROFILE.name}</div>
            <button onClick={() => setShowSimulation(false)} className="btn btn-ghost text-xs">Hide</button>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-2 text-xs">
            <div className="panel p-3 bg-slate-50">
              <div className="font-semibold text-slate-700">Profile</div>
              <div className="text-slate-600 mt-1 space-y-1">
                <div><b>Business:</b> {ABC_HVAC_PROFILE.tagline}</div>
                <div><b>Website:</b> {ABC_HVAC_PROFILE.website}</div>
                <div><b>Ads:</b> {ABC_HVAC_PROFILE.ads}</div>
                <div><b>Hiring:</b> {ABC_HVAC_PROFILE.hiring}</div>
                <div><b>Reviews:</b> {ABC_HVAC_PROFILE.reviews}</div>
                <div><b>Decision maker:</b> {ABC_HVAC_PROFILE.decisionMaker}</div>
                <div><b>Score:</b> fit {ABC_HVAC_PROFILE.score.fit}/10 • intent {ABC_HVAC_PROFILE.score.intent} • {ABC_HVAC_PROFILE.score.tier} {ABC_HVAC_PROFILE.score.qualification}</div>
              </div>
            </div>
            <div className="lg:col-span-2">
              <div className="flex flex-wrap gap-2 mb-2">
                {["positive", "objection", "wrongPerson", "later", "unsubscribe", "angry"].map((k) => (
                  <span key={k} className="px-2 py-1 rounded-full bg-white border border-slate-200 text-slate-600">{k}: {(SIMULATION_VARIANTS as any)[k].intent} — {(SIMULATION_VARIANTS as any)[k].reply.slice(0, 28)}…</span>
                ))}
              </div>
              <div className="overflow-auto max-h-[320px] border border-slate-200 rounded-xl bg-white">
                <table className="w-full text-xs">
                  <thead className="bg-slate-50 text-slate-500 text-[11px] uppercase tracking-wide">
                    <tr><th className="text-left p-2">Stage</th><th className="text-left p-2">Knows / Doesn't</th><th className="text-left p-2">Decision + Why</th><th className="text-left p-2">Evidence forwarded</th></tr>
                  </thead>
                  <tbody>
                    {ABC_HVAC_SIMULATION.map((s) => (
                      <tr key={s.stage} className={`border-t border-slate-100 hover:bg-slate-50 cursor-pointer ${activeId === s.stage ? "bg-sky-50" : ""}`} onClick={() => openStage(s.stage)}>
                        <td className="p-2 font-medium text-slate-900">{s.stageTitle}</td>
                        <td className="p-2 text-slate-600"><div className="line-clamp-2">✓ {s.whatOrbitKnows[0]}</div><div className="text-slate-400 line-clamp-1">? {s.whatOrbitDoesntKnow[0]}</div></td>
                        <td className="p-2 text-slate-700"><div className="font-medium">{s.decision}</div><div className="text-slate-500 line-clamp-2">{s.whyDecision}</div></td>
                        <td className="p-2 text-slate-600 line-clamp-2">{s.informationPassedForward.join(" • ").slice(0, 90)}…</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {/* Conversation branches */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
            {ABC_HVAC_SIMULATION.filter((s) => s.conversation).map((s) => (
              <div key={s.stage} className="panel p-3">
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">{s.stageTitle} — conversation</div>
                <div className="mt-2 space-y-1.5">
                  <div className="bg-slate-50 border border-slate-200 rounded-lg p-2"><span className="text-slate-500">Prospect:</span> “{s.conversation!.prospectSays}” <span className="ml-2 px-1.5 py-0.5 rounded bg-violet-100 text-violet-700 text-xs">{s.conversation!.intent}</span></div>
                  <div className="bg-sky-50 border border-sky-200 rounded-lg p-2"><span className="text-sky-700">Orbit:</span> {s.conversation!.orbitReplies}</div>
                  <div className="text-xs text-slate-500">→ {s.conversation!.nextAction}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Principles — always visible */}
      <div className="card p-4">
        <div className="text-[11px] font-semibold uppercase tracking-widest text-slate-400">System principles — always visible</div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mt-3">
          {GTM_PRINCIPLES.map((p) => (
            <div key={p.n} className="text-xs leading-snug"><span className="font-semibold text-slate-900">{p.n} {p.title}</span> — <span className="text-slate-500">{p.detail}</span></div>
          ))}
        </div>
      </div>

      {/* Detail drawer — keeps map visible */}
      {activeStage || activeBrain ? (
        <div className="fixed inset-0 z-30 flex justify-end pointer-events-none">
          <div className="pointer-events-auto w-[min(640px,96vw)] bg-white border-l border-slate-200 shadow-[-20px_0_60px_rgba(15,23,42,.15)] flex flex-col max-h-screen">
            <div className="shrink-0 p-4 border-b border-slate-200 flex gap-3 items-start">
              <div className="w-10 h-10 rounded-xl grid place-items-center text-white font-extrabold shrink-0" style={{ background: (activeStage?.color ?? activeBrain?.color) as string }}>{(activeStage?.icon ?? activeBrain?.icon) as string}</div>
              <div className="flex-1 min-w-0">
                <div className="font-semibold text-slate-900 leading-tight">{activeStage?.title ?? activeBrain?.title}</div>
                <div className="text-sm text-slate-500">{activeStage?.short ?? activeBrain?.subtitle}</div>
                <div className="mt-2 flex flex-wrap gap-1">
                  {[0, 1, 2, 3, 4].map((lvl) => (
                    <button key={lvl} onClick={() => setDepth(lvl)} className={`px-3 py-1 rounded-full text-xs border ${depth === lvl ? "bg-slate-900 text-white border-slate-900" : "bg-white border-slate-200 text-slate-600 hover:bg-slate-50"}`}>
                      {["L1 One-liner", "L2 Detailed", "L3 How it works", "L4 Example", "L5 Advanced"][lvl]}
                    </button>
                  ))}
                </div>
              </div>
              <button onClick={closeDetail} className="shrink-0 w-8 h-8 grid place-items-center rounded-full hover:bg-slate-100 text-slate-500">✕</button>
            </div>

            <div ref={detailRef} className="flex-1 overflow-auto p-4 space-y-3 bg-slate-50/50">
              {/* Brain detail */}
              {activeBrain && !activeStage && (
                <>
                  <DetailSection title="WHAT IT IS"><p>{activeBrain.whatItIs}</p></DetailSection>
                  <DetailSection title="WHY IT EXISTS"><p>{activeBrain.whatItDoes}</p><p className="mt-2"><b>Does NOT do:</b> {activeBrain.whatItDoesNot}</p></DetailSection>
                  <DetailSection title="WHAT COMES OUT"><p><b>{activeBrain.output}</b></p></DetailSection>
                  <DetailSection title="REAL EXAMPLE"><div className="bg-[#eef2ff] border border-[#e0e7ff] rounded-lg p-3 text-sm">{activeBrain.example}</div></DetailSection>
                  <DetailSection title="CONNECTIONS"><p>GTM Intent provides context: “What changed, why now?”<br />GTM Leads provides qualification: “Who is this, is it worth pursuing?”<br />Together → Opportunity → Outreach → Conversation → Meeting</p></DetailSection>
                  <DetailSection title="WHY IT MATTERS"><div className="bg-[#fffbeb] border border-[#fef3c7] rounded-lg p-3">Distinct brains prevent spam and ensure every outreach has a reason to exist.</div></DetailSection>
                  <DetailSection title="IMPLEMENTATION TRACE"><p className="mono text-xs">{activeBrain.trace.join(" • ")}</p></DetailSection>
                </>
              )}

              {/* Stage detail — 11 required sections + extras */}
              {activeStage && (
                <>
                  {depth >= 0 && <DetailSection title="WHAT IT IS"><p>{activeStage.whatItIs}</p></DetailSection>}
                  {depth >= 0 && <DetailSection title="WHY IT EXISTS"><p>{activeStage.whyExists}</p></DetailSection>}
                  {depth >= 1 && <DetailSection title="WHAT ENTERS"><ul className="list-disc pl-5 space-y-1">{activeStage.whatEnters.map((x) => <li key={x}>{x}</li>)}</ul></DetailSection>}
                  {depth >= 1 && <DetailSection title="WHAT HAPPENS"><p>{activeStage.whatHappens}</p></DetailSection>}
                  {depth >= 1 && <DetailSection title="WHAT DECISIONS ARE MADE"><ul className="list-disc pl-5 space-y-1">{activeStage.decisions.map((x) => <li key={x}>{x}</li>)}</ul></DetailSection>}
                  {depth >= 1 && <DetailSection title="WHAT COMES OUT"><ul className="list-disc pl-5 space-y-1">{activeStage.whatComesOut.map((x) => <li key={x}>{x}</li>)}</ul></DetailSection>}
                  {depth >= 1 && (
                    <DetailSection title="REAL EXAMPLE">
                      <div className="bg-[#eef2ff] border border-[#e0e7ff] rounded-lg p-3">
                        <div className="font-semibold text-sm text-slate-900">{activeStage.realExample.title}</div>
                        <div className="text-sm text-slate-700 mt-1">{activeStage.realExample.body}</div>
                      </div>
                    </DetailSection>
                  )}
                  {depth >= 1 && <DetailSection title="EDGE CASES"><ul className="list-disc pl-5 space-y-1">{activeStage.edgeCases.map((x) => <li key={x}>{x}</li>)}</ul></DetailSection>}
                  {depth >= 2 && <DetailSection title="WHAT CAN GO WRONG"><ul className="list-disc pl-5 space-y-1">{activeStage.whatCanGoWrong.map((x) => <li key={x} className="text-amber-900">{x}</li>)}</ul></DetailSection>}
                  {depth >= 1 && (
                    <DetailSection title="HOW IT CONNECTS TO OTHER STAGES">
                      <div><span className="font-medium">↑ From:</span> {activeStage.howItConnects.from}</div>
                      <div><span className="font-medium">→ To:</span> {activeStage.howItConnects.to}</div>
                      <div className="text-slate-500 mt-1">{activeStage.howItConnects.detail}</div>
                    </DetailSection>
                  )}
                  {depth >= 0 && <DetailSection title="WHY IT MATTERS"><div className="bg-[#fffbeb] border border-[#fef3c7] rounded-lg p-3">{activeStage.whyItMatters}</div></DetailSection>}
                  {depth >= 3 && <DetailSection title="ADVANCED DETAILS"><p className="text-xs leading-relaxed">{activeStage.advanced}</p><p className="mono text-xs mt-2 text-slate-500">Trace: {activeStage.trace.backendModules.join(" • ")} {activeStage.trace.stateMachine ? `| State: ${activeStage.trace.stateMachine}` : ""} {activeStage.trace.agent ? `| Agent: ${activeStage.trace.agent}` : ""}</p></DetailSection>}

                  {/* Simulation for this stage */}
                  {activeSimulationStep && (
                    <DetailSection title="ABC HVAC AT THIS STAGE — simulation">
                      <div className="space-y-2 text-sm">
                        <div><b>What Orbit knows:</b><ul className="list-disc pl-5">{activeSimulationStep.whatOrbitKnows.map((x) => <li key={x}>{x}</li>)}</ul></div>
                        <div><b>What it doesn't know:</b><ul className="list-disc pl-5">{activeSimulationStep.whatOrbitDoesntKnow.map((x) => <li key={x}>{x}</li>)}</ul></div>
                        <div><b>Signal found:</b> {activeSimulationStep.signalFound}</div>
                        <div><b>Interpretation:</b> {activeSimulationStep.howItInterprets}</div>
                        <div><b>Decision:</b> {activeSimulationStep.decision}</div>
                        <div className="bg-slate-50 border border-slate-200 rounded-lg p-2"><b>Why:</b> {activeSimulationStep.whyDecision}</div>
                        <div><b>Information passed forward:</b> <span className="mono text-xs">{activeSimulationStep.informationPassedForward.join(" • ")}</span></div>
                        {activeSimulationStep.conversation && (
                          <div className="border-t pt-2 mt-2 space-y-1">
                            <div className="bg-slate-100 rounded p-2"><b>Prospect says:</b> “{activeSimulationStep.conversation.prospectSays}” <span className="ml-2 px-2 py-0.5 rounded-full bg-violet-100 text-violet-700 text-xs">{activeSimulationStep.conversation.intent}</span></div>
                            <div className="bg-sky-50 border border-sky-100 rounded p-2"><b>Orbit replies:</b> {activeSimulationStep.conversation.orbitReplies}</div>
                            <div className="text-xs text-slate-500">→ {activeSimulationStep.conversation.nextAction}</div>
                          </div>
                        )}
                      </div>
                    </DetailSection>
                  )}

                  {/* Decision transparency */}
                  <DetailSection title="DECISION TRANSPARENCY — Explain why">
                    <p>{GTM_DECISION_TRANSPARENCY.detail}</p>
                    <div className="mt-2 p-3 bg-white border border-slate-200 rounded-lg">
                      <div className="text-sm font-medium text-slate-900">Example: ABC HVAC qualified? [Why?]</div>
                      <div className="text-sm text-slate-600 mt-1 whitespace-pre-wrap">{GTM_DECISION_TRANSPARENCY.example}</div>
                    </div>
                    <div className="mt-2 text-xs text-slate-500">Observable reasoning criteria, evidence, decisions, and system behavior — never hidden chain-of-thought. Backed by: leads.priority_score, scores.contributions[], outbound_gate.checks[], suppression results, qa_runs findings.</div>
                  </DetailSection>
                </>
              )}
            </div>

            <div className="shrink-0 p-3 border-t border-slate-200 bg-white flex items-center gap-2">
              <span className="text-xs px-2 py-1 rounded-full bg-slate-100 border border-slate-200">{activeStage ? `${activeStage.index} / ${GTM_STAGES.length}` : "—"}</span>
              <span className="text-xs text-slate-500 flex-1 truncate">{activeStage ? `↑ ${activeStage.howItConnects.from} → ${activeStage.howItConnects.to}` : ""}</span>
              <button onClick={() => { const idx = GTM_STAGES.findIndex((s) => s.id === activeId); if (idx > 0) openStage(GTM_STAGES[idx - 1].id); }} className="btn btn-ghost text-xs">← Previous</button>
              <button onClick={() => { const idx = GTM_STAGES.findIndex((s) => s.id === activeId); if (idx < GTM_STAGES.length - 1) openStage(GTM_STAGES[idx + 1].id); }} className="btn text-xs">Next lesson →</button>
            </div>
          </div>
        </div>
      ) : null}

      {/* Learn bar */}
      {learnMode && (
        <div className="fixed left-1/2 bottom-5 -translate-x-1/2 bg-slate-900 text-white rounded-xl px-4 py-3 flex items-center gap-3 shadow-xl z-40">
          <span className="text-xs opacity-80">Step {learnIdx + 1} / {GTM_STAGES.length} — {GTM_STAGES[learnIdx].title}</span>
          <button onClick={learnNext} className="bg-white text-slate-900 rounded-full px-4 py-1.5 text-sm font-medium">Next →</button>
          <button onClick={learnPrev} disabled={learnIdx === 0} className="rounded-full px-3 py-1.5 text-sm border border-white/30 disabled:opacity-40">← Back</button>
          <button onClick={exitLearn} className="rounded-full px-3 py-1.5 text-sm border border-white/30">Skip</button>
          <button onClick={exitLearn} className="rounded-full px-3 py-1.5 text-sm border border-white/30">Explore freely</button>
        </div>
      )}
    </div>
  );
}

function DetailSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
      <div className="px-3 py-2 bg-slate-50 border-b border-slate-200 text-[11px] font-semibold uppercase tracking-widest text-slate-400">{title}</div>
      <div className="p-3 text-sm text-slate-700 leading-relaxed">{children}</div>
    </div>
  );
}
