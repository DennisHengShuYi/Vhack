import { Canvas } from '@react-three/fiber';
import { OrbitControls, Sky, Environment, Text } from '@react-three/drei';
import * as THREE from 'three';

type Drone = {
  id: string;
  x: number;
  y: number;
  status?: string;
  status_label?: string;
  returning_to_base?: boolean;
  is_waiting_response?: boolean;
  battery?: number;
};

type Survivor = {
  x: number;
  y: number;
  found?: boolean;
  rescued?: boolean;
  is_mobile?: boolean;
};

type Zone = {
  scanned_cells: boolean[][];
  hazard_cells: boolean[][];
  terrain_types: string[][];
  survivors: Survivor[];
};

type Props = {
  zone: Zone;
  drones: Drone[];
  baseX: number;
  baseY: number;
  showRtbOnly: boolean;
};

const GRID_W = 20;
const GRID_H = 15;
const CELL_SIZE = 1.0;
const MOUNTAIN_HEIGHT = 0.65;
const LAKE_DEPTH = -0.12;
const FLAT_BASE_HEIGHT = 0.08;
const TREE_DENSITY = 5;
const FOG_COLOR = '#7ea08f';
const FOG_NEAR = 12;
const FOG_FAR = 40;
const CAMERA_POSITION: [number, number, number] = [0, 26, 10];

function toWorld(x: number, y: number) {
  const halfW = (GRID_W - 1) / 2;
  const halfH = (GRID_H - 1) / 2;
  return {
    wx: (x - halfW) * CELL_SIZE,
    wz: (y - halfH) * CELL_SIZE,
  };
}

function terrainHeight(x: number, y: number, terrain: string) {
  const noise = Math.sin(x * 0.7) * 0.1 + Math.cos(y * 0.6) * 0.1;
  if (terrain === 'city') return MOUNTAIN_HEIGHT * 0.6 + noise;
  if (terrain === 'forest') return FLAT_BASE_HEIGHT + 0.15 + noise;
  if (terrain === 'lake') return LAKE_DEPTH;
  return FLAT_BASE_HEIGHT + noise;
}

function isReturning(drone: Drone) {
  return (
    drone?.returning_to_base ||
    String(drone?.status_label || '').toLowerCase().includes('rtb') ||
    String(drone?.status || '').toLowerCase() === 'returning'
  );
}

