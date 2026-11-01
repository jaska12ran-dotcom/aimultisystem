'use client';

import {
  AnimatePresence,
  motion,
  useInView,
  useMotionValue,
  useReducedMotion,
  useScroll,
  useSpring,
} from 'framer-motion';
import {
  ArrowRight,
  ArrowUpRight,
  Check,
  ChevronRight,
  CircleDot,
  Cpu,
  FileCode2,
  FlaskConical,
  GitBranch,
  Layers3,
  LockKeyhole,
  Network,
  Play,
  Radar,
  ScanLine,
  ShieldCheck,
  Sparkles,
  X,
  Zap,
} from 'lucide-react';
import Link from 'next/link';
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ComponentType,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from 'react';
import type { SceneSignal } from '../three/NextWorldScene';
import FloatingVideo from './FloatingVideo';
import HeroStage from './HeroStage';
import WorldBackdrop from './WorldBackdrop';

/* ── content ─────────────────────────────────────────────────────────── */

type Signal = {
  id: SceneSignal;
  index: string;
  name: string;
  title: string;
  copy: string;
  points: string[];
  video: string;
  poster: string;
  accent: string;
  metrics: Array<{ label: string; value: string }>;
};

const SIGNALS: Signal[] = [
  {
    id: 'architecture',
    index: '01',
    name: 'Architecture',
    title: 'See the whole system, not a folder tree.',
    copy: 'CodeTwin resolves files, symbols, routes and dependencies into a navigable graph. Boundaries, hotspots and dead zones become visible before you touch a line.',
    points: [
      'AST-aware file and symbol index',
      'Cross-language dependency graph',
      'Layered architecture and ownership view',
    ],
    video: '/media/orbital.mp4',
    poster: '/media/orbital-poster.jpg',
    accent: '#7df9ff',
    metrics: [
      { label: 'Graph edges', value: '4,820' },
      { label: 'Symbols', value: '1,284' },
      { label: 'Host writes', value: '0' },
    ],
  },
  {
    id: 'impact',
    index: '02',
    name: 'Impact',
    title: 'Trace a change before it breaks something.',
    copy: 'What-if simulation walks callers, routes, tests and contracts to estimate the blast radius of a patch — with the evidence attached to every call.',
    points: [
      'Breaking-change detection',
      'Regression test selection',
      'Migration and rollout constraints',
    ],
    video: '/media/nextworld.mp4',
    poster: '/media/nextworld-poster.jpg',
    accent: '#ffb47a',
    metrics: [
      { label: 'Affected files', value: '14' },
      { label: 'Test candidates', value: '63' },
      { label: 'Confidence', value: '0.91' },
    ],
  },
  {
    id: 'security',
    index: '03',
    name: 'Security',
    title: 'Risk, without the theatre.',
    copy: 'Deterministic dependency checks, secret scanning and authorization boundaries, mapped to the exact files and endpoints they affect. No network required for the baseline.',
    points: [
      'Dependency and CVE-range checks',
      'Secret and unsafe-pattern scanning',
      'Authorization surface mapping',
    ],
    video: '/media/signal.mp4',
    poster: '/media/signal-poster.jpg',
    accent: '#ff8f9f',
    metrics: [
      { label: 'Critical findings', value: '03' },
      { label: 'Packages checked', value: '212' },
      { label: 'Network calls', value: '00' },
    ],
  },
  {
    id: 'verification',
    index: '04',
    name: 'Verification',
    title: 'Proof, executed in a sandbox.',
    copy: 'Generated tests are validated in isolation, never asserted by confidence. Every verdict carries the command, the output and the environment it ran in.',
    points: [
      'Generated-test validation',
      'Sandbox-only execution',
      'Evidence-linked results',
    ],
    video: '/media/nextworld.mp4',
    poster: '/media/nextworld-poster.jpg',
    accent: '#b48cff',
    metrics: [
      { label: 'Sandboxed runs', value: '128' },
      { label: 'Host mutations', value: '0' },
      { label: 'Evidence artifacts', value: '100%' },
    ],
  },
];

const METRICS = [
  { value: 32, suffix: '', label: 'capabilities', detail: 'across seven intelligence systems' },
  { value: 59, suffix: '', label: 'API routes', detail: 'one versioned application surface' },
  { value: 54, suffix: '', label: 'repository endpoints', detail: 'scoped, inspectable operations' },
  { value: 6, suffix: '', label: 'health dimensions', detail: 'scored with file-level evidence' },
];

