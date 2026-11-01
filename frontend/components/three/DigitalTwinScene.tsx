'use client';

import { Float, Sparkles } from '@react-three/drei';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { useEffect, useMemo, useRef, useState, type RefObject } from 'react';
import * as THREE from 'three';

/* ── Palette (matches the site design tokens) ──────────────────────────── */

const COLORS = {
  violet: new THREE.Color('#8b5cf6'),
  cyan: new THREE.Color('#5eead4'),
  blue: new THREE.Color('#60a5fa'),
  emerald: new THREE.Color('#34d399'),
} as const;

type Tone = keyof typeof COLORS;

const NODE_TONES: Tone[] = ['cyan', 'violet', 'blue', 'cyan', 'violet', 'emerald'];

/** Deterministic PRNG so the constellation composition is stable across renders. */
function mulberry32(seed: number) {
  return () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/* ── Scene data ─────────────────────────────────────────────────────────── */

interface NodeSpec {
  position: [number, number, number];
  color: THREE.Color;
  size: number;
  phase: number;
  spin: number;
}

interface SceneData {
  nodes: NodeSpec[];
  /** Core-edge pair for node i lives at floats [i*6, i*6+6). */
  linePositions: Float32Array;
}

/** Build the symbol constellation: nodes in two orbit shells plus coupling edges. */
function buildScene(): SceneData {
  const rand = mulberry32(20261018);
  const nodes: NodeSpec[] = [];

  for (let i = 0; i < 26; i += 1) {
    // Two shells of radius ~2.3 and ~3.0+ for layered depth.
    const shell = i < 14 ? 2.3 + rand() * 0.45 : 3.0 + rand() * 0.55;
    const theta = rand() * Math.PI * 2;
    const phi = Math.acos(2 * rand() - 1);
    nodes.push({
      position: [
        shell * Math.sin(phi) * Math.cos(theta),
        shell * Math.cos(phi) * 0.62, // flattened orbital plane, like a galaxy
        shell * Math.sin(phi) * Math.sin(theta),
      ],
      color: COLORS[NODE_TONES[i % NODE_TONES.length]],
      size: 0.075 + rand() * 0.075,
      phase: rand() * Math.PI * 2,
      spin: 0.6 + rand() * 1.2,
    });
  }

  const points: number[] = [];
  nodes.forEach((node, i) => {
    // Every node couples to the twin core…
    points.push(0, 0, 0, ...node.position);
    // …and every other node shares one neighbor edge to imply symbol relationships.
    if (i % 2 === 0) {
      const neighbor = (i + 3) % nodes.length;
      points.push(...node.position, ...nodes[neighbor].position);
    }
  });

  return { nodes, linePositions: new Float32Array(points) };
}

/* ── Twin core ──────────────────────────────────────────────────────────── */

function TwinCore({ reduced }: { reduced: boolean }) {
  const wire = useRef<THREE.Mesh>(null);
  const shell = useRef<THREE.Mesh>(null);

  useFrame(({ clock }) => {
    if (reduced) return;
    const t = clock.elapsedTime;
    if (wire.current) {
      wire.current.rotation.y = t * 0.12;
      wire.current.rotation.x = Math.sin(t * 0.18) * 0.22;
    }
    if (shell.current) {
      shell.current.scale.setScalar(1 + Math.sin(t * 1.4) * 0.035);
    }
  });

  return (
    <group>
      {/* Inner emissive core */}
      <mesh ref={shell}>
        <icosahedronGeometry args={[0.82, 2]} />
        <meshStandardMaterial
          color="#1e1b4b"
          emissive="#6d28d9"
          emissiveIntensity={0.85}
          roughness={0.25}
          metalness={0.35}
        />
      </mesh>
      {/* Wireframe twin shell — the "AST mirror" */}
      <mesh ref={wire} scale={1.42}>
        <icosahedronGeometry args={[0.82, 1]} />
        <meshBasicMaterial color={COLORS.cyan} wireframe transparent opacity={0.34} />
      </mesh>
      {/* Rim halo */}
      <mesh scale={1.9}>
        <sphereGeometry args={[0.82, 24, 24]} />
        <meshBasicMaterial
          color={COLORS.violet}
          transparent
          opacity={0.05}
          side={THREE.BackSide}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
        />
      </mesh>
      {/* Core light — makes the whole constellation feel lit from within */}
      <pointLight color={COLORS.violet} intensity={9} distance={9} decay={2} />
    </group>
  );
}

/* ── Symbol nodes ───────────────────────────────────────────────────────── */

function TwinNode({
  spec,
  index,
  selected,
  hovered,
  onSelect,
  onHover,
  movedRef,
  reduced,
}: {
  spec: NodeSpec;
  index: number;
  selected: boolean;
  hovered: boolean;
  onSelect: () => void;
  onHover: (index: number | null) => void;
  movedRef: RefObject<boolean>;
  reduced: boolean;
}) {
  const mesh = useRef<THREE.Mesh>(null);

  useFrame(({ clock }, delta) => {
    if (!mesh.current) return;
    const base = spec.position;
    // Natural float: each node drifts out of phase so the field never looks mechanical.
    if (!reduced) {
      const t = clock.elapsedTime;
      mesh.current.position.set(
        base[0] + Math.sin(t * spec.spin * 0.5 + spec.phase) * 0.09,
        base[1] + Math.sin(t * spec.spin * 0.34 + spec.phase * 2) * 0.12,
        base[2] + Math.cos(t * spec.spin * 0.45 + spec.phase) * 0.09,
      );
    }
    // Smooth scale spring toward hover/selection target.
    const target = selected ? 2.1 : hovered ? 1.7 : 1;
    const s = THREE.MathUtils.damp(mesh.current.scale.x, target, 8, delta);
    mesh.current.scale.setScalar(s);
  });

  const handleSelect = () => {
    // Ignore clicks that were actually short drags on the canvas.
    if (!movedRef?.current) onSelect();
  };

  return (
    <mesh
      ref={mesh}
      position={spec.position}
      onPointerDown={handleSelect}
      onPointerOver={() => onHover(index)}
      onPointerOut={() => onHover(null)}
    >
      <octahedronGeometry args={[spec.size, 0]} />
      <meshStandardMaterial
        color={selected || hovered ? '#e0f2fe' : spec.color}
        emissive={spec.color}
        emissiveIntensity={selected || hovered ? 2.4 : 0.9}
        roughness={0.3}
        metalness={0.2}
        flatShading
      />
    </mesh>
  );
}

/* ── Coupling edges ─────────────────────────────────────────────────────── */

function CouplingEdges({
  positions,
  focus,
  reduced,
}: {
  positions: Float32Array;
  focus: number | null;
  reduced: boolean;
}) {
  const geometry = useMemo(() => {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    return geo;
  }, [positions]);

  const material = useRef<THREE.LineBasicMaterial>(null);
  useFrame(({ clock }) => {
    if (!material.current) return;
    material.current.opacity = reduced ? 0.16 : 0.14 + Math.sin(clock.elapsedTime * 1.1) * 0.04;
  });

  // Highlight the edge to the core for the active node.
  const highlight = useMemo(() => {
    if (focus === null) return null;
    const start = focus * 6;
    return new Float32Array([...positions.slice(start, start + 6)]);
  }, [focus, positions]);

  return (
    <group>
      <lineSegments geometry={geometry} frustumCulled={false}>
        <lineBasicMaterial
          ref={material}
          color={COLORS.blue}
          transparent
          opacity={0.16}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
        />
      </lineSegments>
      {highlight && (
        <lineSegments frustumCulled={false}>
          <bufferGeometry>
            <bufferAttribute attach="attributes-position" args={[highlight, 3]} />
          </bufferGeometry>
          <lineBasicMaterial
            color={COLORS.cyan}
            transparent
            opacity={0.85}
            blending={THREE.AdditiveBlending}
            depthWrite={false}
          />
        </lineSegments>
      )}
    </group>
  );
}

/* ── Interaction rig: cursor-follow tilt + drag rotation with inertia ────── */

function Rig({
  reduced,
  movedRef,
  children,
}: {
  reduced: boolean;
  movedRef: RefObject<boolean>;
  children: React.ReactNode;
}) {
  const tilt = useRef<THREE.Group>(null); // damped cursor-follow
  const orbit = useRef<THREE.Group>(null); // auto-orbit + drag inertia
  const drag = useRef({ vx: 0, vy: 0, dragging: false, lastX: 0, lastY: 0 });
  const { gl } = useThree();

  useEffect(() => {
    const el = gl.domElement;
    const touch = matchMedia('(pointer: coarse)').matches;

    const down = (e: PointerEvent) => {
      drag.current.dragging = true;
      drag.current.lastX = e.clientX;
      drag.current.lastY = e.clientY;
      movedRef.current = false;
      // Only capture while dragging with a mouse; touch needs its scroll/zoom gestures.
      if (!touch) el.setPointerCapture(e.pointerId);
    };
    const move = (e: PointerEvent) => {
      if (!drag.current.dragging) return;
      const dx = e.clientX - drag.current.lastX;
      const dy = e.clientY - drag.current.lastY;
      if (Math.abs(dx) + Math.abs(dy) > 4) movedRef.current = true;
      drag.current.vy += dx * 0.00045;
      drag.current.vx += dy * 0.0003;
      drag.current.lastX = e.clientX;
      drag.current.lastY = e.clientY;
      // On touch we rotate directly so scrolling never fights the scene.
      if (touch && orbit.current) {
        orbit.current.rotation.x = THREE.MathUtils.clamp(orbit.current.rotation.x + dy * 0.0016, -0.7, 0.7);
        orbit.current.rotation.y += dx * 0.0022;
      }
    };
    const up = (e: PointerEvent) => {
      drag.current.dragging = false;
      if (el.hasPointerCapture(e.pointerId)) el.releasePointerCapture(e.pointerId);
    };
    el.addEventListener('pointerdown', down);
    el.addEventListener('pointermove', move);
    el.addEventListener('pointerup', up);
    el.addEventListener('pointercancel', up);
    return () => {
      el.removeEventListener('pointerdown', down);
      el.removeEventListener('pointermove', move);
      el.removeEventListener('pointerup', up);
      el.removeEventListener('pointercancel', up);
    };
  }, [gl, movedRef]);

  useFrame(({ pointer: ndc }, delta) => {
    if (reduced) return;
    if (tilt.current) {
      tilt.current.rotation.y = THREE.MathUtils.damp(tilt.current.rotation.y, ndc.x * 0.3, 3, delta);
      tilt.current.rotation.x = THREE.MathUtils.damp(tilt.current.rotation.x, ndc.y * 0.18, 3, delta);
    }
    if (orbit.current) {
      drag.current.vy = THREE.MathUtils.damp(drag.current.vy, 0, 1.6, delta);
      drag.current.vx = THREE.MathUtils.damp(drag.current.vx, 0, 1.6, delta);
      orbit.current.rotation.y += 0.035 * delta + drag.current.vy; // gentle auto-orbit + drag inertia
      orbit.current.rotation.x = THREE.MathUtils.clamp(
        orbit.current.rotation.x + drag.current.vx,
        -0.7,
        0.7,
      );
    }
  });

  return (
    <group ref={tilt}>
      <group ref={orbit}>{children}</group>
    </group>
  );
}

/* ── Canvas entry ───────────────────────────────────────────────────────── */

export default function DigitalTwinScene({ reduced = false }: { reduced?: boolean }) {
  const [hovered, setHovered] = useState<number | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const movedRef = useRef(false);
  const scene = useMemo(() => buildScene(), []);
  const focus = selected ?? hovered;

  return (
    <Canvas
      className="twin-canvas"
      dpr={[1, 1.75]}
      camera={{ position: [0, 0.9, 7.4], fov: 42 }}
      gl={{ alpha: true, antialias: true, powerPreference: 'high-performance' }}
      style={{ position: 'absolute', inset: 0 }}
      aria-label="Interactive 3D visualization of a repository knowledge graph. Drag to rotate, click a symbol to highlight its coupling to the core."
      role="img"
    >
      <ambientLight intensity={0.5} />
      <directionalLight position={[4, 6, 5]} intensity={1.1} color="#c7d2fe" />
      <directionalLight position={[-5, -3, -4]} intensity={0.55} color="#5eead4" />

      <Rig reduced={reduced} movedRef={movedRef}>
        <Float
          speed={reduced ? 0 : 1.15}
          rotationIntensity={reduced ? 0 : 0.22}
          floatIntensity={reduced ? 0 : 0.5}
          floatingRange={[-0.12, 0.14]}
        >
          <TwinCore reduced={reduced} />
          <CouplingEdges positions={scene.linePositions} focus={focus} reduced={reduced} />
          {scene.nodes.map((spec, i) => (
            <TwinNode
              key={i}
              spec={spec}
              index={i}
              selected={selected === i}
              hovered={hovered === i}
              onSelect={() => setSelected((cur) => (cur === i ? null : i))}
              onHover={setHovered}
              movedRef={movedRef}
              reduced={reduced}
            />
          ))}
        </Float>
        <Sparkles
          count={70}
          scale={[9, 5.5, 9]}
          size={2.2}
          speed={reduced ? 0 : 0.35}
          opacity={0.55}
          color="#93c5fd"
        />
      </Rig>
    </Canvas>
  );
}
