'use client';

import { useReducedMotion } from 'framer-motion';
import { Maximize2, Pause, Play } from 'lucide-react';
import {
  useEffect,
  useRef,
  useState,
  useCallback,
  type PointerEvent as ReactPointerEvent,
} from 'react';

export interface FloatingVideoProps {
  src: string;
  poster: string;
  label: string;
  detail?: string;
  className?: string;
  aspect?: string;
  onExpand?: () => void;
  showCaption?: boolean;
  autoTilt?: boolean;
  accentColor?: string;
}

/* ── Main component ───────────────────────────────────────────────────── */
export default function FloatingVideo({
  src,
  poster,
  label,
  detail,
  className = '',
  aspect = '16 / 10',
  onExpand,
  showCaption = true,
  autoTilt = true,
  accentColor = '#7df9ff',
}: FloatingVideoProps) {
  const frameRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const reduced = useReducedMotion() ?? false;
  const [playing, setPlaying] = useState(!reduced);
  const [inView, setInView] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [timeCode, setTimeCode] = useState('00:00:00');
  const timerRef = useRef<number | null>(null);
  const secondsRef = useRef(0);

  // Timecode counter
  useEffect(() => {
    if (!playing) {
      if (timerRef.current) clearInterval(timerRef.current);
      return;
    }
    timerRef.current = window.setInterval(() => {
      secondsRef.current += 1;
      const h = Math.floor(secondsRef.current / 3600);
      const m = Math.floor((secondsRef.current % 3600) / 60);
      const s = secondsRef.current % 60;
      setTimeCode(
        `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`,
      );
    }, 1000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [playing]);

  // Intersection observer
  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    const observer = new IntersectionObserver(
      ([entry]) => setInView(entry.isIntersecting),
      { threshold: 0.12 },
    );
    observer.observe(frame);
    return () => observer.disconnect();
  }, []);

  // Play/pause
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    if (inView && playing && !reduced) {
      void video.play().catch(() => setPlaying(false));
    } else {
      video.pause();
    }
  }, [inView, playing, reduced]);

  // 3D tilt + glare tracking
  const handlePointerMove = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const frame = frameRef.current;
    if (!frame || reduced) return;
    const rect = frame.getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width - 0.5;
    const y = (event.clientY - rect.top) / rect.height - 0.5;
    frame.style.setProperty('--video-tilt-x', `${(-y * 10).toFixed(2)}deg`);
    frame.style.setProperty('--video-tilt-y', `${(x * 14).toFixed(2)}deg`);
    frame.style.setProperty('--video-glare-x', `${((x + 0.5) * 100).toFixed(1)}%`);
    frame.style.setProperty('--video-glare-y', `${((y + 0.5) * 100).toFixed(1)}%`);
    // Depth parallax: move shadow
    frame.style.setProperty('--video-shadow-x', `${(x * 20).toFixed(1)}px`);
    frame.style.setProperty('--video-shadow-y', `${(y * 20 + 8).toFixed(1)}px`);
  }, [reduced]);

  const handlePointerLeave = useCallback(() => {
    const frame = frameRef.current;
    setHovered(false);
    if (!frame) return;
    frame.style.setProperty('--video-tilt-x', '0deg');
    frame.style.setProperty('--video-tilt-y', '0deg');
    frame.style.setProperty('--video-glare-x', '50%');
    frame.style.setProperty('--video-glare-y', '50%');
    frame.style.setProperty('--video-shadow-x', '0px');
    frame.style.setProperty('--video-shadow-y', '8px');
  }, []);

  const togglePlayback = () => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) {
      void video.play().then(() => setPlaying(true)).catch(() => {});
    } else {
      video.pause();
      setPlaying(false);
    }
  };

  return (
    <figure
      ref={frameRef}
      className={`world-video ${autoTilt ? 'world-video-tilt' : ''} ${
        hovered ? 'is-hovered' : ''
      } ${className}`}
      style={{
        aspectRatio: aspect,
        '--video-accent': accentColor,
      } as React.CSSProperties}
      onPointerMove={handlePointerMove}
      onPointerEnter={() => setHovered(true)}
      onPointerLeave={handlePointerLeave}
    >
      <div className="world-video-frame">
        <div className="world-video-window">
          <video
            ref={videoRef}
            className="world-video-media"
            src={src}
            poster={poster}
            muted
            loop
            playsInline
            preload="metadata"
            aria-label={label}
          />

          {/* Clean realistic screen glass glare */}
          <span className="world-video-glare" aria-hidden="true" />

          {/* Top chrome bar */}
          <div className="world-video-chrome">
            <span className="world-video-live">
              <i style={{ background: accentColor, boxShadow: `0 0 6px ${accentColor}` }} />
              LIVE PREVIEW
            </span>
            <span className="world-video-timecode">{timeCode}</span>
          </div>

          {/* Expand / playback toggle */}
          <button
            type="button"
            className="world-video-open"
            aria-label={onExpand ? `Open ${label} in a larger view` : `Toggle ${label}`}
            onClick={onExpand ?? togglePlayback}
          >
            {onExpand ? <Maximize2 size={14} /> : playing ? <Pause size={14} /> : <Play size={14} />}
          </button>

          {showCaption && (
            <figcaption className="world-video-caption">
              <span>{label}</span>
              {detail && <small>{detail}</small>}
            </figcaption>
          )}
        </div>
      </div>

      {/* Realistic soft ambient shadow */}
      <span className="world-video-shadow" aria-hidden="true" />
    </figure>
  );
}
