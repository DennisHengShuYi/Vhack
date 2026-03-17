import { Crosshair, Cpu, Power } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

interface GridMapProps {
  is3DView: boolean;
  zone: any;
  drones: any[];
  stats: any;
  baseX: number;
  baseY: number;
  showRtbOnly: boolean;
  gridW: number;
  gridH: number;
  Map3D: any;
}

export default function GridMap({
  is3DView,
  zone,
  drones,
  stats,
  baseX,
  baseY,
  showRtbOnly,
  gridW,
  gridH,
  Map3D
}: GridMapProps) {
  
  const isReturningDrone = (drone: any) =>
    drone?.returning_to_base ||
    String(drone?.status_label || '').toLowerCase().includes('rtb') ||
    String(drone?.status || '').toLowerCase() === 'returning';

  return (
    <section className={`center-map glass ${is3DView ? 'view-3d' : ''}`}>
      <div className="map-overlay-header">
        <span className="font-mono text-xs"><Crosshair size={12} /> OVERLAY</span>
        <div className="legend">
          {is3DView ? (
            <>
              <span className="legend-item"><div className="dot" style={{ background: '#6b5f7f' }}></div> MOUNTAIN</span>
              <span className="legend-item"><div className="dot" style={{ background: '#355f8b' }}></div> LAKE</span>
              <span className="legend-item"><div className="dot" style={{ background: '#7c2f2f' }}></div> HAZARD</span>
              <span className="legend-item"><div className="dot" style={{ background: '#00f3ff' }}></div> BASE</span>
              <span className="legend-item"><div className="dot" style={{ border: '2px solid #00f3ff', background: 'transparent' }}></div> DRONE</span>
              {stats?.mission_active && <>
                <span className="legend-item"><div className="dot" style={{ background: '#ff3d3d', boxShadow: '0 0 5px #ff3d3d' }}></div> VICTIM</span>
                <span className="legend-item"><div className="dot" style={{ background: 'var(--accent-success)', boxShadow: '0 0 5px var(--accent-success)' }}></div> RESCUED</span>
              </>}
            </>
          ) : (
            <>
              <span className="legend-item"><div className="dot" style={{ background: 'rgba(107, 95, 127, 0.8)' }}></div> MOUNTAIN</span>
              <span className="legend-item"><div className="dot" style={{ background: 'rgba(53, 95, 139, 0.8)' }}></div> LAKE</span>
              <span className="legend-item"><div className="dot" style={{ border: '1px solid #ff3d3d', background: 'rgba(124, 47, 47, 0.5)' }}></div> HAZARD</span>
              <span className="legend-item"><div className="dot" style={{ background: 'var(--accent-cyan)' }}></div> BASE</span>
              <span className="legend-item"><div className="dot" style={{ background: 'rgba(0, 243, 255, 0.7)' }}></div> DRONE</span>
              {stats?.mission_active && <>
                <span className="legend-item"><div className="dot" style={{ background: '#ff3d3d', boxShadow: '0 0 5px #ff3d3d' }}></div> VICTIM</span>
                <span className="legend-item"><div className="dot" style={{ background: 'var(--accent-success)', boxShadow: '0 0 5px var(--accent-success)' }}></div> RESCUED</span>
              </>}
            </>
          )}
        </div>
      </div>

      {is3DView ? (
        <div className="map-3d-wrapper" style={{ flex: 1, position: 'relative', borderRadius: '8px', overflow: 'hidden', border: '1px solid rgba(0, 243, 255, 0.2)' }}>
          <Map3D
            zone={zone}
            drones={drones || []}
            baseX={baseX}
            baseY={baseY}
            showRtbOnly={showRtbOnly}
          />
        </div>
      ) : (
        <div className="grid-container">
          {Array.from({ length: gridW * gridH }).map((_, i) => {
            const x = i % gridW;
            const y = Math.floor(i / gridW);
            const isScanned = zone.scanned_cells[y][x];
            const isBase = x === baseX && y === baseY;
            const dronesAtPos = drones.filter((d: any) => d.x === x && d.y === y);
            const survivorAtPos = stats?.mission_active
              ? zone.survivors.find((s: any) => s.x === x && s.y === y)
              : null;
            const isVictimRescued = !!survivorAtPos?.rescued;

            const terrain = zone.terrain_types[y][x];
            const hazard = zone.hazard_cells[y][x];

            let cellClass = "";
            if (terrain === 'mountain') cellClass += " mountain";
            else if (terrain === 'lake') cellClass += " lake";
            if (hazard) cellClass += " hazard";

            if (isBase) cellClass += " base-cell";
            else if (survivorAtPos) {
              if (isVictimRescued) cellClass += " rescued-cell";
              else cellClass += " victim-cell";
            } else if (isScanned) {
              cellClass += " scanned";
            }

            return (
              <div key={i} className={`grid-cell${cellClass}`}>
                {stats?.mission_active && zone.survivors.find((s: any) => s.x === x && s.y === y && !s.found && !s.rescued) && (
                  <div className="victim-dot" />
                )}
                <AnimatePresence>
                  {survivorAtPos && !isVictimRescued && (
                    <motion.div
                      initial={{ scale: 0 }}
                      animate={{ scale: 1 }}
                      className="victim-found-marker"
                      style={{ position: 'absolute', zIndex: 12 }}
                    >
                      <Crosshair className="animate-pulse" size={13} />
                    </motion.div>
                  )}
                </AnimatePresence>

                {dronesAtPos.length === 1 && (() => {
                  const d = dronesAtPos[0];
                  const returning = isReturningDrone(d);
                  return (
                    <motion.div
                      layoutId={`drone-${d.id}`}
                      className={`drone-marker ${d.is_waiting_response ? 'special' : ''} ${returning ? 'returning' : ''} ${showRtbOnly && !returning ? 'dimmed' : ''}`}
                      title={d.id}
                    >
                      <div className="content-wrapper">
                        <Cpu size={14} />
                        <span className="d-label font-mono">{d.id.split('-')[1]}</span>
                      </div>
                    </motion.div>
                  );
                })()}
                {dronesAtPos.length > 1 && (
                  <div
                    className={`drone-marker multi ${dronesAtPos.some(isReturningDrone) ? 'returning' : ''} ${showRtbOnly && !dronesAtPos.some(isReturningDrone) ? 'dimmed' : ''}`}
                    title={dronesAtPos.map(d => d.id).join(', ')}
                  >
                    <div className="content-wrapper">
                      <span className="d-label font-mono">×{dronesAtPos.length}</span>
                      <span className="d-label font-mono" style={{ fontSize: '0.55rem', opacity: 0.85 }}>
                        {dronesAtPos.map(d => d.id.split('-')[1]).join('·')}
                      </span>
                    </div>
                  </div>
                )}
                {isBase && (
                  <div className="base-marker">
                    <Power size={11} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
