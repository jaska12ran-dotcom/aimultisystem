import { API_BASE } from './api';
import { CodeSymbol, DigitalTwinSummary, FileItem, Repository } from '../types';

export interface GraphNode {
  id: string;
  name: string;
  type: string;
  metadata: Record<string, unknown>;
}

export interface GraphRelationship {
  source: string;
  target: string;
  type: string;
  metadata: Record<string, unknown>;
}

export interface RepositoryGraph {
  repository_id: string;
  nodes: GraphNode[];
  relationships: GraphRelationship[];
  counts: { nodes: number; relationships: number };
}

export interface Dependency {
  id: string;
  package_name: string;
  ecosystem: string;
  version_spec?: string | null;
  is_dev: boolean;
}

export interface GitEvidence {
  commit_hash: string;
  message: string;
  author: string;
  timestamp: string;
  files_changed: string[];
  relevance: string;
}

export interface GitFileHistory {
  file: string;
  change_frequency: number;
  insertions: number;
  deletions: number;
  churn: number;
  last_modified?: string | null;
  recent_commit_count: number;
  is_hotspot: boolean;
  hotspot_risk: string;
  abandoned_area_candidate: boolean;
  critical_component: boolean;
  recently_modified_critical: boolean;
  evidence: GitEvidence[];
}

export interface WhyCodeResult {
  repository_id: string;
  target: string;
  answer: string;
  sufficient_history: boolean;
  evidence: GitEvidence[];
  limitation: string;
}

export interface GitHistory {
  repository_id: string;
  history_available: boolean;
  history_scope: string;
  commits_analyzed: number;
  branches: string[];
  branch_history_available: boolean;
  files: GitFileHistory[];
  frequently_changed_files: GitFileHistory[];
  unstable_modules: string[];
  high_risk_hotspots: GitFileHistory[];
  abandoned_area_candidates: GitFileHistory[];
  recently_modified_critical_components: GitFileHistory[];
  summary: string;
}

export interface ImpactEvidence {
  source: string;
  file: string;
  line?: number | null;
  description: string;
}

export interface ImpactComponent {
  symbol: string;
  symbol_type: string;
  file: string;
  start_line?: number | null;
  end_line?: number | null;
  relationship: string;
  evidence: ImpactEvidence[];
}

export interface ImpactAnalysis {
  repository_id: string;
  symbol: string;
  affected_files?: string[];
  changed_symbols?: string[];
  target: ImpactComponent[];
  direct_impact: ImpactComponent[];
  indirect_impact: ImpactComponent[];
  affected_apis: ImpactComponent[];
  affected_modules: ImpactComponent[];
  affected_tests: ImpactComponent[];
  graph_nodes: Array<{ id: string; symbol: string; file: string; category: 'target' | 'direct' | 'indirect'; line?: number | null }>;
  graph_edges: Array<{ source: string; target: string; relationship: string; evidence: ImpactEvidence }>;
  potential_risks: Array<{ severity: string; description: string; evidence: ImpactEvidence[] }>;
  confidence: number;
  confidence_reasons: string[];
  caveat: string;
}

export interface TestStrengthReport {
  repository_id: string;
  test_file_count: number;
  python_test_file_count: number;
  discovered_test_function_count: number;
  test_files_with_assertions: number;
  test_files_without_assertions: number;
  mapped_symbols: number;
  analyzed_symbols: number;
  symbols: Array<{
    symbol: string; symbol_type: string; file: string; start_line: number; end_line: number;
    complexity: number; mapping_status: 'linked' | 'candidate' | 'unmatched';
    linked_tests: string[]; candidate_tests: string[]; branch_count?: number | null;
    raise_count?: number | null; potential_gaps: string[]; evidence: ImpactEvidence[];
  }>;
  findings: string[];
  limitations: string[];
}

export interface RegressionSelection {
  repository_id: string;
  changed_files: string[];
  changed_symbols: string[];
  matched_symbols: string[];
  selected_tests: Array<{ file: string; confidence: 'high' | 'medium' | 'low'; reasons: string[]; evidence: ImpactEvidence[] }>;
  full_suite_recommended: boolean;
  recommendation_reasons: string[];
  limitations: string[];
}

