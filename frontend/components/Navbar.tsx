'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { Cpu, Terminal, ExternalLink } from 'lucide-react';
import { apiService, API_BASE } from '../services/api';
import { HealthStatus } from '../types';

export default function Navbar() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiService
      .getHealth()
      .then((data) => {
        setHealth(data);
        setLoading(false);
      })
      .catch(() => {
        setLoading(false);
      });
  }, []);

  return (
    <header className="sticky top-0 z-40 w-full border-b border-slate-800/80 bg-slate-950/70 backdrop-blur-xl">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3.5">
        {/* Logo and Brand */}
        <div className="flex items-center space-x-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-tr from-indigo-600 via-indigo-500 to-cyan-400 p-0.5 shadow-lg shadow-indigo-500/20">
            <div className="flex h-full w-full items-center justify-center rounded-[10px] bg-slate-950">
              <Cpu className="h-5 w-5 text-indigo-400" />
            </div>
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <span className="text-lg font-bold tracking-tight text-white">CodeTwin</span>
              <span className="rounded-full bg-indigo-500/10 px-2 py-0.5 text-[11px] font-semibold text-indigo-400 border border-indigo-500/20">
                v1.0-alpha
              </span>
            </div>
            <p className="text-[11px] text-slate-400">AI Software Repository Intelligence & Verification</p>
          </div>
        </div>

        {/* Status Indicators & Links */}
        <div className="flex items-center space-x-4">
          {/* Health status pill */}
          <div className="flex items-center space-x-2 rounded-full border border-slate-800 bg-slate-900/80 px-3 py-1.5 text-xs">
            <span className="relative flex h-2 w-2">
              {health?.status === 'healthy' ? (
                <>
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75"></span>
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500"></span>
                </>
              ) : (
                <span className="relative inline-flex h-2 w-2 rounded-full bg-amber-500"></span>
              )}
            </span>
            <span className="font-medium text-slate-300">
              {loading ? 'Checking Engine...' : health?.status === 'healthy' ? 'Engine Online' : 'Local Standby'}
            </span>
            {health?.database && (
              <span className="border-l border-slate-700 pl-2 text-[11px] text-slate-400">
                DB: {health.database}
              </span>
            )}
          </div>

          <Link
            href="/"
            className="flex items-center space-x-1.5 rounded-lg border border-slate-800 bg-slate-900/50 px-3 py-1.5 text-xs font-medium text-slate-300 transition-colors hover:border-slate-700 hover:bg-slate-800 hover:text-white"
          >
            <span>Home</span>
          </Link>

          <a
            href={`${API_BASE}/docs`}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center space-x-1.5 rounded-lg border border-slate-800 bg-slate-900/50 px-3 py-1.5 text-xs font-medium text-slate-300 transition-colors hover:border-slate-700 hover:bg-slate-800 hover:text-white"
          >
            <Terminal className="h-3.5 w-3.5 text-cyan-400" />
            <span>FastAPI Docs</span>
            <ExternalLink className="h-3 w-3 text-slate-500" />
          </a>
        </div>
      </div>
    </header>
  );
}