const CAPABILITIES: Array<{
  icon: ComponentType<{ size?: number; strokeWidth?: number }>;
  index: string;
  title: string;
  copy: string;
  tags: string[];
  span: string;
  tone: string;
}> = [
  {
    icon: Layers3,
    index: '01',
    title: 'Repository twin',
    copy: 'An AST-aware map of every file, symbol, route and relationship — indexed once, queried forever.',
    tags: ['AST', 'Graph RAG', 'Hotspots'],
    span: 'world-card-wide',
    tone: 'cyan',
  },
  {
    icon: GitBranch,
    index: '02',
    title: 'Impact simulator',
    copy: 'Model a rename, signature change or migration and watch the blast radius resolve across the graph.',
    tags: ['What-if', 'Breaking changes', 'Tests'],
    span: '',
    tone: 'amber',
  },
  {
    icon: ShieldCheck,
    index: '03',
    title: 'Security surface',
    copy: 'Dependency risk, secrets and authorization boundaries mapped to the exact code they touch.',
    tags: ['CVE ranges', 'Secrets', 'Auth'],
    span: '',
    tone: 'rose',
  },
  {
    icon: FlaskConical,
    index: '04',
    title: 'Verification sandbox',
    copy: 'Tests are generated, reviewed and executed in isolation. Evidence — not vibes — decides the verdict.',
    tags: ['Generated tests', 'Isolation', 'Evidence'],
    span: 'world-card-wide',
    tone: 'violet',
  },
  {
    icon: FileCode2,
    index: '05',
    title: 'Documentation drift',
    copy: 'Detect where docs, API references and examples have drifted from the implementation.',
    tags: ['Docs', 'Specs', 'Examples'],
    span: '',
    tone: 'blue',
  },
  {
    icon: Radar,
    index: '06',
    title: 'Health intelligence',
    copy: 'Technical debt, coverage, coupling and risk scored across six evidence-backed dimensions.',
    tags: ['Debt', 'Coverage', 'Risk'],
    span: '',
    tone: 'green',
  },
];

const FLOW = [
  {
    id: '01',
    title: 'Ingest',
    summary: 'Clone, upload or point at a local path.',
    detail:
      'The repository is indexed without executing its code. Source, tests, configuration and documentation enter the same evidence pipeline.',
    tags: ['Git', 'Zip', 'Local'],
  },
  {
    id: '02',
    title: 'Resolve',
    summary: 'Build the AST and relationship graph.',
    detail:
      'Files become symbols. Symbols become calls, routes, schemas, tests and docs. The twin holds both the structure and the semantics.',
    tags: ['AST', 'Graph', 'Symbols'],
  },
  {
    id: '03',
    title: 'Simulate',
    summary: 'Model the change before the commit.',
    detail:
      'Walk the impact frontier, select regression tests, surface breaking contracts and estimate performance and security consequences.',
    tags: ['What-if', 'Blast radius', 'Regression'],
  },
  {
    id: '04',
    title: 'Attest',
    summary: 'Prove the result in a sandbox.',
    detail:
      'Verification runs in isolation and attaches commands, output and file-level evidence to every verdict. No host mutation. No silent guesses.',
    tags: ['Sandbox', 'Evidence', 'Verdict'],
  },
];

const TICKER = [
  'AST-AWARE TWIN',
  'GRAPH RAG',
  'IMPACT SIMULATION',
  'SANDBOX VERIFICATION',
  'DOCUMENTATION DRIFT',
  'SECURITY SURFACE',
  '32 CAPABILITIES',
  'LOCAL-FIRST',
  'EVIDENCE-FIRST',
];

type LightboxState = {
  src: string;
  poster: string;
  label: string;
  detail?: string;
};

/* ── interactive primitives ──────────────────────────────────────────── */

function MagneticLink({
  href,
  children,
  className = '',
}: {
  href: string;
  children: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLAnchorElement>(null);
  const x = useMotionValue(0);
  const y = useMotionValue(0);
  const springX = useSpring(x, { stiffness: 220, damping: 18, mass: 0.3 });
  const springY = useSpring(y, { stiffness: 220, damping: 18, mass: 0.3 });

  const handleMove = (event: ReactPointerEvent<HTMLAnchorElement>) => {
    const element = ref.current;
    if (!element) return;
    const rect = element.getBoundingClientRect();
    x.set((event.clientX - (rect.left + rect.width / 2)) * 0.16);
    y.set((event.clientY - (rect.top + rect.height / 2)) * 0.2);
  };

  const reset = () => {
    x.set(0);
    y.set(0);
  };

  return (
    <motion.a
      ref={ref}
      href={href}
      className={className}
      style={{ x: springX, y: springY }}
      onPointerMove={handleMove}
      onPointerLeave={reset}
    >
      {children}
    </motion.a>
  );
}

function TiltCard({
  children,
  className = '',
}: {
  children: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);

  const handleMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const element = ref.current;
    if (!element) return;
    const rect = element.getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width - 0.5;
    const y = (event.clientY - rect.top) / rect.height - 0.5;
    element.style.setProperty('--card-rotate-x', `${(-y * 7).toFixed(2)}deg`);
    element.style.setProperty('--card-rotate-y', `${(x * 9).toFixed(2)}deg`);
    element.style.setProperty('--card-spot-x', `${((x + 0.5) * 100).toFixed(1)}%`);
    element.style.setProperty('--card-spot-y', `${((y + 0.5) * 100).toFixed(1)}%`);
  };

  const reset = () => {
    const element = ref.current;
    if (!element) return;
    element.style.setProperty('--card-rotate-x', '0deg');
    element.style.setProperty('--card-rotate-y', '0deg');
    element.style.setProperty('--card-spot-x', '50%');
    element.style.setProperty('--card-spot-y', '50%');
  };

  return (
    <div
      ref={ref}
      className={`world-tilt ${className}`}
      onPointerMove={handleMove}
      onPointerLeave={reset}
    >
      {children}
    </div>
  );
}