export interface SecurityFinding {
  severity: string;
  category: string;
  file: string;
  line?: number | null;
  description: string;
  evidence: string;
  remediation: string;
  tool: string;
  confidence: string;
}

export interface SecurityAnalysis {
  summary: string;
  findings: SecurityFinding[];
  dashboard: Record<'critical' | 'high' | 'medium' | 'low' | 'informational', number> & {
    total_findings: number;
  };
  tools_considered: string[];
}

export interface RepositoryFileContent {
  path: string;
  language: string;
  content: string;
  line_count: number;
}

export interface RepositoryIndexStatus {
  repository_id: string;
  status: 'not_indexed' | 'indexing' | 'ready' | 'failed' | string;
  last_started_at?: string | null;
  last_successful_at?: string | null;
  last_error?: string | null;
  indexed_file_count: number;
  indexed_symbol_count: number;
  last_added_files: number;
  last_updated_files: number;
  last_deleted_files: number;
  last_unchanged_files: number;
  indexed_git_head?: string | null;
  hours_since_last_analysis?: number | null;
  indexing_health?: 'fresh' | 'stale' | 'old' | 'never' | null;
}

export interface RepositoryReindexResult extends RepositoryIndexStatus {
  added_files: number;
  updated_files: number;
  deleted_files: number;
  unchanged_files: number;
  refreshed_relationship_files: number;
  refreshed_rag_files: number;
}

export interface DocumentationDrift {
  has_drift: boolean;
  issues: Array<{ issue_type: string; severity: string; title: string; details: string; evidence: Record<string, unknown>; suggested_correction?: string | null }>;
  summary: string;
  doc_was_not_overwritten: boolean;
}

export interface TechnicalDebtReport {
  repository_id: string;
  findings: Array<{ category: string; severity: 'high' | 'medium' | 'low' | 'informational'; title: string; details: string; confidence: string; estimated_effort: string; affected_components: string[]; evidence: Array<{ source: string; file: string; line?: number | null; description: string }>; remediation: string; measured: boolean }>;
  summary: string;
  limitations: string[];
}

export interface CodeHealthDimension {
  name: string;
  score: number;
  weight: number;
  grade: string;
  findings: string[];
  recommendations: string[];
}

export interface CodeHealthReport {
  repository_id: string;
  overall_score: number;
  grade: string;
  dimensions: CodeHealthDimension[];
  summary: string;
  top_risks: string[];
  quick_wins: string[];
  limitations: string[];
}

export interface DependencyRisk {
  package_name: string;
  ecosystem: string;
  declared_version?: string | null;
  manifest_file?: string | null;
  is_dev: boolean;
  cve: string;
  severity: string;
  summary: string;
  recommendation: string;
}

export interface DependencySecurityReport {
  repository_id: string;
  dependencies_scanned: number;
  risky_dependencies: DependencyRisk[];
  critical_count: number;
  high_count: number;
  medium_count: number;
  low_count: number;
  advisories_checked: number;
  summary: string;
  limitations: string[];
}

export interface TestFailureEvidence {
  file: string;
  line?: number | null;
  snippet: string;
}

export interface TestFailureExplanation {
  test_name: string;
  category: string;
  summary: string;
  likely_cause: string;
  suggested_fix: string;
  confidence: string;
  evidence: TestFailureEvidence[];
  source_symbol?: string | null;
  source_symbol_file?: string | null;
}

export interface TestFailureExplanationReport {
  repository_id: string;
  failures_found: number;
  explanations: TestFailureExplanation[];
  category_counts: Record<string, number>;
  summary: string;
  limitations: string[];
}

export interface OrchestratorStep {
  agent: string;
  status: string;
  result_summary: string;
}

export interface OrchestratorReport {
  repository_id: string;
  intent: string;
  steps: OrchestratorStep[];
  answer: string;
  confidence: string;
  limitations: string[];
}

