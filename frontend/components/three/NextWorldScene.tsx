'use client';

/* eslint-disable react-hooks/immutability, react-hooks/set-state-in-effect -- Three.js objects and shader uniforms are intentionally mutated inside frame callbacks and asset subscriptions. */

import {
  Environment,
  Float,
  Grid,
  Lightformer,
  MeshReflectorMaterial,
  RoundedBox,
  Sparkles,
  Stars,
  useCursor,
} from '@react-three/drei';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import * as THREE from 'three';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { ShaderPass } from 'three/examples/jsm/postprocessing/ShaderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';

export type SceneSignal = 'architecture' | 'impact' | 'security' | 'verification';

export interface NextWorldSceneProps {
  active?: SceneSignal;
  scanning?: boolean;
  reduced?: boolean;
  paused?: boolean;
  onInspect?: (signal: SceneSignal) => void;
}

/* ── signal palette definitions ──────────────────────────────────────── */

const SIGNAL_PALETTES: Record<SceneSignal, { primary: string; secondary: string; accent: string }> = {
  architecture: { primary: '#7df9ff', secondary: '#00e5ff', accent: '#b3fdff' },
  impact:       { primary: '#ffb47a', secondary: '#ff8c42', accent: '#ffd4a8' },
  security:     { primary: '#ff8f9f', secondary: '#ff4d6a', accent: '#ffcdd4' },
  verification: { primary: '#a78bfa', secondary: '#7c3aed', accent: '#ddd6fe' },
};

/* ── deterministic random ─────────────────────────────────────────────── */

function mulberry32(seed: number) {
  return () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/* ── shared assets ────────────────────────────────────────────────────── */

function useGlowTexture() {
  const texture = useMemo(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 64;
    canvas.height = 64;
    const ctx = canvas.getContext('2d');
    if (ctx) {
      const gradient = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
      gradient.addColorStop(0, 'rgba(255,255,255,1)');
      gradient.addColorStop(0.3, 'rgba(168,255,246,0.9)');
      gradient.addColorStop(0.66, 'rgba(75,210,220,0.28)');
      gradient.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = gradient;
      ctx.fillRect(0, 0, 64, 64);
    }
    const result = new THREE.CanvasTexture(canvas);
    result.colorSpace = THREE.SRGBColorSpace;
    return result;
  }, []);

  useEffect(() => () => texture.dispose(), [texture]);
  return texture;
}

function useVideoTexture(src: string) {
  const [texture, setTexture] = useState<THREE.VideoTexture | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const video = document.createElement('video');
    video.src = src;
    video.muted = true;
    video.loop = true;
    video.autoplay = true;
    video.playsInline = true;
    video.preload = 'auto';
    video.crossOrigin = 'anonymous';

    const result = new THREE.VideoTexture(video);
    result.colorSpace = THREE.SRGBColorSpace;
    result.minFilter = THREE.LinearFilter;
    result.magFilter = THREE.LinearFilter;
    result.generateMipmaps = false;

    const markReady = () => {
      setReady(true);
      void video.play().catch(() => {});
    };

    video.addEventListener('loadeddata', markReady, { once: true });
    void video.play().catch(() => {});
    setTexture(result);

    return () => {
      video.removeEventListener('loadeddata', markReady);
      video.pause();
      video.removeAttribute('src');
      video.load();
      result.dispose();
      setReady(false);
      setTexture(null);
    };
  }, [src]);

  return { texture, ready };
}

/* ── post processing ──────────────────────────────────────────────────── */

/** Combined grain + chromatic-aberration shader — aberration strength pulses
 *  via uIntensity which is driven externally when scanning is active. */