export default function Map3D({ zone, drones, baseX, baseY, showRtbOnly }: Props) {
  const visibleDrones = showRtbOnly ? drones.filter(isReturning) : drones;

  return (
    <div className="map-3d-shell" style={{ width: '100%', height: '100%', position: 'absolute', inset: 0 }}>
      <Canvas camera={{ position: CAMERA_POSITION, fov: 50 }} shadows>
        <fog attach="fog" args={[FOG_COLOR, FOG_NEAR, FOG_FAR]} />

        <ambientLight intensity={0.45} />
        <directionalLight
          position={[8, 15, 4]}
          intensity={1.2}
          castShadow
          shadow-mapSize-width={1024}
          shadow-mapSize-height={1024}
        />

        <Sky distance={450000} sunPosition={[5, 1, 8]} inclination={0.5} azimuth={0.15} />
        <Environment preset="forest" />

        <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow position={[0, -0.2, 0]}>
          <circleGeometry args={[20, 64]} />
          <meshStandardMaterial color="#47634a" roughness={0.95} metalness={0.05} />
        </mesh>

        {Array.from({ length: GRID_W * GRID_H }).map((_, i) => {
          const x = i % GRID_W;
          const y = Math.floor(i / GRID_W);
          const terrain = zone.terrain_types[y][x];
          const scanned = zone.scanned_cells[y][x];
          const hazard = zone.hazard_cells[y][x];
          const survivorAtPos = zone.survivors.find((s) => s.x === x && s.y === y);
          const isVictimFound = !!survivorAtPos?.found;
          const isVictimRescued = !!survivorAtPos?.rescued;
          const isVictimHidden = survivorAtPos && !isVictimFound && !isVictimRescued;

          const { wx, wz } = toWorld(x, y);
          const h = terrainHeight(x, y, terrain);

          // Base terrain color — scanned tints per terrain type instead of flat override
          let color = '#4b6b4f';
          let metalness = 0.02;
          let roughness = 0.9;
          if (terrain === 'city') { color = scanned ? '#9aab90' : '#8a8a7a'; metalness = 0.18; roughness = 0.65; }
          else if (terrain === 'forest') { color = scanned ? '#3a8050' : '#2a5c35'; }
          else if (terrain === 'lake') { color = '#1e4a7a'; metalness = 0.3; roughness = 0.15; }
          else { color = scanned ? '#55806a' : '#4b6b4f'; }
          if (hazard && terrain !== 'lake') color = '#7c2f2f';

          // Mini-building params for city cells
          const hasBldg = terrain === 'city' && !hazard && (x * 3 + y * 7) % 5 !== 0;
          const bldgH = 0.12 + ((x * 13 + y * 7) % 5) * 0.07;
          const bldgW = 0.28 + ((x * 5 + y * 11) % 3) * 0.08;

          // Forest tree positions (2 trees per cell if density matches)
          const hasTree1 = terrain === 'forest' && !hazard && (x + y) % TREE_DENSITY === 0;
          const hasTree2 = terrain === 'forest' && !hazard && (x * 2 + y) % (TREE_DENSITY + 1) === 0;

          return (
            <group key={`cell-${x}-${y}`}>
              {/* Terrain base block */}
              <mesh position={[wx, h / 2, wz]} castShadow receiveShadow>
                <boxGeometry args={[1.08, Math.max(0.06, h), 1.08]} />
                <meshStandardMaterial color={color} roughness={roughness} metalness={metalness} />
              </mesh>

              {/* Lake: transparent water surface */}
              {terrain === 'lake' && (
                <mesh position={[wx, -0.02, wz]} rotation={[-Math.PI / 2, 0, 0]}>
                  <planeGeometry args={[1.06, 1.06]} />
                  <meshStandardMaterial color="#3a90d8" transparent opacity={0.45} metalness={0.6} roughness={0.05} />
                </mesh>
              )}

              {/* City: small building on top */}
              {hasBldg && (
                <mesh position={[wx + (((x * 7) % 3) - 1) * 0.18, h + bldgH / 2, wz + (((y * 5) % 3) - 1) * 0.18]} castShadow>
                  <boxGeometry args={[bldgW, bldgH, bldgW]} />
                  <meshStandardMaterial color={scanned ? '#b0b8a0' : '#9a9a88'} roughness={0.5} metalness={0.25} />
                </mesh>
              )}

              {/* Forest tree 1 */}
              {hasTree1 && (
                <group position={[wx + 0.18, h + 0.12, wz - 0.08]}>
                  <mesh castShadow>
                    <cylinderGeometry args={[0.04, 0.07, 0.22, 8]} />
                    <meshStandardMaterial color="#5f472f" />
                  </mesh>
                  <mesh position={[0, 0.24, 0]} castShadow>
                    <coneGeometry args={[0.22, 0.5, 10]} />
                    <meshStandardMaterial color="#1a4a25" />
                  </mesh>
                </group>
              )}
              {/* Forest tree 2 (offset) */}
              {hasTree2 && (
                <group position={[wx - 0.15, h + 0.1, wz + 0.14]}>
                  <mesh castShadow>
                    <cylinderGeometry args={[0.035, 0.06, 0.18, 8]} />
                    <meshStandardMaterial color="#4a3520" />
                  </mesh>
                  <mesh position={[0, 0.18, 0]} castShadow>
                    <coneGeometry args={[0.17, 0.38, 10]} />
                    <meshStandardMaterial color="#163d1e" />
                  </mesh>
                </group>
              )}

              {survivorAtPos && !isVictimRescued && (
                <mesh position={[wx, h + 0.32, wz]} castShadow>
                  <sphereGeometry args={[0.12, 16, 16]} />
                  {survivorAtPos.is_mobile && !survivorAtPos.found
                    ? <meshStandardMaterial color="#00f3ff" emissive="#007a80" emissiveIntensity={1.2} />
                    : <meshStandardMaterial color="#ff3d3d" emissive="#800000" emissiveIntensity={0.8} />
                  }
                </mesh>
              )}

              {isVictimRescued && (
                <group position={[wx, h + 0.05, wz]}>
                  {/* Ground Circle */}
                  <mesh receiveShadow rotation={[-Math.PI / 2, 0, 0]}>
                    <circleGeometry args={[0.25, 16]} />
                    <meshStandardMaterial color="#00ff88" transparent opacity={0.3} />
                  </mesh>
                  {/* Flag Pole */}
                  <mesh position={[-0.15, 0.4, -0.15]} castShadow>
                    <cylinderGeometry args={[0.015, 0.015, 0.8, 8]} />
                    <meshStandardMaterial color="#ddd" metalness={0.8} />
                  </mesh>
                  {/* Flag Cloth */}
                  <mesh position={[0, 0.7, -0.15]} castShadow>
                    <boxGeometry args={[0.3, 0.2, 0.02]} />
                    <meshStandardMaterial color="#00ff88" emissive="#004422" emissiveIntensity={0.5} />
                  </mesh>
                </group>
              )}
            </group>
          );
        })}

        {visibleDrones.map((drone) => {
          const terrain = zone.terrain_types[drone.y][drone.x];
          const { wx, wz } = toWorld(drone.x, drone.y);
          const h = terrainHeight(drone.x, drone.y, terrain);
          const returning = isReturning(drone);
          const bodyColor = returning ? '#ffb300' : '#00c8d4';
          const rotorColor = returning ? '#ffd460' : '#00f3ff';
          const armColor = returning ? '#cc8800' : '#0099aa';

          const arms = [
            [0.28, 0, 0.28, Math.PI / 4],
            [-0.28, 0, 0.28, -Math.PI / 4],
            [0.28, 0, -0.28, -Math.PI / 4],
            [-0.28, 0, -0.28, Math.PI / 4],
          ];

          return (
            <group key={drone.id} position={[wx, h + 0.38, wz]}>
              {/* Central body */}
              <mesh castShadow>
                <boxGeometry args={[0.22, 0.09, 0.22]} />
                <meshStandardMaterial color={bodyColor} emissive={returning ? '#7a5000' : '#005588'} emissiveIntensity={0.5} metalness={0.6} roughness={0.3} />
              </mesh>
              {/* Camera dome */}
              <mesh position={[0, -0.06, 0]}>
                <sphereGeometry args={[0.055, 12, 8, 0, Math.PI * 2, 0, Math.PI / 2]} />
                <meshStandardMaterial color="#111" metalness={0.8} roughness={0.2} />
              </mesh>

              {/* 4 Arms + Rotors */}
              {arms.map(([ax, ay, az, rot], idx) => (
                <group key={idx} position={[ax as number, ay as number, az as number]}>
                  <mesh rotation={[0, rot as number, 0]}>
                    <boxGeometry args={[0.32, 0.03, 0.05]} />
                    <meshStandardMaterial color={armColor} metalness={0.5} roughness={0.4} />
                  </mesh>
                  <mesh position={[0, 0.04, 0]}>
                    <cylinderGeometry args={[0.04, 0.04, 0.03, 10]} />
                    <meshStandardMaterial color={bodyColor} metalness={0.7} roughness={0.2} />
                  </mesh>
                  <mesh position={[0, 0.06, 0]} rotation={[Math.PI / 2, 0, 0]}>
                    <ringGeometry args={[0.04, 0.17, 20]} />
                    <meshBasicMaterial color={rotorColor} side={THREE.DoubleSide} transparent opacity={0.55} />
                  </mesh>
                </group>
              ))}

              {/* Landing legs */}
              {[[-0.1, -0.1], [0.1, -0.1], [-0.1, 0.1], [0.1, 0.1]].map(([lx, lz], idx) => (
                <mesh key={`leg-${idx}`} position={[lx, -0.09, lz]}>
                  <cylinderGeometry args={[0.01, 0.01, 0.08, 6]} />
                  <meshStandardMaterial color="#333" />
                </mesh>
              ))}

              {/* Floating Label */}
              <Text
                position={[0, 0.38, 0]}
                fontSize={0.22}
                color={rotorColor}
                anchorX="center"
                anchorY="middle"
                outlineWidth={0.02}
                outlineColor="#000"
              >
                {drone.id.split('-')[1]}
              </Text>
            </group>
          );
        })}

        {(() => {
          const terrain = zone.terrain_types[baseY][baseX];
          const { wx, wz } = toWorld(baseX, baseY);
          const h = terrainHeight(baseX, baseY, terrain);
          return (
            <group position={[wx, h, wz]}>
              <mesh position={[0, 0.06, 0]} castShadow receiveShadow>
                <cylinderGeometry args={[0.55, 0.55, 0.07, 32]} />
                <meshStandardMaterial color="#1a3a3a" metalness={0.8} roughness={0.3} />
              </mesh>
              <mesh position={[0, 0.1, 0]} rotation={[-Math.PI / 2, 0, 0]}>
                <ringGeometry args={[0.4, 0.52, 32]} />
                <meshBasicMaterial color="#00f3ff" side={THREE.DoubleSide} transparent opacity={0.5} />
              </mesh>
              <mesh position={[0, 0.28, 0]} castShadow>
                <cylinderGeometry args={[0.22, 0.28, 0.44, 24]} />
                <meshStandardMaterial color="#00f3ff" emissive="#008188" emissiveIntensity={0.9} metalness={0.5} roughness={0.2} />
              </mesh>
              <mesh position={[0, 0.7, 0]} castShadow>
                <cylinderGeometry args={[0.02, 0.025, 0.8, 8]} />
                <meshStandardMaterial color="#aaddff" metalness={0.9} roughness={0.1} />
              </mesh>
              <mesh position={[0, 1.12, 0]}>
                <sphereGeometry args={[0.05, 12, 12]} />
                <meshBasicMaterial color="#ffffff" />
              </mesh>
              <pointLight position={[0, 1.1, 0]} color="#00f3ff" intensity={2} distance={3} />
              <mesh position={[0, 0.11, 0]} rotation={[Math.PI / 2, 0, 0]}>
                <ringGeometry args={[0.28, 0.35, 32]} />
                <meshBasicMaterial color="#00f3ff" side={THREE.DoubleSide} transparent opacity={0.8} />
              </mesh>
              <mesh position={[0, 0.09, 0]} rotation={[Math.PI / 2, 0, 0]}>
                <ringGeometry args={[0.5, 0.6, 32]} />
                <meshBasicMaterial color="#00f3ff" side={THREE.DoubleSide} transparent opacity={0.4} />
              </mesh>
              <Text
                position={[0, 1.35, 0]}
                fontSize={0.28}
                color="#00f3ff"
                anchorX="center"
                anchorY="middle"
                outlineWidth={0.025}
                outlineColor="#000"
              >
                BASE
              </Text>
            </group>
          );
        })()}

        <OrbitControls makeDefault enablePan={true} minDistance={8} maxDistance={24} maxPolarAngle={Math.PI / 2.1} />
      </Canvas>
    </div>
  );
}
