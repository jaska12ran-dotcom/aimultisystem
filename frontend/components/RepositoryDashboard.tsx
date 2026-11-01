'use client';

import dynamic from 'next/dynamic';
import {
  Activity, AlertTriangle, ArrowUpRight, BookOpen, Boxes,
  Braces, Bug, Check, ChevronDown, CircleHelp, Clock3, Code2, Command,
  FileCode2, FileText, FlaskConical, GitBranch, GitCommitHorizontal, GitPullRequest,
  LayoutDashboard, LoaderCircle, LockKeyhole, Network, Package,
  Plus, RefreshCw, Search, Send, Shield, Sparkles, TerminalSquare, TestTube2,
  Workflow, X,
} from 'lucide-react';
import {
  Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts';
import { useCallback, useEffect, useMemo, useState } from 'react';
import Navbar from './Navbar';
import IngestModal from './IngestModal';
import WhatIfSimulator from './WhatIfSimulator';
import { apiService } from '../services/api';
import {
  DocumentationDrift, GitHistory, ImpactAnalysis, ImpactComponent, RepositoryGraph, SecurityAnalysis,
  RepositoryIndexStatus, RegressionSelection, TestStrengthReport, TechnicalDebtReport, OnboardingGuide, BusinessRuleReport, CodeMemory,
  CodeHealthReport, DependencySecurityReport, TestFailureExplanationReport, OrchestratorStep,
  intelligenceApi,
} from '../services/intelligence';
import { CodeSymbol, FileItem, Repository } from '../types';

const MonacoEditor = dynamic(() => import('@monaco-editor/react'), { ssr: false });

const NAV_ITEMS = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard, group: 'Workspace' },
  { id: 'explorer', label: 'Repository explorer', icon: FileCode2, group: 'Workspace' },
  { id: 'graph', label: 'Knowledge graph', icon: Network, group: 'Workspace' },
  { id: 'chat', label: 'AI chat', icon: Sparkles, group: 'Workspace' },
  { id: 'docs', label: 'Documentation', icon: BookOpen, group: 'Quality' },
  { id: 'tests', label: 'Tests', icon: TestTube2, group: 'Quality' },
  { id: 'security', label: 'Security', icon: Shield, group: 'Quality' },
  { id: 'architecture', label: 'Architecture', icon: Boxes, group: 'Quality' },
  { id: 'impact', label: 'Change impact', icon: GitPullRequest, group: 'Insights' },
  { id: 'whatif', label: 'What-If Simulator', icon: FlaskConical, group: 'Insights' },
  { id: 'git', label: 'Git intelligence', icon: GitBranch, group: 'Insights' },
  { id: 'debt', label: 'Technical debt', icon: AlertTriangle, group: 'Insights' },
  { id: 'onboarding', label: 'Onboarding', icon: BookOpen, group: 'Insights' },
  { id: 'rules', label: 'Business rules', icon: Braces, group: 'Insights' },
  { id: 'health', label: 'Repository health', icon: Activity, group: 'Insights' },
  { id: 'errors', label: 'Error history', icon: Bug, group: 'Insights' },
] as const;

type SectionId = (typeof NAV_ITEMS)[number]['id'];
type SectionData = {
  summary?: Record<string, unknown>;
  files?: FileItem[];
  symbols?: CodeSymbol[];
  dependencies?: Array<{ id: string; package_name: string; ecosystem: string; version_spec?: string | null; is_dev: boolean }>;
  graph?: RepositoryGraph;
  history?: GitHistory;
};
type ChatMessage = {
  role: 'user' | 'assistant';
  text: string;
  citations?: Array<{ file_path: string; line_start?: number; line_end?: number }>;
  confidence?: 'low' | 'medium' | 'high';
  confidenceReasons?: string[];
  limitations?: string;
  intent?: string;
  steps?: OrchestratorStep[];
};
type DocItem = { id: string; title: string; doc_type: string; content_markdown: string };

const TONES = {
  indigo: 'text-indigo-300 bg-indigo-400/10 border-indigo-300/15',
  cyan: 'text-cyan-300 bg-cyan-400/10 border-cyan-300/15',
  emerald: 'text-emerald-300 bg-emerald-400/10 border-emerald-300/15',
  amber: 'text-amber-300 bg-amber-400/10 border-amber-300/15',
  rose: 'text-rose-300 bg-rose-400/10 border-rose-300/15',
};

function cx(...classes: Array<string | false | undefined>) {
  return classes.filter(Boolean).join(' ');
}

function fmt(value: number) {
  return new Intl.NumberFormat('en-US').format(value);
}

function timeAgo(value?: string | null) {
  if (!value) return 'No history';
  const elapsed = Math.max(0, Date.now() - new Date(value).getTime());
  const days = Math.floor(elapsed / 86400000);
  if (days === 0) return 'Today';
  if (days === 1) return 'Yesterday';
  if (days < 30) return `${days} days ago`;
  return `${Math.floor(days / 30)} mo ago`;
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-white/10 bg-white/[0.015] px-6 py-10 text-center">
      <CircleHelp className="mx-auto h-6 w-6 text-slate-600" />
      <p className="mt-3 text-sm font-medium text-slate-300">{title}</p>
      <p className="mx-auto mt-1 max-w-lg text-xs leading-5 text-slate-500">{detail}</p>
    </div>
  );
}