const GrainShader = {
  uniforms: {
    tDiffuse:   { value: null as THREE.Texture | null },
    uTime:      { value: 0 },
    uIntensity: { value: 1 },
    uGrain:     { value: 0.032 },
  },
  vertexShader: /* glsl */ `
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,
  fragmentShader: /* glsl */ `
    uniform sampler2D tDiffuse;
    uniform float uTime;
    uniform float uIntensity;
    uniform float uGrain;
    varying vec2 vUv;

    float hash(vec2 p) {
      return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
    }

    void main() {
      vec2 uv = vUv;
      vec2 center = uv - 0.5;
      float distanceToCenter = length(center);

      /* Natural optical chromatic aberration — very subtle, realistic glass dispersion */
      float aberrStr = distanceToCenter * 0.0008 * uIntensity;
      vec2 aberration = center * aberrStr;

      vec3 color;
      color.r = texture2D(tDiffuse, uv + aberration).r;
      color.g = texture2D(tDiffuse, uv).g;
      color.b = texture2D(tDiffuse, uv - aberration).b;

      /* Gentle film grain — authentic subtle texture without digital noise */
      float grain = (hash(uv * vec2(1920.0, 1080.0) + fract(uTime * 0.2) * 50.0) - 0.5) * 0.012 * uGrain;
      color += grain;

      /* Soft natural vignette */
      float vignette = smoothstep(0.95, 0.35, distanceToCenter);
      color *= mix(0.78, 1.0, vignette);

      gl_FragColor = vec4(color, 1.0);
    }
  `,
};

function PostProcessing({ scanning }: { scanning: boolean }) {
  const { gl, scene, camera, size } = useThree();
  const composerRef = useRef<EffectComposer | null>(null);
  const grainRef    = useRef<ShaderPass | null>(null);

  useEffect(() => {
    const composer = new EffectComposer(gl);
    composer.addPass(new RenderPass(scene, camera));

    /* realistic optical bloom — soft glow, not blown out */
    const bloom = new UnrealBloomPass(
      new THREE.Vector2(size.width, size.height),
      0.65,  // strength: controlled, realistic
      0.4,   // radius: focused
      0.82,  // threshold: only highlights glow naturally
    );
    composer.addPass(bloom);

    const grain = new ShaderPass(GrainShader);
    composer.addPass(grain);
    composer.addPass(new OutputPass());

    composer.setPixelRatio(Math.min(gl.getPixelRatio(), 1.5));
    composer.setSize(size.width, size.height);

    composerRef.current = composer;
    grainRef.current    = grain;

    return () => {
      composer.dispose();
      composerRef.current = null;
      grainRef.current    = null;
    };
    // The composer is rebuilt only when the renderer changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gl, scene, camera]);

  useEffect(() => {
    composerRef.current?.setPixelRatio(Math.min(gl.getPixelRatio(), 1.5));
    composerRef.current?.setSize(size.width, size.height);
  }, [gl, size]);

  useFrame((state, delta) => {
    const composer = composerRef.current;
    if (!composer) return;
    if (grainRef.current) {
      const t = state.clock.elapsedTime;
      grainRef.current.uniforms.uTime.value      = t;
      /* aberration pulses stronger while scanning */
      const targetAberr = scanning ? 1.6 + Math.sin(t * 4.2) * 0.55 : 1.0;
      grainRef.current.uniforms.uIntensity.value = THREE.MathUtils.damp(
        grainRef.current.uniforms.uIntensity.value, targetAberr, 6, delta,
      );
      /* grain pulses during scanning */
      const targetGrain = scanning ? 0.055 + Math.sin(t * 8.5) * 0.018 : 0.032;
      grainRef.current.uniforms.uGrain.value = THREE.MathUtils.damp(
        grainRef.current.uniforms.uGrain.value, targetGrain, 5, delta,
      );
    }
    composer.render(delta);
  }, 1);

  return null;
}

/* ── enhanced portal ──────────────────────────────────────────────────── */

const portalVertex = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

/** Enhanced portal fragment — adds plasma tendrils, energy ripples, and
 *  gravitational lensing distortion on top of the original vortex. */
const portalFragment = /* glsl */ `
  uniform float uTime;
  uniform float uScan;
  uniform vec3  uPalette;
  varying vec2 vUv;

  float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
  }

  float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(
      mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x),
      mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x),
      f.y
    );
  }

  /* ── layer 1: plasma tendrils ──────────────────────────────────────── */
  float tendrils(vec2 p, float t) {
    float a = atan(p.y, p.x);
    float r = length(p);
    float n = 0.0;
    for (int i = 0; i < 4; i++) {
      float fi = float(i);
      n += noise(vec2(
        a * (3.0 + fi) + r * 8.0 - t * (0.4 + fi * 0.12),
        r * 6.0 + fi * 1.7
      ));
    }
    n /= 4.0;
    return pow(n, 1.8);
  }

  /* ── layer 2: energy ripples ───────────────────────────────────────── */
  float ripples(float r, float t) {
    float base  = sin(r * 28.0 - t * 3.1) * 0.5 + 0.5;
    float base2 = sin(r * 44.0 - t * 5.7 + 1.2) * 0.5 + 0.5;
    float env   = smoothstep(0.96, 0.55, r) * smoothstep(0.12, 0.44, r);
    return (base * 0.6 + base2 * 0.4) * env;
  }

  /* ── layer 3: gravitational lensing ───────────────────────────────── */
  vec2 lens(vec2 p) {
    float r = length(p);
    float lensStr = 0.018 / (r * r + 0.14);
    return p * (1.0 + lensStr * sin(uTime * 0.7));
  }

  void main() {
    vec2 p      = vUv * 2.0 - 1.0;
    vec2 lensed = lens(p);
    float radius = length(lensed);
    float angle  = atan(lensed.y, lensed.x);

    float swirl  = noise(vec2(angle * 3.0 + radius * 6.0 - uTime * 0.35, radius * 5.0));
    float swirl2 = noise(vec2(angle * 5.0 - radius * 9.0 + uTime * 0.22, radius * 7.0 + 4.0));
    float bands  = sin(radius * 34.0 - uTime * 1.7 + swirl * 4.0 + angle * 3.0) * 0.5 + 0.5;
    bands        = pow(bands, 2.5);

    float aperture = smoothstep(0.98, 0.74, radius) * smoothstep(0.16, 0.42, radius);
    float inner    = smoothstep(0.52, 0.04, radius);
    float scan     = exp(-pow((radius - fract(uScan * 0.7 + 0.12)) * 8.0, 2.0)) * 0.35;

    /* plasma tendrils */
    float tLayer   = tendrils(lensed, uTime) * aperture * 0.55;
    /* energy ripples */
    float rLayer   = ripples(radius, uTime) * 0.38;

    vec3 deep   = vec3(0.006, 0.02, 0.045);
    vec3 cyan   = vec3(0.12, 0.85, 0.78);
    vec3 violet = vec3(0.42, 0.25, 0.95);
    vec3 amber  = vec3(1.0,  0.55, 0.28);

    vec3 color = deep;
    color += mix(cyan, violet, swirl2) * bands * aperture * 0.7;
    color += cyan * inner * (0.16 + swirl * 0.2);
    color += amber * pow(swirl2, 4.0) * aperture * 0.28;
    color += vec3(0.55, 1.0, 0.95) * scan;

    /* NEW: tendril layer tinted with signal palette */
    color += uPalette * tLayer;
    /* NEW: ripple layer */
    color += mix(cyan, uPalette, 0.5) * rLayer;

    float alpha = clamp(aperture * (0.32 + bands * 0.55) + inner * 0.14 + scan + tLayer * 0.4 + rLayer * 0.3, 0.0, 1.0);
    gl_FragColor = vec4(color, alpha);
  }
