'use client';

import React, { useState } from 'react';
import { X, FolderPlus, GitBranch, Upload, Loader2, AlertCircle } from 'lucide-react';
import { apiService } from '../services/api';
import { Repository } from '../types';

interface IngestModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (repo: Repository) => void;
}

export default function IngestModal({ isOpen, onClose, onSuccess }: IngestModalProps) {
  const [tab, setTab] = useState<'local' | 'github' | 'zip'>('zip');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form states
  const [localPath, setLocalPath] = useState('');
  const [repoName, setRepoName] = useState('');
  const [githubUrl, setGithubUrl] = useState('');
  const [githubBranch, setGithubBranch] = useState('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      let createdRepo: Repository;
      if (tab === 'local') {
        if (!localPath.trim()) throw new Error('Please enter a local directory path.');
        createdRepo = await apiService.ingestLocal(localPath.trim(), repoName.trim() || undefined);
      } else if (tab === 'github') {
        if (!githubUrl.trim()) throw new Error('Please enter a GitHub repository URL.');
        createdRepo = await apiService.ingestGitHub(
          githubUrl.trim(),
          githubBranch.trim() || undefined,
          repoName.trim() || undefined
        );
      } else {
        if (!selectedFile) throw new Error('Please choose a .zip file to upload.');
        createdRepo = await apiService.uploadZip(selectedFile);
      }

      onSuccess(createdRepo);
      onClose();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to ingest repository';
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
      <div className="w-full max-w-lg rounded-2xl border border-slate-800 bg-slate-900 p-6 shadow-2xl">
        <div className="flex items-center justify-between pb-4 border-b border-slate-800">
          <div>
            <h3 className="text-lg font-semibold text-white">Ingest Software Repository</h3>
            <p className="text-xs text-slate-400">Create an AST-verified Digital Twin of the codebase</p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-800 hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Tab selection */}
        <div className="mt-4 flex rounded-xl bg-slate-950 p-1 border border-slate-800">
          <button
            type="button"
            onClick={() => { setTab('local'); setError(null); }}
            className={`flex flex-1 items-center justify-center space-x-2 rounded-lg py-2 text-xs font-medium transition-all ${
              tab === 'local'
                ? 'bg-indigo-600 text-white shadow-md'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            <FolderPlus className="h-4 w-4" />
            <span>Local Folder</span>
          </button>
          <button
            type="button"
            onClick={() => { setTab('github'); setError(null); }}
            className={`flex flex-1 items-center justify-center space-x-2 rounded-lg py-2 text-xs font-medium transition-all ${
              tab === 'github'
                ? 'bg-indigo-600 text-white shadow-md'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            <GitBranch className="h-4 w-4" />
            <span>GitHub URL</span>
          </button>
          <button
            type="button"
            onClick={() => { setTab('zip'); setError(null); }}
            className={`flex flex-1 items-center justify-center space-x-2 rounded-lg py-2 text-xs font-medium transition-all ${
              tab === 'zip'
                ? 'bg-indigo-600 text-white shadow-md'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            <Upload className="h-4 w-4" />
            <span>ZIP Upload</span>
          </button>
        </div>

        {error && (
          <div className="mt-4 flex items-center space-x-2 rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-300">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="mt-5 space-y-4">
          {tab === 'local' && (
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">
                Backend-visible Directory Path <span className="text-rose-400">*</span>
              </label>
              <input
                type="text"
                value={localPath}
                onChange={(e) => setLocalPath(e.target.value)}
                placeholder="Absolute path visible to the backend service"
                required
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3.5 py-2 text-xs text-slate-100 placeholder-slate-500 focus:border-indigo-500 focus:outline-none"
              />
              <p className="mt-1 text-[10px] leading-4 text-slate-500">
                This path is read by the backend machine. For Docker or a remote server, use ZIP upload or GitHub instead unless the folder is mounted there.
              </p>
            </div>
          )}

          {tab === 'github' && (
            <>
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  GitHub Repository URL <span className="text-rose-400">*</span>
                </label>
                <input
                  type="url"
                  value={githubUrl}
                  onChange={(e) => setGithubUrl(e.target.value)}
                  placeholder="https://github.com/owner/repository"
                  required
                  className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3.5 py-2 text-xs text-slate-100 placeholder-slate-500 focus:border-indigo-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Branch (Optional)
                </label>
                <input
                  type="text"
                  value={githubBranch}
                  onChange={(e) => setGithubBranch(e.target.value)}
                  placeholder="main or master"
                  className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3.5 py-2 text-xs text-slate-100 placeholder-slate-500 focus:border-indigo-500 focus:outline-none"
                />
              </div>
            </>
          )}

          {tab === 'zip' && (
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">
                ZIP File Archive <span className="text-rose-400">*</span>
              </label>
              <input
                type="file"
                accept=".zip"
                onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
                required
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-300 file:mr-3 file:rounded-md file:border-0 file:bg-slate-800 file:px-2.5 file:py-1 file:text-xs file:font-medium file:text-indigo-400 hover:file:bg-slate-700"
              />
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              Custom Display Name (Optional)
            </label>
            <input
              type="text"
              value={repoName}
              onChange={(e) => setRepoName(e.target.value)}
              placeholder="e.g. Core Auth Service"
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3.5 py-2 text-xs text-slate-100 placeholder-slate-500 focus:border-indigo-500 focus:outline-none"
            />
          </div>

          <div className="mt-6 flex justify-end space-x-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              disabled={loading}
              className="rounded-lg px-4 py-2 text-xs font-medium text-slate-400 hover:bg-slate-800 hover:text-white"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="flex items-center space-x-2 rounded-lg bg-indigo-600 px-5 py-2 text-xs font-semibold text-white shadow-lg shadow-indigo-600/30 hover:bg-indigo-500 focus:outline-none disabled:opacity-50"
            >
              {loading && <Loader2 className="h-4 w-4 animate-spin" />}
              <span>{loading ? 'Analyzing & Building Twin...' : 'Ingest & Build Twin'}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