function RevealSection({
  children,
  className = '',
  delay = 0,
}: {
  children: ReactNode;
  className?: string;
  delay?: number;
}) {
  const reduced = useReducedMotion() ?? false;
  return (
    <motion.div
      className={className}
      initial={reduced ? { opacity: 1, y: 0 } : { opacity: 0, y: 22 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '-60px' }}
      transition={{
        duration: reduced ? 0 : 0.42,
        delay: reduced ? 0 : delay,
        ease: [0.16, 1, 0.3, 1],
      }}
    >
      {children}
    </motion.div>
  );
}

function useCountUp(target: number, active: boolean, duration = 1500) {
  const reduced = useReducedMotion() ?? false;
  const [value, setValue] = useState(0);

  useEffect(() => {
    if (!active) return;
    if (reduced) {
      return;
    }
    let frame = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const progress = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - progress, 3);
      setValue(Math.round(target * eased));
      if (progress < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [active, duration, reduced, target]);

  return reduced && active ? target : value;
}

function MetricNumber({ value, active }: { value: number; active: boolean }) {
  const number = useCountUp(value, active);
  return <span className="world-metric-number">{number}</span>;
}

function AmbientVideo({
  src,
  poster,
  className,
}: {
  src: string;
  poster: string;
  className?: string;
}) {
  const ref = useRef<HTMLVideoElement>(null);
  const reduced = useReducedMotion() ?? false;
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const video = ref.current;
    if (!video) return;
    const observer = new IntersectionObserver(
      ([entry]) => setVisible(entry.isIntersecting),
      { threshold: 0.15 },
    );
    observer.observe(video);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const video = ref.current;
    if (!video) return;
    if (visible && !reduced) void video.play().catch(() => {});
    else video.pause();
  }, [reduced, visible]);

  return (
    <video
      ref={ref}
      className={className}
      src={src}
      poster={poster}
      muted
      loop
      playsInline
      preload="metadata"
    />
  );
}

/* ── page ────────────────────────────────────────────────────────────── */

