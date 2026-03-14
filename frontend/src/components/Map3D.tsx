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

const GRID_SIZE = 10;
const CELL_SIZE = 1.2;              // World units per grid cell
const MOUNTAIN_HEIGHT = 0.65;       // Base height for mountain terrain
const LAKE_DEPTH = -0.12;          // Depth for lake terrain (negative = sunken)
const FLAT_BASE_HEIGHT = 0.08;     // Base height for flat terrain
const TREE_DENSITY = 5;            // 1 tree per N cells on flat non-hazard terrain
const FOG_COLOR = '#7ea08f';       // Fog/sky ambient colour
const FOG_NEAR = 12;               // Fog start distance
const FOG_FAR = 40;                // Fog end distance
const CAMERA_POSITION: [number, number, number] = [0, 18, 6]; // Initial camera position (top-down isometric)

function toWorld(x: number, y: number) {
  const half = (GRID_SIZE - 1) / 2;
  return {
    wx: (x - half) * CELL_SIZE,
    wz: (y - half) * CELL_SIZE,
  };
}

function terrainHeight(x: number, y: number, terrain: string) {
  const noise = Math.sin(x * 0.7) * 0.1 + Math.cos(y * 0.6) * 0.1;
  if (terrain === 'mountain') return MOUNTAIN_HEIGHT + noise;
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

        {Array.from({ length: GRID_SIZE * GRID_SIZE }).map((_, i) => {
          const x = i % GRID_SIZE;
          const y = Math.floor(i / GRID_SIZE);
          const terrain = zone.terrain_types[y][x];
          const scanned = zone.scanned_cells[y][x];
          const hazard = zone.hazard_cells[y][x];
          const survivorFound = zone.survivors.some((s) => s.x === x && s.y === y && s.found && !s.rescued);

          const { wx, wz } = toWorld(x, y);
          const h = terrainHeight(x, y, terrain);

          let color = '#4b6b4f';
          if (terrain === 'mountain') color = '#6b5f7f';
          if (terrain === 'lake') color = '#355f8b';
          if (scanned) color = '#55806a';
          if (hazard) color = '#7c2f2f';

          return (
            <group key={`cell-${x}-${y}`}>
              <mesh position={[wx, h / 2, wz]} castShadow receiveShadow>
                <boxGeometry args={[1.08, Math.max(0.06, h), 1.08]} />
                <meshStandardMaterial color={color} roughness={0.9} metalness={0.02} />
              </mesh>

              {terrain === 'flat' && !hazard && (x + y) % TREE_DENSITY === 0 && (
                <group position={[wx + 0.18, h + 0.12, wz - 0.08]}>
                  <mesh castShadow>
                    <cylinderGeometry args={[0.05, 0.08, 0.25, 8]} />
                    <meshStandardMaterial color="#5f472f" />
                  </mesh>
                  <mesh position={[0, 0.22, 0]} castShadow>
                    <coneGeometry args={[0.2, 0.45, 10]} />
                    <meshStandardMaterial color="#2f6a3f" />
                  </mesh>
                </group>
              )}

              {survivorFound && (
                <mesh position={[wx, h + 0.32, wz]} castShadow>
                  <sphereGeometry args={[0.12, 16, 16]} />
                  <meshStandardMaterial color="#ffb300" emissive="#8a5f00" emissiveIntensity={0.8} />
                </mesh>
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

          // 4 arm directions: NE, NW, SE, SW
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
                  {/* Arm */}
                  <mesh rotation={[0, rot as number, 0]}>
                    <boxGeometry args={[0.32, 0.03, 0.05]} />
                    <meshStandardMaterial color={armColor} metalness={0.5} roughness={0.4} />
                  </mesh>
                  {/* Rotor hub */}
                  <mesh position={[0, 0.04, 0]}>
                    <cylinderGeometry args={[0.04, 0.04, 0.03, 10]} />
                    <meshStandardMaterial color={bodyColor} metalness={0.7} roughness={0.2} />
                  </mesh>
                  {/* Rotor disc */}
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
              {/* Helipad platform base */}
              <mesh position={[0, 0.06, 0]} castShadow receiveShadow>
                <cylinderGeometry args={[0.55, 0.55, 0.07, 32]} />
                <meshStandardMaterial color="#1a3a3a" metalness={0.8} roughness={0.3} />
              </mesh>
              {/* Helipad H marking */}
              <mesh position={[0, 0.1, 0]} rotation={[-Math.PI / 2, 0, 0]}>
                <ringGeometry args={[0.4, 0.52, 32]} />
                <meshBasicMaterial color="#00f3ff" side={THREE.DoubleSide} transparent opacity={0.5} />
              </mesh>

              {/* Main cylinder body */}
              <mesh position={[0, 0.28, 0]} castShadow>
                <cylinderGeometry args={[0.22, 0.28, 0.44, 24]} />
                <meshStandardMaterial color="#00f3ff" emissive="#008188" emissiveIntensity={0.9} metalness={0.5} roughness={0.2} />
              </mesh>

              {/* Antenna tower */}
              <mesh position={[0, 0.7, 0]} castShadow>
                <cylinderGeometry args={[0.02, 0.025, 0.8, 8]} />
                <meshStandardMaterial color="#aaddff" metalness={0.9} roughness={0.1} />
              </mesh>
              {/* Beacon light on top of antenna */}
              <mesh position={[0, 1.12, 0]}>
                <sphereGeometry args={[0.05, 12, 12]} />
                <meshBasicMaterial color="#ffffff" />
              </mesh>
              <pointLight position={[0, 1.1, 0]} color="#00f3ff" intensity={2} distance={3} />

              {/* Inner glowing ring */}
              <mesh position={[0, 0.11, 0]} rotation={[Math.PI / 2, 0, 0]}>
                <ringGeometry args={[0.28, 0.35, 32]} />
                <meshBasicMaterial color="#00f3ff" side={THREE.DoubleSide} transparent opacity={0.8} />
              </mesh>
              {/* Outer glowing ring */}
              <mesh position={[0, 0.09, 0]} rotation={[Math.PI / 2, 0, 0]}>
                <ringGeometry args={[0.5, 0.6, 32]} />
                <meshBasicMaterial color="#00f3ff" side={THREE.DoubleSide} transparent opacity={0.4} />
              </mesh>

              {/* BASE label */}
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
