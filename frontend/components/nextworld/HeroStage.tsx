'use client';

import dynamic from 'next/dynamic';
import {
  Component,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from 'react';
import { useReducedMotion } from 'framer-motion';
import type { SceneSignal } from '../three/NextWorldScene';

const NextWorldScene = dynamic(() => import('../three/NextWorldScene'), {
  ssr: false,
  loading: () => <StageFallback />,
});

const subscribeNever = () => () => {};
let webglCache: boolean | null = null;

function supportsWebGL() {
  if (webglCache !== null) return webglCache;
  try {
    const canvas = document.createElement('canvas');
    webglCache = Boolean(
      canvas.getContext('webgl2') || canvas.getContext('webgl'),
    );
  } catch {
    webglCache = false;
  }
  return webglCache;
}

interface HeroStageProps {
  active: SceneSignal;
  scanning: boolean;
  onInspect: (signal: SceneSignal) => void;
}

class SceneBoundary extends Component<
  { children: ReactNode; fallback: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

function StageFallback() {
  const reduced = useReducedMotion();

  return (
    <div className="world-stage-fallback" aria-hidden="true">
      <video
        className="world-stage-fallback-video"
        src="/media/nextworld.mp4"
        poster="/media/nextworld-poster.jpg"
        autoPlay={!reduced}
        muted
        loop
        playsInline
        preload="metadata"
      />
      <div className="world-stage-fallback-screen" />
      <div className="world-stage-fallback-ring world-stage-fallback-ring-a" />
      <div className="world-stage-fallback-ring world-stage-fallback-ring-b" />
      <div className="world-stage-fallback-core" />
    </div>
  );
}

export default function HeroStage({ active, scanning, onInspect }: HeroStageProps) {
  const webgl = useSyncExternalStore(subscribeNever, supportsWebGL, () => false);
  const reduced = useReducedMotion() ?? false;
  const hostRef = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const observer = new IntersectionObserver(
      ([entry]) => setVisible(entry.isIntersecting),
      { threshold: 0.02 },
    );
    observer.observe(host);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={hostRef} className="world-stage">
      {webgl ? (
        <SceneBoundary fallback={<StageFallback />}>
          <NextWorldScene
            active={active}
            scanning={scanning}
            reduced={reduced}
            paused={!visible}
            onInspect={onInspect}
          />
        </SceneBoundary>
      ) : (
        <StageFallback />
      )}

      <div className="world-stage-chrome" aria-hidden="true">
        <span className="world-stage-corner world-stage-corner-tl" />
        <span className="world-stage-corner world-stage-corner-tr" />
        <span className="world-stage-corner world-stage-corner-bl" />
        <span className="world-stage-corner world-stage-corner-br" />

        <div className="world-stage-axis world-stage-axis-y">
          <span>+Y / 02.44</span>
          <span>+Y / 01.12</span>
          <span>+Y / 00.00</span>
        </div>

        <div className="world-stage-axis world-stage-axis-x">
          <span>−X</span>
          <i />
          <span>+X</span>
        </div>

        <div className="world-stage-telemetry">
          <span className="world-stage-live">
            <i />
            LIVE RENDER
          </span>
          <span>CAM / ORBITAL-04</span>
          <span>60 FPS</span>
        </div>
      </div>
    </div>
  );
}
