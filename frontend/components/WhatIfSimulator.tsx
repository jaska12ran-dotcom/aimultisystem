'use client';

import { useState, useCallback } from 'react';
import {
  AlertTriangle, ArrowRight, CheckCircle2, ChevronDown, ChevronRight,
  Code2, Copy, FileCode2, FlaskConical, GitBranch, GitCompare,
  Info, Layers, Lock, RefreshCw, Shield, Sparkles,
  TestTube2, X, Zap, AlertCircle,
  CheckCheck, CircleDot, Eye, EyeOff,
} from 'lucide-react';
import {
  whatIfApi,
  WhatIfRequest,
  WhatIfSimulationResult,
  BreakingChangeEntry,
  AffectedFile,
  ImpactedFunction,
  TestFailureRisk,
  SecurityImplication,
  PerformanceConcern,
  MigrationRequirement,
  RegressionTestRecommendation,
  AlternativeProposal,
  WhatIfPatch,
} from '../services/intelligence';
import { FileItem, CodeSymbol, Repository } from '../types';

// ── Helpers ──────────────────────────────────────────────────────────────────

function cx(...classes: Array<string | false | undefined>) {
  return classes.filter(Boolean).join(' ');
}

const SEVERITY_CONFIG: Record<string, { bg: string; text: string; border: string; dot: string }> = {
  critical: {
    bg: 'bg-red-500/10',
    text: 'text-red-400',
    border: 'border-red-500/20',
    dot: 'bg-red-400',
  },
  high: {
    bg: 'bg-orange-500/10',
    text: 'text-orange-400',
    border: 'border-orange-500/20',
    dot: 'bg-orange-400',
  },
  medium: {
    bg: 'bg-amber-500/10',
    text: 'text-amber-400',
    border: 'border-amber-500/20',
    dot: 'bg-amber-400',
  },
  low: {
    bg: 'bg-blue-500/10',
    text: 'text-blue-400',
    border: 'border-blue-500/20',
    dot: 'bg-blue-400',
  },
  info: {
    bg: 'bg-slate-500/10',
    text: 'text-slate-400',
    border: 'border-slate-500/20',
    dot: 'bg-slate-400',
  },
};

const RISK_RING: Record<string, string> = {
  critical: 'ring-red-500 text-red-400',
  high: 'ring-orange-500 text-orange-400',
  medium: 'ring-amber-400 text-amber-400',
  low: 'ring-emerald-500 text-emerald-400',
};