function Panel({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <section className={cx('rounded-2xl border border-white/[0.075] bg-[#111824]/85 shadow-[0_12px_40px_rgba(0,0,0,.12)]', className)}>{children}</section>;
}

function PanelTitle({ icon: Icon, title, detail, action }: {
  icon: typeof Activity;
  title: string;
  detail?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-white/[0.06] px-5 py-4">
      <div className="flex min-w-0 items-center gap-3">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-indigo-300/10 bg-indigo-400/[0.08] text-indigo-300"><Icon size={15} /></span>
        <div className="min-w-0">
          <h2 className="truncate text-[13px] font-semibold text-slate-100">{title}</h2>
          {detail && <p className="mt-0.5 truncate text-[11px] text-slate-500">{detail}</p>}
        </div>
      </div>
      {action}
    </div>
  );
}

function MetricCard({ label, value, sub, icon: Icon, tone, onClick }: {
  label: string; value: string | number; sub: string; icon: typeof Activity; tone: keyof typeof TONES; onClick?: () => void;
}) {
  return (
    <button type="button" onClick={onClick} className="group w-full rounded-2xl border border-white/[0.07] bg-[#111824]/90 p-4 text-left transition hover:-translate-y-0.5 hover:border-indigo-300/20 hover:bg-[#151f2e]">
      <div className="flex items-start justify-between">
        <span className="text-[11px] font-medium text-slate-500">{label}</span>
        <span className={cx('flex h-8 w-8 items-center justify-center rounded-lg border', TONES[tone])}><Icon size={15} /></span>
      </div>
      <div className="mt-3 flex items-end justify-between">
        <span className="text-[25px] font-semibold tracking-tight text-slate-100">{value}</span>
        <ArrowUpRight size={14} className="mb-1 text-slate-700 transition group-hover:text-indigo-300" />
      </div>
      <p className="mt-1 truncate text-[10px] text-slate-500">{sub}</p>
    </button>
  );
}

export default function RepositoryDashboard() {
  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [selectedRepo, setSelectedRepo] = useState<Repository | null>(null);
  const [section, setSection] = useState<SectionId>('overview');
  const [isIngestOpen, setIsIngestOpen] = useState(false);
  const [repositoryLoading, setRepositoryLoading] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [data, setData] = useState<SectionData>({});
  const [activeFile, setActiveFile] = useState<FileItem | null>(null);
  const [editorContent, setEditorContent] = useState('');
  const [editorLoading, setEditorLoading] = useState(false);
  const [highlightLine, setHighlightLine] = useState<number | undefined>();
  const [fileFilter, setFileFilter] = useState('');
  const [graphNode, setGraphNode] = useState<string | null>(null);
  const [question, setQuestion] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [chatLoading, setChatLoading] = useState(false);
  const [chatMode, setChatMode] = useState<'retrieval' | 'agents'>('retrieval');
  const [docs, setDocs] = useState<DocItem[]>([]);
  const [selectedDoc, setSelectedDoc] = useState<DocItem | null>(null);
  const [docDrift, setDocDrift] = useState<DocumentationDrift | null>(null);
  const [driftLoading, setDriftLoading] = useState(false);
  const [docType, setDocType] = useState('architecture');
  const [testResult, setTestResult] = useState<Record<string, unknown> | null>(null);
  const [testLoading, setTestLoading] = useState(false);
  const [testStrength, setTestStrength] = useState<TestStrengthReport | null>(null);
  const [testStrengthLoading, setTestStrengthLoading] = useState(false);
  const [changedTestFiles, setChangedTestFiles] = useState('');
  const [changedTestSymbols, setChangedTestSymbols] = useState('');
  const [regressionSelection, setRegressionSelection] = useState<RegressionSelection | null>(null);
  const [regressionLoading, setRegressionLoading] = useState(false);
  const [security, setSecurity] = useState<SecurityAnalysis | null>(null);
  const [securityLoading, setSecurityLoading] = useState(false);
  const [debt, setDebt] = useState<TechnicalDebtReport | null>(null);
  const [debtLoading, setDebtLoading] = useState(false);
  const [onboarding, setOnboarding] = useState<OnboardingGuide | null>(null);
  const [onboardingLoading, setOnboardingLoading] = useState(false);
  const [businessRules, setBusinessRules] = useState<BusinessRuleReport | null>(null);
  const [rulesLoading, setRulesLoading] = useState(false);
  const [memoryTarget, setMemoryTarget] = useState('');
  const [memory, setMemory] = useState<CodeMemory | null>(null);
  const [impactQuery, setImpactQuery] = useState('');
  const [impactResult, setImpactResult] = useState<ImpactAnalysis | null>(null);
  const [impactLoading, setImpactLoading] = useState(false);
  const [indexStatus, setIndexStatus] = useState<RepositoryIndexStatus | null>(null);
  const [reindexLoading, setReindexLoading] = useState(false);
  const [whyAnswer, setWhyAnswer] = useState<Record<string, unknown> | null>(null);
  const [whyLoading, setWhyLoading] = useState(false);
  const [codeHealth, setCodeHealth] = useState<CodeHealthReport | null>(null);
  const [codeHealthLoading, setCodeHealthLoading] = useState(false);
  const [depSecurity, setDepSecurity] = useState<DependencySecurityReport | null>(null);
  const [depSecurityLoading, setDepSecurityLoading] = useState(false);
  const [errorHistory, setErrorHistory] = useState<ErrorHistoryEntry[]>([]);
  const [errorSummary, setErrorSummary] = useState<RepositoryErrorSummary | null>(null);
  const [errorHistoryLoading, setErrorHistoryLoading] = useState(false);
  const [errorResolvedFilter, setErrorResolvedFilter] = useState<'all' | 'resolved' | 'unresolved'>('all');
  const [failureOutput, setFailureOutput] = useState('');
  const [failureReport, setFailureReport] = useState<TestFailureExplanationReport | null>(null);
  const [failureLoading, setFailureLoading] = useState(false);

  const loadRepositories = useCallback(async () => {
    setRepositoryLoading(true);
    try {
      const items = await apiService.listRepositories();
      setRepositories(items);
      setSelectedRepo((current) => current ? items.find((item) => item.id === current.id) || items[0] || null : items[0] || null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not load repositories.');
    } finally {
      setRepositoryLoading(false);
    }
  }, []);

  useEffect(() => { void loadRepositories(); }, [loadRepositories]);

  const loadWorkspace = useCallback(async (repo: Repository) => {
    setLoading(true);
    setError('');
    setData({});
    setSecurity(null);
    setDebt(null);
    setOnboarding(null);
    setBusinessRules(null);
    setMemory(null);
    setDocs([]);
    setDocDrift(null);
    setTestResult(null);
    setTestStrength(null);
    setRegressionSelection(null);
    setChangedTestFiles('');
    setChangedTestSymbols('');
    setImpactResult(null);
    setWhyAnswer(null);
    setIndexStatus(null);
    setActiveFile(null);
    try {
      const results = await Promise.allSettled([
        intelligenceApi.summary(repo.id),
        intelligenceApi.files(repo.id),
        intelligenceApi.symbols(repo.id),
        intelligenceApi.dependencies(repo.id),
        intelligenceApi.graph(repo.id),
        intelligenceApi.history(repo.id),
        intelligenceApi.indexStatus(repo.id),
      ]);
      const [summary, files, symbols, dependencies, graph, history, indexStatusResult] = results;
      setData({
        summary: summary.status === 'fulfilled' ? summary.value as unknown as Record<string, unknown> : undefined,
        files: files.status === 'fulfilled' ? files.value : undefined,
        symbols: symbols.status === 'fulfilled' ? symbols.value : undefined,
        dependencies: dependencies.status === 'fulfilled' ? dependencies.value : undefined,
        graph: graph.status === 'fulfilled' ? graph.value : undefined,
        history: history.status === 'fulfilled' ? history.value : undefined,
      });
      setIndexStatus(indexStatusResult.status === 'fulfilled' ? indexStatusResult.value : null);
      const failures = results.filter((result) => result.status === 'rejected');
      if (failures.length === results.length) {
        throw new Error('Could not load repository intelligence. Check the API connection.');
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not load repository data.');
    } finally {
      setLoading(false);
    }
  }, []);

  const reindexRepository = async () => {
    if (!selectedRepo || reindexLoading) return;
    setReindexLoading(true);
    setError('');
    try {
      await intelligenceApi.reindex(selectedRepo.id);
      await loadWorkspace(selectedRepo);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Repository reindex failed.');
    } finally {
      setReindexLoading(false);
    }
  };

  useEffect(() => {
    if (selectedRepo) void loadWorkspace(selectedRepo);
  }, [selectedRepo, loadWorkspace]);

  useEffect(() => {
    if (section === 'docs') void loadDocs();
    // Documentation records are fetched when that workspace section is opened.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [section, selectedRepo?.id]);

  const openFile = useCallback(async (path: string, line?: number | null) => {
    if (!selectedRepo) return;
    const found = data.files?.find((file) => file.relative_path === path);
    if (!found) {
      setError(`Source file “${path}” is not present in the repository index.`);
      return;
    }
    setActiveFile(found);
    setHighlightLine(line || undefined);
    setEditorLoading(true);
    setEditorContent('');
    setSection('explorer');
    try {
      const content = await intelligenceApi.fileContent(selectedRepo.id, found.relative_path);
      setEditorContent(content.content);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not load the source file.');
    } finally {
      setEditorLoading(false);
    }
  }, [data.files, selectedRepo]);

  const summary = data.summary as {
    total_files?: number; total_lines?: number; total_symbols?: number; total_relationships?: number;
    symbol_types_breakdown?: Record<string, number>;
    languages?: Array<{ language: string; file_count: number; line_count: number; percentage: number }>;
    api_routes?: CodeSymbol[]; db_models?: CodeSymbol[]; recent_commits?: Array<{ id: string; message: string; author_name: string; committed_at: string; files_changed: string[] }>;
  } | undefined;
  const files = useMemo(() => data.files || [], [data.files]);
  const symbols = data.symbols || [];
  const dependencies = data.dependencies || [];
  const history = data.history;
  const graph = data.graph;
  const countType = (type: string) => symbols.filter((item) => item.symbol_type === type).length;
  const testFiles = files.filter((file) => file.is_test);
  const highComplexity = symbols.filter((symbol) => symbol.complexity_score >= 10);
  const healthParts = [
    Math.min(100, summary?.total_files ? 75 + Math.min(25, Math.round(symbols.length / Math.max(1, summary.total_files))) : 0),
    files.length ? Math.max(0, 100 - Math.round((highComplexity.length / Math.max(1, symbols.length)) * 100)) : 0,
    history?.history_available ? 90 : 40,
    dependencies.length ? 80 : 55,
  ];
  const healthScore = files.length ? Math.round(healthParts.reduce((a, b) => a + b, 0) / healthParts.length) : 0;

  const chartLanguages = (summary?.languages || []).slice(0, 6).map((item) => ({
    name: item.language, files: item.file_count, value: item.line_count,
  }));
  const languageColors = ['#818cf8', '#22d3ee', '#34d399', '#fbbf24', '#f472b6', '#a78bfa'];

  const viewEvidence = (path: string, line?: number | null) => {
    void openFile(path, line);
  };

  const runSecurity = async () => {
    if (!selectedRepo) return;
    setSecurityLoading(true);
    setError('');
    try {
      setSecurity(await intelligenceApi.security(selectedRepo.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Security analysis failed.');
    } finally {
      setSecurityLoading(false);
    }
  };

  const runDebtAnalysis = async () => {
    if (!selectedRepo) return;
    setDebtLoading(true);
    setError('');
    try {
      setDebt(await intelligenceApi.technicalDebt(selectedRepo.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Technical debt analysis failed.');
    } finally {
      setDebtLoading(false);
    }
  };

  const loadOnboarding = async () => { if (!selectedRepo) return; setOnboardingLoading(true); try { setOnboarding(await intelligenceApi.onboarding(selectedRepo.id)); } catch (reason) { setError(reason instanceof Error ? reason.message : 'Onboarding analysis failed.'); } finally { setOnboardingLoading(false); } };
  const loadBusinessRules = async () => { if (!selectedRepo) return; setRulesLoading(true); try { setBusinessRules(await intelligenceApi.businessRules(selectedRepo.id)); } catch (reason) { setError(reason instanceof Error ? reason.message : 'Business rule analysis failed.'); } finally { setRulesLoading(false); } };
  const loadErrorHistory = async () => {
  const loadCodeMemory = async (event: React.FormEvent) => { event.preventDefault(); if (!selectedRepo || !memoryTarget.trim()) return; try { setMemory(await intelligenceApi.codeMemory(selectedRepo.id, memoryTarget.trim())); } catch (reason) { setError(reason instanceof Error ? reason.message : 'Code memory lookup failed.'); } };

  const loadCodeHealth = async () => {
    if (!selectedRepo) return;
    setCodeHealthLoading(true);
    try { setCodeHealth(await intelligenceApi.codeHealth(selectedRepo.id)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Code health analysis failed.'); }
    finally { setCodeHealthLoading(false); }
  };

  const loadErrorHistory = async () => {
    if (!selectedRepo) return;
    setErrorHistoryLoading(true);
    try {
      const [summary, history] = await Promise.allSettled([
        intelligenceApi.errorSummary(selectedRepo.id),
        intelligenceApi.errors(selectedRepo.id, errorResolvedFilter === 'resolved'),
      ]);
      const summaryResult = summary.status === 'fulfilled' ? summary.value : null;
      const historyResult = history.status === 'fulfilled' ? history.value : [];
      setErrorSummary(summaryResult);
      setErrorHistory(historyResult);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Error history load failed.');
    } finally { setErrorHistoryLoading(false); }
  };

  const loadDependencySecurity = async () => {
    if (!selectedRepo) return;
    setDepSecurityLoading(true);
    try { setDepSecurity(await intelligenceApi.dependencySecurity(selectedRepo.id)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Dependency security scan failed.'); }
    finally { setDepSecurityLoading(false); }
  };

  const explainFailures = async () => {
    if (!selectedRepo || !failureOutput.trim()) return;
    setFailureLoading(true);
    try { setFailureReport(await intelligenceApi.explainTestFailures(selectedRepo.id, failureOutput)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Test failure explanation failed.'); }
    finally { setFailureLoading(false); }
  };

  useEffect(() => {
    if (section === 'health' && selectedRepo && !codeHealth && !codeHealthLoading) {
      void loadCodeHealth();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [section, selectedRepo, codeHealth, codeHealthLoading]);

  useEffect(() => {
    if (selectedRepo && !errorHistoryLoading) {
      void loadErrorHistory();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedRepo, errorHistoryLoading]);

  const runPipeline = async () => {
    if (!selectedRepo) return;
    setTestLoading(true);
    setError('');
    try {
      setTestResult(await intelligenceApi.testPipeline(selectedRepo.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Test pipeline failed.');
    } finally {
      setTestLoading(false);
    }
  };

  const runTestStrength = async () => {
    if (!selectedRepo) return;
    setTestStrengthLoading(true);
    setError('');
    try {
      setTestStrength(await intelligenceApi.testStrength(selectedRepo.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Test strength analysis failed.');
    } finally {
      setTestStrengthLoading(false);
    }
  };

  const selectRegressionTests = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selectedRepo) return;
    const changedFiles = changedTestFiles.split(',').map((item) => item.trim()).filter(Boolean);
    const changedSymbols = changedTestSymbols.split(',').map((item) => item.trim()).filter(Boolean);
    setRegressionLoading(true);
    setError('');
    try {
      setRegressionSelection(await intelligenceApi.selectRegressionTests(selectedRepo.id, changedFiles, changedSymbols));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Regression test selection failed.');
    } finally {
      setRegressionLoading(false);
    }
  };

  const sendQuestion = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selectedRepo || !question.trim()) return;
    const prompt = question.trim();
    setMessages((current) => [...current, { role: 'user', text: prompt }]);
    setQuestion('');
    setChatLoading(true);
    try {
      if (chatMode === 'agents') {
        const result = await intelligenceApi.orchestrate(selectedRepo.id, prompt);
        setMessages((current) => [...current, {
          role: 'assistant',
          text: result.answer,
          confidence: (['low', 'medium', 'high'].includes(result.confidence) ? result.confidence : 'medium') as ChatMessage['confidence'],
          intent: result.intent,
          steps: result.steps,
          limitations: result.limitations.join(' '),
        }]);
      } else {
        const response = await intelligenceApi.ask(selectedRepo.id, prompt);
        setMessages((current) => [...current, {
          role: 'assistant',
          text: response.reply,
          citations: response.citations,
          confidence: response.confidence,
          confidenceReasons: response.confidence_reasons,
          limitations: response.limitations,
        }]);
      }
    } catch (reason) {
      setMessages((current) => [...current, { role: 'assistant', text: reason instanceof Error ? reason.message : 'Could not get an answer.' }]);
    } finally {
      setChatLoading(false);
    }
  };

  const loadDocs = async () => {
    if (!selectedRepo) return;
    try {
      setDocs(await intelligenceApi.docs(selectedRepo.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not load documentation.');
    }
  };

  const generateDoc = async () => {
    if (!selectedRepo) return;
    setLoading(true);
    try {
      const doc = await intelligenceApi.generateDocs(selectedRepo.id, docType);
      await loadDocs();
      setSelectedDoc({ ...doc, id: `new-${Date.now()}` });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Documentation generation failed.');
    } finally {
      setLoading(false);
    }
  };

  const checkDocDrift = async () => {
    if (!selectedRepo || !selectedDoc) return;
    setDriftLoading(true);
    try {
      setDocDrift(await intelligenceApi.docsDrift(selectedRepo.id, selectedDoc.content_markdown));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Documentation drift analysis failed.');
    } finally {
      setDriftLoading(false);
    }
  };

  const runImpact = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selectedRepo || !impactQuery.trim()) return;
    setImpactLoading(true);
    try {
      setImpactResult(await intelligenceApi.impact(selectedRepo.id, impactQuery.trim()));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Impact analysis failed.');
    } finally {
      setImpactLoading(false);
    }
  };

  const askWhy = async (target: string) => {
    if (!selectedRepo) return;
    setWhyLoading(true);
    try {
      const result = await intelligenceApi.whyCode(selectedRepo.id, target);
      setWhyAnswer({
        answer: result.answer,
        limitation: result.limitation,
        sufficient_history: result.sufficient_history,
        evidence: result.evidence,
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not query Git history.');
    } finally {
      setWhyLoading(false);
    }
  };

  const filteredFiles = useMemo(() => files.filter((file) => file.relative_path.toLowerCase().includes(fileFilter.toLowerCase())), [files, fileFilter]);
  const navGroups = ['Workspace', 'Quality', 'Insights'];

  const showCode = (path: string, line?: number | null) => (
    <button type="button" onClick={() => viewEvidence(path, line)} className="inline-flex max-w-full items-center gap-1.5 truncate font-mono text-[11px] text-indigo-300 hover:text-indigo-200 hover:underline">
      <FileCode2 size={12} />{path}{line ? `:${line}` : ''}
    </button>
  );

  const renderOverview = () => (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <MetricCard label="Files indexed" value={fmt(summary?.total_files || files.length)} sub={`${fmt(summary?.total_lines || 0)} source lines`} icon={FileCode2} tone="indigo" onClick={() => setSection('explorer')} />
        <MetricCard label="Functions & methods" value={fmt(countType('function') + countType('method'))} sub={`${countType('class')} classes · ${countType('api_route')} APIs`} icon={Braces} tone="cyan" onClick={() => setSection('explorer')} />
        <MetricCard label="Dependencies" value={fmt(dependencies.length)} sub={`${new Set(dependencies.map((item) => item.ecosystem)).size} ecosystems`} icon={Package} tone="emerald" onClick={() => setSection('architecture')} />
        <MetricCard label="Repository health" value={`${healthScore}`} sub="Evidence-derived index score · /100" icon={Activity} tone={healthScore > 75 ? 'emerald' : 'amber'} onClick={() => setSection('health')} />
      </div>
      <Panel>
        <PanelTitle
          icon={RefreshCw}
          title="Digital twin freshness"
          detail={indexStatus?.last_successful_at ? `Last successful analysis ${new Date(indexStatus.last_successful_at).toLocaleString()}` : 'No successful analysis timestamp is available'}
          action={<button type="button" onClick={() => void reindexRepository()} disabled={reindexLoading || loading} className="inline-flex items-center gap-2 rounded-lg border border-indigo-400/20 bg-indigo-400/10 px-3 py-2 text-[11px] text-indigo-200 disabled:opacity-50"><RefreshCw size={13} className={reindexLoading ? 'animate-spin' : ''} />{reindexLoading ? 'Updating' : 'Reindex repository'}</button>}
        />
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-5 pb-4 text-[11px] text-slate-400">
          <span>Status: <strong className="font-medium text-slate-200">{indexStatus?.status || 'unavailable'}</strong></span>
          {indexStatus?.indexing_health && <span className={`text-[11px] text-slate-400`}>({indexStatus.indexing_health})</span>}
          <span>{fmt(indexStatus?.indexed_file_count || 0)} files / {fmt(indexStatus?.indexed_symbol_count || 0)} symbols indexed</span>
          {indexStatus && <span>Last scan: +{indexStatus.last_added_files} · ~{indexStatus.last_updated_files} · −{indexStatus.last_deleted_files} · ={indexStatus.last_unchanged_files}</span>}
          {indexStatus?.last_error && <span className="text-rose-300">{indexStatus.last_error}</span>}
          {indexStatus?.hours_since_last_analysis !== undefined && indexStatus.hours_since_last_analysis !== null && <span className="text-[11px] ml-2">({Math.round(indexStatus.hours_since_last_analysis)}h ago)</span>}
        </div>
      </Panel>
      <div className="grid gap-5 xl:grid-cols-[1.55fr_1fr]">
        <Panel>
          <PanelTitle icon={Activity} title="Repository composition" detail="Language footprint from indexed file and line counts" />
          <div className="grid gap-4 p-5 md:grid-cols-[1fr_1.25fr]">
            <div className="h-[220px] min-w-0">
              {chartLanguages.length ? (
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={chartLanguages} dataKey="value" nameKey="name" innerRadius={58} outerRadius={88} paddingAngle={4} stroke="none">
                      {chartLanguages.map((entry, index) => <Cell key={entry.name} fill={languageColors[index % languageColors.length]} />)}
                    </Pie>
                    <Tooltip contentStyle={{ background: '#111824', border: '1px solid #263244', borderRadius: 12, color: '#e2e8f0' }} />
                  </PieChart>
                </ResponsiveContainer>
              ) : <div className="grid h-full place-items-center text-xs text-slate-500">No language statistics are available.</div>}
            </div>
            <div className="flex flex-col justify-center gap-3">
              {chartLanguages.map((item, index) => (
                <div key={item.name} className="flex items-center gap-3">
                  <span className="h-2 w-2 rounded-full" style={{ backgroundColor: languageColors[index % languageColors.length] }} />
                  <span className="min-w-0 flex-1 truncate text-xs text-slate-300">{item.name}</span>
                  <span className="text-[11px] tabular-nums text-slate-500">{fmt(item.files)} files</span>
                  <span className="w-10 text-right text-xs text-slate-300">{Math.round((item.value / Math.max(1, chartLanguages.reduce((sum, language) => sum + language.value, 0))) * 100)}%</span>
                </div>
              ))}
              <div className="mt-2 flex flex-wrap gap-2 border-t border-white/[0.06] pt-3 text-[10px] text-slate-500">
                <span>{fmt(countType('class') + countType('db_model'))} classes / data models</span><span>·</span>
                <span>{fmt(testFiles.length)} test files</span><span>·</span>
                <span>{fmt(summary?.total_relationships || 0)} graph edges</span>
              </div>
            </div>
          </div>
        </Panel>
        <Panel>
          <PanelTitle icon={GitCommitHorizontal} title="Recent change activity" detail={`${history?.commits_analyzed ?? 0} indexed commits`} action={<button className="text-[10px] font-medium text-indigo-300 hover:text-indigo-200" onClick={() => setSection('git')}>View history</button>} />
          <div className="divide-y divide-white/[0.045]">
            {(summary?.recent_commits || []).slice(0, 4).map((commit) => (
              <div key={commit.id} className="flex gap-3 px-5 py-3.5">
                <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-indigo-400 shadow-[0_0_10px_rgba(129,140,248,.5)]" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs text-slate-200">{commit.message}</p>
                  <p className="mt-1 text-[10px] text-slate-500">{commit.author_name} · {timeAgo(commit.committed_at)}</p>
                </div>
              </div>
            ))}
            {!summary?.recent_commits?.length && <p className="px-5 py-8 text-center text-xs text-slate-500">No indexed commit messages.</p>}
          </div>
        </Panel>
      </div>
      <div className="grid gap-5 xl:grid-cols-[1.2fr_1fr]">
        <Panel>
          <PanelTitle icon={Activity} title="Codebase inventory" detail="Symbols and dependency surfaces" />
          <div className="h-[230px] p-4">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={[
                { name: 'Functions', count: countType('function') + countType('method') },
                { name: 'Classes', count: countType('class') + countType('db_model') },
                { name: 'API routes', count: countType('api_route') },
                { name: 'Dependencies', count: dependencies.length },
                { name: 'Test files', count: testFiles.length },
              ]} margin={{ top: 10, right: 12, left: -20, bottom: 0 }}>
                <CartesianGrid stroke="#253041" strokeDasharray="3 6" vertical={false} />
                <XAxis dataKey="name" tick={{ fill: '#7f8da3', fontSize: 10 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip cursor={{ fill: 'rgba(129,140,248,.06)' }} contentStyle={{ background: '#111824', border: '1px solid #263244', borderRadius: 12 }} />
                <Bar dataKey="count" fill="#818cf8" radius={[5, 5, 0, 0]} maxBarSize={40} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Panel>
        <Panel>
          <PanelTitle icon={Shield} title="Quality signal" detail="Live checks and metrics available in this workspace" />
          <div className="space-y-1 p-4">
            {[
              { label: 'Test suites', value: testFiles.length ? `${testFiles.length} test files indexed` : 'No test files detected', icon: TestTube2, onClick: () => setSection('tests'), color: 'text-cyan-300' },
              { label: 'Coverage', value: 'Not measured', icon: Activity, onClick: () => setSection('tests'), color: 'text-slate-400' },
              { label: 'Security checks', value: security ? security.summary : 'Run configured scanners', icon: Shield, onClick: () => setSection('security'), color: 'text-emerald-300' },
              { label: 'Architecture', value: graph ? `${graph.counts.relationships} relationships indexed` : 'Not analyzed', icon: Workflow, onClick: () => setSection('architecture'), color: 'text-indigo-300' },
              { label: 'Documentation drift', value: docDrift ? (docDrift.has_drift ? `${docDrift.issues.length} drift issue(s)` : 'No drift detected in checked document') : 'Not assessed', icon: BookOpen, onClick: () => setSection('docs'), color: 'text-amber-300' },
            ].map((item) => (
              <button key={item.label} type="button" onClick={item.onClick} className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition hover:bg-white/[0.035]">
                <item.icon size={15} className={item.color} />
                <span className="w-32 text-xs text-slate-400">{item.label}</span>
                <span className="min-w-0 flex-1 truncate text-right text-[11px] text-slate-300">{item.value}</span>
                <ArrowUpRight size={13} className="text-slate-600" />
              </button>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );

  const renderExplorer = () => (
    <div className="grid min-h-[640px] gap-4 xl:grid-cols-[310px_minmax(0,1fr)]">
      <Panel className="overflow-hidden">
        <PanelTitle icon={FileCode2} title="Repository files" detail={`${fmt(files.length)} indexed`} />
        <div className="border-b border-white/[0.06] p-3">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-2.5 text-slate-500" />
            <input value={fileFilter} onChange={(event) => setFileFilter(event.target.value)} placeholder="Find a file..." className="w-full rounded-lg border border-white/[0.08] bg-[#0b111a] py-2 pl-9 pr-3 text-xs text-slate-200 outline-none placeholder:text-slate-600 focus:border-indigo-400/40" />
          </div>
        </div>
        <div className="max-h-[570px] overflow-auto p-2">
          {filteredFiles.map((file) => (
            <button key={file.id} type="button" onClick={() => void openFile(file.relative_path)} className={cx('flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left transition hover:bg-white/[0.04]', activeFile?.id === file.id && 'bg-indigo-400/10 text-indigo-200')}>
              {file.is_test ? <TestTube2 size={14} className="shrink-0 text-emerald-400" /> : <FileCode2 size={14} className="shrink-0 text-slate-500" />}
              <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-slate-300">{file.relative_path}</span>
              <span className="text-[9px] uppercase text-slate-600">{file.language}</span>
            </button>
          ))}
          {!filteredFiles.length && <p className="px-3 py-8 text-center text-xs text-slate-600">No matching files.</p>}
        </div>
      </Panel>
      <Panel className="min-h-[640px] overflow-hidden">
        <div className="flex h-full min-h-[640px] flex-col">
          <PanelTitle icon={TerminalSquare} title={activeFile?.relative_path || 'Source viewer'} detail={activeFile ? `${activeFile.language} · ${fmt(activeFile.line_count)} lines` : 'Select a repository file'} action={activeFile ? <button onClick={() => setActiveFile(null)} className="rounded-md p-1 text-slate-500 hover:bg-white/5 hover:text-slate-200"><X size={14} /></button> : undefined} />
          {activeFile ? (
            editorLoading ? <div className="grid flex-1 place-items-center text-xs text-slate-500"><LoaderCircle className="mb-2 animate-spin" size={20} />Loading source…</div> :
              <div className="flex-1">
                <MonacoEditor
                  key={`${activeFile.id}:${highlightLine || 0}`}
                  height="590px"
                  language={editorLanguage(activeFile.language)}
                  theme="vs-dark"
                  value={editorContent}
                  options={{
                    readOnly: true, minimap: { enabled: false }, fontSize: 12, lineHeight: 21,
                    fontFamily: 'var(--font-geist-mono), ui-monospace, monospace',
                    scrollBeyondLastLine: false, wordWrap: 'on', automaticLayout: true,
                    padding: { top: 16 }, renderLineHighlight: 'all',
                  }}
                  onMount={(editor) => {
                    if (highlightLine) {
                      editor.revealLineInCenter(highlightLine);
                      editor.setPosition({ lineNumber: highlightLine, column: 1 });
                      editor.focus();
                    }
                  }}
                />
                {highlightLine && <div className="border-t border-indigo-400/20 bg-indigo-400/[0.06] px-4 py-2 text-[10px] text-indigo-200">Opened from repository evidence at line {highlightLine}.</div>}
              </div>
          ) : (
            <div className="grid flex-1 place-items-center px-8 text-center">
              <div><Code2 className="mx-auto h-8 w-8 text-slate-700" /><p className="mt-3 text-sm text-slate-300">Code, without losing context</p><p className="mt-1 max-w-sm text-xs leading-5 text-slate-500">Select a file or open any AI citation to jump directly to its source line.</p></div>
            </div>
          )}
        </div>
      </Panel>
    </div>
  );

  const renderGraph = () => {
    const nodes = (graph?.nodes || []).filter((node) => ['symbol', 'function', 'method', 'class', 'api', 'api_route', 'db_model', 'interface', 'file', 'module'].includes(node.type)).slice(0, 90);
    const edges = (graph?.relationships || []).filter((edge) => nodes.some((node) => node.id === edge.source) && nodes.some((node) => node.id === edge.target)).slice(0, 160);
    const radius = 205;
    const nodePosition = new Map(nodes.map((node, index) => {
      const angle = (Math.PI * 2 * index) / Math.max(nodes.length, 1) - Math.PI / 2;
      return [node.id, { x: 360 + Math.cos(angle) * radius, y: 265 + Math.sin(angle) * radius }];
    }));
    const colorByType: Record<string, string> = { api: '#fb7185', api_route: '#fb7185', class: '#818cf8', db_model: '#34d399', function: '#22d3ee', method: '#22d3ee', file: '#64748b', module: '#fbbf24' };
    const openNode = (nodeId: string) => {
      setGraphNode(nodeId);
      const node = nodes.find((item) => item.id === nodeId);
      const filePath = String(node?.metadata.path || '');
      const fileId = String(node?.metadata.file_id || '');
      const relatedFile = files.find((file) => file.relative_path === filePath || file.id === fileId);
      if (relatedFile) void openFile(relatedFile.relative_path, Number(node?.metadata.start_line) || undefined);
      else {
        const targetSymbol = symbols.find((symbol) => `symbol:${symbol.id}` === nodeId);
        if (targetSymbol?.relative_path) void openFile(targetSymbol.relative_path, targetSymbol.start_line);
      }
    };
    return (
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.7fr)_330px]">
        <Panel className="overflow-hidden">
          <PanelTitle icon={Network} title="Interactive repository graph" detail={`${graph?.counts.nodes || 0} nodes · ${graph?.counts.relationships || 0} relationships`} />
          {nodes.length ? (
            <div className="h-[570px] overflow-hidden bg-[radial-gradient(ellipse_at_center,rgba(99,102,241,.08),transparent_70%)]">
              <svg viewBox="0 0 720 530" className="h-full w-full" role="img" aria-label="Interactive code relationship graph">
                {edges.map((edge, index) => {
                  const from = nodePosition.get(edge.source);
                  const to = nodePosition.get(edge.target);
                  if (!from || !to) return null;
                  return <line key={`${edge.source}-${edge.target}-${index}`} x1={from.x} y1={from.y} x2={to.x} y2={to.y} stroke={edge.type === 'calls' ? '#818cf8' : '#334155'} strokeOpacity={edge.type === 'calls' ? '.52' : '.38'} strokeWidth={edge.type === 'calls' ? 1.3 : 1} />;
                })}
                {nodes.map((node) => {
                  const pos = nodePosition.get(node.id);
                  if (!pos) return null;
                  const color = colorByType[node.type] || '#a78bfa';
                  const selected = graphNode === node.id;
                  return (
                    <g key={node.id} className="cursor-pointer" onClick={() => openNode(node.id)} tabIndex={0} role="button" aria-label={`Open ${node.name}`}>
                      <circle cx={pos.x} cy={pos.y} r={selected ? 10 : 7} fill={color} fillOpacity={selected ? '.95' : '.78'} stroke={selected ? '#fff' : color} strokeWidth={selected ? 2 : 1} />
                      <text x={pos.x} y={pos.y + 20} fill={selected ? '#f8fafc' : '#9aa8bd'} textAnchor="middle" fontSize="9">{node.name.slice(0, 24)}</text>
                    </g>
                  );
                })}
              </svg>
            </div>
          ) : <div className="p-5"><EmptyState title="Graph relationships are not indexed" detail="Run repository analysis and refresh the graph to explore relationships." /></div>}
          <div className="flex flex-wrap gap-4 border-t border-white/[0.06] px-5 py-3">
            {Object.entries(colorByType).slice(0, 5).map(([label, color]) => <span key={label} className="flex items-center gap-2 text-[10px] capitalize text-slate-500"><i className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />{label.replace('_', ' ')}</span>)}
            <span className="ml-auto text-[10px] text-slate-600">Select a node to open its source file</span>
          </div>
        </Panel>
        <Panel>
          <PanelTitle icon={Workflow} title="Relationship feed" detail="Stored graph edges" />
          <div className="max-h-[620px] divide-y divide-white/[0.045] overflow-auto">
            {edges.slice(0, 32).map((edge, index) => {
              const from = nodes.find((item) => item.id === edge.source);
              const to = nodes.find((item) => item.id === edge.target);
              return <button key={`${edge.source}-${edge.target}-${index}`} onClick={() => openNode(edge.source)} className="block w-full px-4 py-3 text-left transition hover:bg-white/[0.035]">
                <div className="truncate text-[11px] text-slate-300">{from?.name || edge.source}</div>
                <div className="my-1 flex items-center gap-2 pl-2 text-[9px] uppercase tracking-wider text-indigo-300"><span className="h-px w-4 bg-indigo-400/40" />{edge.type}<span className="h-px w-4 bg-indigo-400/40" /></div>
                <div className="truncate text-[11px] text-slate-500">{to?.name || edge.target}</div>
              </button>;
            })}
          </div>
        </Panel>
      </div>
    );
  };

  const renderChat = () => (
    <Panel className="mx-auto flex min-h-[650px] max-w-5xl flex-col overflow-hidden">
      <PanelTitle
        icon={Sparkles}
        title="Repository AI"
        detail={chatMode === 'agents' ? 'Multi-agent mode: your question is routed to specialist analyzers' : 'Answers are grounded in repository context and citations'}
        action={<div className="flex overflow-hidden rounded-lg border border-white/[0.08]">{([['retrieval', 'Retrieval'], ['agents', 'Multi-agent']] as const).map(([mode, label]) => <button key={mode} onClick={() => setChatMode(mode)} className={cx('px-3 py-1.5 text-[10px] font-medium', chatMode === mode ? 'bg-indigo-500 text-white' : 'text-slate-400 hover:bg-white/[0.04]')}>{label}</button>)}</div>}
      />
      <div className="flex-1 space-y-5 overflow-auto p-5">
        {!messages.length && <div className="mx-auto mt-16 max-w-lg text-center"><div className="mx-auto grid h-12 w-12 place-items-center rounded-2xl border border-indigo-300/15 bg-indigo-400/10 text-indigo-300"><Sparkles size={20} /></div><h2 className="mt-4 text-lg font-semibold text-slate-100">Ask about this codebase</h2><p className="mt-2 text-xs leading-5 text-slate-500">Explore implementation details, dependencies, APIs, and relationships. Answers can be checked against cited source.</p><div className="mt-5 flex flex-wrap justify-center gap-2">{(chatMode === 'agents' ? ['Is the code health good?', 'Do we have vulnerable dependencies?', 'What is the production readiness?'] : ['Where are API routes defined?', 'How does authentication work?', 'Which modules call this function?']).map((example) => <button key={example} onClick={() => setQuestion(example)} className="rounded-full border border-white/[0.08] px-3 py-2 text-[10px] text-slate-400 hover:border-indigo-300/30 hover:text-slate-200">{example}</button>)}</div></div>}
        {messages.map((message, index) => (
          <div key={`${message.role}-${index}`} className={cx('flex gap-3', message.role === 'user' && 'flex-row-reverse')}>
            <div className={cx('grid h-8 w-8 shrink-0 place-items-center rounded-lg', message.role === 'user' ? 'bg-slate-700 text-slate-300' : 'bg-indigo-400/10 text-indigo-300')}><span className="text-[10px] font-bold">{message.role === 'user' ? 'YOU' : 'AI'}</span></div>
            <div className={cx('max-w-[82%] rounded-2xl px-4 py-3', message.role === 'user' ? 'bg-indigo-500/15 text-slate-200' : 'border border-white/[0.06] bg-[#0c121c] text-slate-300')}>
              <p className="whitespace-pre-wrap text-xs leading-6">{message.text}</p>
              {message.role === 'assistant' && message.intent && <div className="mt-3 border-t border-white/[0.06] pt-2">
                <span className="rounded-full border border-indigo-300/20 bg-indigo-400/[0.08] px-2 py-0.5 text-[9px] uppercase tracking-wide text-indigo-300">intent: {message.intent}</span>
                {!!message.steps?.length && <div className="mt-2 space-y-1.5">{message.steps.map((step, stepIndex) => <div key={`${step.agent}-${stepIndex}`} className="flex items-start gap-2 text-[9px] leading-4">
                  <span className={cx('mt-1 h-1.5 w-1.5 shrink-0 rounded-full', step.status === 'completed' ? 'bg-emerald-400' : step.status === 'failed' ? 'bg-rose-400' : 'bg-slate-500')} />
                  <span className="shrink-0 font-medium text-slate-300">{step.agent}</span>
                  <span className="text-slate-500">{step.result_summary}</span>
                </div>)}</div>}
              </div>}
              {message.role === 'assistant' && message.confidence && <div className="mt-3 border-t border-white/[0.06] pt-2 text-[9px] leading-4 text-slate-500">
                <span className="font-semibold uppercase tracking-wide text-indigo-300">Evidence confidence: {message.confidence}</span>
                {message.confidenceReasons?.map((reason, reasonIndex) => <p key={reasonIndex}>{reason}</p>)}
                {message.limitations && <p>{message.limitations}</p>}
              </div>}
              {!!message.citations?.length && <div className="mt-3 flex flex-wrap gap-2 border-t border-white/[0.06] pt-2">{message.citations.map((citation, citeIndex) => <button key={`${citation.file_path}-${citeIndex}`} onClick={() => viewEvidence(citation.file_path, citation.line_start)} className="rounded-lg border border-indigo-300/15 bg-indigo-400/[0.06] px-2 py-1.5 font-mono text-[9px] text-indigo-300 hover:bg-indigo-400/10">{citation.file_path}{citation.line_start ? `:${citation.line_start}` : ''}</button>)}</div>}
            </div>
          </div>
        ))}
        {chatLoading && <div className="flex items-center gap-2 text-xs text-slate-500"><LoaderCircle size={14} className="animate-spin" />Reading repository context…</div>}
      </div>
      <form onSubmit={sendQuestion} className="border-t border-white/[0.06] bg-[#0c121c]/60 p-4">
        <div className="flex items-end gap-3 rounded-xl border border-white/[0.09] bg-[#0a1018] p-2 focus-within:border-indigo-300/35">
          <textarea rows={2} value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Ask a question about the repository…" className="max-h-32 min-h-12 flex-1 resize-y bg-transparent px-2 py-1.5 text-xs leading-5 text-slate-200 outline-none placeholder:text-slate-600" />
          <button disabled={!question.trim() || chatLoading} className="mb-1 grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-indigo-500 text-white transition hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-40"><Send size={15} /></button>
        </div>
        <p className="mt-2 text-center text-[9px] text-slate-600">Repository-backed answers can be incomplete; use the evidence links to verify.</p>
      </form>
    </Panel>
  );

  const renderDocs = () => (
    <div className="grid gap-4 xl:grid-cols-[330px_minmax(0,1fr)]">
      <Panel className="overflow-hidden">
        <PanelTitle icon={BookOpen} title="Documentation studio" detail="Generate, review, and verify" />
        <div className="space-y-4 p-4">
          <label className="block text-[10px] font-medium uppercase tracking-wide text-slate-500">Documentation type
            <select value={docType} onChange={(event) => setDocType(event.target.value)} className="mt-2 w-full rounded-lg border border-white/[0.08] bg-[#0a1018] px-3 py-2.5 text-xs text-slate-200 outline-none">
              {[
                ['architecture', 'Architecture'],
                ['api', 'API reference'],
                ['models', 'Data models'],
                ['module', 'Module spec'],
                ['readme', 'README'],
                ['diagram', 'Mermaid diagram'],
                ['custom', 'Custom'],
              ].map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <button onClick={() => void generateDoc()} disabled={loading} className="flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-500 px-3 py-2.5 text-xs font-semibold text-white hover:bg-indigo-400 disabled:opacity-50">{loading ? <LoaderCircle size={14} className="animate-spin" /> : <Plus size={14} />} Generate with evidence</button>
          <button onClick={() => void loadDocs()} className="flex w-full items-center justify-center gap-2 rounded-lg border border-white/[0.08] px-3 py-2.5 text-xs text-slate-300 hover:bg-white/[0.04]"><RefreshCw size={13} />Refresh generated docs</button>
          <button onClick={() => void checkDocDrift()} disabled={!selectedDoc || driftLoading} className="flex w-full items-center justify-center gap-2 rounded-lg border border-amber-300/15 bg-amber-300/[0.04] px-3 py-2.5 text-xs text-amber-200 hover:bg-amber-300/[0.08] disabled:opacity-40">{driftLoading ? <LoaderCircle size={13} className="animate-spin" /> : <Activity size={13} />}Check selected doc drift</button>
          <div className="pt-3">
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-slate-500">Generated documents</p>
            {docs.map((doc) => <button key={doc.id} onClick={() => setSelectedDoc(doc)} className={cx('mb-1 w-full rounded-lg px-3 py-2.5 text-left hover:bg-white/[0.04]', selectedDoc?.id === doc.id && 'bg-indigo-400/10')}><span className="block truncate text-xs text-slate-300">{doc.title}</span><span className="mt-1 text-[9px] uppercase text-slate-600">{doc.doc_type}</span></button>)}
            {!docs.length && <p className="text-[10px] leading-5 text-slate-600">Generate documentation or refresh to list existing items.</p>}
          </div>
        </div>
      </Panel>
      <Panel className="min-h-[620px] overflow-hidden">
        <PanelTitle icon={FileText} title={selectedDoc?.title || 'Documentation preview'} detail={selectedDoc ? `${selectedDoc.doc_type} · generated content` : 'Select or generate a document'} />
        {selectedDoc ? <article className="prose prose-invert max-w-none overflow-auto p-6 text-xs leading-6 text-slate-300">
          {selectedDoc.content_markdown.split('\n').map((line, index) => line.startsWith('#') ? <h2 key={index} className="mb-3 mt-6 text-base font-semibold text-slate-100">{line.replace(/^#+\s*/, '')}</h2> : line.trim() ? <p key={index} className="my-2">{line.replace(/\*\*/g, '')}</p> : <div key={index} className="h-2" />)}
          {docDrift && <div className="not-prose mt-8 rounded-xl border border-white/[0.08] bg-[#0b111a] p-4"><div className="flex items-center gap-2"><span className={cx('rounded border px-2 py-1 text-[9px] uppercase', docDrift.has_drift ? TONES.amber : TONES.emerald)}>{docDrift.has_drift ? 'Drift detected' : 'No drift detected'}</span><span className="text-[10px] text-slate-500">{docDrift.issues.length} finding(s)</span></div><p className="mt-3 text-xs text-slate-300">{docDrift.summary}</p>{docDrift.issues.map((issue, index) => <div key={`${issue.issue_type}-${index}`} className="mt-3 border-t border-white/[0.06] pt-3"><p className="text-xs text-slate-200">{issue.title}</p><p className="mt-1 text-[10px] leading-5 text-slate-500">{issue.details}</p>{issue.suggested_correction && <p className="mt-2 rounded bg-indigo-400/[0.06] px-2 py-1.5 text-[10px] text-indigo-200">Suggested correction: {issue.suggested_correction}</p>}</div>)}<p className="mt-3 text-[9px] text-slate-600">The existing document was not overwritten.</p></div>}
        </article> : <div className="grid min-h-[560px] place-items-center p-8"><EmptyState title="Documentation preview" detail="Generated statements should be reviewed and verified against repository evidence. Existing user documentation is not overwritten." /></div>}
      </Panel>
    </div>
  );

  const renderTests = () => {
    const pipeline = testResult;
    const verification = pipeline?.verification as Record<string, unknown> | undefined;
    const coverage = pipeline?.coverage as Record<string, unknown> | undefined;
    const quality = pipeline?.quality_score as Record<string, unknown> | undefined;
    return (
      <div className="space-y-4">
        <Panel>
          <PanelTitle icon={Activity} title="Static test strength and gap analysis" detail="Uses indexed symbols, test imports, relationships, and read-only Python AST inspection" action={<button onClick={() => void runTestStrength()} disabled={testStrengthLoading} className="flex items-center gap-2 rounded-lg border border-white/[0.08] px-3 py-2 text-[10px] text-slate-200 hover:bg-white/[0.04] disabled:opacity-50">{testStrengthLoading ? <LoaderCircle size={13} className="animate-spin" /> : <Search size={13} />} Analyze test gaps</button>} />
          {testStrength ? <>
            <div className="grid gap-3 p-5 sm:grid-cols-2 xl:grid-cols-4">
              <MiniMetric label="Mapped symbols" value={`${testStrength.mapped_symbols}/${testStrength.analyzed_symbols}`} />
              <MiniMetric label="Python test functions" value={fmt(testStrength.discovered_test_function_count)} />
              <MiniMetric label="Test files with assertions" value={`${testStrength.test_files_with_assertions}/${testStrength.python_test_file_count}`} />
              <MiniMetric label="Files without assertions" value={fmt(testStrength.test_files_without_assertions)} />
            </div>
            {!!testStrength.findings.length && <div className="space-y-2 border-t border-white/[0.06] px-5 py-4">{testStrength.findings.map((finding, index) => <p key={index} className="text-[11px] leading-5 text-amber-200/80">{finding}</p>)}</div>}
            <div className="max-h-[420px] divide-y divide-white/[0.05] overflow-auto border-t border-white/[0.06]">
              {testStrength.symbols.map((item) => <div key={`${item.file}:${item.symbol}:${item.start_line}`} className="grid gap-2 p-4 md:grid-cols-[minmax(180px,1fr)_110px_minmax(220px,1.5fr)]">
                <button onClick={() => viewEvidence(item.file, item.start_line)} className="truncate text-left font-mono text-[10px] text-indigo-300">{item.file}:{item.start_line} · {item.symbol}</button>
                <span className={cx('h-fit w-fit rounded border px-2 py-1 text-[9px] uppercase', item.mapping_status === 'linked' ? TONES.emerald : item.mapping_status === 'candidate' ? TONES.amber : TONES.rose)}>{item.mapping_status}</span>
                <div className="space-y-1">{item.potential_gaps.length ? item.potential_gaps.map((gap, index) => <p key={index} className="text-[10px] leading-4 text-slate-500">{gap}</p>) : <p className="text-[10px] text-slate-600">No static gap signal identified.</p>}
                  {(item.linked_tests.length > 0 || item.candidate_tests.length > 0) && <p className="text-[9px] text-slate-600">Tests: {[...new Set([...item.linked_tests, ...item.candidate_tests])].join(', ')}</p>}
                </div>
              </div>)}
              {!testStrength.symbols.length && <p className="p-5 text-xs text-slate-500">No indexed production symbols were available for analysis.</p>}
            </div>
            <div className="space-y-1 border-t border-white/[0.06] px-5 py-3">{testStrength.limitations.map((item, index) => <p key={index} className="text-[9px] leading-4 text-slate-600">{item}</p>)}</div>
          </> : <EmptyState title="Test quality has not been analyzed" detail="Static findings are candidate gaps, not measured coverage. No repository tests are executed by this analysis." />}
        </Panel>

        <Panel>
          <PanelTitle icon={GitBranch} title="Regression test selection" detail="Selects candidate existing tests from changed files/symbols and indexed dependencies" />
          <form onSubmit={selectRegressionTests} className="grid gap-3 p-5 md:grid-cols-2">
            <input value={changedTestFiles} onChange={(event) => { setChangedTestFiles(event.target.value); setRegressionSelection(null); }} placeholder="Changed files, comma-separated (e.g. src/auth.py)" className="rounded-lg border border-white/[0.08] bg-[#0a1018] px-3 py-2.5 text-xs text-slate-200 outline-none placeholder:text-slate-600" />
            <input value={changedTestSymbols} onChange={(event) => { setChangedTestSymbols(event.target.value); setRegressionSelection(null); }} placeholder="Changed symbols, comma-separated (e.g. validate_token)" className="rounded-lg border border-white/[0.08] bg-[#0a1018] px-3 py-2.5 text-xs text-slate-200 outline-none placeholder:text-slate-600" />
            <div className="flex items-center justify-between gap-3 md:col-span-2"><p className="text-[9px] text-slate-600">Names are matched against this repository’s indexed files and symbols.</p><button disabled={regressionLoading || (!changedTestFiles.trim() && !changedTestSymbols.trim())} className="flex items-center gap-2 rounded-lg bg-indigo-500 px-3 py-2 text-[10px] font-semibold text-white disabled:opacity-50">{regressionLoading ? <LoaderCircle size={13} className="animate-spin" /> : <Activity size={13} />} Select tests</button></div>
          </form>
          {regressionSelection && <div className="border-t border-white/[0.06]">
            <div className={cx('px-5 py-3 text-[10px]', regressionSelection.full_suite_recommended ? 'bg-amber-400/[0.05] text-amber-200' : 'bg-indigo-400/[0.04] text-slate-300')}>
              {regressionSelection.full_suite_recommended ? 'A broader repository test run is recommended.' : 'Targeted tests were found; selection may still be incomplete.'}
              {regressionSelection.recommendation_reasons.map((reason, index) => <p key={index} className="mt-1 text-slate-500">{reason}</p>)}
            </div>
            <div className="divide-y divide-white/[0.05]">{regressionSelection.selected_tests.map((test) => <div key={test.file} className="flex flex-col gap-2 p-4 sm:flex-row sm:items-start sm:justify-between"><button onClick={() => viewEvidence(test.file)} className="text-left font-mono text-[10px] text-indigo-300">{test.file}</button><div className="max-w-2xl text-right"><span className="text-[9px] uppercase text-slate-500">{test.confidence} evidence</span>{test.reasons.map((reason, index) => <p key={index} className="mt-1 text-[10px] text-slate-500">{reason}</p>)}</div></div>)}
              {!regressionSelection.selected_tests.length && <p className="p-4 text-xs text-slate-500">No candidate test files matched this change.</p>}
            </div>
            <div className="space-y-1 px-5 py-3">{regressionSelection.limitations.map((item, index) => <p key={index} className="text-[9px] leading-4 text-slate-600">{item}</p>)}</div>
          </div>}
        </Panel>

        <Panel>
          <PanelTitle icon={TestTube2} title="Test intelligence" detail={`${testFiles.length} test files indexed · run the repository test-generation pipeline`} action={<button onClick={() => void runPipeline()} disabled={testLoading} className="flex items-center gap-2 rounded-lg bg-indigo-500 px-3 py-2 text-[10px] font-semibold text-white hover:bg-indigo-400 disabled:opacity-50">{testLoading ? <LoaderCircle size={13} className="animate-spin" /> : <Sparkles size={13} />} Run pipeline</button>} />
          <div className="grid gap-3 p-5 sm:grid-cols-2 xl:grid-cols-4">
            <MiniMetric label="Test files" value={fmt(testFiles.length)} />
            <MiniMetric label="Execution status" value={String(verification?.status || 'Not run')} />
            <MiniMetric label="Coverage" value={coverage?.percent != null ? `${coverage.percent}%` : 'Not measured'} />
            <MiniMetric label="Quality score" value={quality?.score != null ? String(quality.score) : 'Not scored'} />
          </div>
        </Panel>

        <Panel>
          <PanelTitle icon={Bug} title="Failure explainer" detail="Paste pytest output to classify each failure and map it back to indexed source — deterministic, no code is executed" />
          <div className="space-y-3 p-5">
            <textarea
              value={failureOutput}
              onChange={(event) => setFailureOutput(event.target.value)}
              rows={5}
              placeholder="Paste failing pytest/unittest output including tracebacks…"
              className="w-full rounded-lg border border-white/[0.08] bg-[#0a1018] px-3 py-2.5 font-mono text-[11px] text-slate-200 outline-none placeholder:text-slate-600"
            />
            <button onClick={() => void explainFailures()} disabled={failureLoading || !failureOutput.trim()} className="flex items-center gap-2 rounded-lg bg-indigo-500 px-4 py-2 text-[11px] font-semibold text-white hover:bg-indigo-400 disabled:opacity-40">
              {failureLoading ? <LoaderCircle size={13} className="animate-spin" /> : <Search size={13} />} Explain failures
            </button>
          </div>
          {failureReport && (
            <div className="border-t border-white/[0.06]">
              <div className="flex flex-wrap items-center gap-2 px-5 py-3">
                <span className="text-[11px] text-slate-300">{failureReport.summary}</span>
                {Object.entries(failureReport.category_counts).map(([category, count]) => (
                  <span key={category} className="rounded-full border border-white/[0.08] bg-white/[0.03] px-2 py-0.5 text-[9px] uppercase tracking-wide text-slate-400">{category}: {count}</span>
                ))}
              </div>
              <div className="divide-y divide-white/[0.05]">
                {failureReport.explanations.map((item, index) => (
                  <div key={index} className="space-y-2 p-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-[11px] text-indigo-300">{item.test_name}</span>
                      <span className={cx('rounded border px-2 py-0.5 text-[9px] uppercase', item.category === 'assertion' ? TONES.amber : item.category === 'import' || item.category === 'syntax' ? TONES.rose : TONES.indigo)}>{item.category}</span>
                      <span className="text-[9px] text-slate-600">confidence: {item.confidence}</span>
                    </div>
                    <p className="text-[11px] leading-5 text-slate-300">{item.summary}</p>
                    <p className="text-[10px] leading-4 text-slate-500"><span className="text-slate-400">Likely cause:</span> {item.likely_cause}</p>
                    <p className="text-[10px] leading-4 text-emerald-300/80"><span className="text-emerald-300/60">Fix:</span> {item.suggested_fix}</p>
                    {item.source_symbol && (
                      <button onClick={() => item.source_symbol_file && viewEvidence(item.source_symbol_file, item.evidence[0]?.line ?? undefined)} className="font-mono text-[10px] text-indigo-300">
                        → {item.source_symbol_file} · {item.source_symbol}
                      </button>
                    )}
                    {item.evidence.length > 0 && (
                      <div className="space-y-0.5">{item.evidence.map((ev, i) => <p key={i} className="font-mono text-[9px] text-slate-600">{ev.file}{ev.line ? `:${ev.line}` : ''} {ev.snippet}</p>)}</div>
                    )}
                  </div>
                ))}
              </div>
              <div className="space-y-1 px-5 py-3">{failureReport.limitations.map((item, index) => <p key={index} className="text-[9px] leading-4 text-slate-600">{item}</p>)}</div>
            </div>
          )}
        </Panel>
        {pipeline ? <div className="grid gap-4 xl:grid-cols-2">
          <Panel><PanelTitle icon={Check} title="Pipeline report" detail="Verification reflects execution result, not generated test count" /><pre className="max-h-[420px] overflow-auto whitespace-pre-wrap p-5 font-mono text-[10px] leading-5 text-slate-400">{JSON.stringify(pipeline, null, 2)}</pre></Panel>
          <Panel><PanelTitle icon={Bug} title="Coverage & mutation" detail="Reported only when available from the configured toolchain" /><div className="space-y-4 p-5"><div><p className="text-xs text-slate-300">Coverage analysis</p><p className="mt-1 text-[11px] text-slate-500">{coverage ? JSON.stringify(coverage) : 'The pipeline did not return coverage metrics.'}</p></div><div className="border-t border-white/[0.06] pt-4"><p className="text-xs text-slate-300">Mutation testing</p><p className="mt-1 text-[11px] text-slate-500">{pipeline.mutation ? JSON.stringify(pipeline.mutation) : 'Mutation testing is not reported for this run.'}</p></div></div></Panel>
        </div> : <EmptyState title="No pipeline run yet" detail="Start the pipeline to inspect test gaps, verification, coverage, mutation results, and quality scoring." />}
      </div>
    );
  };

  const renderSecurity = () => (
    <div className="space-y-4">
      <Panel>
        <PanelTitle icon={LockKeyhole} title="Security posture" detail="Results cover configured checks only; they do not establish that this repository is secure." action={<button onClick={() => void runSecurity()} disabled={securityLoading} className="flex items-center gap-2 rounded-lg bg-indigo-500 px-3 py-2 text-[10px] font-semibold text-white hover:bg-indigo-400 disabled:opacity-50">{securityLoading ? <LoaderCircle size={13} className="animate-spin" /> : <RefreshCw size={13} />} Run configured checks</button>} />
        <div className="grid grid-cols-2 gap-3 p-5 md:grid-cols-5">
          {(['critical', 'high', 'medium', 'low', 'informational'] as const).map((severity) => <div key={severity} className="rounded-xl border border-white/[0.06] bg-[#0b111a] p-3"><p className="text-[10px] capitalize text-slate-500">{severity}</p><p className={cx('mt-2 text-2xl font-semibold', severity === 'critical' || severity === 'high' ? 'text-rose-300' : severity === 'medium' ? 'text-amber-300' : 'text-slate-200')}>{security?.dashboard[severity] ?? '—'}</p></div>)}
        </div>
      </Panel>
      {security ? <Panel>
        <PanelTitle icon={Shield} title={security.summary} detail={security.tools_considered.length ? `Ran: ${security.tools_considered.join(', ')}` : 'No configured scanner returned findings; unavailable tools are not proof of security.'} />
        <div className="divide-y divide-white/[0.05]">
          {security.findings.map((finding, index) => <div key={`${finding.file}-${finding.line}-${index}`} className="grid gap-3 p-4 md:grid-cols-[90px_minmax(0,1fr)_115px]">
            <span className={cx('h-fit rounded-md border px-2 py-1 text-center text-[9px] font-semibold uppercase', finding.severity === 'critical' || finding.severity === 'high' ? TONES.rose : finding.severity === 'medium' ? TONES.amber : TONES.cyan)}>{finding.severity}</span>
            <div><p className="text-xs font-medium text-slate-200">{finding.description}</p><div className="mt-1">{showCode(finding.file, finding.line)}</div><p className="mt-2 text-[10px] leading-5 text-slate-500">{finding.remediation}</p></div>
            <span className="text-right text-[10px] text-slate-500">{finding.tool} · {finding.confidence}</span>
          </div>)}
          {!security.findings.length && <p className="p-5 text-xs text-slate-400">No detected issue from the configured security checks. This is not a guarantee that the repository is secure.</p>}
        </div>
      </Panel> : <EmptyState title="Security checks have not been run" detail="Run the configured scanners to populate the finding dashboard. Missing scanners or empty results must not be interpreted as a security guarantee." />}
    </div>
  );

  const impactCard = (title: string, items: ImpactComponent[]) => (
    <Panel key={title}>
      <PanelTitle icon={GitPullRequest} title={title} detail={`${items.length} component${items.length === 1 ? '' : 's'}`} />
      <div className="divide-y divide-white/[0.05]">
        {items.map((item, index) => <div key={`${item.file}-${item.symbol}-${index}`} className="p-4">
          <p className="text-xs font-medium text-slate-200">{item.symbol}</p>
          <div className="mt-1">{showCode(item.file, item.start_line)}</div>
          <span className="mt-2 inline-flex rounded border border-white/[0.07] px-1.5 py-1 text-[9px] text-slate-500">{item.relationship}</span>
          {item.evidence.map((evidence, evidenceIndex) => <p key={evidenceIndex} className="mt-2 text-[10px] leading-4 text-slate-500">{evidence.description}</p>)}
        </div>)}
        {!items.length && <p className="p-4 text-[10px] text-slate-600">No component matches were found.</p>}
      </div>
    </Panel>
  );

  const renderImpact = () => (
    <div className="space-y-4">
      <Panel>
        <PanelTitle icon={GitPullRequest} title="Change impact analysis" detail="Risk estimate based on graph, imports, APIs, tests, Git history, and repository evidence" />
        <form onSubmit={runImpact} className="flex flex-col gap-3 p-5 sm:flex-row">
          <div className="relative flex-1"><Search size={14} className="absolute left-3 top-3 text-slate-500" /><input value={impactQuery} onChange={(event) => setImpactQuery(event.target.value)} placeholder="payments.process_payment or src/payments.py" className="w-full rounded-lg border border-white/[0.08] bg-[#0a1018] py-2.5 pl-9 pr-3 text-xs text-slate-200 outline-none placeholder:text-slate-600 focus:border-indigo-400/30" /></div>
          <button disabled={impactLoading || !impactQuery.trim()} className="flex items-center justify-center gap-2 rounded-lg bg-indigo-500 px-4 py-2.5 text-xs font-semibold text-white hover:bg-indigo-400 disabled:opacity-40">{impactLoading ? <LoaderCircle size={14} className="animate-spin" /> : <Activity size={14} />} Analyze impact</button>
        </form>
      </Panel>
      {impactResult ? <>
        <Panel><div className="flex flex-wrap items-center justify-between gap-3 p-5"><div><p className="text-sm font-semibold text-slate-100">Impact estimate · {impactResult.symbol}</p><p className="mt-1 max-w-3xl text-[10px] text-slate-500">{impactResult.caveat}</p></div><div className="rounded-xl border border-indigo-300/15 bg-indigo-400/[0.07] px-4 py-2 text-right"><p className="text-xl font-semibold text-indigo-200">{Math.round(impactResult.confidence * 100)}%</p><p className="text-[9px] text-slate-500">confidence</p></div></div><div className="flex flex-wrap gap-2 border-t border-white/[0.06] px-5 py-3">{impactResult.confidence_reasons.map((reason, index) => <span key={index} className="rounded-full border border-white/[0.07] px-2.5 py-1 text-[9px] text-slate-500">{reason}</span>)}</div></Panel>
        <Panel><PanelTitle icon={Network} title="Evidence-linked dependency graph" detail="Arrows point from the selected code to components identified as potentially affected" />
          {impactResult.graph_nodes.length ? (() => {
            const shown = impactResult.graph_nodes.slice(0, 36);
            const shownIds = new Set(shown.map((node) => node.id));
            const grouped = {
              target: shown.filter((node) => node.category === 'target'),
              direct: shown.filter((node) => node.category === 'direct'),
              indirect: shown.filter((node) => node.category === 'indirect'),
            };
            const yById = new Map<string, number>();
            Object.values(grouped).forEach((nodes) => nodes.forEach((node, index) => yById.set(node.id, 42 + index * 76)));
            const height = Math.max(150, ...Object.values(grouped).map((nodes) => 42 + nodes.length * 76));
            const xByCategory = { target: 24, direct: 304, indirect: 584 };
            return <div className="overflow-x-auto p-4"><svg role="img" aria-label="Dependency impact graph" viewBox={`0 0 820 ${height}`} className="min-w-[760px] w-full">
              {(['target', 'direct', 'indirect'] as const).map((category) => <text key={category} x={xByCategory[category]} y="18" fill="#94a3b8" fontSize="10">{category === 'target' ? 'SELECTED' : category.toUpperCase()} IMPACT</text>)}
              {impactResult.graph_edges.filter((edge) => shownIds.has(edge.source) && shownIds.has(edge.target)).map((edge, index) => {
                const source = shown.find((node) => node.id === edge.source)!;
                const target = shown.find((node) => node.id === edge.target)!;
                const x1 = xByCategory[source.category] + 220;
                const x2 = xByCategory[target.category];
                const y1 = yById.get(source.id)! + 16;
                const y2 = yById.get(target.id)! + 16;
                return <g key={`${edge.source}-${edge.target}-${index}`}><path d={`M ${x1} ${y1} C ${x1 + 32} ${y1}, ${x2 - 32} ${y2}, ${x2} ${y2}`} fill="none" stroke="#6366f1" strokeOpacity=".55" strokeWidth="1.5" markerEnd="url(#impact-arrow)"/><title>{edge.relationship}: {edge.evidence.description} ({edge.evidence.file}{edge.evidence.line ? `:${edge.evidence.line}` : ''})</title></g>;
              })}
              <defs><marker id="impact-arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="#818cf8" /></marker></defs>
              {shown.map((node) => <g key={node.id} role="button" tabIndex={0} aria-label={`${node.category} impact: ${node.symbol} in ${node.file}`} onClick={() => viewEvidence(node.file, node.line || undefined)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') viewEvidence(node.file, node.line || undefined); }} className="cursor-pointer">
                <rect x={xByCategory[node.category]} y={yById.get(node.id)} width="220" height="34" rx="8" fill={node.category === 'target' ? '#312e81' : '#111827'} stroke={node.category === 'target' ? '#818cf8' : '#334155'} />
                <text x={xByCategory[node.category] + 10} y={(yById.get(node.id) || 0) + 14} fill="#e2e8f0" fontSize="10">{node.symbol.slice(0, 25)}</text>
                <text x={xByCategory[node.category] + 10} y={(yById.get(node.id) || 0) + 27} fill="#94a3b8" fontSize="8">{node.file.slice(-32)}{node.line ? `:${node.line}` : ''}</text>
              </g>)}
            </svg>{impactResult.graph_nodes.length > shown.length && <p className="mt-2 text-[10px] text-slate-500">Showing {shown.length} of {impactResult.graph_nodes.length} graph nodes.</p>}</div>;
          })() : <p className="p-5 text-xs text-slate-500">No persisted dependency edges were found for this selection. Other impact evidence is listed below.</p>}
        </Panel>
        <div className="grid gap-4 xl:grid-cols-2">{impactCard('Direct impact', impactResult.direct_impact)}{impactCard('Indirect impact', impactResult.indirect_impact)}{impactCard('Affected APIs', impactResult.affected_apis)}{impactCard('Affected modules', impactResult.affected_modules)}{impactCard('Affected tests', impactResult.affected_tests)}
          <Panel><PanelTitle icon={AlertTriangle} title="Potential risks" detail={`${impactResult.potential_risks.length} risk signals`} /><div className="divide-y divide-white/[0.05]">{impactResult.potential_risks.map((risk, index) => <div key={index} className="p-4"><span className={cx('rounded border px-2 py-1 text-[9px] uppercase', risk.severity === 'high' ? TONES.rose : risk.severity === 'medium' ? TONES.amber : TONES.cyan)}>{risk.severity}</span><p className="mt-3 text-xs leading-5 text-slate-300">{risk.description}</p>{risk.evidence.map((item, i) => <div key={i} className="mt-2">{showCode(item.file, item.line)}<p className="mt-1 text-[10px] text-slate-500">{item.description}</p></div>)}</div>)}</div></Panel>
        </div>
      </> : <EmptyState title="Select a symbol or file to estimate impact" detail="The result is a risk estimate, not a guarantee. Unindexed or dynamic relationships may not be included." />}
    </div>
  );

  const renderGit = () => (
    <div className="space-y-4">
      <Panel>
        <PanelTitle icon={GitBranch} title="Git intelligence" detail={history?.history_scope || 'Git history has not been indexed'} />
        <div className="grid gap-3 p-5 sm:grid-cols-2 xl:grid-cols-4"><MiniMetric label="Commits analyzed" value={history ? fmt(history.commits_analyzed) : '—'} /><MiniMetric label="Branches available" value={history?.branch_history_available ? fmt(history.branches.length) : 'Not available'} /><MiniMetric label="Hotspots" value={history ? fmt(history.high_risk_hotspots.length) : '—'} /><MiniMetric label="Recently changed critical" value={history ? fmt(history.recently_modified_critical_components.length) : '—'} /></div>
      </Panel>
      {history?.history_available ? <div className="grid gap-4 xl:grid-cols-[1.35fr_1fr]">
        <Panel><PanelTitle icon={GitCommitHorizontal} title="File churn" detail="Commit frequency and total insertions + deletions" /><div className="h-[310px] p-4"><ResponsiveContainer width="100%" height="100%"><BarChart data={history.files.slice(0, 12).map((item) => ({ name: item.file.split('/').slice(-2).join('/'), frequency: item.change_frequency, churn: item.churn }))} layout="vertical" margin={{ left: 16, right: 20, top: 4, bottom: 4 }}><CartesianGrid stroke="#253041" strokeDasharray="3 6" horizontal={false} /><XAxis type="number" tick={{ fill: '#7f8da3', fontSize: 9 }} axisLine={false} tickLine={false} /><YAxis type="category" dataKey="name" width={115} tick={{ fill: '#a3b0c2', fontSize: 9 }} axisLine={false} tickLine={false} /><Tooltip contentStyle={{ background: '#111824', border: '1px solid #263244', borderRadius: 12 }} /><Bar dataKey="churn" name="Line churn" fill="#818cf8" radius={[0, 4, 4, 0]} /><Bar dataKey="frequency" name="Commit frequency" fill="#22d3ee" radius={[0, 4, 4, 0]} /></BarChart></ResponsiveContainer></div></Panel>
        <Panel><PanelTitle icon={AlertTriangle} title="History signals" detail="Candidates, not proof of intent or neglect" /><div className="space-y-4 p-4">{[
          ['High-risk hotspots', history.high_risk_hotspots],
          ['Frequently changed', history.frequently_changed_files],
          ['Abandoned-area candidates', history.abandoned_area_candidates],
          ['Recent critical components', history.recently_modified_critical_components],
        ].map(([title, collection]) => <div key={String(title)}><p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-slate-500">{String(title)}</p>{(collection as GitHistory['files']).slice(0, 4).map((item) => <div key={item.file} className="flex items-center justify-between gap-3 rounded-lg px-2 py-2 hover:bg-white/[0.03]"><button onClick={() => viewEvidence(item.file)} className="truncate font-mono text-[10px] text-slate-300 hover:text-indigo-300">{item.file}</button><span className="shrink-0 text-[9px] text-slate-600">{item.change_frequency} changes · {timeAgo(item.last_modified)}</span></div>)}{!(collection as GitHistory['files']).length && <p className="text-[10px] text-slate-600">No matching signals.</p>}</div>)}</div></Panel>
        <Panel className="xl:col-span-2"><PanelTitle icon={GitCommitHorizontal} title="History evidence" detail={history.summary} /><div className="divide-y divide-white/[0.045]">{history.files.filter((item) => item.evidence.length).slice(0, 8).map((item) => <div key={item.file} className="grid gap-2 p-4 md:grid-cols-[220px_minmax(0,1fr)]"><button onClick={() => viewEvidence(item.file)} className="h-fit truncate text-left font-mono text-[10px] text-indigo-300">{item.file}</button><div className="space-y-2">{item.evidence.slice(0, 2).map((evidence) => <div key={evidence.commit_hash} className="flex justify-between gap-4"><p className="text-[10px] text-slate-300">{evidence.message}</p><span className="shrink-0 text-[9px] text-slate-600">{evidence.author} · {timeAgo(evidence.timestamp)}</span></div>)}</div></div>)}</div></Panel>
      </div> : <EmptyState title="Git history is not available" detail={history?.summary || 'This repository has no indexed commits. Commit-pattern analysis and historical rationale are not available.'} />}
      <Panel><PanelTitle icon={CircleHelp} title="Why does this code exist?" detail="Uses recorded commit messages only; it does not invent developer intentions." /><form onSubmit={(event) => { event.preventDefault(); const form = new FormData(event.currentTarget); void askWhy(String(form.get('target') || '')); }} className="flex flex-col gap-2 p-4 sm:flex-row"><input name="target" placeholder="File path or symbol name" className="flex-1 rounded-lg border border-white/[0.08] bg-[#0a1018] px-3 py-2.5 text-xs text-slate-200 outline-none placeholder:text-slate-600" /><button disabled={whyLoading} className="flex items-center justify-center gap-2 rounded-lg border border-white/[0.08] px-4 py-2.5 text-xs text-slate-200 hover:bg-white/[0.04]">{whyLoading && <LoaderCircle size={13} className="animate-spin" />}Ask Git history</button></form>{whyAnswer && <div className="mx-4 mb-4 rounded-xl border border-white/[0.06] bg-[#0a1018] p-4"><p className="text-xs leading-6 text-slate-300">{String(whyAnswer.answer)}</p><p className="mt-2 text-[10px] text-slate-500">{String(whyAnswer.limitation)}</p></div>}</Panel>
    </div>
  );

  const renderArchitecture = () => {
    const relationCounts = (graph?.relationships || []).reduce<Record<string, number>>((all, rel) => { all[rel.type] = (all[rel.type] || 0) + 1; return all; }, {});
    return <div className="space-y-4"><Panel><PanelTitle icon={Boxes} title="Architecture map" detail="Observed repository structure and persisted graph relations" /><div className="grid gap-3 p-5 sm:grid-cols-2 xl:grid-cols-4"><MiniMetric label="Modules / files" value={fmt(files.length)} /><MiniMetric label="Symbols" value={fmt(symbols.length)} /><MiniMetric label="Relationships" value={fmt(graph?.counts.relationships || 0)} /><MiniMetric label="Dependency packages" value={fmt(dependencies.length)} /></div></Panel><div className="grid gap-4 xl:grid-cols-2"><Panel><PanelTitle icon={Network} title="Relationship types" detail="Graph index counts; not an architecture violation scan" /><div className="space-y-4 p-5">{Object.entries(relationCounts).sort((a, b) => b[1] - a[1]).map(([type, count]) => <div key={type}><div className="mb-1.5 flex justify-between text-[10px]"><span className="text-slate-400">{type}</span><span className="text-slate-300">{count}</span></div><div className="h-1.5 rounded-full bg-slate-800"><div className="h-full rounded-full bg-indigo-400" style={{ width: `${Math.max(2, count / Math.max(1, graph?.counts.relationships || 1) * 100)}%` }} /></div></div>)}{!Object.keys(relationCounts).length && <p className="text-xs text-slate-500">No graph relationships are indexed.</p>}</div></Panel><Panel><PanelTitle icon={Package} title="Dependencies" detail="Declared dependencies extracted from repository manifests" /><div className="max-h-[450px] divide-y divide-white/[0.05] overflow-auto">{dependencies.map((dep) => <div key={dep.id} className="flex items-center justify-between gap-3 px-4 py-3"><div className="flex min-w-0 items-center gap-2"><Package size={13} className="shrink-0 text-cyan-300" /><span className="truncate text-xs text-slate-200">{dep.package_name}</span></div><span className="shrink-0 text-[9px] text-slate-600">{dep.ecosystem} {dep.version_spec || ''}</span></div>)}{!dependencies.length && <p className="p-5 text-xs text-slate-500">No dependencies were extracted.</p>}</div></Panel></div></div>;
  };

  const renderDebt = () => <div className="space-y-4">
    <Panel><PanelTitle icon={AlertTriangle} title="Technical debt payoff planner" detail="Prioritized static and historical signals; no source changes are made" action={<button onClick={() => void runDebtAnalysis()} disabled={debtLoading} className="flex items-center gap-2 rounded-lg bg-indigo-500 px-3 py-2 text-[10px] font-semibold text-white disabled:opacity-50">{debtLoading ? <LoaderCircle size={13} className="animate-spin" /> : <RefreshCw size={13} />} Analyze debt</button>} />
      <div className="grid gap-3 p-5 sm:grid-cols-3"><MiniMetric label="High-complexity symbols" value={fmt(highComplexity.length)} /><MiniMetric label="History hotspots" value={fmt(history?.high_risk_hotspots.length || 0)} /><MiniMetric label="Findings" value={debt ? fmt(debt.findings.length) : 'Not analyzed'} /></div>
    </Panel>
    {debt ? <><Panel><div className="p-5 text-xs text-slate-300">{debt.summary}</div><div className="divide-y divide-white/[0.05]">{debt.findings.map((finding, index) => <div key={`${finding.category}-${finding.title}-${index}`} className="grid gap-3 p-5 lg:grid-cols-[110px_minmax(0,1fr)_220px]"><div><span className={cx('rounded border px-2 py-1 text-[9px] uppercase', finding.severity === 'high' ? TONES.rose : finding.severity === 'medium' ? TONES.amber : TONES.cyan)}>{finding.severity}</span><p className="mt-2 text-[9px] uppercase text-slate-600">{finding.category}</p></div><div><p className="text-xs font-medium text-slate-200">{finding.title}</p><p className="mt-1 text-[10px] leading-5 text-slate-500">{finding.details}</p><p className="mt-2 text-[10px] text-indigo-200">Suggested next step: {finding.remediation}</p></div><div className="space-y-1 text-[10px] text-slate-500"><p>Confidence: {finding.confidence}</p><p>Estimated effort: {finding.estimated_effort}</p><p>{finding.measured ? 'Measured signal' : 'Heuristic candidate'}</p>{finding.evidence.slice(0, 2).map((item, evidenceIndex) => <button key={evidenceIndex} onClick={() => item.file && viewEvidence(item.file, item.line)} className="block max-w-full truncate text-left font-mono text-indigo-300">{item.file}{item.line ? `:${item.line}` : ''}</button>)}</div></div>)}{!debt.findings.length && <p className="p-5 text-xs text-slate-500">No configured debt signals were found.</p>}</div></Panel><Panel><PanelTitle icon={CircleHelp} title="Analysis limits" detail="Review each finding before planning refactoring" /><div className="space-y-2 p-5">{debt.limitations.map((item, index) => <p key={index} className="text-[10px] leading-5 text-slate-500">{item}</p>)}</div></Panel></> : <EmptyState title="Debt analysis has not run" detail="The existing complexity and history metrics remain available; run analysis to prioritize cycles, duplicate functions, large modules, dependency candidates, and churn." />}
  </div>;

  const renderOnboarding = () => <div className="space-y-4"><Panel><PanelTitle icon={BookOpen} title="Developer onboarding" detail="Guided reading path from indexed repository evidence" action={<button onClick={() => void loadOnboarding()} disabled={onboardingLoading} className="rounded-lg bg-indigo-500 px-3 py-2 text-[10px] font-semibold text-white disabled:opacity-50">{onboardingLoading ? 'Loading…' : 'Generate guide'}</button>} />{onboarding ? <div className="p-5"><p className="text-xs text-slate-300">{onboarding.overview}</p><div className="mt-5 grid gap-4 lg:grid-cols-2">{onboarding.guided_paths.map((step, index) => <div key={index} className="rounded-xl border border-white/[0.06] p-4"><p className="text-[9px] uppercase text-indigo-300">{step.level}</p><p className="mt-1 text-xs text-slate-200">{step.title}</p><p className="mt-2 text-[10px] leading-5 text-slate-500">{step.description}</p>{step.references.map((reference, refIndex) => <button key={refIndex} onClick={() => viewEvidence(reference.file, reference.line)} className="mt-2 block font-mono text-[10px] text-indigo-300">{reference.file}{reference.line ? `:${reference.line}` : ''}</button>)}</div>)}</div><div className="mt-5"><p className="text-xs text-slate-300">Learning tasks</p>{onboarding.learning_tasks.map((task, index) => <div key={index} className="mt-2 rounded-lg border border-white/[0.05] p-3 text-[10px] text-slate-500"><span className="text-slate-200">{task.title}</span> · {task.description}</div>)}</div><div className="mt-4 space-y-1">{onboarding.limitations.map((item, index) => <p key={index} className="text-[9px] text-slate-600">{item}</p>)}</div></div> : <EmptyState title="Generate a guided path" detail="The guide uses actual entry points, indexed symbols, and relationships. It does not infer business context." />}</Panel></div>;

  const renderRules = () => <div className="space-y-4"><Panel><PanelTitle icon={Braces} title="Candidate business rules" detail="Static Python conditions and validation branches; review before relying on them" action={<button onClick={() => void loadBusinessRules()} disabled={rulesLoading} className="rounded-lg bg-indigo-500 px-3 py-2 text-[10px] font-semibold text-white disabled:opacity-50">{rulesLoading ? 'Analyzing…' : 'Extract rules'}</button>} />{businessRules ? <div className="divide-y divide-white/[0.05]">{businessRules.rules.map((rule, index) => <div key={index} className="p-5"><div className="flex gap-2"><span className={cx('rounded border px-2 py-1 text-[9px] uppercase', rule.explicit ? TONES.emerald : TONES.amber)}>{rule.explicit ? 'explicit' : 'inferred'}</span><span className="text-[9px] text-slate-500">{rule.confidence} confidence</span></div><p className="mt-3 text-xs text-slate-200">{rule.description}</p>{rule.source_evidence.map((evidence, evidenceIndex) => <button key={evidenceIndex} onClick={() => viewEvidence(evidence.file, evidence.line)} className="mt-2 block font-mono text-[10px] text-indigo-300">{evidence.file}{evidence.line ? `:${evidence.line}` : ''} · {evidence.description}</button>)}</div>)}{!businessRules.rules.length && <p className="p-5 text-xs text-slate-500">No Python conditional rules were extracted.</p>}<div className="p-5">{businessRules.limitations.map((item, index) => <p key={index} className="text-[9px] text-slate-600">{item}</p>)}</div></div> : <EmptyState title="Extract candidate rules" detail="Only repository evidence is used. Conditions without explicit errors are labelled inferred." />}</Panel><Panel><PanelTitle icon={GitCommitHorizontal} title="Code memory" detail="Available commit messages and changed-file records, not inferred intent" /><form onSubmit={loadCodeMemory} className="flex gap-2 p-4"><input value={memoryTarget} onChange={(event) => setMemoryTarget(event.target.value)} placeholder="File path or symbol" className="flex-1 rounded-lg border border-white/[0.08] bg-[#0a1018] px-3 py-2 text-xs text-slate-200" /><button className="rounded-lg border border-white/[0.08] px-3 text-xs text-slate-300">Search</button></form>{memory && <div className="border-t border-white/[0.06] p-4"><p className="text-xs text-slate-300">{memory.summary}</p>{memory.commits.map((commit) => <div key={commit.commit_hash} className="mt-3 text-[10px] text-slate-500"><span className="font-mono text-indigo-300">{commit.commit_hash.slice(0, 12)}</span> · {commit.message}</div>)}{memory.limitations.map((item, index) => <p key={index} className="mt-2 text-[9px] text-slate-600">{item}</p>)}</div>}</Panel></div>;

  const renderHealth = () => (
    <div className="space-y-4">
      <Panel>
        <PanelTitle
          icon={Activity}
          title="Code health score"
          detail="Maintenance-focused composite across security, tests, docs, deps, structure, and stability"
          action={
            <button
              onClick={loadCodeHealth}
              disabled={codeHealthLoading}
              className="flex items-center gap-2 rounded-lg border border-indigo-300/20 bg-indigo-400/10 px-3 py-1.5 text-xs font-medium text-indigo-300 transition hover:bg-indigo-400/20 disabled:opacity-50"
            >
              <RefreshCw size={13} className={codeHealthLoading ? 'animate-spin' : ''} />
              {codeHealth ? 'Re-run' : 'Analyze'}
            </button>
          }
        />
        {codeHealthLoading && !codeHealth ? (
          <div className="grid place-items-center gap-3 p-10 text-slate-500"><LoaderCircle className="h-5 w-5 animate-spin" /><p className="text-xs">Computing code health across six dimensions…</p></div>
        ) : codeHealth ? (
          <div className="p-6">
            <div className="grid gap-6 lg:grid-cols-[220px_1fr]">
              <div className="grid place-items-center rounded-2xl border border-white/[0.06] bg-[#0b111a] py-8">
                <div className="text-center">
                  <p className={`text-5xl font-semibold tracking-tight ${codeHealth.overall_score >= 75 ? 'text-emerald-300' : codeHealth.overall_score >= 50 ? 'text-amber-300' : 'text-rose-300'}`}>{Math.round(codeHealth.overall_score)}</p>
                  <p className="mt-1 text-lg font-bold text-slate-300">Grade {codeHealth.grade}</p>
                  <p className="mt-2 text-[10px] uppercase tracking-widest text-slate-500">Health / 100</p>
                </div>
              </div>
              <div className="space-y-3">
                {codeHealth.dimensions.map((dim) => (
                  <div key={dim.name} className="rounded-xl border border-white/[0.05] bg-[#0b111a]/50 p-3">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium capitalize text-slate-200">{dim.name}</span>
                      <span className={`text-xs font-semibold ${dim.score >= 75 ? 'text-emerald-300' : dim.score >= 50 ? 'text-amber-300' : 'text-rose-300'}`}>{Math.round(dim.score)} · {dim.grade}</span>
                    </div>
                    <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-white/5">
                      <div className={`h-full rounded-full ${dim.score >= 75 ? 'bg-emerald-400' : dim.score >= 50 ? 'bg-amber-400' : 'bg-rose-400'}`} style={{ width: `${Math.min(100, dim.score)}%` }} />
                    </div>
                    {dim.findings[0] && <p className="mt-1.5 text-[11px] text-slate-400">{dim.findings[0]}</p>}
                  </div>
                ))}
              </div>
            </div>
            {codeHealth.top_risks.length > 0 && (
              <div className="mt-5 rounded-xl border border-rose-300/15 bg-rose-400/5 p-4">
                <p className="text-xs font-semibold text-rose-300">Top risks</p>
                <ul className="mt-2 space-y-1">{codeHealth.top_risks.map((r, i) => <li key={i} className="text-[11px] leading-5 text-slate-300">• {r}</li>)}</ul>
              </div>
            )}
            {codeHealth.quick_wins.length > 0 && (
              <div className="mt-3 rounded-xl border border-emerald-300/15 bg-emerald-400/5 p-4">
                <p className="text-xs font-semibold text-emerald-300">Quick wins</p>
                <ul className="mt-2 space-y-1">{codeHealth.quick_wins.map((w, i) => <li key={i} className="text-[11px] leading-5 text-slate-300">• {w}</li>)}</ul>
              </div>
            )}
            <p className="mt-4 border-t border-white/[0.06] pt-3 text-[10px] leading-5 text-slate-600">{codeHealth.summary}</p>
          </div>
        ) : (
          <EmptyState title="No health analysis yet" detail="Run the code-health analysis to get a maintenance score with per-dimension findings and prioritized fixes." />
        )}
      </Panel>

      <Panel>
        <PanelTitle
          icon={Shield}
          title="Dependency security"
          detail="Offline advisory scan of declared pip/npm dependencies (CVE-backed)"
          action={
            <button
              onClick={loadDependencySecurity}
              disabled={depSecurityLoading}
              className="flex items-center gap-2 rounded-lg border border-indigo-300/20 bg-indigo-400/10 px-3 py-1.5 text-xs font-medium text-indigo-300 transition hover:bg-indigo-400/20 disabled:opacity-50"
            >
              <RefreshCw size={13} className={depSecurityLoading ? 'animate-spin' : ''} />
              {depSecurity ? 'Re-run' : 'Scan'}
            </button>
          }
        />
        {depSecurityLoading && !depSecurity ? (
          <div className="grid place-items-center gap-3 p-10 text-slate-500"><LoaderCircle className="h-5 w-5 animate-spin" /><p className="text-xs">Scanning dependencies against advisory database…</p></div>
        ) : depSecurity ? (
          <div className="p-5">
            <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
              {[['Scanned', depSecurity.dependencies_scanned, 'text-slate-200'], ['Critical', depSecurity.critical_count, 'text-rose-400'], ['High', depSecurity.high_count, 'text-orange-400'], ['Medium', depSecurity.medium_count, 'text-amber-400'], ['Low', depSecurity.low_count, 'text-cyan-400']].map(([label, value, tone]) => (
                <div key={label as string} className="rounded-xl border border-white/[0.05] bg-[#0b111a]/50 p-3 text-center">
                  <p className={`text-xl font-semibold ${tone as string}`}>{value as number}</p>
                  <p className="text-[10px] uppercase tracking-wider text-slate-500">{label as string}</p>
                </div>
              ))}
            </div>
            {depSecurity.risky_dependencies.length === 0 ? (
              <EmptyState title="No known-vulnerable dependencies" detail={depSecurity.summary} />
            ) : (
              <div className="space-y-2">
                {depSecurity.risky_dependencies.map((risk, i) => (
                  <div key={i} className="rounded-xl border border-white/[0.05] bg-[#0b111a]/50 p-3">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-slate-200">{risk.package_name} <span className="text-slate-500">{risk.declared_version || '?'}</span></span>
                      <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${risk.severity === 'critical' ? 'bg-rose-500/10 text-rose-300' : risk.severity === 'high' ? 'bg-orange-500/10 text-orange-300' : 'bg-amber-500/10 text-amber-300'}`}>{risk.cve}</span>
                    </div>
                    <p className="mt-1 text-[11px] text-slate-400">{risk.summary}</p>
                    <p className="mt-1 text-[11px] text-emerald-300/80">{risk.recommendation}</p>
                  </div>
                ))}
              </div>
            )}
            <p className="mt-4 border-t border-white/[0.06] pt-3 text-[10px] leading-5 text-slate-600">{depSecurity.summary}</p>
          </div>
        ) : (
          <EmptyState title="No dependency scan yet" detail="Run the dependency security scan to check declared packages against known CVE version ranges — no network required." />
        )}
      </Panel>
    </div>
  );

  const renderSection = () => {
    switch (section) {
      case 'overview': return renderOverview();
      case 'explorer': return renderExplorer();
      case 'graph': return renderGraph();
      case 'chat': return renderChat();
      case 'docs': return renderDocs();
      case 'tests': return renderTests();
      case 'security': return renderSecurity();
      case 'architecture': return renderArchitecture();
      case 'impact': return renderImpact();
      case 'whatif': return (
        <Panel className="min-h-[80vh] overflow-hidden">
          <WhatIfSimulator
            repository={selectedRepo!}
            files={files}
            symbols={symbols}
          />
        </Panel>
      );
      case 'git': return renderGit();
      case 'errors': return renderErrorSection();
      case 'debt': return renderDebt();
      case 'onboarding': return renderOnboarding();
      case 'rules': return renderRules();
      case 'health': return renderHealth();
    }
  };

  return (
    <div className="min-h-screen bg-[#090e16] text-slate-100">
      <Navbar />
      <div className="mx-auto flex min-h-[calc(100vh-65px)] max-w-[1720px]">
        <aside className="hidden w-[248px] shrink-0 border-r border-white/[0.06] bg-[#0c121b] px-3 py-5 lg:block">
          <div className="mb-4 px-2">
            <div className="flex items-center justify-between">
              <p className="text-[9px] font-semibold uppercase tracking-[.18em] text-slate-600">Workspace</p>
              <button onClick={() => setIsIngestOpen(true)} title="Connect repository" className="rounded-md p-1 text-slate-500 hover:bg-white/5 hover:text-slate-200"><Plus size={14} /></button>
            </div>
            <div className="relative mt-3">
              <FolderIcon className="absolute left-3 top-2.5 h-4 w-4 text-indigo-300" />
              <select value={selectedRepo?.id || ''} onChange={(event) => setSelectedRepo(repositories.find((repo) => repo.id === event.target.value) || null)} className="w-full appearance-none rounded-lg border border-white/[0.08] bg-[#111824] py-2.5 pl-9 pr-8 text-xs text-slate-200 outline-none focus:border-indigo-300/30">
                <option value="">Select repository</option>
                {repositories.map((repo) => <option key={repo.id} value={repo.id}>{repo.name}</option>)}
              </select>
              <ChevronDown size={13} className="pointer-events-none absolute right-3 top-3 text-slate-600" />
            </div>
          </div>
          {navGroups.map((group) => <div key={group} className="mb-5"><p className="mb-2 px-2 text-[9px] font-semibold uppercase tracking-[.17em] text-slate-600">{group}</p><nav className="space-y-0.5">{NAV_ITEMS.filter((item) => item.group === group).map((item) => <button key={item.id} onClick={() => setSection(item.id)} className={cx('flex w-full items-center gap-3 rounded-lg px-2.5 py-2.5 text-left transition', section === item.id ? 'bg-indigo-400/[0.11] text-indigo-200' : 'text-slate-400 hover:bg-white/[0.035] hover:text-slate-200')}><item.icon size={15} className={section === item.id ? 'text-indigo-300' : 'text-slate-500'} /><span className="flex-1 text-[11px] font-medium">{item.label}</span>{item.id === 'overview' && <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />}</button>)}</nav></div>)}
          <div className="mt-auto rounded-xl border border-white/[0.06] bg-[#111824] p-3">
            <div className="flex items-center gap-2"><span className={cx('h-1.5 w-1.5 rounded-full', repositoryLoading ? 'bg-amber-400' : selectedRepo ? 'bg-emerald-400' : 'bg-slate-600')} /><span className="text-[10px] font-medium text-slate-400">{repositoryLoading ? 'Connecting…' : selectedRepo ? 'Repository connected' : 'No repository selected'}</span></div>
            <p className="mt-2 truncate font-mono text-[9px] text-slate-600">{selectedRepo?.default_branch || 'Connect a codebase'}</p>
          </div>
        </aside>

        <main className="min-w-0 flex-1 px-4 py-5 sm:px-6 lg:px-8">
          <div className="mb-5 flex flex-col justify-between gap-4 xl:flex-row xl:items-center">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-[10px] text-slate-600"><span>Repositories</span><span>/</span><span className="truncate text-slate-400">{selectedRepo?.name || 'Workspace'}</span><span>/</span><span className="text-indigo-300">{NAV_ITEMS.find((item) => item.id === section)?.label}</span></div>
              <h1 className="mt-2 text-xl font-semibold tracking-tight text-slate-100 sm:text-2xl">{selectedRepo?.name || 'Repository intelligence'}<span className="ml-2 align-middle text-sm font-normal text-slate-500">/ {NAV_ITEMS.find((item) => item.id === section)?.label}</span></h1>
              <p className="mt-1 max-w-3xl truncate font-mono text-[10px] text-slate-600">{selectedRepo?.source_path || 'Connect a repository to begin exploring its intelligence dashboard.'}</p>
            </div>
            <div className="flex items-center gap-2">
              <div className="flex items-center gap-2 rounded-lg border border-white/[0.07] bg-[#111824] px-3 py-2 text-[10px] text-slate-500"><Clock3 size={13} />{selectedRepo ? `Updated ${timeAgo(selectedRepo.updated_at)}` : 'Workspace ready'}</div>
              {selectedRepo && <button onClick={() => void loadWorkspace(selectedRepo)} title="Refresh repository data" className="grid h-9 w-9 place-items-center rounded-lg border border-white/[0.07] bg-[#111824] text-slate-400 hover:text-slate-200"><RefreshCw size={14} className={loading ? 'animate-spin' : ''} /></button>}
              <button onClick={() => setIsIngestOpen(true)} className="flex items-center gap-2 rounded-lg bg-indigo-500 px-3.5 py-2.5 text-[10px] font-semibold text-white shadow-lg shadow-indigo-950/40 hover:bg-indigo-400"><Plus size={13} />Connect repository</button>
            </div>
          </div>

          <div className="mb-4 flex gap-1 overflow-x-auto pb-1 lg:hidden">{NAV_ITEMS.map((item) => <button key={item.id} onClick={() => setSection(item.id)} className={cx('shrink-0 rounded-lg px-3 py-2 text-[10px]', section === item.id ? 'bg-indigo-400/15 text-indigo-200' : 'bg-white/[0.03] text-slate-500')}>{item.label}</button>)}</div>

          {error && <div className="mb-4 flex items-start justify-between gap-3 rounded-xl border border-rose-400/15 bg-rose-400/[0.06] px-4 py-3 text-xs text-rose-200"><span>{error}</span><button onClick={() => setError('')}><X size={14} /></button></div>}
          {loading && section === 'overview' && !summary ? <div className="grid min-h-[50vh] place-items-center text-xs text-slate-500"><div className="text-center"><LoaderCircle size={24} className="mx-auto mb-3 animate-spin text-indigo-300" />Loading repository intelligence…</div></div>
            : selectedRepo ? renderSection()
              : <Panel className="grid min-h-[60vh] place-items-center"><div className="max-w-md px-6 text-center"><div className="mx-auto grid h-14 w-14 place-items-center rounded-2xl border border-indigo-300/15 bg-indigo-400/[0.08] text-indigo-300"><Command size={24} /></div><h2 className="mt-5 text-lg font-semibold text-slate-100">Your codebase, understood</h2><p className="mt-2 text-xs leading-6 text-slate-500">Connect a repository to explore its architecture, security signals, tests, Git history, and evidence-backed code intelligence.</p><button onClick={() => setIsIngestOpen(true)} className="mt-5 rounded-lg bg-indigo-500 px-4 py-2.5 text-xs font-semibold text-white hover:bg-indigo-400"><Plus size={14} className="mr-2 inline" />Connect a repository</button></div></Panel>}
          <footer className="mt-7 flex flex-wrap justify-between gap-2 border-t border-white/[0.05] pt-4 text-[9px] text-slate-700"><span>CodeTwin Intelligence Workspace</span><span>Analysis is evidence-based and may be incomplete.</span></footer>
        </main>
      </div>
      <IngestModal isOpen={isIngestOpen} onClose={() => setIsIngestOpen(false)} onSuccess={(repo) => {
        setRepositories((current) => [repo, ...current.filter((item) => item.id !== repo.id)]);
        setSelectedRepo(repo);
      }} />
    </div>
  );
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl border border-white/[0.06] bg-[#0b111a] p-3.5"><p className="text-[10px] text-slate-500">{label}</p><p className="mt-2 truncate text-lg font-semibold text-slate-200">{value}</p></div>;
}

function editorLanguage(language: string) {
  const languages: Record<string, string> = {
    python: 'python', javascript: 'javascript', typescript: 'typescript', java: 'java',
    c: 'c', cpp: 'cpp', go: 'go', rust: 'rust', html: 'html', css: 'css',
    json: 'json', yaml: 'yaml', markdown: 'markdown', shell: 'shell',
  };
  return languages[language.toLowerCase()] || 'plaintext';
}

function FolderIcon({ className }: { className?: string }) {
  return <FileCode2 className={className} />;
}