export interface OnboardingGuide { repository_id: string; overview: string; entry_points: Array<{ file: string; line?: number | null; description: string }>; important_modules: Array<{ file: string; line?: number | null; description: string }>; guided_paths: Array<{ title: string; level: string; description: string; references: Array<{ file: string; line?: number | null; description: string }> }>; learning_tasks: Array<{ title: string; level: string; description: string; references: Array<{ file: string; line?: number | null; description: string }> }>; testing_instructions: string[]; limitations: string[]; }
export interface BusinessRuleReport { repository_id: string; rules: Array<{ rule_type: string; description: string; confidence: string; explicit: boolean; source_evidence: Array<{ file: string; line?: number | null; description: string }>; related_tests: Array<{ file: string; line?: number | null; description: string }>; related_apis: Array<{ file: string; line?: number | null; description: string }>; contradictions: string[] }>; limitations: string[]; }
export interface CodeMemory { repository_id: string; target: string; matched_files: string[]; history_available: boolean; commits: Array<{ commit_hash: string; message: string; author: string; timestamp: string; files_changed: string[] }>; documentation_references: Array<{ file: string; line?: number | null; description: string }>; summary: string; limitations: string[]; }

export interface RepositoryErrorSummary {
  repository_id: string;
  total_errors: number;
  resolved_errors: number;
  unresolved_errors: number;
  by_type: Record<string, number>;
  recent_errors: ErrorHistoryEntry[];
  summary: string;
}

export interface ErrorHistoryEntry {
  id: string;
  occurred_at: string;
  error_type: string;
  error_message: string;
  file_path: string | null;
  resolved: boolean;
  resolution_notes?: string | null;
}

export interface CodeSearchResultItem {
  language: string;
  code: string;
  docstring: string;
  score: number;
  match_reason: string;
}

export interface CodeSearchResult {
  repository_id: string;
  query: string;
  results: CodeSearchResultItem[];
  total_results: number;
  dataset_source: string;
}

export interface CodeExampleItem {
  language: string;
  code: string;
  docstring: string;
}

export interface SWEBenchInstanceSummary {
  instance_id: string;
  repo: string;
  problem_statement: string;
  base_commit?: string;
  version?: string;
  patch?: string;
  modified_files?: string[];
  fail_to_pass?: string[];
  score: number;
  match_reason: string;
}

export interface SWEBenchSearchResult {
  query: string;
  total_results: number;
  results: SWEBenchInstanceSummary[];
  dataset_source: string;
}