export default function WorldLanding() {
  const [activeSignal, setActiveSignal] = useState<SceneSignal>('architecture');
  const [scanning, setScanning] = useState(false);
  const [scanCount, setScanCount] = useState(0);
  const [activeStep, setActiveStep] = useState(0);
  const [lightbox, setLightbox] = useState<LightboxState | null>(null);
  const scanTimer = useRef<number | null>(null);
  const cursorRef = useRef<HTMLDivElement>(null);

  const { scrollYProgress } = useScroll();
  const progress = useSpring(scrollYProgress, {
    stiffness: 140,
    damping: 30,
    mass: 0.35,
  });

  const metricsRef = useRef<HTMLDivElement>(null);
  const metricsInView = useInView(metricsRef, { once: true, margin: '-12% 0px' });
  const flowRef = useRef<HTMLDivElement>(null);
  const { scrollYProgress: flowProgress } = useScroll({
    target: flowRef,
    offset: ['start 72%', 'end 62%'],
  });
  const flowScale = useSpring(flowProgress, {
    stiffness: 120,
    damping: 28,
    mass: 0.4,
  });

  const active = SIGNALS.find((signal) => signal.id === activeSignal) ?? SIGNALS[0];

  useEffect(() => {
    if (!lightbox) return;
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setLightbox(null);
    };
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    window.addEventListener('keydown', handleKey);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', handleKey);
    };
  }, [lightbox]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (window.matchMedia('(pointer: coarse)').matches) return;
    const element = cursorRef.current;
    if (!element) return;

    let x = window.innerWidth / 2;
    let y = window.innerHeight / 2;
    let targetX = x;
    let targetY = y;
    let frame = 0;

    const handleMove = (event: PointerEvent) => {
      targetX = event.clientX;
      targetY = event.clientY;
      element.dataset.visible = 'true';
      const target = event.target as HTMLElement | null;
      element.dataset.active = target?.closest('a, button, [data-cursor="active"]') ? 'true' : 'false';
    };
    const handleLeave = () => {
      element.dataset.visible = 'false';
    };
    const tick = () => {
      x += (targetX - x) * 0.2;
      y += (targetY - y) * 0.2;
      element.style.transform = `translate3d(${x - 18}px, ${y - 18}px, 0)`;
      frame = requestAnimationFrame(tick);
    };

    window.addEventListener('pointermove', handleMove, { passive: true });
    window.addEventListener('pointerleave', handleLeave);
    frame = requestAnimationFrame(tick);

    return () => {
      window.removeEventListener('pointermove', handleMove);
      window.removeEventListener('pointerleave', handleLeave);
      cancelAnimationFrame(frame);
    };
  }, []);

  useEffect(
    () => () => {
      if (scanTimer.current) window.clearTimeout(scanTimer.current);
    },
    [],
  );

  const runScan = useCallback(() => {
    if (scanning) return;
    setScanning(true);
    if (scanTimer.current) window.clearTimeout(scanTimer.current);
    scanTimer.current = window.setTimeout(() => {
      setScanning(false);
      setScanCount((count) => count + 1);
    }, 2400);
  }, [scanning]);

  const inspectSignal = useCallback((signal: SceneSignal) => {
    setActiveSignal(signal);
  }, []);

  return (
    <div className="world-page">
      <WorldBackdrop />
      <a className="world-skip" href="#signals">
        Skip to the interface
      </a>

      <motion.div className="world-scroll-progress" style={{ scaleX: progress }} />

      <header className="world-nav">
        <a href="#world" className="world-brand" aria-label="CodeTwin home">
          <span className="world-logo" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
          <span className="world-brand-text">
            CODETWIN
            <small>NEXTWORLD OS</small>
          </span>
        </a>

        <nav className="world-nav-links" aria-label="Primary navigation">
          <a href="#signals">Signals</a>
          <a href="#systems">Systems</a>
          <a href="#reels">Reels</a>
          <a href="#flow">Flow</a>
          <a href="#evidence">Evidence</a>
        </nav>

        <div className="world-nav-actions">
          <span className="world-nav-status">
            <i />
            INDEX ONLINE
          </span>
          <Link className="world-nav-cta" href="/app">
            Enter workspace
            <ArrowUpRight size={15} />
          </Link>
        </div>
      </header>

      <main>
        {/* ── hero ─────────────────────────────────────────────────── */}
        <section id="world" className="world-hero">
          <div className="world-hero-stage">
            <HeroStage
              active={activeSignal}
              scanning={scanning}
              onInspect={inspectSignal}
            />
          </div>

          <div className="world-hero-wash" aria-hidden="true" />

          <div className="world-hero-inner">
            <div className="world-hero-copy">
              <div className="world-eyebrow">
                <span className="world-pulse" />
                CODETWIN / NEXTWORLD INTERFACE
                <span className="world-eyebrow-version">v1.0</span>
              </div>

              <h1 className="world-hero-title">
                <span>Your codebase,</span>
                <span>
                  <em>rendered</em> alive.
                </span>
              </h1>

              <p className="world-hero-lead">
                A navigable 3D twin of your repository — architecture, impact,
                security and verification on one living surface. Explore the
                world. Then ask it what breaks.
              </p>

              <div className="world-hero-actions">
                <MagneticLink
                  className="world-button world-button-primary"
                  href="/app"
                >
                  <span>Enter the twin</span>
                  <ArrowRight size={17} />
                </MagneticLink>
                <button
                  type="button"
                  className="world-button world-button-ghost"
                  onClick={() => {
                    setActiveSignal('impact');
                    document.getElementById('signals')?.scrollIntoView({ behavior: 'smooth' });
                  }}
                >
                  <Play size={15} />
                  See the signals
                </button>
              </div>

              <div className="world-hero-chips" aria-label="Platform facts">
                <span>
                  <Sparkles size={13} /> 32 capabilities
                </span>
                <span>
                  <Network size={13} /> Graph RAG
                </span>
                <span>
                  <LockKeyhole size={13} /> Sandbox-first
                </span>
                <span>
                  <Cpu size={13} /> Local-first
                </span>
              </div>
            </div>

            <aside className="world-hero-hud" aria-label="World status">
              <div className="world-hud-head">
                <span>ACTIVE LENS</span>
                <i />
                <span>{scanning ? 'MAPPING' : 'SYNCED'}</span>
              </div>
              <strong className="world-hud-lens">{active.name}</strong>
              <p className="world-hud-copy">{active.title}</p>

              <div className="world-hud-readout">
                <div>
                  <span>symbols</span>
                  <b>{scanning ? '——' : '1,284'}</b>
                </div>
                <div>
                  <span>edges</span>
                  <b>{scanning ? '——' : '4,820'}</b>
                </div>
                <div>
                  <span>host writes</span>
                  <b>0</b>
                </div>
              </div>

              <button
                type="button"
                className={`world-scan ${scanning ? 'is-scanning' : ''}`}
                onClick={runScan}
                disabled={scanning}
              >
                <ScanLine size={16} />
                <span>
                  {scanning
                    ? 'Resolving the twin…'
                    : scanCount
                      ? 'Run spatial scan again'
                      : 'Run spatial scan'}
                </span>
                <i aria-hidden="true" />
              </button>

              <p className="world-hud-note">
                {scanning
                  ? 'Walking symbols, routes and relationships. No repository code is executed.'
                  : scanCount
                    ? 'Scan complete. 1,284 symbols · 4,820 edges · 0 host writes.'
                    : 'Drag the world to orbit · Click a floating screen to inspect.'}
              </p>
            </aside>
          </div>

          <FloatingVideo
            className="world-hero-video"
            src="/media/nextworld.mp4"
            poster="/media/nextworld-poster.jpg"
            label="WORLD RENDER / LIVE"
            detail="Orbital camera · twin core"
            accentColor="#7df9ff"
            onExpand={() =>
              setLightbox({
                src: '/media/nextworld.mp4',
                poster: '/media/nextworld-poster.jpg',
                label: 'WORLD RENDER / LIVE',
                detail: 'Procedural world render generated for the NextWorld interface.',
              })
            }
          />

          <div className="world-hero-foot">
            <a href="#signals" className="world-scroll-cue">
              <span className="world-scroll-line" />
              Scroll to enter the world
            </a>
            <div className="world-coords">
              <span>51.5072° N</span>
              <span>0.1276° W</span>
              <span>ORBITAL / 04</span>
            </div>
          </div>
        </section>

        {/* ── ticker ──────────────────────────────────────────────── */}
        <div className="world-ticker" aria-hidden="true">
          <div className="world-ticker-track">
            {[...TICKER, ...TICKER].map((item, index) => (
              <span key={`${item}-${index}`}>
                {item}
                <i />
              </span>
            ))}
          </div>
        </div>

        {/* ── signals ─────────────────────────────────────────────── */}
        <section id="signals" className="world-section world-signals">
          <div className="world-section-inner">
            <RevealSection>
              <div className="world-section-head">
                <div className="world-kicker">
                  <span>01</span>
                  THE LIVING INTERFACE
                </div>
                <h2>
                  The repository,
                  <br />
                  rendered <em>legible.</em>
                </h2>
                <p>
                  Four lenses, one twin. Move between architecture, impact,
                  security and verification without losing the thread — or the
                  evidence.
                </p>
              </div>

              <div ref={metricsRef} className="world-metrics">
                {METRICS.map((metric) => (
                  <div key={metric.label} className="world-metric">
                    <span className="world-metric-top">{metric.label}</span>
                    <MetricNumber value={metric.value} active={metricsInView} />
                    <span className="world-metric-detail">{metric.detail}</span>
                  </div>
                ))}
              </div>
            </RevealSection>

            <div className="world-console">
              <div
                className="world-console-tabs"
                role="tablist"
                aria-label="Intelligence lenses"
              >
                {SIGNALS.map((signal) => (
                  <button
                    key={signal.id}
                    type="button"
                    role="tab"
                    aria-selected={activeSignal === signal.id}
                    aria-controls="world-console-panel"
                    id={`world-tab-${signal.id}`}
                    className={`world-console-tab ${
                      activeSignal === signal.id ? 'is-active' : ''
                    }`}
                    onClick={() => setActiveSignal(signal.id)}
                  >
                    <span className="world-console-index">{signal.index}</span>
                    <span className="world-console-name">{signal.name}</span>
                    <span className="world-console-arrow">
                      <ChevronRight size={15} />
                    </span>
                  </button>
                ))}

                <div className="world-console-note">
                  <Zap size={14} />
                  Every lens resolves to files, symbols and evidence.
                </div>
              </div>

              <div
                id="world-console-panel"
                role="tabpanel"
                aria-labelledby={`world-tab-${activeSignal}`}
                className="world-console-stage"
              >
                <div className="world-console-screen" style={{ '--signal-accent': active.accent } as CSSProperties}>
                  <AmbientVideo
                    key={active.video}
                    src={active.video}
                    poster={active.poster}
                    className="world-console-video"
                  />
                  <div className="world-console-scanlines" aria-hidden="true" />
                  <div className="world-console-corners" aria-hidden="true">
                    <i />
                    <i />
                    <i />
                    <i />
                  </div>

                  <div className="world-console-hud">
                    <span>
                      <i /> LIVE / {active.name.toUpperCase()}
                    </span>
                    <span>TRACE 0{active.index}</span>
                  </div>

                  <div className="world-console-metrics">
                    {active.metrics.map((metric) => (
                      <div key={metric.label}>
                        <span>{metric.label}</span>
                        <b>{metric.value}</b>
                      </div>
                    ))}
                  </div>

                  <div className="world-console-reticle" aria-hidden="true">
                    <span />
                    <span />
                    <span />
                  </div>
                </div>

                <div className="world-console-detail">
                  <AnimatePresence mode="wait">
                    <motion.div
                      key={active.id}
                      initial={{ opacity: 0, y: 12 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -8 }}
                      transition={{ duration: 0.28 }}
                    >
                      <span className="world-detail-label">
                        LENS {active.index} / {active.name.toUpperCase()}
                      </span>
                      <h3>{active.title}</h3>
                      <p>{active.copy}</p>
                      <ul>
                        {active.points.map((point) => (
                          <li key={point}>
                            <Check size={14} />
                            {point}
                          </li>
                        ))}
                      </ul>
                      <Link href="/app" className="world-inline-link">
                        Open this lens in the workspace
                        <ArrowUpRight size={15} />
                      </Link>
                    </motion.div>
                  </AnimatePresence>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ── systems ─────────────────────────────────────────────── */}
        <section id="systems" className="world-section world-systems">
          <div className="world-section-inner">
            <RevealSection>
              <div className="world-section-head world-section-head-row">
                <div>
                  <div className="world-kicker">
                    <span>02</span>
                    SYSTEM SURFACE
                  </div>
                  <h2>
                    Every layer
                    <br />
                    of the <em>twin.</em>
                  </h2>
                </div>
                <p>
                  Not a chat window with a repository attached. A set of
                  deterministic systems that can be inspected, composed and
                  verified independently.
                </p>
              </div>
            </RevealSection>

            <div className="world-card-grid">
              {CAPABILITIES.map((capability) => {
                const Icon = capability.icon;
                return (
                  <TiltCard
                    key={capability.title}
                    className={`world-card world-card-${capability.tone} ${capability.span}`}
                  >
                    <div className="world-card-head">
                      <span className="world-card-icon">
                        <Icon size={20} strokeWidth={1.6} />
                      </span>
                      <span className="world-card-index">/{capability.index}</span>
                    </div>
                    <h3>{capability.title}</h3>
                    <p>{capability.copy}</p>
                    <div className="world-card-tags">
                      {capability.tags.map((tag) => (
                        <span key={tag}>{tag}</span>
                      ))}
                    </div>
                    <span className="world-card-glow" aria-hidden="true" />
                  </TiltCard>
                );
              })}
            </div>
          </div>
        </section>

        {/* ── reels ───────────────────────────────────────────────── */}
        <section id="reels" className="world-section world-reels">
          <div className="world-reels-portal" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>

          <div className="world-section-inner">
            <RevealSection>
              <div className="world-section-head world-section-head-row">
                <div>
                  <div className="world-kicker">
                    <span>03</span>
                    FLOATING FEEDS
                  </div>
                  <h2>
                    Signals that
                    <br />
                    follow <em>you.</em>
                  </h2>
                </div>
                <p>
                  Three live surfaces rendered as floating monitors. Hover to
                  bring them forward, open one to inspect the full feed.
                </p>
              </div>
            </RevealSection>

            <div className="world-reel-stack">
              <div className="world-reel world-reel-a">
                <FloatingVideo
                  src="/media/nextworld.mp4"
                  poster="/media/nextworld-poster.jpg"
                  label="WORLD / RENDER"
                  detail="Twin state · orbital"
                  accentColor="#7df9ff"
                  onExpand={() =>
                    setLightbox({
                      src: '/media/nextworld.mp4',
                      poster: '/media/nextworld-poster.jpg',
                      label: 'WORLD / RENDER',
                      detail: 'A procedural render of the twin world in motion.',
                    })
                  }
                />
              </div>
              <div className="world-reel world-reel-b">
                <FloatingVideo
                  src="/media/signal.mp4"
                  poster="/media/signal-poster.jpg"
                  label="SIGNAL / TRACE"
                  detail="Repository telemetry"
                  accentColor="#ff8f9f"
                  onExpand={() =>
                    setLightbox({
                      src: '/media/signal.mp4',
                      poster: '/media/signal-poster.jpg',
                      label: 'SIGNAL / TRACE',
                      detail: 'A live code and telemetry trace rendered as a signal feed.',
                    })
                  }
                />
              </div>
              <div className="world-reel world-reel-c">
                <FloatingVideo
                  src="/media/orbital.mp4"
                  poster="/media/orbital-poster.jpg"
                  label="GRAPH / ORBITAL"
                  detail="Symbols · relationships"
                  accentColor="#ffb47a"
                  onExpand={() =>
                    setLightbox({
                      src: '/media/orbital.mp4',
                      poster: '/media/orbital-poster.jpg',
                      label: 'GRAPH / ORBITAL',
                      detail: 'A rotating view of the repository relationship graph.',
                    })
                  }
                />
              </div>

              <div className="world-reel-shadow" aria-hidden="true" />
            </div>

            <div className="world-reel-meta">
              <span>
                <CircleDot size={13} />
                Three procedural loops · zero third-party footage
              </span>
              <span>Click any feed to inspect</span>
            </div>
          </div>
        </section>

        {/* ── flow ────────────────────────────────────────────────── */}
        <section id="flow" className="world-section world-flow">
          <div className="world-section-inner">
            <RevealSection>
              <div className="world-section-head">
                <div className="world-kicker">
                  <span>04</span>
                  THE PIPELINE
                </div>
                <h2>
                  From repository
                  <br />
                  to <em>receipt.</em>
                </h2>
                <p>
                  One evidence chain from ingest to verification. Click a stage
                  to inspect what happens inside it.
                </p>
              </div>
            </RevealSection>

            <div ref={flowRef} className="world-flow-map">
              <div className="world-flow-line" aria-hidden="true">
                <motion.span style={{ scaleX: flowScale }} />
              </div>

              <div className="world-flow-grid">
                {FLOW.map((step, index) => (
                  <button
                    key={step.id}
                    type="button"
                    className={`world-flow-step ${activeStep === index ? 'is-active' : ''}`}
                    onClick={() => setActiveStep(index)}
                    aria-expanded={activeStep === index}
                  >
                    <span className="world-flow-node">
                      <i />
                    </span>
                    <span className="world-flow-index">{step.id}</span>
                    <strong>{step.title}</strong>
                    <small>{step.summary}</small>
                    <span className="world-flow-tags">
                      {step.tags.map((tag) => (
                        <em key={tag}>{tag}</em>
                      ))}
                    </span>
                  </button>
                ))}
              </div>

              <div className="world-flow-detail">
                <AnimatePresence mode="wait">
                  <motion.div
                    key={FLOW[activeStep].id}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -8 }}
                    transition={{ duration: 0.25 }}
                  >
                    <span>
                      STAGE {FLOW[activeStep].id} / {FLOW[activeStep].title.toUpperCase()}
                    </span>
                    <p>{FLOW[activeStep].detail}</p>
                  </motion.div>
                </AnimatePresence>
                <Link href="/app" className="world-inline-link">
                  Run the pipeline
                  <ArrowRight size={15} />
                </Link>
              </div>
            </div>
          </div>
        </section>

        {/* ── evidence ────────────────────────────────────────────── */}
        <section id="evidence" className="world-section world-evidence">
          <div className="world-section-inner">
            <div className="world-evidence-grid">
              <RevealSection className="world-evidence-copy">
                <div className="world-kicker">
                  <span>05</span>
                  OPERATING PRINCIPLES
                </div>
                <h2>
                  Built for
                  <br />
                  <em>evidence.</em>
                </h2>
                <p>
                  The twin is useful only if you can trust it. Every capability
                  is designed around inspectable inputs, isolated execution and
                  explicit uncertainty.
                </p>

                <ul className="world-principles">
                  <li>
                    <span>01</span>
                    <div>
                      <strong>No LLM-only claims.</strong>
                      <p>Findings link back to a file, symbol, command or test.</p>
                    </div>
                  </li>
                  <li>
                    <span>02</span>
                    <div>
                      <strong>No host mutation.</strong>
                      <p>Verification runs inside an isolated sandbox, never against your machine.</p>
                    </div>
                  </li>
                  <li>
                    <span>03</span>
                    <div>
                      <strong>No silent guesses.</strong>
                      <p>Unknowns stay labeled as unknowns until evidence resolves them.</p>
                    </div>
                  </li>
                </ul>

                <div className="world-evidence-stats">
                  <div>
                    <b>0</b>
                    <span>repository code executed during indexing</span>
                  </div>
                  <div>
                    <b>100%</b>
                    <span>of verdicts carry a command and output</span>
                  </div>
                </div>
              </RevealSection>

              <div className="world-terminal" aria-label="Example verification evidence">
                <div className="world-terminal-head">
                  <span className="world-terminal-dots" aria-hidden="true">
                    <i />
                    <i />
                    <i />
                  </span>
                  <span>VERIFICATION / EVIDENCE TRACE</span>
                  <span className="world-terminal-live">
                    <i /> REC
                  </span>
                </div>
                <div className="world-terminal-body">
                  <p>
                    <span className="world-terminal-prompt">twin@codetwin</span>
                    <span className="world-terminal-path">~/repo</span>
                    <span className="world-terminal-command"> verify --sandbox --scope impact</span>
                  </p>
                  <p className="world-terminal-muted">› resolving impact frontier…</p>
                  <p className="world-terminal-muted">› selected 63 regression candidates</p>
                  <p className="world-terminal-ok">✓ sandbox prepared (network disabled)</p>
                  <p className="world-terminal-ok">✓ 61 passed · 2 skipped · 0 failed</p>
                  <p className="world-terminal-ok">✓ evidence bundle sealed · 4.2 MB</p>
                  <p className="world-terminal-muted">› host writes: 0 · mutations: 0</p>
                  <p className="world-terminal-command">
                    <span className="world-terminal-prompt">twin@codetwin</span>
                    <span className="world-terminal-path">~/repo</span> cat verdict.json
                  </p>
                  <pre>
{`{
  "verdict": "verified_with_evidence",
  "scope": "impact",
  "confidence": 0.91,
  "artifacts": 18,
  "host_mutations": 0
}`}
                  </pre>
                  <p className="world-terminal-cursor" aria-hidden="true">
                    <span>▍</span>
                  </p>
                </div>
                <div className="world-terminal-foot">
                  <span>TRACE / 7F3A-91C2</span>
                  <span>SIGNED</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ── launch ──────────────────────────────────────────────── */}
        <section id="launch" className="world-section world-launch">
          <div className="world-section-inner">
            <div className="world-launch-panel">
              <div className="world-launch-portal" aria-hidden="true">
                <span className="world-launch-ring world-launch-ring-a" />
                <span className="world-launch-ring world-launch-ring-b" />
                <span className="world-launch-ring world-launch-ring-c" />
                <span className="world-launch-core">
                  <AmbientVideo
                    src="/media/nextworld.mp4"
                    poster="/media/nextworld-poster.jpg"
                    className="world-launch-video"
                  />
                </span>
              </div>

              <RevealSection className="world-launch-copy">
                <div className="world-kicker">
                  <span>06</span>
                  ENTER THE WORLD
                </div>
                <h2>
                  Open the
                  <br />
                  <em>twin.</em>
                </h2>
                <p>
                  Point it at a repository and walk the surface. Every claim
                  stays connected to the code behind it.
                </p>
                <div className="world-launch-actions">
                  <Link href="/app" className="world-button world-button-primary">
                    <span>Launch workspace</span>
                    <ArrowUpRight size={17} />
                  </Link>
                  <a href="#world" className="world-button world-button-ghost">
                    <Play size={14} />
                    Replay the world
                  </a>
                </div>
              </RevealSection>

              <div className="world-launch-spec">
                <div>
                  <span>BUILD</span>
                  <b>NEXTWORLD / 1.0</b>
                </div>
                <div>
                  <span>STATUS</span>
                  <b className="world-launch-status">ALL SYSTEMS NOMINAL</b>
                </div>
                <div>
                  <span>SURFACE</span>
                  <b>59 ROUTES / 32 CAPABILITIES</b>
                </div>
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="world-footer">
        <div className="world-footer-main">
          <div className="world-footer-brand">
            <span className="world-logo" aria-hidden="true">
              <i />
              <i />
              <i />
            </span>
            <div>
              <strong>CODETWIN</strong>
              <p>Repository intelligence, rendered as a world.</p>
            </div>
          </div>

          <div className="world-footer-links">
            <div>
              <span>EXPLORE</span>
              <a href="#signals">Signals</a>
              <a href="#systems">Systems</a>
              <a href="#reels">Reels</a>
              <a href="#evidence">Evidence</a>
            </div>
            <div>
              <span>WORKSPACE</span>
              <Link href="/app">Overview</Link>
              <Link href="/app">Graph</Link>
              <Link href="/app">Security</Link>
              <Link href="/app">What-if</Link>
            </div>
            <div>
              <span>SYSTEM</span>
              <span className="world-footer-muted">AST index / online</span>
              <span className="world-footer-muted">Sandbox / isolated</span>
              <span className="world-footer-muted">Network / disabled</span>
            </div>
          </div>
        </div>

        <div className="world-footer-base">
          <span>© 2026 CODETWIN / NEXTWORLD INTERFACE</span>
          <span>DESIGNED FOR EVIDENCE · BUILT FOR THE WHOLE REPOSITORY</span>
          <span>
            <i />
            SYSTEMS NOMINAL
          </span>
        </div>
      </footer>

      <AnimatePresence>
        {lightbox && (
          <motion.div
            className="world-lightbox"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            role="dialog"
            aria-modal="true"
            aria-label={`${lightbox.label} large view`}
            onClick={() => setLightbox(null)}
          >
            <motion.div
              className="world-lightbox-panel"
              initial={{ y: 24, scale: 0.97, opacity: 0 }}
              animate={{ y: 0, scale: 1, opacity: 1 }}
              exit={{ y: 16, scale: 0.98, opacity: 0 }}
              transition={{ type: 'spring', stiffness: 220, damping: 26 }}
              onClick={(event) => event.stopPropagation()}
            >
              <div className="world-lightbox-head">
                <span>
                  <i /> {lightbox.label}
                </span>
                <button type="button" onClick={() => setLightbox(null)} aria-label="Close video">
                  <X size={18} />
                </button>
              </div>

              <div className="world-lightbox-media">
                <video
                  src={lightbox.src}
                  poster={lightbox.poster}
                  autoPlay
                  controls
                  loop
                  playsInline
                />
                <span className="world-lightbox-scanlines" aria-hidden="true" />
              </div>

              <div className="world-lightbox-foot">
                <p>{lightbox.detail}</p>
                <span>PROCEDURAL / NO THIRD-PARTY FOOTAGE</span>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