`;

function ScanWave({ scanning }: { scanning: boolean }) {
  const meshRef  = useRef<THREE.Mesh>(null);
  const progress = useRef(1);
  const previous = useRef(false);

  useEffect(() => {
    if (scanning && !previous.current) progress.current = 0;
    previous.current = scanning;
  }, [scanning]);

  useFrame((_, delta) => {
    if (!meshRef.current) return;
    if (progress.current >= 1) {
      meshRef.current.scale.setScalar(0.001);
      return;
    }
    progress.current = Math.min(1, progress.current + delta * 0.62);
    const eased = 1 - Math.pow(1 - progress.current, 2);
    meshRef.current.scale.setScalar(0.5 + eased * 5.4);
    const material = meshRef.current.material as THREE.MeshBasicMaterial;
    material.opacity = (1 - progress.current) * 0.55;
  });

  return (
    <mesh ref={meshRef} scale={0.001}>
      <torusGeometry args={[1, 0.012, 6, 200]} />
      <meshBasicMaterial
        color="#9ffff2"
        transparent
        opacity={0}
        depthWrite={false}
        blending={THREE.AdditiveBlending}
        toneMapped={false}
      />
    </mesh>
  );
}

function Portal({
  scanning,
  reduced,
  active,
}: {
  scanning: boolean;
  reduced: boolean;
  active: SceneSignal;
}) {
  const ringRef  = useRef<THREE.Group>(null);
  const tiltRef  = useRef<THREE.Group>(null);
  const palette  = SIGNAL_PALETTES[active];
  const uniforms = useMemo(
    () => ({
      uTime:    { value: 0 },
      uScan:    { value: 0 },
      uPalette: { value: new THREE.Color(palette.primary) },
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  useFrame((state, delta) => {
    uniforms.uTime.value  = state.clock.elapsedTime;
    uniforms.uScan.value  = state.clock.elapsedTime * 0.06;
    uniforms.uPalette.value.lerp(
      new THREE.Color(SIGNAL_PALETTES[active].primary),
      Math.min(1, delta * 3),
    );
    if (reduced) return;
    if (ringRef.current) ringRef.current.rotation.z += delta * 0.035;
    if (tiltRef.current) tiltRef.current.rotation.z -= delta * 0.02;
  });

  return (
    <group position={[0, 0.28, -3.6]}>
      <mesh>
        <circleGeometry args={[3.5, 128]} />
        <shaderMaterial
          uniforms={uniforms}
          vertexShader={portalVertex}
          fragmentShader={portalFragment}
          transparent
          depthWrite={false}
          blending={THREE.AdditiveBlending}
          toneMapped={false}
        />
      </mesh>

      {/* chromatic aberration rings */}
      {[
        { r: 3.28, tube: 0.03, color: '#59e4d7', emissive: '#59e4d7', emissiveI: 2.8 },
        { r: 3.12, tube: 0.007, color: '#ff4d6a', emissive: '#ff4d6a', emissiveI: 1.5 },
        { r: 3.44, tube: 0.006, color: '#7df9ff', emissive: '#7df9ff', emissiveI: 1.2 },
      ].map((ring, i) => (
        <group key={i} ref={i === 0 ? ringRef : undefined}>
          <mesh>
            <torusGeometry args={[ring.r, ring.tube, 16, 280]} />
            <meshStandardMaterial
              color={ring.color}
              emissive={ring.emissive}
              emissiveIntensity={ring.emissiveI}
              metalness={0.88}
              roughness={0.2}
              toneMapped={false}
            />
          </mesh>
        </group>
      ))}

      <group rotation={[0, 0, Math.PI * 0.17]}>
        <mesh>
          <torusGeometry args={[3.5, 0.012, 8, 280]} />
          <meshBasicMaterial color="#9b7cff" transparent opacity={0.55} toneMapped={false} />
        </mesh>
      </group>

      <group ref={tiltRef} rotation={[Math.PI * 0.1, Math.PI * 0.08, 0]}>
        <mesh>
          <torusGeometry args={[3.88, 0.01, 8, 280]} />
          <meshBasicMaterial color="#ffb57c" transparent opacity={0.25} toneMapped={false} />
        </mesh>
      </group>

      <ScanWave scanning={scanning} />
    </group>
  );
}

/* ── core ─────────────────────────────────────────────────────────────── */

function TwinCore({
  scanning,
  reduced,
  active,
}: {
  scanning: boolean;
  reduced: boolean;
  active: SceneSignal;
}) {
  const glassRef = useRef<THREE.Mesh>(null);
  const innerRef = useRef<THREE.Mesh>(null);
  const shellRef = useRef<THREE.Mesh>(null);
  const palette  = SIGNAL_PALETTES[active];

  useFrame((state, delta) => {
    const t = state.clock.elapsedTime;
    if (reduced) return;

    if (glassRef.current) {
      glassRef.current.rotation.y += delta * 0.12;
      glassRef.current.rotation.x = Math.sin(t * 0.28) * 0.16;
    }
    if (innerRef.current) {
      innerRef.current.rotation.y -= delta * 0.42;
      innerRef.current.rotation.z += delta * 0.08;
    }
    if (shellRef.current) {
      shellRef.current.rotation.y += delta * 0.065;
      shellRef.current.rotation.x -= delta * 0.04;
    }
  });

  return (
    <group position={[0, 0.18, 0]}>
      <Float speed={reduced ? 0 : 1.1} rotationIntensity={0} floatIntensity={reduced ? 0 : 0.28}>
        <mesh ref={glassRef}>
          <icosahedronGeometry args={[1.3, 3]} />
          <meshPhysicalMaterial
            color="#071019"
            metalness={0.55}
            roughness={0.08}
            transmission={0.62}
            thickness={1.65}
            ior={1.44}
            clearcoat={1}
            clearcoatRoughness={0.06}
            envMapIntensity={2.4}
            emissive="#062b33"
            emissiveIntensity={scanning ? 1.3 : 0.45}
          />
        </mesh>

        <mesh ref={innerRef} scale={0.7}>
          <icosahedronGeometry args={[1.3, 1]} />
          <meshBasicMaterial
            color={palette.primary}
            wireframe
            transparent
            opacity={0.38}
            toneMapped={false}
          />
        </mesh>

        <mesh ref={shellRef} scale={1.46}>
          <icosahedronGeometry args={[1.3, 1]} />
          <meshBasicMaterial
            color="#4e8dbf"
            wireframe
            transparent
            opacity={0.12}
            toneMapped={false}
          />
        </mesh>

        <mesh scale={0.5}>
          <sphereGeometry args={[1, 48, 48]} />
          <meshBasicMaterial color="#ddfffb" toneMapped={false} />
        </mesh>

        <pointLight color={palette.primary}  intensity={9}  distance={9}  decay={2} />
        <pointLight color={palette.secondary} intensity={7} distance={8}  decay={2} position={[1.7, -1.1, 1.4]} />
      </Float>
    </group>
  );
}

function CoreRings({ reduced }: { reduced: boolean }) {
  const groupRef = useRef<THREE.Group>(null);

  useFrame((_, delta) => {
    if (!groupRef.current || reduced) return;
    groupRef.current.rotation.y += delta * 0.055;
    groupRef.current.rotation.z -= delta * 0.018;
  });

  return (
    <group ref={groupRef} position={[0, 0.18, 0]} rotation={[0.18, 0, -0.14]}>
      {[
        { radius: 1.78, tilt: [1.32, 0.12, 0.1]   as [number,number,number], color: '#79f4e7', opacity: 0.62 },
        { radius: 2.02, tilt: [1.62, -0.45, 0.45]  as [number,number,number], color: '#a88bff', opacity: 0.5  },
        { radius: 2.3,  tilt: [1.12, 0.55, -0.35] as [number,number,number], color: '#ffb47a', opacity: 0.24 },
      ].map((ring) => (
        <mesh key={ring.radius} rotation={ring.tilt}>
          <torusGeometry args={[ring.radius, 0.008, 5, 240]} />
          <meshBasicMaterial
            color={ring.color}
            transparent
            opacity={ring.opacity}
            toneMapped={false}
          />
        </mesh>
      ))}
    </group>
  );
}

/* ── floating video screens ───────────────────────────────────────────── */

const screenVertex = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const screenFragment = /* glsl */ `
  uniform sampler2D uMap;
  uniform float uTime;
  uniform float uReady;
  uniform float uActive;
  varying vec2 vUv;

  float hash(vec2 p) {
    return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
  }

  void main() {
    vec3 sampled  = texture2D(uMap, vUv).rgb;
    vec3 fallback = vec3(0.008, 0.035, 0.055);
    fallback += vec3(0.03, 0.24, 0.25) * (0.3 + 0.7 * hash(floor(vUv * vec2(48.0, 28.0))));
    fallback *= 0.7 + 0.3 * sin(vUv.y * 320.0);
    vec3 color = mix(fallback, sampled, uReady);

    float scan = 0.93 + 0.07 * sin(vUv.y * 520.0);
    color *= scan;

    float sweep     = fract(vUv.y + uTime * 0.13);
    float sweepLine = smoothstep(0.0, 0.035, sweep) * (1.0 - smoothstep(0.035, 0.07, sweep));
    color += vec3(0.18, 0.95, 0.86) * sweepLine * 0.05;

    vec2  centered = vUv - 0.5;
    float vignette = smoothstep(0.88, 0.32, length(centered));
    color *= mix(0.66, 1.0, vignette);
    color += vec3(0.07, 0.65, 0.62) * uActive * 0.035;
    color += vec3(0.2, 0.12, 0.45) * uActive * (0.5 - abs(centered.y)) * 0.06;

    gl_FragColor = vec4(color, 1.0);
  }
