// The 3D view of a build: one instanced mesh per distinct block (its shape boxes merged), orbit controls, and a
// layer cut (RU.5). Coordinates are Minecraft's (x east, y up, z south); three.js uses the same handedness.
import { Canvas, useThree } from "@react-three/fiber";
import { OrbitControls, Stats } from "@react-three/drei";
import { useEffect, useLayoutEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import type { Box, Grid } from "./api";

const FULL: Box[] = [[0, 0, 0, 1, 1, 1]];

function geometryFor(parts: Box[]): THREE.BufferGeometry {
  const boxes = parts.map(([x0, y0, z0, x1, y1, z1]) => {
    const g = new THREE.BoxGeometry(x1 - x0, y1 - y0, z1 - z0);
    g.translate((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2);
    return g;
  });
  return boxes.length === 1 ? boxes[0] : mergeGeometries(boxes)!;
}

function BlockMesh({ positions, parts, color, opacity }:
  { positions: number[]; parts: Box[]; color: string; opacity: number }) {
  const ref = useRef<THREE.InstancedMesh>(null);
  const geometry = useMemo(() => geometryFor(parts), [parts]);
  const count = positions.length / 3;
  useLayoutEffect(() => {
    const m = new THREE.Matrix4();
    for (let i = 0; i < count; i++) {
      m.makeTranslation(positions[3 * i], positions[3 * i + 1], positions[3 * i + 2]);
      ref.current!.setMatrixAt(i, m);
    }
    ref.current!.instanceMatrix.needsUpdate = true;
    ref.current!.computeBoundingSphere();
  }, [positions, count]);
  return (
    <instancedMesh ref={ref} args={[geometry, undefined, count]} key={count}>
      <meshLambertMaterial color={color} transparent={opacity < 1} opacity={opacity} depthWrite={opacity >= 1} />
    </instancedMesh>
  );
}

function Blocks({ grid, layer }: { grid: Grid; layer: number }) {
  const groups = useMemo(() => {
    const byBlock = new Map<number, number[]>();
    const c = grid.cells;
    for (let i = 0; i < c.length; i += 4) {
      if (c[i + 1] > layer) continue;
      const list = byBlock.get(c[i + 3]) ?? [];
      list.push(c[i], c[i + 1], c[i + 2]);
      byBlock.set(c[i + 3], list);
    }
    return [...byBlock.entries()];
  }, [grid, layer]);
  const [w, , l] = grid.size;
  return (
    <group position={[-w / 2, 0, -l / 2]}>
      {groups.map(([id, positions]) => {
        const b = grid.blocks[id];
        return <BlockMesh key={`${id}:${positions.length}`} positions={positions} parts={b.parts ?? FULL}
          color={b.color ?? "#888"} opacity={b.opacity ?? 1} />;
      })}
    </group>
  );
}

// Frame the build when another one loads (frame changes) or it grows past the view: camera to the north-west,
// above, like the previews.
function Framing({ size, frame }: { size: [number, number, number]; frame: string }) {
  const { camera, controls } = useThree();
  const fitted = useRef<{ frame: string; d: number }>({ frame: "", d: 0 });
  const d = Math.max(size[0], size[1] * 1.3, size[2], 8);
  useEffect(() => {
    if (fitted.current.frame === frame && d <= fitted.current.d * 1.25) return;
    fitted.current = { frame, d };
    camera.position.set(-d * 0.95, d * 0.8, -d * 0.95);
    const c = controls as unknown as { target: THREE.Vector3; update: () => void } | null;
    c?.target.set(0, size[1] / 3, 0);
    c?.update();
  }, [camera, controls, d, frame, size]);
  return null;
}

export default function Viewport({ grid, layer, stats, frame }:
  { grid: Grid | null; layer: number; stats: boolean; frame: string }) {
  const size = grid?.size ?? [16, 16, 16];
  const d = Math.max(size[0], size[1], size[2], 8);
  return (
    <Canvas camera={{ position: [-d * 1.1, d * 0.9, -d * 1.1], fov: 45, near: 0.1, far: d * 20 }}
      gl={{ antialias: true }}>
      <color attach="background" args={["#1b1d22"]} />
      <ambientLight intensity={0.75} />
      <directionalLight position={[-0.6 * d, 2 * d, -0.9 * d]} intensity={1.6} />
      <directionalLight position={[d, d, d]} intensity={0.35} />
      <gridHelper args={[Math.ceil(d * 2), Math.ceil(d * 2), "#3a3f4a", "#2a2e36"]} position={[0, -0.01, 0]} />
      {grid && <Blocks grid={grid} layer={layer} />}
      <OrbitControls makeDefault target={[0, size[1] / 3, 0]} />
      <Framing size={size as [number, number, number]} frame={frame} />
      {stats && <Stats />}
    </Canvas>
  );
}
