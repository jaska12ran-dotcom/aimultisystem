'use client';

import {
  ArrowRight,
  ChevronRight,
  Globe2,
  Layers3,
  Play,
  Radar,
  Shield,
  TestTube2,
  Workflow,
} from 'lucide-react';
import {
  motion,
  useMotionValue,
  useReducedMotion,
  useSpring,
} from 'framer-motion';
import { type ReactNode } from 'react';
import HeroScene from './HeroScene';

const navItems = [
  { label: 'Overview', href: '#overview' },
  { label: 'Intelligence', href: '#system' },
  { label: 'Graph', href: '#graph' },
  { label: 'Security', href: '#security' },
  { label: 'What-if', href: '#whatif' },
];

const metrics = [
  { value: 'AST-aware', label: 'Repository twin', detail: 'Live semantic understanding of the codebase' },
  { value: 'Graph RAG', label: 'Entity mapping', detail: 'Relationships across symbols, modules, and flows' },
  { value: 'Verified', label: 'Sandbox testing', detail: 'Evidence-based validation before release' },
  { value: 'Drift-safe', label: 'Documentation', detail: 'Detect mismatch between docs and implementation' },
];

const features = [
  {
    title: 'Repository intelligence',
    copy: 'Map architecture, ownership, dependencies, and code trajectories with a living repository model that updates as the system evolves.',
    icon: Layers3,
    tone: 'violet',
  },
  {
    title: 'Knowledge graph',
    copy: 'Connect files, functions, services, modules, and business rules into a navigable graph that reveals hidden coupling and impact paths.',
    icon: Radar,
    tone: 'cyan',
  },
  {
    title: 'Security & risk',
    copy: 'Surface sensitive flows, risky change patterns, and high-impact exposures before they reach production environments.',
    icon: Shield,
    tone: 'emerald',
  },
  {
    title: 'What-if simulator',
    copy: 'Model proposed changes, inspect likely effects, and understand blast radius across the repository before editing code.',
    icon: Workflow,
    tone: 'violet',
  },
  {
    title: 'Documentation drift',
    copy: 'Compare implementation with docs and onboarding material to keep architecture guidance accurate and actionable for teams.',
    icon: Globe2,
    tone: 'cyan',
  },
  {
    title: 'Verification engine',
    copy: 'Combine generated tests, regression signals, and sandbox execution into a more trustworthy release decision process.',
    icon: TestTube2,
    tone: 'emerald',
  },
];

const showcase = [
  {
    title: 'Architecture intelligence',
    subtitle: 'System map',
    body: 'Visualize repository structure, graph relationships, and modules in a navigable layer designed for technical clarity.',
    accent: 'violet',
  },
  {
    title: 'Change impact analysis',
    subtitle: 'Risk lens',
    body: 'Trace likely consequences of edits across code paths, deployments, and hidden service dependencies before changes ship.',
    accent: 'cyan',
  },
  {
    title: 'Evidence-based validation',
    subtitle: 'Release confidence',
    body: 'Tie documentation, tests, security checks, and code behavior together so engineering teams can act with confidence.',
    accent: 'emerald',
  },
];

const process = [
  { label: '1. Map', detail: 'Index repository structure, symbol context, and logic flow.' },
  { label: '2. Assess', detail: 'Run graph, security, git, and documentation analysis across the system.' },
  { label: '3. Verify', detail: 'Validate changes in a sandboxed loop before confident release decisions.' },
];

const feedback = [
  { quote: 'The platform helps the team see system risk before a change becomes a production issue.', author: 'Engineering leadership review' },
  { quote: 'The graph and verification layers make architecture decisions feel concrete instead of abstract.', author: 'Architecture review signal' },
];

/* ── Motion helpers ─────────────────────────────────────────────────────── */

const EASE = [0.22, 1, 0.36, 1] as const;

/** Scroll-triggered entrance; collapses to a quick fade for reduced-motion users. */
function FadeIn({ children, delay = 0, className }: { children: ReactNode; delay?: number; className?: string }) {
  const reduced = useReducedMotion();
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y: reduced ? 0 : 28 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '-60px' }}
      transition={reduced ? { duration: 0.2 } : { duration: 0.65, delay, ease: EASE }}
    >
      {children}
    </motion.div>
  );
}