`;

const SCREEN_DATA: Record<
  'architecture' | 'security' | 'verification',
  {
    src: string;
    label: string;
    position: [number, number, number];
    rotation: [number, number, number];
    size: [number, number];
  }
> = {
  architecture: {
    src: '/media/orbital.mp4',
    label: 'ARCHITECTURE / ORBITAL',
    position: [-4.12, 0.82, 1.05],
    rotation: [0.02, 0.42, -0.012],
    size: [3.0, 1.7],
  },
  security: {
    src: '/media/signal.mp4',
    label: 'SECURITY / SIGNAL',
    position: [4.12, 0.14, 0.72],
    rotation: [-0.02, -0.43, 0.02],
    size: [3.0, 1.7],
  },
  verification: {
    src: '/media/nextworld.mp4',
    label: 'VERIFICATION / WORLD',
    position: [0.38, 2.5, -0.9],
    rotation: [-0.2, 0.05, 0.018],
    size: [2.55, 1.45],
  },
};

function HoloScreen({
  signal,
  active,
  reduced,
  onInspect,
}: {
  signal: 'architecture' | 'security' | 'verification';
  active: boolean;
  reduced: boolean;
  onInspect?: (signal: SceneSignal) => void;
}) {
  const data        = SCREEN_DATA[signal];
  const groupRef    = useRef<THREE.Group>(null);
  const materialRef = useRef<THREE.ShaderMaterial>(null);
  const [hovered, setHovered] = useState(false);
  useCursor(hovered);

  const { texture, ready } = useVideoTexture(data.src);
  const fallback = useMemo(() => {
    const result = new THREE.DataTexture(
      new Uint8Array([8, 22, 34, 255]),
      1,
      1,
      THREE.RGBAFormat,
    );
    result.needsUpdate = true;
    return result;
  }, []);

  useEffect(() => () => fallback.dispose(), [fallback]);

  const uniforms = useMemo(
    () => ({
      uMap:    { value: fallback as THREE.Texture },
      uTime:   { value: 0 },
      uReady:  { value: 0 },
      uActive: { value: 0 },
    }),
    [fallback],
  );

  useEffect(() => {
    uniforms.uMap.value   = texture ?? fallback;
    uniforms.uReady.value = ready ? 1 : 0;
  }, [fallback, ready, texture, uniforms]);

  useFrame((state, delta) => {
    if (materialRef.current) {
      materialRef.current.uniforms.uTime.value = state.clock.elapsedTime;
      const target = active || hovered ? 1 : 0;
      materialRef.current.uniforms.uActive.value = THREE.MathUtils.damp(
        materialRef.current.uniforms.uActive.value,
        target,
        6,
        delta,
      );
    }
    if (groupRef.current) {
      const targetScale = active || hovered ? 1.07 : 1;
      groupRef.current.scale.x = THREE.MathUtils.damp(
        groupRef.current.scale.x,
        targetScale,
        5,
        delta,
      );
      groupRef.current.scale.y = groupRef.current.scale.x;
      groupRef.current.scale.z = groupRef.current.scale.x;
      if (!reduced) {
        groupRef.current.position.y =
          data.position[1] +
          Math.sin(state.clock.elapsedTime * 0.55 + data.position[0]) * 0.045;
      }
    }
  });

  const [width, height] = data.size;

  return (
    <Float
      speed={reduced ? 0 : 1}
      rotationIntensity={reduced ? 0 : 0.055}
      floatIntensity={reduced ? 0 : 0.18}
    >
      <group
        ref={groupRef}
        position={data.position}
        rotation={data.rotation}
        onPointerOver={(event) => { event.stopPropagation(); setHovered(true); }}
        onPointerOut={() => setHovered(false)}
        onClick={(event) => { event.stopPropagation(); onInspect?.(signal); }}
      >
        <RoundedBox
          args={[width + 0.14, height + 0.14, 0.07]}
          radius={0.045}
          smoothness={4}
          position={[0, 0, 0]}
        >
          <meshStandardMaterial
            color="#04080e"
            metalness={0.92}
            roughness={0.24}
            envMapIntensity={1.4}
          />
        </RoundedBox>

        <mesh position={[0, 0, 0.041]}>
          <planeGeometry args={[width, height]} />
          <shaderMaterial
            ref={materialRef}
            uniforms={uniforms}
            vertexShader={screenVertex}
            fragmentShader={screenFragment}
            toneMapped={false}
          />
        </mesh>

        <mesh position={[0, height / 2 + 0.074, 0.016]}>
          <boxGeometry args={[width + 0.14, 0.012, 0.018]} />
          <meshBasicMaterial
            color={active || hovered ? '#a8fff3' : '#2e6d72'}
            toneMapped={false}
          />
        </mesh>

        {[-1, 1].map((side) => (
          <mesh key={side} position={[side * (width / 2 + 0.087), 0, 0.016]}>
            <boxGeometry args={[0.018, height * 0.42, 0.014]} />
            <meshBasicMaterial color="#2d777c" transparent opacity={0.7} toneMapped={false} />
          </mesh>
        ))}

        <mesh position={[0, -height / 2 - 0.62, -0.12]}>
          <cylinderGeometry args={[0.012, 0.15, 1.3, 16, 1, true]} />
          <meshBasicMaterial
            color="#59e4d7"
            transparent
            opacity={0.06}
            side={THREE.DoubleSide}
            depthWrite={false}
            blending={THREE.AdditiveBlending}
            toneMapped={false}
          />
        </mesh>
      </group>
    </Float>
  );
}

/* ── decorative layers ────────────────────────────────────────────────── */

function Constellation({ reduced }: { reduced: boolean }) {
  const groupRef = useRef<THREE.Group>(null);
  const nodes = useMemo(() => {
    const random = mulberry32(1337);
    const tones  = ['#72f2e4', '#a88bff', '#ffb47a', '#8bb7ff'];
    return Array.from({ length: 38 }, () => {
      const theta  = random() * Math.PI * 2;
      const phi    = Math.acos(2 * random() - 1);
      const radius = 2.25 + random() * 1.55;
      return {
        position: [
          Math.sin(phi) * Math.cos(theta) * radius,
          Math.cos(phi) * radius * 0.78,
          Math.sin(phi) * Math.sin(theta) * radius * 0.72,
        ] as [number, number, number],
        scale: 0.022 + random() * 0.055,
        color: tones[Math.floor(random() * tones.length)],
      };
    });
  }, []);

  const lineGeometry = useMemo(() => {
    const positions: number[] = [];
    for (const node of nodes) positions.push(0, 0.18, 0, ...node.position);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    return geometry;
  }, [nodes]);

  useEffect(() => () => lineGeometry.dispose(), [lineGeometry]);

  useFrame((_, delta) => {
    if (!groupRef.current || reduced) return;
    groupRef.current.rotation.y += delta * 0.018;
  });

  return (
    <group ref={groupRef}>
      <lineSegments geometry={lineGeometry}>
        <lineBasicMaterial color="#165566" transparent opacity={0.26} depthWrite={false} />
      </lineSegments>
      {nodes.map((node, index) => (
        <mesh key={index} position={node.position}>
          <octahedronGeometry args={[node.scale, 0]} />
          <meshBasicMaterial
            color={node.color}
            transparent
            opacity={0.82}
            toneMapped={false}
          />
        </mesh>
      ))}
    </group>
  );
}

function DataStreams({
  reduced,
  active,
}: {
  reduced: boolean;
  active: SceneSignal;
}) {
  const count     = 130;
  const pointsRef = useRef<THREE.Points>(null);
  const glow      = useGlowTexture();
  const palette   = SIGNAL_PALETTES[active];

  const positions = useMemo(() => new Float32Array(count * 3), [count]);
  const seeds     = useMemo(() => {
    const random = mulberry32(90210);
    return Array.from({ length: count }, () => ({
      radius: 1.45 + random() * 2.6,
      y:      (random() - 0.5) * 3.4,
      speed:  0.1 + random() * 0.34,
      phase:  random() * Math.PI * 2,
      wobble: random() * Math.PI * 2,
    }));
  }, [count]);

  useFrame((state) => {
    if (!pointsRef.current) return;
    const time      = state.clock.elapsedTime;
    const attribute = pointsRef.current.geometry.attributes.position as THREE.BufferAttribute;
    for (let index = 0; index < count; index += 1) {
      const seed  = seeds[index];
      const angle = seed.phase + time * seed.speed + seed.radius * 0.12;
      const drift = reduced ? 0 : Math.sin(time * 0.35 + seed.wobble) * 0.22;
      attribute.setXYZ(
        index,
        Math.cos(angle) * seed.radius,
        0.18 + seed.y + drift,
        Math.sin(angle) * seed.radius * 0.74,
      );
    }
    attribute.needsUpdate = true;

    /* update colour to match signal palette */
    const mat = pointsRef.current.material as THREE.PointsMaterial;
    mat.color.lerp(new THREE.Color(palette.primary), 0.05);
  });

  return (
    <points ref={pointsRef}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
      </bufferGeometry>
      <pointsMaterial
        map={glow}
        color={palette.primary}
        size={0.085}
        transparent
        opacity={0.78}
        depthWrite={false}
        blending={THREE.AdditiveBlending}
        sizeAttenuation
      />
    </points>
  );
}

/* ── QuantumField ─────────────────────────────────────────────────────── */

/** 2000-instance plasma micro-particle cloud using GLSL vertex displacement. */
const quantumVertexShader = /* glsl */ `
  attribute float aPhase;
  attribute float aSpeed;
  attribute float aRadius;
  uniform   float uTime;
  uniform   vec3  uPalette;
  varying   float vBrightness;

  void main() {
    float t     = uTime * aSpeed + aPhase;
    float theta = aPhase * 6.2832 + t * 0.42;
    float phi   = aPhase * 3.1416;
    float r     = aRadius + sin(t * 1.7 + aPhase * 12.0) * 0.15;

    vec3 displaced = vec3(
      sin(phi) * cos(theta) * r + sin(t * 2.3 + aPhase) * 0.08,
      cos(phi) * r * 0.75        + cos(t * 1.9 + aPhase) * 0.06,
      sin(phi) * sin(theta) * r  + sin(t * 2.8 + aPhase) * 0.07
    );

    vBrightness = 0.5 + 0.5 * sin(t * 3.0 + aPhase * 5.0);

    vec4 mvPosition = modelViewMatrix * vec4(displaced, 1.0);
    gl_PointSize    = (3.5 + vBrightness * 2.5) * (180.0 / -mvPosition.z);
    gl_Position     = projectionMatrix * mvPosition;
  }
