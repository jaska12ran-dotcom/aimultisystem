'use client';

import { GitBranch, Globe2, Sparkles } from 'lucide-react';
import dynamic from 'next/dynamic';
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';

// The 3D stack is heavy: split it out of the initial bundle and mount client-side only.
const DigitalTwinScene = dynamic(() => import('./three/DigitalTwinScene'), { ssr: false });

const REDUCED_MOTION = '(prefers-reduced-motion: reduce)';

function supportsWebGL(): boolean {
  try {
    const canvas = document.createElement('canvas');
    return Boolean(canvas.getContext('webgl2') || canvas.getContext('webgl'));
  } catch {
    return false;
  }
}

const subscribeNever = () => () => {};

export default function HeroScene() {
  // Client-only snapshots via useSyncExternalStore: no sync setState in effects,
  // automatically SSR-safe (both resolve to false/paused on the server).
  const webgl = useSyncExternalStore(subscribeNever, supportsWebGL, () => false);

  const motionQuery = useMemo(
    () => (typeof window !== 'undefined' ? matchMedia(REDUCED_MOTION) : null),
    [],
  );
  const reduced = useSyncExternalStore(
    (callback) => {
      motionQuery?.addEventListener('change', callback);
      return () => motionQuery?.removeEventListener('change', callback);
    },
    () => motionQuery?.matches ?? false,
    () => false,
  );

  // Mount the canvas only when the hero is reachable; keep it mounted afterwards.
  const [inView, setInView] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) setInView(true);
      },
      { rootMargin: '120px' },
    );
    if (containerRef.current) observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  return (
    <div className="hero-visual" ref={containerRef} data-testid="hero-visual">
      {webgl === true && (
        <div className="twin-stage" aria-hidden="true">
          {inView && <DigitalTwinScene reduced={reduced} />}
        </div>
      )}

      {/* CSS fallback: the original orbital rings, only when WebGL is unavailable. */}
      {webgl === false && (
        <div className="orbital-scene" aria-hidden="true">
          <div className="orbital-ring ring-one" />
          <div className="orbital-ring ring-two" />
          <div className="orbital-ring ring-three" />
        </div>
      )}

      <div className="core-panel">
        <div className="core-header">
          <span className="status-dot" />
          <span>Repository health</span>
        </div>
        <div className="core-metrics">
          <div>
            <small>Architecture</small>
            <strong>Mapped</strong>
          </div>
          <div>
            <small>Risk</small>
            <strong>Tracked</strong>
          </div>
        </div>
        <div className="signal-bars" aria-label="Signal bars">
          <span style={{ height: '34%' }} />
          <span style={{ height: '52%' }} />
          <span style={{ height: '84%' }} />
          <span style={{ height: '49%' }} />
          <span style={{ height: '90%' }} />
          <span style={{ height: '72%' }} />
        </div>
      </div>

      <div className="floating-card card-one">
        <div className="mini-icon"><GitBranch size={14} /></div>
        <div>
          <span>Change impact</span>
          <strong>Modeled</strong>
        </div>
      </div>

      <div className="floating-card card-two">
        <div className="mini-icon"><Globe2 size={14} /></div>
        <div>
          <span>Knowledge graph</span>
          <strong>Connected</strong>
        </div>
      </div>

      <div className="floating-card card-three">
        <div className="mini-icon"><Sparkles size={14} /></div>
        <div>
          <span>Drag to rotate</span>
          <strong>Live twin</strong>
        </div>
      </div>
    </div>
  );
}
