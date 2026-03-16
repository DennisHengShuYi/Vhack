import { useState, useEffect, useRef } from 'react';
import {
  Shield,
  Cpu,

  Search,
  Battery,
  Activity,
  Map as MapIcon,
  History,
  AlertTriangle,
  Crosshair,
  Navigation,
  CheckCircle2,
  RefreshCcw,
  Volume2,
  Send,
  Zap,
  Power,
  Wifi,
  WifiOff
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import Map3D from './components/Map3D';

// --- Constants ---
const API_BASE = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";
const GRID_W = 20;
const GRID_H = 15;
const POLL_INTERVAL_MS = 800;
const LOW_BATTERY_PCT = 25;

// --- Components ---

/**
 * Main Sentinel Mission Dashboard
 */
export default function App() {
  const [state, setState] = useState<any>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [connectionStatus, setConnectionStatus] = useState<'connected' | 'disconnected'>('disconnected');
  const [operatorMsg, setOperatorMsg] = useState("");
  const [isDeploying, setIsDeploying] = useState(false);
  const [activeDroneId, setActiveDroneId] = useState<string | null>(null);
  const [logFilter, setLogFilter] = useState<'all' | 'warn' | 'error' | 'victim_found' | 'ai'>('ai');
  const [showRtbOnly, setShowRtbOnly] = useState(false);
  const [is3DView, setIs3DView] = useState(false);
  const [victimCount, setVictimCount] = useState(10);

  const logEndRef = useRef<HTMLDivElement>(null);
  const recognitionRef = useRef<any>(null);
  const autoRescuedRef = useRef<Set<string>>(new Set());

  // Auto-rescue victims (popup removed temporarily)
  useEffect(() => {
    const waiting = state?.drones?.find((d: any) => d.is_waiting_response);
    if (waiting && !autoRescuedRef.current.has(waiting.id)) {
      autoRescuedRef.current.add(waiting.id);
      fetch(`${API_BASE}/victim-response?drone_id=${waiting.id}`, { method: 'POST' });
    }
    if (!waiting) autoRescuedRef.current.clear();
  }, [state]);

  // Poll state every 800ms
  useEffect(() => {
    const fetchData = async () => {
      try {
        const resp = await fetch(`${API_BASE}/state`);
        const data = await resp.json();
        setState(data);
        setIsLoading(false);
        setConnectionStatus('connected');
      } catch (err) {
        console.error("Fetch failed:", err);
        setConnectionStatus('disconnected');
      }
    };

    fetchData();
    const interval = setInterval(fetchData, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, []);

  const runMission = async () => {
    setIsDeploying(true);
    await fetch(`${API_BASE}/reset?num_victims=${victimCount}`, { method: 'POST' });
    await fetch(`${API_BASE}/run-mission`, { method: 'POST' });
    setTimeout(() => setIsDeploying(false), 2000);
  };

  const [isTalking, setIsTalking] = useState<boolean | null>(null);
  const [isRecording, setIsRecording] = useState(false);
  const [transcription, setTranscription] = useState("");
  const [speechError, setSpeechError] = useState<string | null>(null);

  const toggleVoiceCapture = () => {
    setSpeechError(null);
    if (isRecording) {
      if (recognitionRef.current) {
        recognitionRef.current.onend = null;
        recognitionRef.current.stop();
      }
      setIsRecording(false);
      return;
    }

    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (SpeechRecognition) {
      try {
        const recognition = new SpeechRecognition();
        recognitionRef.current = recognition;
        recognition.continuous = true;
        recognition.interimResults = true;
        recognition.lang = 'en-US';

        recognition.onstart = () => {
          setIsRecording(true);
        };

        recognition.onresult = (event: any) => {
          let currentTranscription = '';
          for (let i = 0; i < event.results.length; i++) {
            currentTranscription += event.results[i][0].transcript;
          }
          if (currentTranscription) {
            setTranscription(currentTranscription);
            setOperatorMsg(currentTranscription);
          }
        };

        recognition.onerror = (event: any) => {
          setSpeechError(`Error: ${event.error}. Check microphone permissions.`);
          setIsRecording(false);
        };

        recognition.onend = () => {
          setIsRecording(false);
        };

        recognition.start();
      } catch (_err) {
        setSpeechError("Failed to initialize speech recognition.");
        setIsRecording(false);
      }
    } else {
      setSpeechError("Web Speech API not supported in this browser.");
      setIsRecording(true);
      setTimeout(() => {
        setTranscription("Simulated: My friend is at grid 10");
        setOperatorMsg("My friend is at grid 10");
        setIsRecording(false);
      }, 3000);
    }
  };

  const stopMission = async () => {
    await fetch(`${API_BASE}/stop-mission`, { method: 'POST' });
  };

  const resetMission = async () => {
    await fetch(`${API_BASE}/reset`, { method: 'POST' });
    setActiveDroneId(null);
    setIsTalking(null);
  };

  const respondToVictim = async (droneId: string) => {
    await fetch(`${API_BASE}/victim-response?drone_id=${droneId}&operator_message=${encodeURIComponent(operatorMsg)}`, { method: 'POST' });
    setOperatorMsg("");
    setIsTalking(null);
    setTranscription("");
  };

  const guideVictim = async (droneId: string) => {
    await fetch(`${API_BASE}/guide-victim?drone_id=${droneId}`, { method: 'POST' });
    setIsTalking(null);
  };


  if (isLoading) return <div className="loading-container"><Zap className="animate-pulse" /> INITIALIZING SENTINEL...</div>;

  const { stats, drones, zone, log, base_station } = state || {};
  const baseX = base_station?.x ?? 0;
  const baseY = base_station?.y ?? 0;
const waitingDrone = drones?.find((d: any) => d.is_waiting_response);
  const isReturningDrone = (drone: any) =>
    drone?.returning_to_base ||
    String(drone?.status_label || '').toLowerCase().includes('rtb') ||
    String(drone?.status || '').toLowerCase() === 'returning';
  const displayedDrones = showRtbOnly ? (drones || []).filter(isReturningDrone) : (drones || []);
  const filteredLog = (log || []).filter((entry: any) => {
    if (logFilter === 'all') return true;
    return entry.level?.toLowerCase() === logFilter;
  });

  return (
    <div className="app-container">
      {/* --- HUD HEADER --- */}
      <header className="hud-header glass">
        <div className="brand">
          <Shield className="brand-logo" />
          <div className="brand-text">
            <h1>SENTINEL COMMAND</h1>
            <span className="subtitle">First Responder Swarm Intelligence v2.0.0</span>
          </div>
        </div>

        <div className="global-stats">
          <div className={`conn-badge ${connectionStatus}`}>
            {connectionStatus === 'connected'
              ? <><Wifi size={13} /> ONLINE</>
              : <><WifiOff size={13} /> OFFLINE</>}
          </div>
          <StatBox icon={<MapIcon size={14} />} label="COVERAGE" value={`${stats.coverage_pct}%`} color="cyan" />
          <StatBox icon={<Search size={14} />} label="FOUND" value={`${stats.victims_found}/${stats.total_victims}`} color="amber" />
          <StatBox icon={<CheckCircle2 size={14} />} label="RESCUED" value={`${stats.victims_rescued}`} color="success" />
          <div className="mission-timer font-mono">{stats.elapsed_ts}</div>
        </div>

        <div className="header-actions">
          {!stats.mission_active && (
            <div className="victim-stepper">
              <span className="victim-stepper-label">SURVIVORS</span>
              <div className="stepper-control">
                <button className="stepper-btn" onClick={() => setVictimCount(c => Math.max(1, c - 1))}>−</button>
                <span className="stepper-value font-mono">{victimCount}</span>
                <button className="stepper-btn" onClick={() => setVictimCount(c => Math.min(50, c + 1))}>+</button>
              </div>
            </div>
          )}
          {stats.mission_active ? (
            <button className="cyber-button danger" onClick={stopMission}>
              STOP MISSION
            </button>
          ) : (
            <button className="cyber-button primary" onClick={runMission} disabled={isDeploying}>
              {isDeploying ? <RefreshCcw className="animate-spin" size={16} /> : "DEPLOY SWARM"}
            </button>
          )}
          <button className={`cyber-button toggle-3d ${is3DView ? 'active' : ''}`} onClick={() => setIs3DView(p => !p)}>
            3D VIEW
          </button>
          <button className="cyber-button secondary" onClick={resetMission} disabled={stats.mission_active}>RESET</button>
        </div>
      </header>

      {/* --- MAIN LAYOUT --- */}
      <main className="main-content">

        {/* Left Side: Fleet Status */}
        <section className="side-panel">
          <div className="panel-section-header glass">
            <Activity size={14} /> FLEET STATUS
            <div className="fleet-controls">
              <button className={`toggle-btn ${showRtbOnly ? 'active' : ''}`} onClick={() => setShowRtbOnly((v) => !v)}>
                {showRtbOnly ? 'RTB ONLY' : 'ALL'}
              </button>
              <span className="telemetry-count">{displayedDrones.length}</span>
            </div>
          </div>
          <div className="tab-content glass scroll-area">
            <div className="drone-list">
              {displayedDrones.map((drone: any) => (
                <motion.div
                  key={drone.id}
                  className={`drone-card ${activeDroneId === drone.id ? 'active' : ''} ${drone.is_waiting_response ? 'alert' : ''}`}
                  whileHover={{ scale: 1.02 }}
                  onClick={() => setActiveDroneId(drone.id)}
                >
                  <div className="drone-card-header">
                    <span className="drone-id font-mono">{drone.id}</span>
                    <div className="flex-row gap-2 items-center">
                      <span className="text-xs opacity-60">{drone.battery.toFixed(0)}%</span>
                      <div className={`status-dot ${drone.status_label.toLowerCase().replace(/ /g, '-')}`}></div>
                    </div>
                  </div>
                  <div className="drone-card-body">
                    <div className="drone-telemetry">
                      <div className="tel-row">
                        <Battery size={14} />
                        <div className="battery-bar-container">
                          <div className={`battery-fill ${drone.battery < LOW_BATTERY_PCT ? 'critical' : ''}`} style={{ width: `${drone.battery}%` }}></div>
                        </div>
                        <span className="font-mono text-xs">{drone.battery.toFixed(0)}%</span>
                      </div>
                      <div className="tel-row">
                        <Navigation size={14} />
                        <span className="font-mono text-xs">({drone.x}, {drone.y}) · {drone.terrain?.toUpperCase() ?? 'N/A'}</span>
                      </div>
                      <div className={`status-chip ${drone.status_label.toLowerCase().replace(/ /g, '-').replace(/[^a-z0-9-]/g, '')}`}>
                        {drone.status_label}
                      </div>
                    </div>
                  </div>
                </motion.div>
              ))}
            </div>
          </div>
        </section>

        {/* Center: Map */}
        <section className={`center-map glass ${is3DView ? 'view-3d' : ''}`}>
          <div className="map-overlay-header">
            <span className="font-mono text-xs"><Crosshair size={12} /> OVERLAY</span>
            <div className="legend">
              {is3DView ? (
                <>
                  <span className="legend-item"><div className="dot" style={{ background: '#4b6b4f' }}></div> FLAT</span>
                  <span className="legend-item"><div className="dot" style={{ background: '#55806a' }}></div> SCANNED</span>
                  <span className="legend-item"><div className="dot" style={{ background: '#6b5f7f' }}></div> MOUNTAIN</span>
                  <span className="legend-item"><div className="dot" style={{ background: '#355f8b' }}></div> LAKE</span>
                  <span className="legend-item"><div className="dot" style={{ background: '#7c2f2f' }}></div> HAZARD</span>
                  <span className="legend-item"><div className="dot" style={{ background: '#00f3ff' }}></div> BASE</span>
                  <span className="legend-item"><div className="dot" style={{ background: '#ffb300' }}></div> VICTIM</span>
                </>
              ) : (
                <>
                  <span className="legend-item"><div className="dot base"></div> BASE</span>
                  <span className="legend-item"><div className="dot" style={{ background: 'rgba(0,220,200,0.4)', border: '1px solid rgba(0,220,200,0.3)' }}></div> SCANNED</span>
                  <span className="legend-item"><div className="dot" style={{ background: 'rgba(0,243,255,0.7)' }}></div> DRONE</span>
                  {stats.mission_active && <>
                    <span className="legend-item"><div className="dot victim-hidden"></div> VICTIM</span>
                    <span className="legend-item"><div className="dot victim-found-dot"></div> DETECTED</span>
                    <span className="legend-item"><div className="dot" style={{ background: 'rgba(0,200,100,0.5)', border: '1px solid rgba(0,200,100,0.4)' }}></div> RESCUED</span>
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
              {Array.from({ length: GRID_W * GRID_H }).map((_, i) => {
                const x = i % GRID_W;
                const y = Math.floor(i / GRID_W);
                const isScanned = zone.scanned_cells[y][x];
                const isBase = x === baseX && y === baseY;
                const dronesAtPos = drones.filter((d: any) => d.x === x && d.y === y);
                // Permanent victim color: include rescued survivors so the cell stays colored
                const survivorAtPos = stats.mission_active
                  ? zone.survivors.find((s: any) => s.x === x && s.y === y && s.found)
                  : null;
                const isVictimRescued = !!survivorAtPos?.rescued;

                return (
                  <div key={i} className={`grid-cell${isBase ? ' base-cell' : ''}${survivorAtPos ? (isVictimRescued ? ' rescued-cell' : ' victim-cell') : (isScanned ? ' scanned' : '')}`}>
                    {stats.mission_active && zone.survivors.find((s: any) => s.x === x && s.y === y && !s.found && !s.rescued) && (
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

        {/* Right Side: Agent Reasoning Log */}
        <section className="log-panel">
          <div className="panel-section-header glass">
            <History size={14} /> SENTINEL REASONING LOG
            <div className="log-filter-group">
              <button className={`log-filter-btn ${logFilter === 'ai' ? 'active' : ''}`} onClick={() => setLogFilter('ai')}>AI</button>
              <button className={`log-filter-btn ${logFilter === 'all' ? 'active' : ''}`} onClick={() => setLogFilter('all')}>ALL</button>
              <button className={`log-filter-btn ${logFilter === 'warn' ? 'active' : ''}`} onClick={() => setLogFilter('warn')}>WARN</button>
              <button className={`log-filter-btn ${logFilter === 'victim_found' ? 'active' : ''}`} onClick={() => setLogFilter('victim_found')}>VICTIM</button>
            </div>
          </div>
          <div className="log-scroll glass">
            <div className="mission-log font-mono">
              {filteredLog.length === 0 && (
                <div className="log-empty"><Cpu size={20} className="animate-pulse" /><span>Awaiting SENTINEL activity...</span></div>
              )}
              {filteredLog.map((entry: any) => {
                const isAi = entry.level?.toLowerCase() === 'ai';
                return (
                  <div key={entry.id} className={`log-entry ${entry.level.toLowerCase()}`}>
                    {isAi ? (
                      <>
                        <div className="ai-log-header">
                          <span className="ai-log-label">⬡ SENTINEL AI</span>
                          <span className="log-ts">{entry.ts}</span>
                        </div>
                        <div className="ai-log-body">{entry.text || ""}</div>
                      </>
                    ) : (
                      <>
                        <span className="log-ts">[{entry.ts}]</span>
                        {entry.drone && <span className="log-drone">[{entry.drone}]</span>}
                        <span className="log-text" dangerouslySetInnerHTML={{
                          __html: (entry.text || "")
                            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                            .replace(/\n/g, '<br />')
                        }}></span>
                      </>
                    )}
                  </div>
                );
              })}
              <div ref={logEndRef} />
            </div>
          </div>
        </section>
      </main>

      {/* Victim comms popup removed temporarily — auto-rescue active */}

      {/* --- CSS - Inline specifically for the dashboard components --- */}
      <style>{`
        .app-container {
          display: flex;
          flex-direction: column;
          height: 100vh;
          width: 100vw;
          padding: 1rem;
          gap: 1rem;
          background: radial-gradient(circle at top right, #10101a 0%, #050508 100%);
        }

        .hud-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 1rem 2rem;
          min-height: 80px;
        }

        .brand {
          display: flex;
          align-items: center;
          gap: 1rem;
        }
        .brand-logo { color: var(--accent-cyan); width: 32px; height: 32px; filter: drop-shadow(0 0 8px var(--accent-cyan)); }
        .brand-text h1 { font-size: 1.5rem; margin: 0; line-height: 1; }
        .brand-text .subtitle { font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase; }

        .global-stats {
          display: flex;
          gap: 2rem;
          align-items: center;
        }

        .mission-timer {
          font-size: 1.5rem;
          color: var(--accent-cyan);
          text-shadow: 0 0 10px rgba(0, 243, 255, 0.5);
          min-width: 120px;
          text-align: center;
        }

        .main-content {
          display: grid;
          grid-template-columns: 260px 1fr 420px;
          gap: 1rem;
          flex: 1;
          overflow: hidden;
        }

        .side-panel { display: flex; flex-direction: column; gap: 0.5rem; height: 100%; overflow: hidden; }
        .log-panel { display: flex; flex-direction: column; gap: 0.5rem; height: 100%; overflow: hidden; }

        .panel-section-header {
          display: flex; align-items: center; gap: 8px;
          padding: 10px 14px; font-family: 'Orbitron', sans-serif;
          font-size: 0.75rem; color: var(--accent-cyan);
          border-radius: 8px 8px 0 0; flex-shrink: 0;
        }
        .fleet-controls { margin-left: auto; display: flex; align-items: center; gap: 8px; }
        .log-filter-group { margin-left: auto; display: flex; gap: 4px; }

        .tab-content { flex: 1; padding: 1rem; position: relative; overflow: hidden; }
        .scroll-area { overflow-y: auto; }
        .log-scroll { flex: 1; padding: 1rem; overflow-y: auto; }

        .telemetry-toolbar {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 10px;
          gap: 8px;
        }
        .toggle-btn {
          font-size: 0.68rem;
          padding: 5px 10px;
          border-radius: 999px;
          border: 1px solid rgba(255,255,255,0.25);
          color: var(--text-muted);
          background: rgba(255,255,255,0.04);
          cursor: pointer;
        }
        .toggle-btn.active {
          color: #ffe8b5;
          border-color: var(--accent-amber);
          background: rgba(255, 179, 0, 0.14);
        }
        .telemetry-count { font-size: 0.75rem; color: var(--text-muted); }

        .drone-card {
          background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.05);
          border-radius: 8px; padding: 12px; margin-bottom: 0.8rem; cursor: pointer;
        }
        .drone-card.active { border-color: var(--accent-cyan); background: rgba(0, 243, 255, 0.05); }
        .drone-card.alert { border-color: var(--accent-amber); background: rgba(255, 179, 0, 0.1); box-shadow: 0 0 15px rgba(255, 179, 0, 0.2); }
        .drone-card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
        .drone-id { font-size: 1rem; font-weight: bold; }
        .status-dot { width: 8px; height: 8px; border-radius: 50%; background: #444; }
        .status-dot.ready { background: var(--accent-success); box-shadow: 0 0 5px var(--accent-success); }
        .status-dot.navigating, .status-dot.resuming { background: var(--accent-cyan); }
        .status-dot.scanning { background: var(--accent-amber); animation: pulse 1s infinite; }
        .status-dot.victim_detected, .status-dot.alert { background: var(--accent-red); }

        .battery-bar-container { flex: 1; height: 4px; background: rgba(255,255,255,0.1); border-radius: 2px; }
        .battery-fill { height: 100%; background: var(--accent-success); border-radius: 2px; }
        .battery-fill.critical { background: var(--accent-red); }
        .tel-row { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
        .status-chip {
          display: inline-flex;
          margin-top: 6px;
          padding: 3px 8px;
          border-radius: 999px;
          font-size: 0.72rem;
          color: #dff9ff;
          background: rgba(0, 243, 255, 0.12);
          border: 1px solid rgba(0, 243, 255, 0.35);
          text-transform: uppercase;
          letter-spacing: 0.04em;
        }
        .status-chip.charging { color: #ffe8b5; background: rgba(255, 179, 0, 0.12); border-color: rgba(255, 179, 0, 0.35); }
        .status-chip.victim-detected, .status-chip.victim-standby { color: #ffd2d2; background: rgba(255, 61, 61, 0.15); border-color: rgba(255, 61, 61, 0.4); }
        .status-chip.ready, .status-chip.awaiting-orders { color: #ccffe8; background: rgba(0, 255, 136, 0.1); border-color: rgba(0, 255, 136, 0.35); }
        .status-chip.rtb--complete, .status-chip.guiding-to-base { color: #ffe8b5; background: rgba(255, 179, 0, 0.12); border-color: rgba(255, 179, 0, 0.35); }

        .log-controls { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }
        .log-filter-btn {
          font-size: 0.68rem;
          padding: 4px 8px;
          border-radius: 999px;
          border: 1px solid rgba(255,255,255,0.2);
          color: var(--text-muted);
          background: rgba(255,255,255,0.04);
          cursor: pointer;
        }
        .log-filter-btn.active {
          color: var(--text-primary);
          border-color: var(--accent-cyan);
          background: rgba(0, 243, 255, 0.12);
        }
        .mission-log { font-size: 0.8rem; line-height: 1.6; color: var(--text-primary); }
        .log-entry { margin-bottom: 4px; display: flex; gap: 6px; }
        .log-ts { color: var(--accent-cyan); opacity: 0.85; }
        .log-drone { color: var(--accent-amber); }
        .log-entry.verbal { color: #00f3ff; font-style: italic; border-left: 3px solid #00f3ff; padding-left: 10px; margin: 4px 0; text-shadow: 0 0 5px rgba(0, 243, 255, 0.3); }
        .log-entry.victim_found { color: #ffb300; font-weight: bold; background: rgba(255, 179, 0, 0.15); padding: 5px 8px; border-radius: 4px; margin: 6px 0; border: 1px solid rgba(255, 179, 0, 0.3); box-shadow: 0 0 10px rgba(255, 179, 0, 0.2); }
        .log-entry.ai {
          display: block;
          background: rgba(165, 243, 252, 0.05);
          border: 1px solid rgba(165, 243, 252, 0.18);
          border-left: 3px solid #a5f3fc;
          border-radius: 0 6px 6px 0;
          padding: 8px 10px;
          margin: 8px 0;
        }
        .ai-log-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 6px;
          padding-bottom: 5px;
          border-bottom: 1px solid rgba(165, 243, 252, 0.12);
        }
        .ai-log-label {
          font-size: 0.68rem;
          color: #a5f3fc;
          letter-spacing: 0.08em;
          font-family: 'Orbitron', sans-serif;
        }
        .ai-log-header .log-ts { color: rgba(165, 243, 252, 0.45); font-size: 0.68rem; }
        .ai-log-body {
          color: #dff9ff;
          font-size: 0.78rem;
          line-height: 1.75;
          white-space: pre-wrap;
          word-break: break-word;
        }
        .log-entry.warn { color: #ffb300; opacity: 0.9; }
        .log-entry.error { color: #ff3d3d; font-weight: bold; background: rgba(255, 61, 61, 0.1); padding: 2px 4px; }
        .log-entry.success { color: #00ff88; text-shadow: 0 0 5px rgba(0, 255, 136, 0.3); }

        .center-map { display: flex; flex-direction: column; position: relative; padding: 1rem; }
        .map-overlay-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
        .legend { display: flex; gap: 1rem; font-size: 0.72rem; }
        .legend-item { display: flex; align-items: center; gap: 4px; opacity: 0.8; }
        .dot { width: 6px; height: 6px; border-radius: 50%; }
        .dot.base { background: var(--accent-cyan); }
        .dot.scanned { background: rgba(0, 243, 255, 0.2); }
        .dot.victim { background: var(--accent-amber); }
        .dot.hazard { background: rgba(255, 61, 61, 0.3); }

        .grid-container {
          display: grid;
          grid-template-columns: repeat(20, 1fr);
          grid-template-rows: repeat(15, 1fr);
          gap: 2px;
          flex: 1;
          background: rgba(255,255,255,0.02);
          border: 1px solid rgba(255,255,255,0.1);
          padding: 2px;
          transition: transform 0.8s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.8s ease, border 0.8s ease, clip-path 0.8s ease;
          transform-style: preserve-3d;
        }

        .center-map.view-3d {
          perspective: 1200px;
        }

        .center-map.view-3d .grid-container {
          transform: rotateX(60deg) rotateZ(-45deg);
          box-shadow: -20px 30px 40px rgba(0,0,0,0.6);
          border: 1px solid rgba(0, 243, 255, 0.4);
          transform-origin: center center;
          align-self: center;
          justify-self: center;
          width: 80%;
          margin: 20px auto;
        }

        .grid-cell {
          background: rgba(14, 14, 28, 0.6);
          position: relative;
          display: flex;
          align-items: center;
          justify-content: center;
          border: 1px solid rgba(255,255,255,0.03);
          transform-style: preserve-3d;
          transition: background-color 0.4s;
        }
        .grid-cell.scanned { background: rgba(0, 220, 200, 0.13); border-color: rgba(0,220,200,0.08); }
        .grid-cell.victim-cell {
          background: rgba(255, 160, 0, 0.22) !important;
          border-color: rgba(255, 160, 0, 0.4) !important;
          box-shadow: inset 0 0 6px rgba(255, 160, 0, 0.2);
        }
        .grid-cell.rescued-cell {
          background: rgba(0, 200, 100, 0.15) !important;
          border-color: rgba(0, 200, 100, 0.3) !important;
        }
        .drone-marker.multi {
          width: 34px; height: 34px;
          background: rgba(0, 243, 255, 0.75);
          outline: 2px solid rgba(255, 243, 0, 0.8);
          box-shadow: 0 0 14px var(--accent-cyan), 0 0 6px rgba(255,243,0,0.4);
        }
        .grid-cell.base-cell {
          background: rgba(0, 243, 255, 0.18) !important;
          border: 1px solid rgba(0, 243, 255, 0.5) !important;
          box-shadow: inset 0 0 8px rgba(0, 243, 255, 0.25), 0 0 6px rgba(0, 243, 255, 0.3);
        }
        .base-marker {
          position: absolute; z-index: 10;
          display: flex; flex-direction: column; align-items: center; justify-content: center;
          color: var(--accent-cyan);
          filter: drop-shadow(0 0 6px var(--accent-cyan));
          animation: pulse 1.8s ease-in-out infinite;
        }
        .grid-cell:hover { background: rgba(255,255,255,0.04); }

        .content-wrapper {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          transition: transform 0.8s cubic-bezier(0.34, 1.56, 0.64, 1);
          transform-style: preserve-3d;
        }

        .center-map.view-3d .content-wrapper {
          transform: rotateZ(45deg) rotateX(-60deg) translateY(-15px);
          filter: drop-shadow(-8px 10px 6px rgba(0,0,0,0.6));
        }


        .drone-marker {
          width: 30px; height: 30px; background: rgba(0, 243, 255, 0.8); color: black;
          border-radius: 4px; display: flex; flex-direction: column; align-items: center; justify-content: center;
          box-shadow: 0 0 15px var(--accent-cyan); z-index: 10;
        }
        .drone-marker.special { background: var(--accent-amber); box-shadow: 0 0 15px var(--accent-amber); }
        .drone-marker.returning { outline: 2px solid var(--accent-amber); box-shadow: 0 0 18px rgba(255, 179, 0, 0.55); }
        .drone-marker.dimmed { opacity: 0.2; }
        .d-label { font-size: 0.7rem; line-height: 1; font-weight: bold; }
        .victim-dot {
          position: absolute; z-index: 8;
          width: 5px; height: 5px; border-radius: 50%;
          background: rgba(255, 179, 0, 0.45);
          box-shadow: 0 0 3px rgba(255, 179, 0, 0.3);
        }
        .victim-found-marker {
          position: absolute; z-index: 12;
          color: var(--accent-amber);
          filter: drop-shadow(0 0 5px var(--accent-amber));
        }
        .dot.victim-hidden { background: rgba(255,179,0,0.4); }
        .dot.victim-found-dot { background: var(--accent-amber); box-shadow: 0 0 4px var(--accent-amber); }

        .victim-stepper {
          display: flex; flex-direction: column; align-items: center; gap: 4px;
          padding: 6px 12px;
          border: 1px solid rgba(255,179,0,0.3);
          border-radius: 8px;
          background: rgba(255,179,0,0.05);
        }
        .victim-stepper-label {
          font-family: 'Orbitron', sans-serif; font-size: 0.6rem;
          color: var(--accent-amber); letter-spacing: 0.1em; opacity: 0.8;
        }
        .stepper-control { display: flex; align-items: center; gap: 8px; }
        .stepper-btn {
          width: 22px; height: 22px; border-radius: 4px;
          border: 1px solid rgba(255,179,0,0.4);
          background: rgba(255,179,0,0.08);
          color: var(--accent-amber); font-size: 1rem; line-height: 1;
          cursor: pointer; display: flex; align-items: center; justify-content: center;
          transition: background 0.15s;
        }
        .stepper-btn:hover { background: rgba(255,179,0,0.2); }
        .stepper-value {
          font-size: 1.2rem; font-weight: bold;
          color: var(--accent-amber); min-width: 28px; text-align: center;
        }
        .base-icon { color: var(--accent-cyan); opacity: 0.5; }
        .toggle-3d { margin-left: 1rem; margin-right: 15px; border-color: rgba(255,255,255,0.2); }
        .toggle-3d.active { background: rgba(0,243,255,0.15); border-color: var(--accent-cyan); color: var(--accent-cyan); box-shadow: 0 0 10px rgba(0,243,255,0.3); }

        .log-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; padding: 40px 0; color: var(--text-muted); opacity: 0.35; font-size: 0.8rem; font-family: 'Orbitron', sans-serif; }

        .flex-row { display: flex; }
        .gap-2 { gap: 0.5rem; }
        .full-w { width: 100%; }
        .mt-4 { margin-top: 1rem; }
        .header-actions { display: flex; align-items: center; gap: 0.5rem; }

        .conn-badge {
          display: flex;
          align-items: center;
          gap: 5px;
          font-family: 'Orbitron', sans-serif;
          font-size: 0.68rem;
          padding: 4px 10px;
          border-radius: 999px;
          border: 1px solid;
          letter-spacing: 0.05em;
        }
        .conn-badge.connected { color: var(--accent-success); border-color: var(--accent-success); background: rgba(0, 255, 136, 0.08); box-shadow: 0 0 8px rgba(0, 255, 136, 0.2); }
        .conn-badge.disconnected { color: #ff3d3d; border-color: #ff3d3d; background: rgba(255, 61, 61, 0.08); animation: pulse 1.5s infinite; }

        @keyframes pulse { 0% { opacity: 0.4; } 50% { opacity: 1; } 100% { opacity: 0.4; } }
        .loading-container { height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 1rem; font-family: 'Orbitron'; font-size: 1.2rem; color: var(--accent-cyan); }
        .animate-pulse { animation: pulse 1s infinite; }
        .text-cyan { color: var(--accent-cyan); }
        .text-muted { color: var(--text-muted); }
        .text-success { color: var(--accent-success); }
        .text-amber { color: var(--accent-amber); }
        .text-xs { font-size: 0.75rem; }
        .mb-2 { margin-bottom: 0.5rem; }
        .mb-3 { margin-bottom: 0.75rem; }
        .mb-4 { margin-bottom: 1rem; }
        .font-bold { font-weight: bold; }
        .text-sm { font-size: 0.875rem; }
        .items-center { align-items: center; }
        .opacity-60 { opacity: 0.6; }
        .opacity-70 { opacity: 0.7; }
        .italic { font-style: italic; }
        .panel-header { display: flex; align-items: center; gap: 0.5rem; padding: 0.75rem 1rem; font-size: 0.8rem; font-family: 'Orbitron'; }
        .drone-card-body {}
        .drone-telemetry {}
        .drone-list {}
      `}</style>
    </div>
  );
}

function StatBox({ icon, label, value, color }: { icon: any, label: string, value: string, color: 'cyan' | 'amber' | 'success' }) {
  const colors = {
    cyan: 'var(--accent-cyan)',
    amber: 'var(--accent-amber)',
    success: 'var(--accent-success)'
  };
  return (
    <div className="stat-box">
      <div className="stat-label">
        <span style={{ color: colors[color] }}>{icon}</span> {label}
      </div>
      <div className="stat-value font-mono" style={{ color: colors[color] }}>{value}</div>
      <style>{`
        .stat-box { display: flex; flex-direction: column; align-items: flex-start; }
        .stat-label { font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase; display: flex; align-items: center; gap: 4px; }
        .stat-value { font-size: 1.1rem; font-weight: bold; }
      `}</style>
    </div>
  );
}

