export interface Repository {
  id: string;
  name: string;
  description?: string | null;
  source_type: 'github' | 'zip' | 'local' | string;
  source_url?: string | null;
  source_path: string;
  default_branch: string;
  /** File count keyed by language, as returned by the backend. */
  file_count_by_language: Record<string, number>;
  total_files: number;
  total_lines: number;
  total_symbols: number;
  total_size_bytes: number;
  status: 'created' | 'analyzing' | 'ready' | 'failed' | string;
  analysis_phase: string;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
}

export interface FileItem {
  id: string;
  relative_path: string;
  file_name: string;
  file_extension: string;
  language: string;
  size_bytes: number;
  line_count: number;
  is_test: boolean;
  is_binary: boolean;
}

export interface FolderItem {
  id: string;
  relative_path: string;
  folder_name: string;
  parent_path?: string;
  file_count: number;
}

export interface CodeSymbol {
  id: string;
  file_id: string;
  relative_path?: string;
  name: string;
  qualified_name: string;
  symbol_type: 'class' | 'function' | 'method' | 'interface' | 'api_route' | 'db_model' | 'schema_model';
  start_line: number;
  end_line: number;
  signature: string;
  docstring?: string;
  parameters: Array<{ name: string; type?: string }>;
  return_type?: string;
  complexity_score: number;
  is_exported: boolean;
}

export interface DigitalTwinSummary {
  repository: Repository;
  total_files: number;
  total_lines: number;
  total_symbols: number;
  total_relationships: number;
  total_commits: number;
  languages: Array<{
    language: string;
    file_count: number;
    line_count: number;
    size_bytes: number;
    percentage: number;
  }>;
  symbol_types_breakdown: Record<string, number>;
  api_routes: CodeSymbol[];
  db_models: CodeSymbol[];
  recent_commits: Array<{
    id: string;
    commit_hash: string;
    author_name: string;
    committed_at: string;
    message: string;
    files_changed: string[];
    insertions: number;
    deletions: number;
  }>;
}

export interface HealthStatus {
  status: string;
  service: string;
  database: string;
  runtime: {
    python_version: string;
    platform: string;
    cpu_percent: number;
    memory_usage_mb: number;
  };
}
