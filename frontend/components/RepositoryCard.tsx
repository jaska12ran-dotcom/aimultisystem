'use client';

import React from 'react';
import { Folder, GitBranch, CheckCircle2, AlertTriangle, ArrowRight } from 'lucide-react';
import { Repository } from '../types';
import { formatNumber } from '../lib/utils';

interface RepositoryCardProps {
  repo: Repository;
  onSelect: (repo: Repository) => void;
}

export default function RepositoryCard({ repo, onSelect }: RepositoryCardProps) {
  const languageCounts = repo.file_count_by_language || {};
  const languageTotal = Object.values(languageCounts).reduce((sum, count) => sum + count, 0);
  const languageList = Object.entries(languageCounts).slice(0, 3);

  return (
    <div
      onClick={() => onSelect(repo)}
      className="glass-panel glass-panel-hover group relative flex flex-col justify-between rounded-xl p-5 cursor-pointer"
    >
      <div>
        {/* Header */}
        <div className="flex items-start justify-between">
          <div className="flex items-center space-x-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 group-hover:scale-105 transition-transform">
              {repo.source_type === 'github' ? (
                <GitBranch className="h-4 w-4" />
              ) : (
                <Folder className="h-4 w-4" />
              )}
            </div>
            <div>
              <h4 className="text-sm font-semibold text-white group-hover:text-indigo-300 transition-colors">
                {repo.name}
              </h4>
              <p className="text-[11px] text-slate-400 font-mono truncate max-w-[200px]">
                {repo.source_path}
              </p>
            </div>
          </div>

          <span
            className={`inline-flex items-center space-x-1 rounded-full px-2 py-0.5 text-[10px] font-medium border ${
              repo.status === 'ready'
                ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
                : repo.status === 'analyzing'
                ? 'border-indigo-500/30 bg-indigo-500/10 text-indigo-400 animate-pulse'
                : 'border-rose-500/30 bg-rose-500/10 text-rose-400'
            }`}
          >
            {repo.status === 'ready' ? (
              <CheckCircle2 className="h-2.5 w-2.5" />
            ) : (
              <AlertTriangle className="h-2.5 w-2.5" />
            )}
            <span className="capitalize">{repo.status}</span>
          </span>
        </div>

        {/* Metrics Grid */}
        <div className="mt-4 grid grid-cols-3 gap-2 rounded-lg bg-slate-950/60 p-2.5 border border-slate-800/80">
          <div>
            <span className="block text-[10px] text-slate-500">Files</span>
            <span className="text-xs font-semibold text-slate-200">
              {formatNumber(repo.total_files)}
            </span>
          </div>
          <div>
            <span className="block text-[10px] text-slate-500">Lines</span>
            <span className="text-xs font-semibold text-slate-200">
              {formatNumber(repo.total_lines)}
            </span>
          </div>
          <div>
            <span className="block text-[10px] text-slate-500">AST Symbols</span>
            <span className="text-xs font-semibold text-indigo-400">
              {formatNumber(repo.total_symbols)}
            </span>
          </div>
        </div>

        {/* Language badges */}
        {languageList.length > 0 && (
          <div className="mt-3 flex items-center space-x-2">
            {languageList.map(([lang, count]) => (
              <span
                key={lang}
                className="rounded bg-slate-800/80 px-2 py-0.5 text-[10px] font-medium text-slate-300"
              >
                {lang} <span className="text-slate-500">{languageTotal ? Math.round((count / languageTotal) * 100) : 0}%</span>
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Footer link */}
      <div className="mt-4 flex items-center justify-between border-t border-slate-800/60 pt-3 text-[11px] text-slate-400">
        <span>Branch: {repo.default_branch || 'main'}</span>
        <span className="flex items-center space-x-1 font-medium text-indigo-400 group-hover:translate-x-0.5 transition-transform">
          <span>Open Twin</span>
          <ArrowRight className="h-3 w-3" />
        </span>
      </div>
    </div>
  );
}