function SeverityBadge({ severity, verified }: { severity: string; verified?: boolean }) {
  const cfg = SEVERITY_CONFIG[severity.toLowerCase()] ?? SEVERITY_CONFIG.info;
  return (
    <span className={cx('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide border', cfg.bg, cfg.text, cfg.border)}>
      <span className={cx('h-1.5 w-1.5 rounded-full', cfg.dot)} />
      {severity}
      {verified !== undefined && (
        <span className={cx('ml-0.5 rounded px-1 text-[9px] font-bold', verified ? 'bg-emerald-400/15 text-emerald-400' : 'bg-purple-400/15 text-purple-400')}>
          {verified ? 'VERIFIED' : 'AI'}
        </span>
      )}
    </span>
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = pct >= 80 ? 'bg-emerald-500' : pct >= 60 ? 'bg-amber-400' : 'bg-rose-500';
  return (
    <div className="flex items-center gap-2">
      <div className="h-1 flex-1 rounded-full bg-white/5">
        <div className={cx('h-full rounded-full transition-all', color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] text-slate-400 tabular-nums">{pct}%</span>
    </div>
  );
}

function CollapsibleSection({
  title,
  icon: Icon,
  count,
  badge,
  defaultOpen = false,
  children,
}: {
  title: string;
  icon: typeof Shield;
  count?: number;
  badge?: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-xl border border-white/[0.07] bg-[#0d1420]/60 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-white/[0.03] transition-colors"
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <Icon size={14} className="text-indigo-400 shrink-0" />
          <span className="text-sm font-semibold text-slate-200 truncate">{title}</span>
          {count !== undefined && (
            <span className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] font-semibold text-slate-300">
              {count}
            </span>
          )}
          {badge}
        </div>
        <ChevronDown size={14} className={cx('text-slate-500 transition-transform', open && 'rotate-180')} />
      </button>
      {open && <div className="px-4 pb-4 pt-0.5">{children}</div>}
    </div>
  );
}

function DiffViewer({ diff, label }: { diff: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(diff).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }, [diff]);

  const lines = diff.split('\n');
  return (
    <div className="rounded-lg border border-white/[0.07] overflow-hidden text-[11px] font-mono">
      <div className="flex items-center justify-between border-b border-white/[0.07] bg-white/[0.03] px-3 py-1.5">
        <span className="text-slate-400">{label}</span>
        <button
          type="button"
          onClick={handleCopy}
          className="flex items-center gap-1 text-slate-500 hover:text-slate-300 transition-colors"
        >
          {copied ? <CheckCheck size={12} className="text-emerald-400" /> : <Copy size={12} />}
          <span className="text-[10px]">{copied ? 'Copied' : 'Copy'}</span>
        </button>
      </div>
      <div className="max-h-64 overflow-y-auto bg-[#080e18] px-3 py-2 leading-5">
        {lines.map((line, i) => (
          <div
            key={i}
            className={cx(
              'whitespace-pre-wrap break-all',
              line.startsWith('+') && !line.startsWith('+++') ? 'text-emerald-400 bg-emerald-500/5' :
              line.startsWith('-') && !line.startsWith('---') ? 'text-rose-400 bg-rose-500/5' :
              line.startsWith('@@') ? 'text-indigo-400 bg-indigo-500/5' :
              'text-slate-400',
            )}
          >
            {line || '\u00a0'}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface WhatIfSimulatorProps {
  repository: Repository;
  files?: FileItem[];
  symbols?: CodeSymbol[];
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function WhatIfSimulator({ repository, files = [], symbols = [] }: WhatIfSimulatorProps) {
  // Form state
  const [filePath, setFilePath] = useState('');
  const [symbolName, setSymbolName] = useState('');
  const [branch, setBranch] = useState('');
  const [description, setDescription] = useState('');
  const [proposedCode, setProposedCode] = useState('');
  const [proposedDiff, setProposedDiff] = useState('');
  const [alternatives, setAlternatives] = useState('');
  const [includeFlags, setIncludeFlags] = useState({
    security: true,
    performance: true,
    migration: true,
    regression: true,
  });
  const [inputMode, setInputMode] = useState<'description' | 'code' | 'diff'>('description');
  const [alternativesMode, setAlternativesMode] = useState(false);

  // Autocomplete
  const [fileQuery, setFileQuery] = useState('');
  const [symbolQuery, setSymbolQuery] = useState('');
  const [showFileSuggestions, setShowFileSuggestions] = useState(false);
  const [showSymbolSuggestions, setShowSymbolSuggestions] = useState(false);

  // Results state
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<WhatIfSimulationResult | null>(null);

  // Active tab in results
  const [activeTab, setActiveTab] = useState<
    'overview' | 'breaking' | 'affected' | 'tests' | 'security' | 'perf' | 'migration' | 'patch' | 'alternatives'
  >('overview');

  const [showRollback, setShowRollback] = useState(false);

  // Autocomplete lists
  const filteredFiles = files
    .filter((f) => !f.is_binary && f.relative_path.toLowerCase().includes(fileQuery.toLowerCase()))
    .slice(0, 10);
  const filteredSymbols = symbols
    .filter((s) => (s.qualified_name || s.name).toLowerCase().includes(symbolQuery.toLowerCase()))
    .slice(0, 10);

  // Submit
  const handleSimulate = useCallback(async () => {
    if (!description.trim()) {
      setError('Please describe the proposed change in natural language.');
      return;
    }
    setError('');
    setLoading(true);
    setResult(null);

    const payload: WhatIfRequest = {
      file_path: filePath.trim() || null,
      symbol: symbolName.trim() || null,
      branch: branch.trim() || null,
      natural_language_description: description.trim(),
      proposed_code: inputMode === 'code' ? proposedCode.trim() || null : null,
      proposed_diff: inputMode === 'diff' ? proposedDiff.trim() || null : null,
      alternatives: alternativesMode
        ? alternatives.split('\n').map((s) => s.trim()).filter(Boolean)
        : null,
      include_security: includeFlags.security,
      include_performance: includeFlags.performance,
      include_migration: includeFlags.migration,
      include_regression_tests: includeFlags.regression,
    };

    try {
      const data = await whatIfApi.simulate(repository.id, payload);
      setResult(data);
      setActiveTab('overview');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Simulation failed.');
    } finally {
      setLoading(false);
    }
  }, [repository.id, filePath, symbolName, branch, description, proposedCode, proposedDiff,
      alternatives, includeFlags, inputMode, alternativesMode]);

  const handleReset = useCallback(() => {
    setResult(null);
    setError('');
  }, []);

  // ── Result Sections ────────────────────────────────────────────────────────

  function RiskOverview({ r }: { r: WhatIfSimulationResult }) {
    const riskCfg = SEVERITY_CONFIG[r.overall_risk] ?? SEVERITY_CONFIG.medium;
    const ringCfg = RISK_RING[r.overall_risk] ?? 'ring-amber-400 text-amber-400';
    const pct = Math.round(r.overall_confidence * 100);

    return (
      <div className="space-y-4">
        {/* Risk score + stats */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {/* Overall risk */}
          <div className={cx('rounded-xl border p-3 flex flex-col items-center justify-center gap-1', riskCfg.bg, riskCfg.border)}>
            <div className={cx('h-14 w-14 rounded-full ring-2 flex items-center justify-center font-black text-base uppercase', ringCfg)}>
              {r.overall_risk}
            </div>
            <p className="text-[10px] text-slate-400 uppercase tracking-wide mt-1">Overall Risk</p>
          </div>
          {/* Confidence */}
          <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-3 flex flex-col justify-center gap-1.5">
            <p className="text-[10px] text-slate-500 uppercase tracking-wide">Confidence</p>
            <span className="text-2xl font-bold text-slate-100">{pct}%</span>
            <ConfidenceBar value={r.overall_confidence} />
          </div>
          {/* Verified */}
          <div className="rounded-xl border border-emerald-500/15 bg-emerald-500/5 p-3 flex flex-col justify-center gap-1">
            <p className="text-[10px] text-emerald-400/70 uppercase tracking-wide">Verified Findings</p>
            <span className="text-2xl font-bold text-emerald-400">{r.verified_finding_count}</span>
            <p className="text-[10px] text-slate-500">AST / Graph analysis</p>
          </div>
          {/* AI predicted */}
          <div className="rounded-xl border border-purple-500/15 bg-purple-500/5 p-3 flex flex-col justify-center gap-1">
            <p className="text-[10px] text-purple-400/70 uppercase tracking-wide">AI Predictions</p>
            <span className="text-2xl font-bold text-purple-400">{r.predicted_finding_count}</span>
            <p className="text-[10px] text-slate-500">Heuristic estimates</p>
          </div>
        </div>

        {/* Summary */}
        <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-4">
          <p className="text-sm text-slate-300 leading-relaxed whitespace-pre-wrap"
            dangerouslySetInnerHTML={{ __html: r.summary.replace(/\*\*(.*?)\*\*/g, '<strong class="text-slate-100">$1</strong>') }}
          />
        </div>

        {/* Safety notice */}
        <div className="flex items-start gap-3 rounded-xl border border-indigo-300/10 bg-indigo-400/[0.05] px-4 py-3">
          <Lock size={14} className="text-indigo-400 mt-0.5 shrink-0" />
          <p className="text-[11px] text-indigo-300/80 leading-relaxed">{r.simulation_note}</p>
        </div>

        {/* Quick stats grid */}
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {[
            { label: 'Affected Files', value: r.affected_files.length, color: 'text-cyan-400', tab: 'affected' as const },
            { label: 'Breaking Changes', value: r.breaking_changes.length, color: 'text-rose-400', tab: 'breaking' as const },
            { label: 'Test Risks', value: r.test_failure_risks.length, color: 'text-amber-400', tab: 'tests' as const },
            { label: 'Security Issues', value: r.security_implications.length, color: 'text-orange-400', tab: 'security' as const },
          ].map(({ label, value, color, tab }) => (
            <button
              key={label}
              type="button"
              onClick={() => setActiveTab(tab)}
              className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-3 text-left hover:border-white/15 hover:bg-white/[0.04] transition-colors group"
            >
              <span className={cx('text-xl font-bold', color)}>{value}</span>
              <p className="mt-0.5 text-[10px] text-slate-500 group-hover:text-slate-400 transition-colors">{label}</p>
            </button>
          ))}
        </div>

        {/* Assumptions & limitations */}
        {(r.assumptions.length > 0 || r.limitations.length > 0) && (
          <CollapsibleSection title="Assumptions & Limitations" icon={Info} defaultOpen={false}>
            {r.assumptions.length > 0 && (
              <div className="mb-3">
                <p className="mb-1.5 text-[11px] font-semibold text-slate-400 uppercase tracking-wide">Assumptions</p>
                <ul className="space-y-1">
                  {r.assumptions.map((a, i) => (
                    <li key={i} className="flex items-start gap-2 text-[11px] text-slate-400">
                      <CircleDot size={10} className="text-indigo-400 mt-0.5 shrink-0" />
                      {a}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {r.limitations.length > 0 && (
              <div>
                <p className="mb-1.5 text-[11px] font-semibold text-slate-400 uppercase tracking-wide">Limitations</p>
                <ul className="space-y-1">
                  {r.limitations.map((l, i) => (
                    <li key={i} className="flex items-start gap-2 text-[11px] text-amber-400/70">
                      <AlertCircle size={10} className="text-amber-400 mt-0.5 shrink-0" />
                      {l}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </CollapsibleSection>
        )}
      </div>
    );
}

function BreakingChangesTab({ items }: { items: BreakingChangeEntry[] }) {
  return (
    <div className="space-y-3">
      {items.length === 0 ? (
        <div className="flex items-center gap-3 rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-4">
          <CheckCircle2 size={18} className="text-emerald-400 shrink-0" />
          <div>
            <p className="text-sm font-semibold text-emerald-300">No breaking changes detected</p>
            <p className="text-[11px] text-slate-400 mt-0.5">Deterministic AST analysis found no API breaks in the proposed change.</p>
          </div>
        </div>
      ) : (
        items.map((bc, i) => (
          <div key={i} className="rounded-xl border border-white/[0.07] bg-[#0a1020]/50 p-4 space-y-2">
            <div className="flex items-start justify-between gap-2 flex-wrap">
              <code className="text-sm font-mono text-indigo-300 break-all">{bc.symbol}</code>
              <div className="flex gap-1.5 flex-wrap">
                <SeverityBadge severity={bc.severity} verified={bc.verified} />
                <span className="inline-flex items-center rounded-full bg-white/[0.06] px-2 py-0.5 text-[10px] text-slate-400 border border-white/[0.08]">
                  {bc.category}
                </span>
              </div>
            </div>
            <p className="text-[12px] text-slate-300">{bc.description}</p>
            <p className="text-[11px] text-slate-500">
              <FileCode2 size={10} className="inline mr-1" />
              {bc.file}{bc.line ? `:${bc.line}` : ''}
            </p>
            {(bc.before || bc.after) && (
              <div className="grid gap-2 sm:grid-cols-2 mt-2">
                {bc.before && (
                  <div className="rounded-lg border border-rose-500/15 bg-rose-500/5 px-3 py-2">
                    <p className="mb-1 text-[9px] font-bold uppercase tracking-wide text-rose-400">Before</p>
                    <code className="text-[11px] text-rose-300/80 break-all">{bc.before}</code>
                  </div>
                )}
                {bc.after && (
                  <div className="rounded-lg border border-emerald-500/15 bg-emerald-500/5 px-3 py-2">
                    <p className="mb-1 text-[9px] font-bold uppercase tracking-wide text-emerald-400">After</p>
                    <code className="text-[11px] text-emerald-300/80 break-all">{bc.after}</code>
                  </div>
                )}
              </div>
            )}
          </div>
        ))
      )}
    </div>
  );
}

function AffectedFilesTab({ items, funcs }: { items: AffectedFile[]; funcs: ImpactedFunction[] }) {
  return (
    <div className="space-y-4">
      {items.length > 0 && (
        <div className="space-y-2">
          <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wide">Affected Files ({items.length})</p>
          {items.map((af, i) => (
            <div key={i} className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-3 flex items-start gap-3">
              <FileCode2 size={13} className="text-cyan-400 mt-0.5 shrink-0" />
              <div className="flex-1 min-w-0">
                <code className="text-[11px] text-cyan-300 break-all">{af.file}</code>
                <div className="flex items-center gap-2 mt-1 flex-wrap">
                  <span className="rounded bg-white/[0.06] px-1.5 py-0.5 text-[9px] text-slate-400">{af.relationship}</span>
                  <span className="text-[10px] text-slate-500">{af.reason}</span>
                </div>
                <ConfidenceBar value={af.confidence} />
              </div>
            </div>
          ))}
        </div>
      )}
      {funcs.length > 0 && (
        <div className="space-y-2">
          <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wide">Impacted Functions ({funcs.length})</p>
          {funcs.map((fn, i) => (
            <div key={i} className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-3 flex items-start gap-3">
              <Code2 size={13} className="text-indigo-400 mt-0.5 shrink-0" />
              <div className="flex-1 min-w-0">
                <code className="text-[11px] text-indigo-300 break-all">{fn.symbol}</code>
                <p className="text-[10px] text-slate-500 mt-0.5">
                  {fn.file}{fn.line ? `:${fn.line}` : ''} — via <strong className="text-slate-400">{fn.relationship}</strong>
                </p>
                <div className="flex items-center gap-2 mt-1 flex-wrap">
                  <span className={cx('rounded px-1.5 py-0.5 text-[9px] font-semibold',
                    fn.impact_type === 'signature_break' ? 'bg-rose-500/15 text-rose-400' :
                    fn.impact_type === 'test_failure_risk' ? 'bg-amber-500/15 text-amber-400' :
                    'bg-indigo-500/15 text-indigo-400'
                  )}>
                    {fn.impact_type}
                  </span>
                  <ConfidenceBar value={fn.confidence} />
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
      {items.length === 0 && funcs.length === 0 && (
        <div className="text-center py-8 text-slate-500 text-sm">No affected files or functions found in the indexed graph.</div>
      )}
    </div>
  );
}

function TestRisksTab({ risks, recs }: { risks: TestFailureRisk[]; recs: RegressionTestRecommendation[] }) {
  return (
    <div className="space-y-4">
      {risks.length > 0 && (
        <div className="space-y-2">
          <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wide">Test Failure Risks ({risks.length})</p>
          {risks.map((r, i) => (
            <div key={i} className={cx('rounded-lg border p-3 flex items-start gap-3',
              r.risk_level === 'high' ? 'border-rose-500/20 bg-rose-500/5' : 'border-amber-500/20 bg-amber-500/5'
            )}>
              <TestTube2 size={13} className={r.risk_level === 'high' ? 'text-rose-400' : 'text-amber-400'} />
              <div className="flex-1 min-w-0">
                <code className="text-[11px] break-all" style={{ color: r.risk_level === 'high' ? '#f87171' : '#fbbf24' }}>
                  {r.test_function || r.test_file}
                </code>
                <p className="text-[10px] text-slate-500 mt-0.5">{r.test_file}{r.line ? `:${r.line}` : ''}</p>
                <p className="text-[11px] text-slate-300 mt-1">{r.reason}</p>
                {!r.verified && (
                  <span className="inline-block mt-1 rounded px-1.5 py-0.5 text-[9px] bg-purple-500/15 text-purple-400">AI estimate</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
      {recs.length > 0 && (
        <div className="space-y-2">
          <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wide">Recommended Regression Tests ({recs.length})</p>
          {recs.map((rec, i) => (
            <div key={i} className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-3">
              <div className="flex items-center justify-between gap-2 flex-wrap mb-1">
                <span className="text-[12px] font-medium text-slate-200">{rec.test_name}</span>
                <SeverityBadge severity={rec.priority} />
              </div>
              <p className="text-[11px] text-slate-400">{rec.description}</p>
              <p className="text-[10px] text-slate-500 mt-1 italic">{rec.rationale}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function SecurityTab({ items }: { items: SecurityImplication[] }) {
  return (
    <div className="space-y-3">
      {items.length === 0 ? (
        <div className="flex items-center gap-3 rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-4">
          <Shield size={18} className="text-emerald-400 shrink-0" />
          <div>
            <p className="text-sm font-semibold text-emerald-300">No security patterns detected</p>
            <p className="text-[11px] text-slate-400 mt-0.5">Heuristic pattern scan found no known security anti-patterns in the proposed code.</p>
          </div>
        </div>
      ) : (
        items.map((si, i) => (
          <div key={i} className="rounded-xl border border-white/[0.07] bg-[#0a1020]/50 p-4 space-y-2">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <div className="flex items-center gap-2">
                <Shield size={13} className="text-orange-400 shrink-0" />
                <span className="text-[12px] font-semibold text-slate-200">{si.category.replace(/_/g, ' ').toUpperCase()}</span>
              </div>
              <SeverityBadge severity={si.severity} verified={si.verified} />
            </div>
            <p className="text-[12px] text-slate-300">{si.description}</p>
            {si.remediation && (
              <p className="text-[11px] text-indigo-300/70 border-l-2 border-indigo-400/30 pl-2">
                💡 {si.remediation}
              </p>
            )}
            {si.locations.map((loc, j) => (
              <p key={j} className="text-[10px] text-slate-500">
                <FileCode2 size={10} className="inline mr-1" />
                {loc.file}{loc.line ? `:${loc.line}` : ''}
              </p>
            ))}
          </div>
        ))
      )}
    </div>
  );
}

function PerfTab({ perf, mig }: { perf: PerformanceConcern[]; mig: MigrationRequirement[] }) {
  return (
    <div className="space-y-4">
      {perf.length > 0 && (
        <div className="space-y-3">
          <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wide">Performance Concerns ({perf.length})</p>
          {perf.map((pc, i) => (
            <div key={i} className="rounded-xl border border-white/[0.07] bg-[#0a1020]/50 p-4 space-y-1.5">
              <div className="flex items-center gap-2 flex-wrap">
                <Zap size={13} className="text-yellow-400 shrink-0" />
                <span className="text-[12px] font-semibold text-slate-200">{pc.category.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}</span>
                <SeverityBadge severity={pc.severity} verified={pc.verified} />
              </div>
              <p className="text-[12px] text-slate-300">{pc.description}</p>
            </div>
          ))}
        </div>
      )}
      {mig.length > 0 && (
        <div className="space-y-3">
          <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wide">Migration Requirements ({mig.length})</p>
          {mig.map((mr, i) => (
            <div key={i} className="rounded-xl border border-amber-500/15 bg-amber-500/5 p-4 space-y-1.5">
              <div className="flex items-center gap-2 flex-wrap">
                <Layers size={13} className="text-amber-400 shrink-0" />
                <span className="text-[12px] font-semibold text-amber-300">{mr.category.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}</span>
                <SeverityBadge severity={mr.severity} />
              </div>
              <p className="text-[12px] text-slate-300">{mr.description}</p>
              <p className="text-[11px] text-amber-400/80">
                <ArrowRight size={10} className="inline mr-1" />
                {mr.action_required}
              </p>
            </div>
          ))}
        </div>
      )}
      {perf.length === 0 && mig.length === 0 && (
        <div className="text-center py-8 text-slate-500 text-sm">No performance or migration concerns detected.</div>
      )}
    </div>
  );
}

function PatchTab({ patch }: { patch: WhatIfPatch | null | undefined }) {
  if (!patch) return (
    <div className="text-center py-8 text-slate-500 text-sm">No patch generated.</div>
  );
  return (
    <div className="space-y-4">
      <div className="flex items-start gap-3 rounded-xl border border-indigo-300/10 bg-indigo-400/[0.05] px-4 py-3">
        <Lock size={14} className="text-indigo-400 mt-0.5 shrink-0" />
        <p className="text-[11px] text-indigo-300/80 leading-relaxed">{patch.workspace_note}</p>
      </div>
      <div className="flex items-center gap-2 rounded-lg border border-white/[0.07] bg-white/[0.02] px-3 py-2">
        <FileCode2 size={12} className="text-slate-400" />
        <span className="text-[11px] text-slate-300">{patch.file_path}</span>
      </div>
      {patch.unified_diff && (
        <DiffViewer diff={patch.unified_diff} label="Proposed diff (simulated workspace)" />
      )}
      {patch.rollback_diff && (
        <div>
          <button
            type="button"
            onClick={() => setShowRollback((v) => !v)}
            className="flex items-center gap-1.5 text-[11px] text-slate-400 hover:text-slate-200 transition-colors mb-2"
          >
            {showRollback ? <EyeOff size={11} /> : <Eye size={11} />}
            {showRollback ? 'Hide' : 'Show'} rollback diff (inverse patch)
          </button>
          {showRollback && <DiffViewer diff={patch.rollback_diff} label="Rollback diff (to undo the change)" />}
        </div>
      )}
    </div>
  );
}

function AlternativesTab({ alts }: { alts: AlternativeProposal[] }) {
  return (
    <div className="space-y-3">
      {alts.map((alt, i) => (
        <div key={i} className="rounded-xl border border-white/[0.07] bg-[#0a1020]/50 p-4 space-y-2">
          <div className="flex items-center gap-2 flex-wrap">
            <GitBranch size={13} className="text-indigo-400 shrink-0" />
            <span className="text-[12px] font-semibold text-slate-200">Alternative {i + 1}</span>
            {alt.estimated_risk !== 'unknown' && <SeverityBadge severity={alt.estimated_risk} />}
          </div>
          <p className="text-[12px] text-slate-300">{alt.description}</p>
          {alt.tradeoffs && (
            <p className="text-[11px] text-slate-500 italic">
              <span className="text-slate-400 font-medium">Tradeoffs:</span> {alt.tradeoffs}
            </p>
          )}
          {alt.patch_hint && (
            <pre className="rounded-lg bg-[#080e18] px-3 py-2 text-[10px] text-slate-400 font-mono overflow-x-auto">
              {alt.patch_hint}
            </pre>
          )}
        </div>
      ))}
    </div>
  );
}

  // ── Tab config ────────────────────────────────────────────────────────────

  const tabs = result ? [
    { id: 'overview', label: 'Overview', icon: Sparkles, count: undefined },
    { id: 'breaking', label: 'Breaking Changes', icon: AlertTriangle, count: result.breaking_changes.length },
    { id: 'affected', label: 'Affected Files', icon: FileCode2, count: result.affected_files.length },
    { id: 'tests', label: 'Test Risks', icon: TestTube2, count: result.test_failure_risks.length },
    { id: 'security', label: 'Security', icon: Shield, count: result.security_implications.length },
    { id: 'perf', label: 'Perf & Migration', icon: Zap, count: result.performance_concerns.length + result.migration_requirements.length },
    { id: 'patch', label: 'Patch / Rollback', icon: GitCompare, count: undefined },
    { id: 'alternatives', label: 'Alternatives', icon: GitBranch, count: result.alternatives.length },
  ] as const : [];

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="h-full flex flex-col gap-0 min-h-0">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-white/[0.06] px-5 py-4 shrink-0">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-indigo-300/10 bg-indigo-400/[0.08] text-indigo-300">
          <FlaskConical size={15} />
        </span>
        <div>
          <h2 className="text-[13px] font-semibold text-slate-100">What-If Code Change Simulator</h2>
          <p className="text-[11px] text-slate-500">Simulate proposed changes — deterministic AST + AI analysis. Read-only; never modifies your repo.</p>
        </div>
        {result && (
          <button
            type="button"
            onClick={handleReset}
            className="ml-auto flex items-center gap-1.5 rounded-lg border border-white/[0.07] px-3 py-1.5 text-[11px] text-slate-400 hover:border-white/15 hover:text-slate-200 transition-colors"
          >
            <RefreshCw size={11} />
            New Simulation
          </button>
        )}
      </div>

      {/* Main scrollable content */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {!result ? (
          /* ── Simulator Form ─────────────────────────────────────────────── */
          <div className="px-5 py-5 space-y-5 max-w-3xl">
            {/* Target selection */}
            <div className="space-y-3">
              <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wide">1. Select Target</p>

              {/* File selector */}
              <div className="relative">
                <label className="mb-1 block text-[11px] text-slate-400">File (optional)</label>
                <div className="flex items-center gap-2 rounded-lg border border-white/[0.08] bg-white/[0.03] px-3 py-2">
                  <FileCode2 size={13} className="text-slate-500 shrink-0" />
                  <input
                    value={filePath}
                    onChange={(e) => {
                      setFilePath(e.target.value);
                      setFileQuery(e.target.value);
                      setShowFileSuggestions(true);
                    }}
                    onBlur={() => setTimeout(() => setShowFileSuggestions(false), 200)}
                    placeholder="e.g. backend/app/services/change_impact.py"
                    className="w-full bg-transparent text-[12px] text-slate-200 placeholder-slate-600 outline-none"
                  />
                  {filePath && (
                    <button type="button" onClick={() => setFilePath('')}>
                      <X size={12} className="text-slate-500 hover:text-slate-300" />
                    </button>
                  )}
                </div>
                {showFileSuggestions && filteredFiles.length > 0 && (
                  <div className="absolute z-20 mt-1 w-full rounded-lg border border-white/[0.08] bg-[#111824] shadow-xl overflow-hidden">
                    {filteredFiles.map((f) => (
                      <button
                        key={f.id}
                        type="button"
                        onMouseDown={() => { setFilePath(f.relative_path); setFileQuery(f.relative_path); setShowFileSuggestions(false); }}
                        className="flex w-full items-center gap-2 px-3 py-2 text-left text-[11px] hover:bg-white/[0.05] transition-colors"
                      >
                        <FileCode2 size={11} className="text-slate-500 shrink-0" />
                        <span className="text-slate-300 truncate">{f.relative_path}</span>
                        <span className="ml-auto text-slate-600">{f.language}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* Symbol selector */}
              <div className="relative">
                <label className="mb-1 block text-[11px] text-slate-400">Function / Class / API (optional)</label>
                <div className="flex items-center gap-2 rounded-lg border border-white/[0.08] bg-white/[0.03] px-3 py-2">
                  <Code2 size={13} className="text-slate-500 shrink-0" />
                  <input
                    value={symbolName}
                    onChange={(e) => {
                      setSymbolName(e.target.value);
                      setSymbolQuery(e.target.value);
                      setShowSymbolSuggestions(true);
                    }}
                    onBlur={() => setTimeout(() => setShowSymbolSuggestions(false), 200)}
                    placeholder="e.g. ChangeImpactService.analyze"
                    className="w-full bg-transparent text-[12px] text-slate-200 placeholder-slate-600 outline-none"
                  />
                  {symbolName && (
                    <button type="button" onClick={() => setSymbolName('')}>
                      <X size={12} className="text-slate-500 hover:text-slate-300" />
                    </button>
                  )}
                </div>
                {showSymbolSuggestions && filteredSymbols.length > 0 && (
                  <div className="absolute z-20 mt-1 w-full rounded-lg border border-white/[0.08] bg-[#111824] shadow-xl overflow-hidden">
                    {filteredSymbols.map((s) => (
                      <button
                        key={s.id}
                        type="button"
                        onMouseDown={() => { setSymbolName(s.qualified_name || s.name); setSymbolQuery(s.qualified_name || s.name); setShowSymbolSuggestions(false); }}
                        className="flex w-full items-center gap-2 px-3 py-2 text-left text-[11px] hover:bg-white/[0.05] transition-colors"
                      >
                        <Code2 size={11} className="text-slate-500 shrink-0" />
                        <span className="text-slate-300 truncate">{s.qualified_name || s.name}</span>
                        <span className="ml-auto rounded bg-indigo-500/15 px-1 py-0.5 text-[9px] text-indigo-400">{s.symbol_type}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* Branch */}
              <div>
                <label className="mb-1 block text-[11px] text-slate-400">Branch context (optional, informational)</label>
                <div className="flex items-center gap-2 rounded-lg border border-white/[0.08] bg-white/[0.03] px-3 py-2">
                  <GitBranch size={13} className="text-slate-500 shrink-0" />
                  <input
                    value={branch}
                    onChange={(e) => setBranch(e.target.value)}
                    placeholder={`e.g. ${repository.default_branch || 'main'}`}
                    className="w-full bg-transparent text-[12px] text-slate-200 placeholder-slate-600 outline-none"
                  />
                </div>
              </div>
            </div>

            {/* Proposed change */}
            <div className="space-y-3">
              <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wide">2. Describe the Proposed Change</p>

              {/* Mode toggle */}
              <div className="flex rounded-lg border border-white/[0.07] overflow-hidden">
                {([
                  { id: 'description', label: 'Natural Language', icon: Sparkles },
                  { id: 'code', label: 'Proposed Code', icon: Code2 },
                  { id: 'diff', label: 'Diff / Patch', icon: GitCompare },
                ] as const).map(({ id, label, icon: Icon }) => (
                  <button
                    key={id}
                    type="button"
                    onClick={() => setInputMode(id)}
                    className={cx(
                      'flex flex-1 items-center justify-center gap-1.5 py-2 text-[11px] font-medium transition-colors',
                      inputMode === id
                        ? 'bg-indigo-500/20 text-indigo-300 border-r border-white/[0.07] last:border-r-0'
                        : 'text-slate-500 hover:text-slate-300 border-r border-white/[0.07] last:border-r-0',
                    )}
                  >
                    <Icon size={11} />
                    {label}
                  </button>
                ))}
              </div>

              {/* Required: natural language description */}
              <div>
                <label className="mb-1 block text-[11px] text-slate-400">
                  Natural language description <span className="text-rose-400">*</span>
                </label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="e.g. Add rate limiting middleware to the /analyze endpoint that limits to 100 requests/minute per IP, returning 429 if exceeded."
                  rows={3}
                  className="w-full rounded-lg border border-white/[0.08] bg-white/[0.03] px-3 py-2 text-[12px] text-slate-200 placeholder-slate-600 outline-none resize-none focus:border-indigo-400/40 focus:bg-white/[0.04] transition-colors"
                />
              </div>

              {/* Optional: proposed code */}
              {inputMode === 'code' && (
                <div>
                  <label className="mb-1 block text-[11px] text-slate-400">Proposed replacement code (optional)</label>
                  <textarea
                    value={proposedCode}
                    onChange={(e) => setProposedCode(e.target.value)}
                    placeholder="Paste the proposed function/class implementation here..."
                    rows={8}
                    className="w-full rounded-lg border border-white/[0.08] bg-[#080e18] px-3 py-2 font-mono text-[11px] text-emerald-300/80 placeholder-slate-600 outline-none resize-none focus:border-indigo-400/40 transition-colors"
                  />
                </div>
              )}

              {/* Optional: diff */}
              {inputMode === 'diff' && (
                <div>
                  <label className="mb-1 block text-[11px] text-slate-400">Unified diff / patch (optional)</label>
                  <textarea
                    value={proposedDiff}
                    onChange={(e) => setProposedDiff(e.target.value)}
                    placeholder="--- a/file.py&#10;+++ b/file.py&#10;@@ -1,5 +1,6 @@&#10; ..."
                    rows={8}
                    className="w-full rounded-lg border border-white/[0.08] bg-[#080e18] px-3 py-2 font-mono text-[11px] text-slate-300 placeholder-slate-600 outline-none resize-none focus:border-indigo-400/40 transition-colors"
                  />
                </div>
              )}
            </div>

            {/* Analysis options */}
            <div className="space-y-3">
              <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wide">3. Analysis Options</p>
              <div className="grid grid-cols-2 gap-2">
                {([
                  { key: 'security', label: 'Security analysis', icon: Shield },
                  { key: 'performance', label: 'Performance analysis', icon: Zap },
                  { key: 'migration', label: 'Migration requirements', icon: Layers },
                  { key: 'regression', label: 'Regression test recs', icon: TestTube2 },
                ] as const).map(({ key, label, icon: Icon }) => (
                  <label key={key} className="flex items-center gap-2 cursor-pointer rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2 hover:border-white/15 transition-colors">
                    <input
                      type="checkbox"
                      checked={includeFlags[key]}
                      onChange={(e) => setIncludeFlags((f) => ({ ...f, [key]: e.target.checked }))}
                      className="accent-indigo-500"
                    />
                    <Icon size={11} className="text-slate-500 shrink-0" />
                    <span className="text-[11px] text-slate-300">{label}</span>
                  </label>
                ))}
              </div>

              {/* Alternative proposals */}
              <div>
                <button
                  type="button"
                  onClick={() => setAlternativesMode((v) => !v)}
                  className="flex items-center gap-1.5 text-[11px] text-slate-500 hover:text-slate-300 transition-colors"
                >
                  <ChevronRight size={11} className={cx('transition-transform', alternativesMode && 'rotate-90')} />
                  Add alternative proposals to compare
                </button>
                {alternativesMode && (
                  <div className="mt-2">
                    <label className="mb-1 block text-[11px] text-slate-400">One alternative per line</label>
                    <textarea
                      value={alternatives}
                      onChange={(e) => setAlternatives(e.target.value)}
                      placeholder={"Add caching layer instead of rate limiting\nRefactor to a separate microservice"}
                      rows={3}
                      className="w-full rounded-lg border border-white/[0.08] bg-white/[0.03] px-3 py-2 text-[12px] text-slate-200 placeholder-slate-600 outline-none resize-none focus:border-indigo-400/40 transition-colors"
                    />
                  </div>
                )}
              </div>
            </div>

            {/* Error */}
            {error && (
              <div className="flex items-center gap-2 rounded-lg border border-rose-500/20 bg-rose-500/10 px-3 py-2">
                <AlertTriangle size={13} className="text-rose-400 shrink-0" />
                <p className="text-[12px] text-rose-300">{error}</p>
              </div>
            )}

            {/* Submit */}
            <button
              type="button"
              onClick={handleSimulate}
              disabled={loading || !description.trim()}
              className={cx(
                'flex w-full items-center justify-center gap-2 rounded-xl py-3 text-[13px] font-semibold transition-all',
                loading || !description.trim()
                  ? 'cursor-not-allowed bg-indigo-500/20 text-indigo-400/50'
                  : 'bg-indigo-500 text-white hover:bg-indigo-400 hover:shadow-[0_0_20px_rgba(99,102,241,0.3)] active:scale-[0.99]',
              )}
            >
              {loading ? (
                <>
                  <RefreshCw size={14} className="animate-spin" />
                  Simulating change…
                </>
              ) : (
                <>
                  <FlaskConical size={14} />
                  Run Simulation
                </>
              )}
            </button>

            {/* Safety guarantee */}
            <div className="flex items-center gap-2 rounded-lg border border-slate-700/50 bg-slate-800/30 px-3 py-2">
              <Lock size={11} className="text-slate-500 shrink-0" />
              <p className="text-[10px] text-slate-500">
                This simulation is <strong className="text-slate-400">read-only</strong>. No changes are written, committed, or deployed.
              </p>
            </div>
          </div>
        ) : (
          /* ── Results View ──────────────────────────────────────────────── */
          <div className="flex flex-col min-h-0">
            {/* Simulation info bar */}
            <div className="flex items-center gap-3 border-b border-white/[0.05] px-5 py-2.5 bg-[#0a0f1a]/50 shrink-0 flex-wrap gap-y-1">
              <span className="text-[10px] text-slate-500 font-mono">SIM#{result.simulation_id}</span>
              {result.target_file && (
                <span className="flex items-center gap-1 text-[10px] text-slate-400">
                  <FileCode2 size={10} className="text-cyan-400" />
                  {result.target_file}
                </span>
              )}
              {result.target_symbol && (
                <span className="flex items-center gap-1 text-[10px] text-slate-400">
                  <Code2 size={10} className="text-indigo-400" />
                  {result.target_symbol}
                </span>
              )}
              {result.branch_context && (
                <span className="flex items-center gap-1 text-[10px] text-slate-400">
                  <GitBranch size={10} />
                  {result.branch_context}
                </span>
              )}
              <span className={cx('ml-auto flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase border',
                (SEVERITY_CONFIG[result.overall_risk] ?? SEVERITY_CONFIG.medium).bg,
                (SEVERITY_CONFIG[result.overall_risk] ?? SEVERITY_CONFIG.medium).text,
                (SEVERITY_CONFIG[result.overall_risk] ?? SEVERITY_CONFIG.medium).border,
              )}>
                <AlertCircle size={9} />
                {result.overall_risk} risk
              </span>
            </div>

            {/* Tabs */}
            <div className="flex overflow-x-auto border-b border-white/[0.05] shrink-0 scrollbar-none">
              {tabs.map(({ id, label, icon: Icon, count }) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setActiveTab(id as typeof activeTab)}
                  className={cx(
                    'flex shrink-0 items-center gap-1.5 border-b-2 px-4 py-2.5 text-[11px] font-medium transition-colors whitespace-nowrap',
                    activeTab === id
                      ? 'border-indigo-400 text-indigo-300'
                      : 'border-transparent text-slate-500 hover:text-slate-300 hover:border-white/20',
                  )}
                >
                  <Icon size={11} />
                  {label}
                  {count !== undefined && count > 0 && (
                    <span className={cx('rounded-full px-1.5 py-0.5 text-[9px] font-bold',
                      activeTab === id ? 'bg-indigo-500/30 text-indigo-300' : 'bg-white/[0.08] text-slate-400'
                    )}>
                      {count}
                    </span>
                  )}
                </button>
              ))}
            </div>

            {/* Tab content */}
            <div className="flex-1 overflow-y-auto px-5 py-5 min-h-0">
              {activeTab === 'overview' && <RiskOverview r={result} />}
              {activeTab === 'breaking' && <BreakingChangesTab items={result.breaking_changes} />}
              {activeTab === 'affected' && <AffectedFilesTab items={result.affected_files} funcs={result.impacted_functions} />}
              {activeTab === 'tests' && <TestRisksTab risks={result.test_failure_risks} recs={result.regression_test_recommendations} />}
              {activeTab === 'security' && <SecurityTab items={result.security_implications} />}
              {activeTab === 'perf' && <PerfTab perf={result.performance_concerns} mig={result.migration_requirements} />}
              {activeTab === 'patch' && <PatchTab patch={result.patch} />}
              {activeTab === 'alternatives' && <AlternativesTab alts={result.alternatives} />}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