`;

const quantumFragmentShader = /* glsl */ `
  varying float vBrightness;

  void main() {
    vec2  uv   = gl_PointCoord * 2.0 - 1.0;
    float dist = length(uv);
    if (dist > 1.0) discard;
    float alpha = (1.0 - dist) * vBrightness * 0.75;
    gl_FragColor = vec4(vec3(1.0), alpha);
  }
`;

function QuantumField({ active }: { active: SceneSignal }) {
  const COUNT      = 400; // Realistic subtle ambient dust particles
  const meshRef    = useRef<THREE.Points>(null);
  const palette    = SIGNAL_PALETTES[active];
  const colorRef   = useRef(new THREE.Color(palette.primary));

  const { geo, uniforms } = useMemo(() => {
    const random  = mulberry32(424242);
    const phase   = new Float32Array(COUNT);
    const speed   = new Float32Array(COUNT);
    const radius  = new Float32Array(COUNT);
    const colors  = new Float32Array(COUNT * 3);
    const col     = new THREE.Color();

    for (let i = 0; i < COUNT; i++) {
      phase[i]  = random() * Math.PI * 2;
      speed[i]  = 0.08 + random() * 0.22;
      radius[i] = 0.9 + random() * 1.6;
      col.set(palette.primary);
      colors[i * 3]     = col.r;
      colors[i * 3 + 1] = col.g;
      colors[i * 3 + 2] = col.b;
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(new Float32Array(COUNT * 3), 3));
    geometry.setAttribute('aPhase',   new THREE.Float32BufferAttribute(phase, 1));
    geometry.setAttribute('aSpeed',   new THREE.Float32BufferAttribute(speed, 1));
    geometry.setAttribute('aRadius',  new THREE.Float32BufferAttribute(radius, 1));
    geometry.setAttribute('color',    new THREE.Float32BufferAttribute(colors, 3));

    const uni = { uTime: { value: 0 }, uPalette: { value: new THREE.Color(palette.primary) } };
    return { geo: geometry, uniforms: uni };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => () => geo.dispose(), [geo]);

  useFrame((state, delta) => {
    if (!meshRef.current) return;
    uniforms.uTime.value = state.clock.elapsedTime;
    colorRef.current.lerp(new THREE.Color(SIGNAL_PALETTES[active].primary), Math.min(1, delta * 2.5));
    uniforms.uPalette.value.copy(colorRef.current);
    const mat = meshRef.current.material as THREE.ShaderMaterial;
    mat.uniforms.uPalette.value.copy(colorRef.current);
  });

  return (
    <points ref={meshRef} geometry={geo} position={[0, 0.18, 0]}>
      <shaderMaterial
        vertexShader={quantumVertexShader}
        fragmentShader={quantumFragmentShader}
        uniforms={uniforms}
        transparent
        depthWrite={false}
        blending={THREE.AdditiveBlending}
        vertexColors
        toneMapped={false}
      />
    </points>
  );
}

/* ── HoloPillar ───────────────────────────────────────────────────────── */

/** Animated bar-chart data pillar at a cardinal position. */
function HoloPillar({
  position,
  active,
}: {
  position: [number, number, number];
  active: SceneSignal;
}) {
  const BARS       = 8;
  const groupRef   = useRef<THREE.Group>(null);
  const barsRef    = useRef<THREE.InstancedMesh>(null);
  const palette    = SIGNAL_PALETTES[active];
  const colorRef   = useRef(new THREE.Color(palette.primary));
  const dummy      = useMemo(() => new THREE.Object3D(), []);

  const barSeeds = useMemo(() => {
    const random = mulberry32(position[0] * 100 + position[2] * 37 | 0);
    return Array.from({ length: BARS }, () => ({
      base:  0.2 + random() * 0.8,
      speed: 0.4 + random() * 1.2,
      phase: random() * Math.PI * 2,
    }));
  }, [position]);

  useFrame((state, delta) => {
    if (!barsRef.current) return;
    const t  = state.clock.elapsedTime;
    colorRef.current.lerp(new THREE.Color(SIGNAL_PALETTES[active].primary), Math.min(1, delta * 2.5));
    const col = colorRef.current;
    const mat = barsRef.current.material as THREE.MeshStandardMaterial;
    mat.emissive.copy(col);
    mat.color.copy(col).multiplyScalar(0.18);

    for (let i = 0; i < BARS; i++) {
      const seed   = barSeeds[i];
      const height = seed.base + Math.sin(t * seed.speed + seed.phase) * 0.25;
      const xOffset = (i - (BARS - 1) / 2) * 0.22;
      dummy.position.set(xOffset, height / 2, 0);
      dummy.scale.set(0.14, height, 0.14);
      dummy.updateMatrix();
      barsRef.current.setMatrixAt(i, dummy.matrix);
    }
    barsRef.current.instanceMatrix.needsUpdate = true;
  });

  return (
    <group ref={groupRef} position={position}>
      {/* base plate */}
      <mesh position={[0, -0.04, 0]}>
        <boxGeometry args={[2.2, 0.04, 0.35]} />
        <meshStandardMaterial
          color="#0a1a22"
          emissive={palette.primary}
          emissiveIntensity={0.4}
          metalness={0.9}
          roughness={0.3}
          toneMapped={false}
        />
      </mesh>

      {/* bars */}
      <instancedMesh ref={barsRef} args={[undefined, undefined, BARS]}>
        <boxGeometry args={[1, 1, 1]} />
        <meshStandardMaterial
          color={palette.primary}
          emissive={palette.primary}
          emissiveIntensity={1.8}
          metalness={0.3}
          roughness={0.2}
          transparent
          opacity={0.85}
          toneMapped={false}
        />
      </instancedMesh>

      {/* label line */}
      <mesh position={[0, -0.08, 0]}>
        <boxGeometry args={[2.2, 0.005, 0.005]} />
        <meshBasicMaterial color={palette.accent} toneMapped={false} />
      </mesh>
    </group>
  );
}

/* ── NeuralWebs ───────────────────────────────────────────────────────── */

/** Animated quadratic bezier web between constellation node pairs. */
function NeuralWebs({ reduced, active }: { reduced: boolean; active: SceneSignal }) {
  const groupRef  = useRef<THREE.Group>(null);
  const palette   = SIGNAL_PALETTES[active];

  /* Build stable node set matching Constellation (same seed) */
  const nodes = useMemo(() => {
    const random = mulberry32(1337);
    return Array.from({ length: 38 }, () => {
      const theta  = random() * Math.PI * 2;
      const phi    = Math.acos(2 * random() - 1);
      const radius = 2.25 + random() * 1.55;
      return new THREE.Vector3(
        Math.sin(phi) * Math.cos(theta) * radius,
        Math.cos(phi) * radius * 0.78,
        Math.sin(phi) * Math.sin(theta) * radius * 0.72,
      );
    });
  }, []);

  /* Build curves and line geometries */
  const curves = useMemo(() => {
    const random = mulberry32(5555);
    const result: { geo: THREE.BufferGeometry; phase: number; speed: number }[] = [];
    for (let i = 0; i < 28; i++) {
      const a   = Math.floor(random() * nodes.length);
      const b   = Math.floor(random() * nodes.length);
      if (a === b) continue;
      const mid = new THREE.Vector3()
        .addVectors(nodes[a], nodes[b])
        .multiplyScalar(0.5)
        .add(new THREE.Vector3(
          (random() - 0.5) * 1.8,
          (random() - 0.5) * 1.8,
          (random() - 0.5) * 1.8,
        ));
      const curve = new THREE.QuadraticBezierCurve3(nodes[a], mid, nodes[b]);
      const pts   = curve.getPoints(32);
      const geo   = new THREE.BufferGeometry().setFromPoints(pts);
      result.push({ geo, phase: random() * Math.PI * 2, speed: 0.3 + random() * 0.7 });
    }
    return result;
  }, [nodes]);

  useEffect(() => () => { curves.forEach((c) => c.geo.dispose()); }, [curves]);

  useFrame((state, delta) => {
    if (!groupRef.current || reduced) return;
    groupRef.current.rotation.y += delta * 0.012;

    const t = state.clock.elapsedTime;
    groupRef.current.children.forEach((child, i) => {
      if (!(child instanceof THREE.Line)) return;
      const mat = child.material as THREE.LineBasicMaterial;
      const curve = curves[i];
      if (!curve) return;
      mat.opacity = 0.12 + 0.18 * Math.abs(Math.sin(t * curve.speed + curve.phase));
      mat.color.lerp(new THREE.Color(SIGNAL_PALETTES[active].primary), Math.min(1, delta * 2));
    });
  });

  return (
    <group ref={groupRef}>
      {curves.map((curve, i) => (
        <primitive key={i} object={new THREE.Line(
          curve.geo,
          new THREE.LineBasicMaterial({
            color: palette.primary,
            transparent: true,
            opacity: 0.15,
            depthWrite: false,
            blending: THREE.AdditiveBlending,
            toneMapped: false,
          })
        )} />
      ))}
    </group>
  );
}

/* ── DynamicGround ────────────────────────────────────────────────────── */

function DynamicGround({ active }: { active: SceneSignal }) {
  const palette    = SIGNAL_PALETTES[active];
  const glowRef    = useRef<THREE.Mesh>(null);
  const colorRef   = useRef(new THREE.Color(palette.primary));

  useFrame((state, delta) => {
    if (!glowRef.current) return;
    colorRef.current.lerp(new THREE.Color(SIGNAL_PALETTES[active].primary), Math.min(1, delta * 2));
    const mat = glowRef.current.material as THREE.MeshBasicMaterial;
    mat.color.copy(colorRef.current);
    const t = state.clock.elapsedTime;
    mat.opacity = 0.04 + 0.025 * Math.sin(t * 0.7);
  });

  return (
    <group position={[0, -2.42, 0]}>
      {/* reflective ground plane */}
      <mesh rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[54, 54]} />
        <MeshReflectorMaterial
          resolution={512}
          blur={[280, 90]}
          mixBlur={0.9}
          mixStrength={2.1}
          roughness={0.92}
          depthScale={1.1}
          minDepthThreshold={0.4}
          maxDepthThreshold={1.4}
          color="#040811"
          metalness={0.66}
          mirror={0.45}
        />
      </mesh>

      {/* animated fresnel glow ring */}
      <mesh ref={glowRef} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.008, 0]}>
        <ringGeometry args={[5.5, 13, 80]} />
        <meshBasicMaterial
          color={palette.primary}
          transparent
          opacity={0.055}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
          side={THREE.DoubleSide}
          toneMapped={false}
        />
      </mesh>

      <Grid
        position={[0, 0.014, 0]}
        args={[42, 42]}
        cellSize={0.36}
        cellThickness={0.55}
        cellColor="#0b3340"
        sectionSize={2.9}
        sectionThickness={1.1}
        sectionColor="#145463"
        fadeDistance={28}
        fadeStrength={2.2}
        infiniteGrid
      />
    </group>
  );
}

/* ── camera + interaction ─────────────────────────────────────────────── */

function Rig({ children, reduced }: { children: ReactNode; reduced: boolean }) {
  const groupRef = useRef<THREE.Group>(null);
  const drag     = useRef({
    active:    false,
    lastX:     0,
    lastY:     0,
    rotationX: 0,
    rotationY: 0,
    targetX:   0,
    targetY:   0,
  });
  const { gl } = useThree();

  useEffect(() => {
    const element = gl.domElement;
    const onPointerDown = (event: PointerEvent) => {
      if (event.pointerType !== 'mouse') return;
      drag.current.active = true;
      drag.current.lastX  = event.clientX;
      drag.current.lastY  = event.clientY;
      element.style.cursor = 'grabbing';
    };
    const onPointerMove = (event: PointerEvent) => {
      if (!drag.current.active) return;
      const deltaX = event.clientX - drag.current.lastX;
      const deltaY = event.clientY - drag.current.lastY;
      drag.current.lastX = event.clientX;
      drag.current.lastY = event.clientY;
      drag.current.targetY = THREE.MathUtils.clamp(
        drag.current.targetY + deltaX * 0.0035, -0.52, 0.52,
      );
      drag.current.targetX = THREE.MathUtils.clamp(
        drag.current.targetX + deltaY * 0.0025, -0.28, 0.28,
      );
    };
    const onPointerUp = () => {
      drag.current.active  = false;
      element.style.cursor = 'grab';
    };

    element.style.cursor     = 'grab';
    element.style.touchAction = 'pan-y';
    element.addEventListener('pointerdown', onPointerDown);
    window.addEventListener('pointermove',  onPointerMove);
    window.addEventListener('pointerup',    onPointerUp);
    window.addEventListener('pointercancel', onPointerUp);

    return () => {
      element.style.cursor = '';
      element.removeEventListener('pointerdown', onPointerDown);
      window.removeEventListener('pointermove',  onPointerMove);
      window.removeEventListener('pointerup',    onPointerUp);
      window.removeEventListener('pointercancel', onPointerUp);
    };
  }, [gl]);

  useFrame((state, delta) => {
    if (!groupRef.current) return;
    drag.current.rotationY = THREE.MathUtils.damp(drag.current.rotationY, drag.current.targetY, 5, delta);
    drag.current.rotationX = THREE.MathUtils.damp(drag.current.rotationX, drag.current.targetX, 5, delta);

    const time     = state.clock.elapsedTime;
    const auto     = reduced ? 0 : Math.sin(time * 0.11) * 0.035;
    const pointerX = reduced ? 0 : state.pointer.x * 0.055;
    const pointerY = reduced ? 0 : state.pointer.y * 0.038;

    groupRef.current.rotation.y = drag.current.rotationY + auto + pointerX;
    groupRef.current.rotation.x = drag.current.rotationX + pointerY;
  });

  return <group ref={groupRef}>{children}</group>;
}

function CameraDrift({ reduced }: { reduced: boolean }) {
  const { camera } = useThree();
  const scroll     = useRef(0);

  useFrame((state, delta) => {
    const scrollTop = typeof window === 'undefined' ? 0 : window.scrollY;
    const viewport  = typeof window === 'undefined' ? 900 : window.innerHeight;
    const target    = Math.min(1, scrollTop / Math.max(1, viewport));
    scroll.current  = THREE.MathUtils.damp(scroll.current, target, 4, delta);

    const pointerX = reduced ? 0 : state.pointer.x * 0.32;
    const pointerY = reduced ? 0 : state.pointer.y * 0.18;

    camera.position.x = THREE.MathUtils.damp(camera.position.x, pointerX, 3, delta);
    camera.position.y = THREE.MathUtils.damp(
      camera.position.y, 0.67 + pointerY + scroll.current * 0.42, 3, delta,
    );
    camera.position.z = THREE.MathUtils.damp(
      camera.position.z, 10.5 - scroll.current * 2.1, 3, delta,
    );
    camera.lookAt(0.34, 0.2 - scroll.current * 0.12, 0);
  });

  return null;
}

/* ── scene ────────────────────────────────────────────────────────────── */

function SceneContent({
  active,
  scanning,
  reduced,
  onInspect,
}: Required<Pick<NextWorldSceneProps, 'active' | 'scanning' | 'reduced'>> & {
  onInspect?: (signal: SceneSignal) => void;
}) {
  const { size } = useThree();
  const compact  = size.width < 760;
  const palette  = SIGNAL_PALETTES[active];

  /* HoloPillar positions — cardinal XZ axes at distance 5 */
  const pillarPositions: [number, number, number][] = [
    [ 5.2, -2.3, 0],
    [-5.2, -2.3, 0],
    [0, -2.3,  5.2],
    [0, -2.3, -5.2],
  ];

  return (
    <>
      <ambientLight intensity={0.4} />
      <directionalLight position={[5, 7, 4]} intensity={1.8} color="#dbeafe" />
      <pointLight position={[-4, 2.6, 3]}   intensity={6.5} distance={14} decay={2} color={palette.secondary} />
      <pointLight position={[4.4, -0.8, 2.4]} intensity={5.0} distance={12} decay={2} color={palette.primary} />

      <Environment resolution={128} frames={1}>
        <Lightformer form="rect"  intensity={2.6} color="#3b82f6" position={[-5, 3, -4]}  scale={[6, 6, 1]} />
        <Lightformer form="rect"  intensity={2.2} color="#67e8f9" position={[5, 1.5, -2]} scale={[4, 5, 1]} />
        <Lightformer form="ring"  intensity={1.6} color="#a78bfa" position={[0, -2, 3]}   scale={[5, 5, 1]} />
        <Lightformer form="rect"  intensity={1.2} color="#ffb47a" position={[0, 4, 2]}    scale={[4, 2, 1]} />
      </Environment>

      <Stars
        radius={55}
        depth={35}
        count={1100}
        factor={2.2}
        saturation={0}
        fade
        speed={reduced ? 0 : 0.4}
      />
      <Sparkles
        count={compact ? 45 : 90}
        scale={[12, 8, 10]}
        size={1.5}
        speed={reduced ? 0 : 0.25}
        opacity={0.42}
        color={palette.primary}
      />

      {/* QuantumField — plasma micro-particles */}
      {!reduced && <QuantumField active={active} />}

      <Portal scanning={scanning} reduced={reduced} active={active} />

      <Rig reduced={reduced}>
        <group
          position={[compact ? 0 : 0.92, compact ? 0.3 : 0, 0]}
          scale={compact ? 0.72 : 1}
        >
          <TwinCore scanning={scanning} reduced={reduced} active={active} />
          <CoreRings reduced={reduced} />

          {/* NeuralWebs */}
          {!reduced && <NeuralWebs reduced={reduced} active={active} />}

          {!compact && (
            <>
              <HoloScreen
                signal="architecture"
                active={active === 'architecture'}
                reduced={reduced}
                onInspect={onInspect}
              />
              <HoloScreen
                signal="security"
                active={active === 'security' || active === 'impact'}
                reduced={reduced}
                onInspect={onInspect}
              />
              <HoloScreen
                signal="verification"
                active={active === 'verification'}
                reduced={reduced}
                onInspect={onInspect}
              />
            </>
          )}
          {compact && (
            <HoloScreen
              signal="verification"
              active
              reduced={reduced}
              onInspect={onInspect}
            />
          )}
          <Constellation reduced={reduced} />
          <DataStreams reduced={reduced} active={active} />
        </group>
      </Rig>

      {/* HoloPillars at cardinal positions */}
      {!compact && !reduced && pillarPositions.map((pos, i) => (
        <HoloPillar key={i} position={pos} active={active} />
      ))}

      {/* DynamicGround */}
      <DynamicGround active={active} />

      <CameraDrift reduced={reduced} />
    </>
  );
}

export default function NextWorldScene({
  active   = 'architecture',
  scanning = false,
  reduced  = false,
  paused   = false,
  onInspect,
}: NextWorldSceneProps) {
  return (
    <Canvas
      camera={{ position: [0, 0.67, 10.5], fov: 38, near: 0.1, far: 70 }}
      dpr={[1, 1.6]}
      frameloop={paused ? 'demand' : 'always'}
      gl={{ antialias: true, alpha: false, powerPreference: 'high-performance' }}
      onCreated={({ gl }) => {
        gl.toneMapping         = THREE.ACESFilmicToneMapping;
        gl.toneMappingExposure = 1.08;
      }}
    >
      <color attach="background" args={['#03060c']} />
      <fogExp2 attach="fog" args={['#03060c', 0.026]} />
      <SceneContent
        active={active}
        scanning={scanning}
        reduced={reduced}
        onInspect={onInspect}
      />
      <PostProcessing scanning={scanning} />
    </Canvas>
  );
}