export interface CodeExamplesResult {
  repository_id: string;
  concept: string;
  examples: CodeExampleItem[];
  language_filter: string | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    cache: 'no-store',
    headers: {
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export const intelligenceApi = {
  summary: (id: string) => request<DigitalTwinSummary>(`/repositories/${id}/summary`),
  files: (id: string) => request<FileItem[]>(`/repositories/${id}/files?limit=2000`),
  symbols: (id: string) => request<CodeSymbol[]>(`/repositories/${id}/symbols?limit=2000`),
  dependencies: (id: string) => request<Dependency[]>(`/repositories/${id}/dependencies`),
  graph: (id: string) => request<RepositoryGraph>(`/repositories/${id}/graph`),
  fileContent: (id: string, path: string) =>
    request<RepositoryFileContent>(`/repositories/${id}/file-content?path=${encodeURIComponent(path)}`),
  history: (id: string) => request<GitHistory>(`/repositories/${id}/history-analysis`),
  whyCode: (id: string, target: string) =>
    request<WhyCodeResult>(`/repositories/${id}/history/why`, {
      method: 'POST',
      body: JSON.stringify({ target, limit: 10 }),
    }),
  onboarding: (id: string) => request<OnboardingGuide>(`/repositories/${id}/onboarding`),
  businessRules: (id: string) => request<BusinessRuleReport>(`/repositories/${id}/business-rules`),
  codeMemory: (id: string, target: string) => request<CodeMemory>(`/repositories/${id}/code-memory?target=${encodeURIComponent(target)}`),
  indexStatus: (id: string) => request<RepositoryIndexStatus>(`/repositories/${id}/index-status`),
  reindex: (id: string) => request<RepositoryReindexResult>(`/repositories/${id}/reindex`, { method: 'POST' }),
  impact: (
    id: string,
    params: string | { symbol?: string; file_path?: string; changed_code?: string; diff?: string }
  ) => {
    const payload = typeof params === 'string' ? { symbol: params } : params;
    return request<ImpactAnalysis>(`/repositories/${id}/impact-analysis`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
  security: (id: string) =>
    request<SecurityAnalysis>(`/repositories/${id}/security/analyze`, { method: 'POST' }),
  technicalDebt: (id: string) => request<TechnicalDebtReport>(`/repositories/${id}/technical-debt`),
  codeHealth: (id: string) => request<CodeHealthReport>(`/repositories/${id}/code-health`),
  dependencySecurity: (id: string) => request<DependencySecurityReport>(`/repositories/${id}/security/dependencies`),
  ask: (id: string, message: string) =>
    request<{
      reply: string;
      citations: Array<{ file_path: string; line_start?: number; line_end?: number }>;
      confidence: 'low' | 'medium' | 'high';
      confidence_reasons: string[];
      limitations: string;
    }>(
      `/repositories/${id}/chat`,
      { method: 'POST', body: JSON.stringify({ message }) },
    ),
  orchestrate: (id: string, query: string) =>
    request<OrchestratorReport>(`/repositories/${id}/ask/orchestrate`, {
      method: 'POST',
      body: JSON.stringify({ query }),
    }),
  generateDocs: (id: string, docType: string) =>
    request<{ title: string; content_markdown: string; doc_type: string }>(
      `/repositories/${id}/docs/generate`,
      { method: 'POST', body: JSON.stringify({ doc_type: docType }) },
    ),
  docs: (id: string) => request<Array<{ id: string; title: string; doc_type: string; content_markdown: string }>>(
    `/repositories/${id}/docs`,
  ),
  docsDrift: (id: string, content: string) =>
    request<DocumentationDrift>(`/repositories/${id}/docs/drift`, {
      method: 'POST',
      body: JSON.stringify({ existing_documentation: content }),
    }),
  testPipeline: (id: string) =>
    request<Record<string, unknown>>(`/repositories/${id}/tests/pipeline`, {
      method: 'POST',
      body: JSON.stringify({ framework: 'pytest', include_mutation: false }),
    }),
  testStrength: (id: string) => request<TestStrengthReport>(`/repositories/${id}/tests/strength`),
  selectRegressionTests: (id: string, changedFiles: string[], changedSymbols: string[]) =>
    request<RegressionSelection>(`/repositories/${id}/tests/select`, {
      method: 'POST',
      body: JSON.stringify({ changed_files: changedFiles, changed_symbols: changedSymbols }),
    }),
  testPlan: (id: string, file: string) =>
    request<Record<string, unknown>>(`/repositories/${id}/tests/plan`, {
      method: 'POST',
      body: JSON.stringify({ target_file: file, test_framework: 'pytest' }),
    }),
  explainTestFailures: (id: string, executionOutput: string) =>
    request<TestFailureExplanationReport>(`/repositories/${id}/tests/explain-failures`, {
      method: 'POST',
      body: JSON.stringify({ execution_output: executionOutput }),
    }),
  errors: (id: string, resolved?: boolean) => request<ErrorHistoryEntry[]>(`/repositories/${id}/errors${resolved !== undefined ? `?resolved=${resolved}` : ''}`),
  errorSummary: (id: string) => request<RepositoryErrorSummary>(`/repositories/${id}/error-summary`),
  codeSearch: (id: string, query: string, language?: string, limit: number = 5) =>
    request<CodeSearchResult>(`/repositories/${id}/code-search`, {
      method: 'POST',
      body: JSON.stringify({ query, language, limit }),
    }),
  swebenchSearch: (id: string, query: string, repoFilter?: string, limit: number = 5) =>
    request<SWEBenchSearchResult>(`/repositories/${id}/swebench/search`, {
      method: 'POST',
      body: JSON.stringify({ query, repo_filter: repoFilter, limit }),
    }),
  swebenchInstance: (id: string, instanceId: string) =>
    request<SWEBenchInstanceSummary>(`/repositories/${id}/swebench/${instanceId}`),
  codeExamples: (id: string, concept: string, language?: string, limit: number = 3) =>
    request<CodeExamplesResult>(`/repositories/${id}/code-examples`, {
      method: 'POST',
      body: JSON.stringify({ concept, language, limit }),
    }),
};

export type RepositoryOption = Repository;

// ─────────────────────────────────────────────────────────────────────────────
// What-If Code Change Simulator
// ─────────────────────────────────────────────────────────────────────────────

export interface WhatIfRequest {
  file_path?: string | null;
  symbol?: string | null;
  branch?: string | null;
  natural_language_description: string;
  proposed_code?: string | null;
  proposed_diff?: string | null;
  alternatives?: string[] | null;
  include_security?: boolean;
  include_performance?: boolean;
  include_migration?: boolean;
  include_regression_tests?: boolean;
}

export interface SourceLocation {
  file: string;
  line?: number | null;
  end_line?: number | null;
  symbol?: string | null;
  url?: string | null;
}

export interface AffectedFile {
  file: string;
  reason: string;
  relationship: string;
  confidence: number;
  locations: SourceLocation[];
}

export interface ImpactedFunction {
  symbol: string;
  file: string;
  line?: number | null;
  relationship: string;
  impact_type: string;
  confidence: number;
  evidence: SourceLocation[];
}

export interface BreakingChangeEntry {
  symbol: string;
  file: string;
  line?: number | null;
  category: string;
  severity: string;
  before?: string | null;
  after?: string | null;
  description: string;
  verified: boolean;
}

export interface TestFailureRisk {
  test_file: string;
  test_function?: string | null;
  line?: number | null;
  risk_level: string;
  reason: string;
  verified: boolean;
}

export interface SecurityImplication {
  severity: string;
  category: string;
  description: string;
  verified: boolean;
  locations: SourceLocation[];
  remediation: string;
}

export interface PerformanceConcern {
  severity: string;
  category: string;
  description: string;
  verified: boolean;
  locations: SourceLocation[];
}

export interface MigrationRequirement {
  category: string;
  severity: string;
  description: string;
  action_required: string;
  locations: SourceLocation[];
}

export interface RegressionTestRecommendation {
  test_name: string;
  description: string;
  target_symbol?: string | null;
  target_file?: string | null;
  priority: string;
  rationale: string;
}

export interface AlternativeProposal {
  description: string;
  patch_hint?: string | null;
  tradeoffs: string;
  estimated_risk: string;
}

export interface WhatIfPatch {
  file_path: string;
  original_snippet?: string | null;
  proposed_snippet?: string | null;
  unified_diff?: string | null;
  rollback_diff?: string | null;
  workspace_note: string;
}

export interface WhatIfSimulationResult {
  repository_id: string;
  simulation_id: string;
  target_file?: string | null;
  target_symbol?: string | null;
  branch_context?: string | null;
  patch?: WhatIfPatch | null;
  affected_files: AffectedFile[];
  impacted_functions: ImpactedFunction[];
  breaking_changes: BreakingChangeEntry[];
  test_failure_risks: TestFailureRisk[];
  security_implications: SecurityImplication[];
  performance_concerns: PerformanceConcern[];
  migration_requirements: MigrationRequirement[];
  regression_test_recommendations: RegressionTestRecommendation[];
  alternatives: AlternativeProposal[];
  overall_risk: string;
  overall_confidence: number;
  verified_finding_count: number;
  predicted_finding_count: number;
  summary: string;
  assumptions: string[];
  limitations: string[];
  simulation_note: string;
}

// Extend the main intelligenceApi with What-If
export const whatIfApi = {
  simulate: (id: string, payload: WhatIfRequest) =>
    request<WhatIfSimulationResult>(`/repositories/${id}/whatif/simulate`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
};
