'use client';

import { useEffect, useRef } from 'react';

export default function WorldBackdrop({ variant = 'landing' }: { variant?: 'landing' | 'app' }) {
  const hexRef = useRef<HTMLDivElement>(null);

  // Subtle parallax on aurora blobs based on scroll
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const handleScroll = () => {
      const y = window.scrollY;
      const el = hexRef.current;
      if (el) {
        el.style.transform = `translateY(${y * 0.04}px)`;
      }
    };
    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  return (
    <div
      className={`world-backdrop world-backdrop-${variant}`}
      aria-hidden="true"
    >
      {/* Depth base */}
      <div className="world-backdrop-base" />

      {/* Aurora blobs — animated plasma clouds */}
      <div className="world-backdrop-aurora world-backdrop-aurora-a" />
      <div className="world-backdrop-aurora world-backdrop-aurora-b" />
      <div className="world-backdrop-aurora world-backdrop-aurora-c" />
      <div className="world-backdrop-aurora world-backdrop-aurora-d" />

      {/* Star field */}
      <div className="world-backdrop-stars" />

      {/* Perspective grid */}
      <div ref={hexRef} className="world-backdrop-grid" />

      {/* Horizon glow line */}
      <div className="world-backdrop-horizon" />

      {/* Film grain */}
      <div className="world-backdrop-noise" />

      {/* Vignette */}
      <div className="world-backdrop-vignette" />
    </div>
  );
}