/** Glass panel with 3D hover tilt driven by pointer position. */
function TiltCard({ children, className }: { children: ReactNode; className?: string }) {
  const reduced = useReducedMotion();
  const rotateX = useMotionValue(0);
  const rotateY = useMotionValue(0);
  const springX = useSpring(rotateX, { stiffness: 180, damping: 18 });
  const springY = useSpring(rotateY, { stiffness: 180, damping: 18 });

  const handleMove = (event: React.PointerEvent<HTMLElement>) => {
    if (reduced || event.pointerType !== 'mouse') return;
    const rect = event.currentTarget.getBoundingClientRect();
    const nx = (event.clientX - rect.left) / rect.width - 0.5;
    const ny = (event.clientY - rect.top) / rect.height - 0.5;
    rotateY.set(nx * 7);
    rotateX.set(-ny * 6);
  };

  const reset = () => {
    rotateX.set(0);
    rotateY.set(0);
  };

  return (
    <motion.div
      className={className}
      onPointerMove={handleMove}
      onPointerLeave={reset}
      style={reduced ? undefined : { rotateX: springX, rotateY: springY, transformPerspective: 900 }}
    >
      {children}
    </motion.div>
  );
}

export default function CinematicLanding() {
  const reduced = useReducedMotion();

  const heroStagger = {
    hidden: {},
    show: { transition: { staggerChildren: 0.12, delayChildren: 0.1 } },
  };
  const heroItem = {
    hidden: { opacity: 0, y: reduced ? 0 : 26 },
    show: { opacity: 1, y: 0, transition: { duration: 0.7, ease: EASE } },
  };

  return (
    <main className="landing-shell">
      <div className="mesh-backdrop" aria-hidden="true" />

      <header className="topbar" id="overview">
        <div className="brand-wrap">
          <div className="brand-mark">C</div>
          <div>
            <p className="brand-name">CodeTwin</p>
            <p className="brand-tag">AI repository intelligence</p>
          </div>
        </div>

        <nav className="main-nav" aria-label="Main navigation">
          {navItems.map((item) => (
            <a key={item.label} href={item.href}>
              {item.label}
            </a>
          ))}
        </nav>

        <a className="nav-cta" href="/app">
          Launch app
        </a>
      </header>

      <section className="hero-panel">
        <div className="hero-copy">
          <motion.div variants={heroStagger} initial="hidden" animate="show">
            <motion.span className="eyebrow" variants={heroItem}>AI SOFTWARE INTELLIGENCE</motion.span>
            <motion.h1 variants={heroItem}>
              Turn your <span className="gradient-text">codebase</span> into a living, legible system.
            </motion.h1>
            <motion.p variants={heroItem}>
              CodeTwin fuses repository intelligence, graph analysis, security checks, documentation drift detection,
              what-if simulation, and verified test execution into one unified operating layer for modern engineering teams.
            </motion.p>

            <motion.div className="cta-row" variants={heroItem}>
              <a className="primary-cta" href="/app">
                Launch the app
                <ArrowRight size={16} />
              </a>
              <a className="secondary-cta" href="#system">
                <Play size={15} />
                View intelligence stack
              </a>
            </motion.div>

            <motion.div className="proof-strip" variants={heroItem} aria-label="System capabilities">
              <div>
                <span className="proof-label">Signals</span>
                <strong>Repository</strong>
              </div>
              <div>
                <span className="proof-label">Insight</span>
                <strong>Graph</strong>
              </div>
              <div>
                <span className="proof-label">Trust</span>
                <strong>Verified</strong>
              </div>
            </motion.div>
          </motion.div>
        </div>

        {/* Interactive 3D twin (lazy-loaded, WebGL fallback built in). */}
        <HeroScene />
      </section>

      <motion.a
        href="#system"
        className="scroll-hint"
        aria-label="Scroll to the intelligence stack"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 1.4, duration: 0.6 }}
      >
        <motion.span
          aria-hidden="true"
          animate={reduced ? undefined : { y: [0, 7, 0] }}
          transition={reduced ? undefined : { repeat: Infinity, duration: 1.9, ease: 'easeInOut' }}
        />
      </motion.a>

      <section className="metrics-grid" aria-label="Platform capabilities">
        {metrics.map((metric, index) => (
          <FadeIn key={metric.label} delay={index * 0.08}>
            <TiltCard className="metric-card glass-panel">
              <span className="metric-value">{metric.value}</span>
              <span className="metric-label">{metric.label}</span>
              <small>{metric.detail}</small>
            </TiltCard>
          </FadeIn>
        ))}
      </section>

      <section id="system" className="content-section">
        <FadeIn>
          <div className="section-heading">
            <span className="eyebrow">INTELLIGENCE STACK</span>
            <h2>An operating system for engineering clarity.</h2>
          </div>
        </FadeIn>

        <div className="feature-grid">
          {features.map(({ title, copy, icon: Icon, tone }, index) => (
            <FadeIn key={title} delay={index * 0.07}>
              <TiltCard className="feature-card glass-panel">
                <div className={`feature-icon ${tone}`}>
                  <Icon size={18} />
                </div>
                <h3>{title}</h3>
                <p>{copy}</p>
              </TiltCard>
            </FadeIn>
          ))}
        </div>
      </section>

      <section id="graph" className="content-section">
        <FadeIn>
          <div className="section-heading">
            <span className="eyebrow">SYSTEM VIEW</span>
            <h2>See the repository as a connected system, not a folder tree.</h2>
          </div>
        </FadeIn>

        <div className="showcase-grid">
          {showcase.map((item, index) => (
            <FadeIn key={item.title} delay={index * 0.09}>
              <TiltCard className={`showcase-card glass-panel accent-${item.accent}`}>
                <div className="showcase-topline">
                  <span>{item.subtitle}</span>
                  <ChevronRight size={16} />
                </div>
                <h3>{item.title}</h3>
                <p>{item.body}</p>
                <div className="showcase-visual" aria-hidden="true">
                  <span className="visual-pill pill-one" />
                  <span className="visual-pill pill-two" />
                  <span className="visual-pill pill-three" />
                </div>
              </TiltCard>
            </FadeIn>
          ))}
        </div>
      </section>

      <section className="content-section process-section" id="whatif">
        <FadeIn>
          <div className="section-heading">
            <span className="eyebrow">DECISION FLOW</span>
            <h2>From signal to action, with evidence at every step.</h2>
          </div>
        </FadeIn>

        <div className="process-grid">
          {process.map((step, index) => (
            <FadeIn key={step.label} delay={index * 0.09}>
              <TiltCard className="process-card glass-panel">
                <span>{step.label}</span>
                <p>{step.detail}</p>
              </TiltCard>
            </FadeIn>
          ))}
        </div>
      </section>

      <section className="content-section testimonial-section" id="security" aria-label="Platform observations">
        <FadeIn>
          <div className="section-heading">
            <span className="eyebrow">SYSTEM SIGNALS</span>
            <h2>Clear signals for architecture, risk, and release confidence.</h2>
          </div>
        </FadeIn>

        <div className="testimonial-grid">
          {feedback.map((review, index) => (
            <FadeIn key={review.author} delay={index * 0.1}>
              <TiltCard className="testimonial-card glass-panel">
                <p>“{review.quote}”</p>
                <footer>{review.author}</footer>
              </TiltCard>
            </FadeIn>
          ))}
        </div>
      </section>

      <FadeIn>
        <section id="launch" className="cta-panel glass-panel">
          <div>
            <span className="eyebrow">READY TO OPERATE</span>
            <h2>Build with repository intelligence, not blind edits.</h2>
          </div>
          <a className="primary-cta" href="/app">
            Open the workspace
            <ArrowRight size={16} />
          </a>
        </section>
      </FadeIn>

      <footer className="site-footer">
        <div className="brand-wrap">
          <div className="brand-mark">C</div>
          <div>
            <p className="brand-name">CodeTwin</p>
          </div>
        </div>

        <div className="footer-links">
          <a href="#overview">Overview</a>
          <a href="#system">Intelligence</a>
          <a href="#graph">Graph</a>
          <a href="#launch">Launch</a>
        </div>
      </footer>
    </main>
  );
}
