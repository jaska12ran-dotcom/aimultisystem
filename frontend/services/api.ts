import { Repository, DigitalTwinSummary, FileItem, CodeSymbol, HealthStatus } from '../types';

/**
 * Default to the same-origin Next.js proxy (`/api/v1`), which forwards to the
 * FastAPI service configured by `BACKEND_URL`. This keeps browser requests
 * free of CORS and works unchanged in local dev, Docker and hosted setups.
 * Set `NEXT_PUBLIC_API_URL` only to call the API origin directly.
 */
export const API_BASE = (process.env.NEXT_PUBLIC_API_URL || '/api/v1').replace(/\/$/, '');

export const apiService = {
  async getHealth(): Promise<HealthStatus> {
    const res = await fetch(`${API_BASE}/health`, { cache: 'no-store' });
    if (!res.ok) throw new Error('Health check failed');
    return res.json();
  },

  async listRepositories(): Promise<Repository[]> {
    const res = await fetch(`${API_BASE}/repositories`, { cache: 'no-store' });
    if (!res.ok) throw new Error('Failed to fetch repositories');
    return res.json();
  },

  async getRepository(repoId: string): Promise<Repository> {
    const res = await fetch(`${API_BASE}/repositories/${repoId}`, { cache: 'no-store' });
    if (!res.ok) throw new Error('Repository not found');
    return res.json();
  },

  async getDigitalTwinSummary(repoId: string): Promise<DigitalTwinSummary> {
    const res = await fetch(`${API_BASE}/repositories/${repoId}/summary`, { cache: 'no-store' });
    if (!res.ok) throw new Error('Failed to fetch twin summary');
    return res.json();
  },

  async getFiles(repoId: string): Promise<FileItem[]> {
    const res = await fetch(`${API_BASE}/repositories/${repoId}/files`, { cache: 'no-store' });
    if (!res.ok) throw new Error('Failed to fetch repository files');
    return res.json();
  },

  async getSymbols(repoId: string, type?: string): Promise<CodeSymbol[]> {
    const params = new URLSearchParams();
    if (type) params.set('symbol_type', type);
    const query = params.toString();
    const res = await fetch(
      `${API_BASE}/repositories/${encodeURIComponent(repoId)}/symbols${query ? `?${query}` : ''}`,
      { cache: 'no-store' },
    );
    if (!res.ok) throw new Error('Failed to fetch symbols');
    return res.json();
  },

  async ingestLocal(path: string, name?: string): Promise<Repository> {
    const res = await fetch(`${API_BASE}/repositories/local`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, name }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Ingestion failed' }));
      throw new Error(err.detail || 'Failed to ingest repository');
    }
    return res.json();
  },

  async ingestGitHub(url: string, branch?: string, name?: string): Promise<Repository> {
    const res = await fetch(`${API_BASE}/repositories/clone`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, branch, name }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Clone failed' }));
      throw new Error(err.detail || 'Failed to clone repository');
    }
    return res.json();
  },

  async uploadZip(file: File): Promise<Repository> {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${API_BASE}/repositories/upload`, {
      method: 'POST',
      body: formData,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'ZIP upload failed' }));
      throw new Error(err.detail || 'Failed to upload archive');
    }
    return res.json();
  },
};
