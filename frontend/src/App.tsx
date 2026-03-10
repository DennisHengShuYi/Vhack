import React, { useState, useEffect, useRef } from 'react';
import {
  Shield,
  Cpu,
  Waves,
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
  Power
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

// --- Constants ---
const API_BASE = "http://127.0.0.1:8005";
const GRID_SIZE = 10;

// --- Components ---

/**
 * Main Sentinel Mission Dashboard
 */
export default function App() {
  const [state, setState] = useState<any>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<'mission' | 'telemetry' | 'log'>('mission');
  const [operatorMsg, setOperatorMsg] = useState("");
  const [isDeploying, setIsDeploying] = useState(false);
  const [activeDroneId, setActiveDroneId] = useState<string | null>(null);

  const logEndRef = useRef<HTMLDivElement>(null);

  // Poll state every 800ms
  useEffect(() => {
    const fetchData = async () => {
      try {
        const resp = await fetch(`${API_BASE}/state`);
        const data = await resp.json();
        setState(data);
        setIsLoading(false);
      } catch (err) {
        console.error("Fetch failed:", err);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 800);
    return () => clearInterval(interval);
  }, []);

  // Auto-scroll logic
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [state?.log]);

  const runMission = async () => {
    setIsDeploying(true);
    await fetch(`${API_BASE}/run-mission`, { method: 'POST' });
    setTimeout(() => setIsDeploying(false), 2000);
  };

  const [isTalking, setIsTalking] = useState<boolean | null>(null);
  const [isRecording, setIsRecording] = useState(false);
  const [transcription, setTranscription] = useState("");

  const startVoiceCapture = () => {
    setIsRecording(true);
    // Use Web Speech API if available
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (SpeechRecognition) {
      const recognition = new SpeechRecognition();
      recognition.onresult = (event: any) => {
        const text = event.results[0][0].transcript;
        setTranscription(text);
        setOperatorMsg(text);
        setIsRecording(false);
      };
      recognition.onerror = () => setIsRecording(false);
      recognition.start();
    } else {
      // Mock for environments without speech API
      setTimeout(() => {
        const mocks = [
          "My family is trapped at coordinate 5 8, please help",
          "There are more people at sector 2 9 under the bridge",
          "I am okay but my friend is bleeding at the south east corner",
          "Help, we are at the middle of the grid, position 4 4"
        ];
        const text = mocks[Math.floor(Math.random() * mocks.length)];
        setTranscription(text);
        setOperatorMsg(text);
        setIsRecording(false);
      }, 2000);
    }
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

  if (isLoading) return <div className="loading-container"><Zap className="animate-pulse" /> INITIALIZING SENTINEL...</div>;

  const { stats, drones, zone, log } = state || {};
  const activeDronesCount = drones?.filter((d: any) => d.status_label !== "STANDBY")?.length || 0;
  const waitingDrone = drones?.find((d: any) => d.is_waiting_response);

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
          <StatBox icon={<MapIcon size={14} />} label="COVERAGE" value={`${stats.coverage_pct}%`} color="cyan" />
          <StatBox icon={<Search size={14} />} label="FOUND" value={`${stats.victims_found}/${stats.total_victims}`} color="amber" />
          <StatBox icon={<CheckCircle2 size={14} />} label="RESCUED" value={`${stats.victims_rescued}`} color="success" />
          <div className="mission-timer font-mono">{stats.elapsed_ts}</div>
        </div>

        <div className="header-actions">
          {!stats.mission_active && (
            <button className="cyber-button primary" onClick={runMission} disabled={isDeploying}>
              {isDeploying ? <RefreshCcw className="animate-spin" size={16} /> : "DEPLOY SWARM"}
            </button>
          )}
          <button className="cyber-button danger" onClick={resetMission}>RESET</button>
        </div>
      </header>

      {/* --- MAIN LAYOUT --- */}
      <main className="main-content">

        {/* Left Side: Fleet Telemetry & Log */}
        <section className="side-panel">
          <div className="panel-tabs">
            <button className={activeTab === 'telemetry' ? 'active' : ''} onClick={() => setActiveTab('telemetry')}>
              <Activity size={16} /> FLEET
            </button>
            <button className={activeTab === 'log' ? 'active' : ''} onClick={() => setActiveTab('log')}>
              <History size={16} /> LOG
            </button>
          </div>

          <div className="tab-content glass scroll-area">
            {activeTab === 'telemetry' ? (
              <div className="drone-list">
                {drones.map((drone: any) => (
                  <motion.div
                    key={drone.id}
                    className={`drone-card ${activeDroneId === drone.id ? 'active' : ''} ${drone.is_waiting_response ? 'alert' : ''}`}
                    whileHover={{ scale: 1.02 }}
                    onClick={() => setActiveDroneId(drone.id)}
                  >
                    <div className="drone-card-header">
                      <span className="drone-id font-mono">{drone.id}</span>
                      <div className={`status-dot ${drone.status_label.toLowerCase()}`}></div>
                    </div>
                    <div className="drone-card-body">
                      <div className="drone-telemetry">
                        <div className="tel-row">
                          <Battery size={14} />
                          <div className="battery-bar-container">
                            <div className={`battery-fill ${drone.battery < 30 ? 'critical' : ''}`} style={{ width: `${drone.battery}%` }}></div>
                          </div>
                          <span className="font-mono text-xs">{drone.battery.toFixed(0)}%</span>
                        </div>
                        <div className="tel-row">
                          <Navigation size={14} />
                          <span className="font-mono text-xs">POS: ({drone.x}, {drone.y})</span>
                        </div>
                        <div className="tel-status font-mono">{drone.status_label}</div>
                      </div>
                    </div>
                  </motion.div>
                ))}
              </div>
            ) : (
              <div className="mission-log font-mono">
                {log.map((entry: any) => (
                  <div key={entry.id} className={`log-entry ${entry.level.toLowerCase()}`}>
                    <span className="log-ts">[{entry.ts}]</span>
                    {entry.drone && <span className="log-drone">[{entry.drone}]</span>}
                    <span className="log-text">{entry.text}</span>
                  </div>
                ))}
                <div ref={logEndRef} />
              </div>
            )}
          </div>

          {/* Victim Interaction Overlay (Inline) */}
          <AnimatePresence>
            {waitingDrone && (
              <motion.div
                initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.95 }}
                className="victim-comms-panel glass accent-amber"
              >
                <div className="panel-header">
                  <AlertTriangle className="animate-pulse text-amber" />
                  <span className="font-bold">VICTIM CONTACT: {waitingDrone.id}</span>
                </div>

                <div className="victim-report font-mono">
                  {waitingDrone.victim_report}
                </div>

                {isTalking === null ? (
                  <div className="talk-query">
                    <p className="text-sm mb-3">Is the victim talking?</p>
                    <div className="flex-row gap-2">
                      <button className="cyber-button primary compact" onClick={() => setIsTalking(true)}>YES</button>
                      <button className="cyber-button danger compact" onClick={() => setIsTalking(false)}>NO</button>
                    </div>
                  </div>
                ) : isTalking ? (
                  <div className="voice-capture-section">
                    <button
                      className={`voice-record-btn ${isRecording ? 'recording' : ''}`}
                      onClick={startVoiceCapture}
                      disabled={isRecording}
                    >
                      {isRecording ? <Activity className="animate-pulse" /> : <Volume2 />}
                      {isRecording ? "RECORDING..." : "START VOICE CAPTURE"}
                    </button>
                    {transcription && (
                      <div className="transcription-preview font-mono">
                        <span className="text-cyan">TRANSCRIBED:</span> "{transcription}"
                      </div>
                    )}
                    <div className="operator-control mt-4">
                      <button className="cyber-button primary full-w" onClick={() => respondToVictim(waitingDrone.id)}>
                        <Send size={16} /> SEND TO SENTINEL AI
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="no-talk-section">
                    <p className="text-xs italic opacity-70 mb-4">No verbal response detected. Proceeding with immediate extraction.</p>
                    <button className="cyber-button primary full-w" onClick={() => respondToVictim(waitingDrone.id)}>
                      EXECUTE EXTRACTION
                    </button>
                  </div>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </section>

        {/* Center: Tactical Map */}
        <section className="center-map glass">
          <div className="map-overlay-header">
            <span className="font-mono text-xs"><Crosshair size={12} /> TACTICAL OVERLAY</span>
            <div className="legend">
              <span className="legend-item"><div className="dot base"></div> BASE</span>
              <span className="legend-item"><div className="dot scanned"></div> SCANNED</span>
              <span className="legend-item"><div className="dot victim"></div> VICTIM</span>
              <span className="legend-item"><div className="dot hazard"></div> HAZARD</span>
            </div>
          </div>

          <div className="grid-container">
            {Array.from({ length: GRID_SIZE * GRID_SIZE }).map((_, i) => {
              const x = i % GRID_SIZE;
              const y = Math.floor(i / GRID_SIZE);
              const isScanned = zone.scanned_cells[y][x];
              const isHazard = zone.hazard_cells[y][x];
              const droneAtPos = drones.find((d: any) => d.x === x && d.y === y);
              const survivorFound = zone.survivors.find((s: any) => s.x === x && s.y === y && s.found && !s.rescued);

              return (
                <div key={i} className={`grid-cell ${isScanned ? 'scanned' : ''} ${isHazard ? 'hazard' : ''}`}>
                  <AnimatePresence>
                    {survivorFound && (
                      <motion.div initial={{ scale: 0 }} animate={{ scale: 1 }} className="survivor-icon">
                        <Crosshair className="animate-pulse" size={16} />
                      </motion.div>
                    )}
                  </AnimatePresence>

                  {droneAtPos && (
                    <motion.div
                      layoutId={`drone-${droneAtPos.id}`}
                      className={`drone-marker ${droneAtPos.is_waiting_response ? 'special' : ''}`}
                      title={droneAtPos.id}
                    >
                      <Cpu size={14} />
                      <span className="d-label font-mono">{droneAtPos.id.split('-')[1]}</span>
                    </motion.div>
                  )}
                  {x === 0 && y === 0 && <Power size={14} className="base-icon" />}
                </div>
              );
            })}
          </div>
        </section>

        {/* Right Side: Drone Feeds & Triage */}
        <section className="detail-panel">
          <div className="panel-header glass">
            <Activity className="text-cyan" size={16} /> REAL-TIME SENSOR FEED
          </div>

          <div className="sensor-matrix-grid glass">
            {activeDroneId ? (
              <div className="drone-detailed-sensor">
                <div className="sensor-meta">
                  <span className="font-mono text-cyan">{activeDroneId}</span>
                  <span className="font-mono text-muted text-xs">MODEL 1404-T</span>
                </div>
                <div className="thermal-preview glass">
                  {drones.find((d: any) => d.id === activeDroneId)?.last_thermal_matrix ? (
                    <div className="thermal-matrix">
                      {drones.find((d: any) => d.id === activeDroneId).last_thermal_matrix.flatMap((row: any) => row).map((val: number, idx: number) => (
                        <div key={idx} className="thermal-pixel" style={{ backgroundColor: `rgba(255, ${val * 1.5}, 0, ${val / 100})` }}></div>
                      ))}
                    </div>
                  ) : (
                    <div className="thermal-no-data font-mono">NO SENSOR DATA RECEIVED</div>
                  )}
                </div>
                <div className="sensor-readouts glass">
                  <Readout label="ALTITUDE" value="4.2m" />
                  <Readout label="WIND VELOC" value="12 kph" />
                  <Readout label="PITCH/YAW" value="+2.0 / -0.4" />
                  <Readout label="ENCRYPTION" value="AES-256-S" />
                </div>
              </div>
            ) : (
              <div className="sensor-placeholder">
                <Waves className="animate-pulse" />
                <span>SELECT DRONE FOR SENSOR LINK</span>
              </div>
            )}
          </div>

          <div className="active-mission-stats glass">
            <h3 className="text-xs mb-2">NETWORK STATUS</h3>
            <div className="net-stat-row">
              <span>Drones Active</span>
              <span className="font-mono text-cyan">{activeDronesCount}</span>
            </div>
            <div className="net-stat-row">
              <span>Mesh Reliability</span>
              <span className="font-mono text-success">98.4%</span>
            </div>
            <div className="net-stat-row">
              <span>LLM Latency</span>
              <span className="font-mono text-amber">120ms</span>
            </div>
          </div>
        </section>
      </main>

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
        .brand-text .subtitle { font-size: 0.6rem; color: var(--text-muted); text-transform: uppercase; }

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
          grid-template-columns: 320px 1fr 280px;
          gap: 1rem;
          flex: 1;
          overflow: hidden;
        }

        .side-panel { display: flex; flex-direction: column; gap: 0.5rem; height: 100%; overflow: hidden; }
        .panel-tabs { display: flex; gap: 4px; }
        .panel-tabs button {
          flex: 1; background: rgba(255, 255, 255, 0.05); border: none; color: var(--text-muted);
          padding: 10px; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 8px;
          font-family: 'Orbitron', sans-serif; font-size: 0.7rem; border-radius: 8px 8px 0 0;
          transition: all 0.2s;
        }
        .panel-tabs button.active { background: var(--bg-panel); color: var(--accent-cyan); border: 1px solid var(--border-glass); border-bottom: none; }

        .tab-content { flex: 1; padding: 1rem; position: relative; }
        .scroll-area { overflow-y: auto; }

        .drone-card {
          background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.05);
          border-radius: 8px; padding: 12px; margin-bottom: 0.8rem; cursor: pointer;
        }
        .drone-card.active { border-color: var(--accent-cyan); background: rgba(0, 243, 255, 0.05); }
        .drone-card.alert { border-color: var(--accent-amber); background: rgba(255, 179, 0, 0.1); box-shadow: 0 0 15px rgba(255, 179, 0, 0.2); }
        .drone-card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
        .drone-id { font-size: 0.9rem; font-weight: bold; }
        .status-dot { width: 8px; height: 8px; border-radius: 50%; background: #444; }
        .status-dot.ready { background: var(--accent-success); box-shadow: 0 0 5px var(--accent-success); }
        .status-dot.navigating, .status-dot.resuming { background: var(--accent-cyan); }
        .status-dot.scanning { background: var(--accent-amber); animation: pulse 1s infinite; }
        .status-dot.victim_detected, .status-dot.alert { background: var(--accent-red); }

        .battery-bar-container { flex: 1; height: 4px; background: rgba(255,255,255,0.1); border-radius: 2px; }
        .battery-fill { height: 100%; background: var(--accent-success); border-radius: 2px; }
        .battery-fill.critical { background: var(--accent-red); }
        .tel-row { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
        .tel-status { font-size: 0.65rem; color: var(--accent-cyan); margin-top: 4px; text-transform: uppercase; }

        .mission-log { font-size: 0.7rem; line-height: 1.5; color: var(--text-muted); }
        .log-entry { margin-bottom: 4px; display: flex; gap: 6px; }
        .log-ts { color: var(--accent-cyan); opacity: 0.6; }
        .log-drone { color: var(--accent-amber); }
        .log-entry.critical { color: var(--accent-red); font-weight: bold; }
        .log-entry.success { color: var(--accent-success); }
        .log-entry.ai { border-left: 2px solid var(--accent-cyan); padding-left: 6px; color: #a5f3fc; }

        .center-map { display: flex; flex-direction: column; position: relative; padding: 1rem; }
        .map-overlay-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
        .legend { display: flex; gap: 1rem; font-size: 0.6rem; }
        .legend-item { display: flex; align-items: center; gap: 4px; opacity: 0.8; }
        .dot { width: 6px; height: 6px; border-radius: 50%; }
        .dot.base { background: var(--accent-cyan); }
        .dot.scanned { background: rgba(0, 243, 255, 0.2); }
        .dot.victim { background: var(--accent-amber); }
        .dot.hazard { background: rgba(255, 61, 61, 0.3); }

        .grid-container {
          display: grid;
          grid-template-columns: repeat(10, 1fr);
          grid-template-rows: repeat(10, 1fr);
          gap: 2px;
          flex: 1;
          background: rgba(255,255,255,0.02);
          border: 1px solid rgba(255,255,255,0.1);
          padding: 2px;
        }
        .grid-cell {
          background: rgba(20, 20, 40, 0.4);
          position: relative;
          display: flex;
          align-items: center;
          justify-content: center;
          border: 1px solid rgba(255,255,255,0.01);
        }
        .grid-cell.scanned { background: rgba(0, 243, 255, 0.08); }
        .grid-cell.hazard { background: rgba(255, 61, 61, 0.15); }
        .grid-cell:hover { background: rgba(255,255,255,0.05); }

        .drone-marker {
          width: 30px; height: 30px; background: rgba(0, 243, 255, 0.8); color: black;
          border-radius: 4px; display: flex; flex-direction: column; align-items: center; justify-content: center;
          box-shadow: 0 0 15px var(--accent-cyan); z-index: 10;
        }
        .drone-marker.special { background: var(--accent-amber); box-shadow: 0 0 15px var(--accent-amber); }
        .d-label { font-size: 0.6rem; line-height: 1; font-weight: bold; }
        .survivor-icon { color: var(--accent-amber); filter: drop-shadow(0 0 8px var(--accent-amber)); }
        .base-icon { color: var(--accent-cyan); opacity: 0.5; }

        .detail-panel { display: flex; flex-direction: column; gap: 1rem; }
        .sensor-matrix-grid { flex: 1; display: flex; flex-direction: column; padding: 1rem; }
        .sensor-placeholder { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 1rem; color: var(--text-muted); opacity: 0.4; text-align: center; }
        
        .thermal-preview { flex: 1; min-height: 150px; margin: 10px 0; display: flex; align-items: center; justify-content: center; background: #000; overflow: hidden; }
        .thermal-matrix { display: grid; grid-template-columns: repeat(5, 1fr); gap: 2px; width: 100%; height: 100%; }
        .thermal-pixel { width: 100%; height: 100%; transition: background 0.3s; }
        .readout { display: flex; justify-content: space-between; font-size: 0.6rem; color: var(--text-muted); padding: 4px 0; border-bottom: 1px solid rgba(255,255,255,0.05); }
        .readout .val { color: var(--accent-cyan); }
        
        .active-mission-stats { padding: 1rem; }
        .net-stat-row { display: flex; justify-content: space-between; margin-bottom: 6px; font-size: 0.7rem; }

        .victim-comms-panel {
          position: absolute; bottom: 1rem; left: 1rem; right: 1rem; z-index: 50; padding: 1.5rem;
          border: 2px solid var(--accent-amber) !important; box-shadow: 0 0 30px rgba(255, 179, 0, 0.4);
        }
        .victim-report { background: rgba(0,0,0,0.6); padding: 10px; border-radius: 4px; border: 1px solid rgba(255,179,0,0.2); margin: 10px 0; font-size: 0.75rem; color: var(--accent-amber); }
        .talk-query { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 10px; border: 1px dashed rgba(255,255,255,0.1); border-radius: 8px; }
        .voice-record-btn {
          width: 100%; display: flex; align-items: center; justify-content: center; gap: 10px;
          background: rgba(0, 243, 255, 0.1); border: 1px solid var(--accent-cyan); color: var(--accent-cyan);
          padding: 12px; border-radius: 8px; cursor: pointer; transition: all 0.3s; font-family: 'Orbitron'; font-size: 0.7rem;
        }
        .voice-record-btn.recording { background: rgba(255, 61, 61, 0.2); border-color: var(--accent-red); color: var(--accent-red); }
        .transcription-preview { margin-top: 10px; font-size: 0.7rem; background: rgba(0,0,0,0.3); padding: 8px; border-radius: 4px; border-left: 2px solid var(--accent-cyan); }
        .flex-row { display: flex; }
        .gap-2 { gap: 0.5rem; }
        .full-w { width: 100%; }
        .mt-4 { margin-top: 1rem; }
        .cyber-input { flex: 1; background: rgba(255,255,255,0.05); border: 1px solid var(--border-glass); color: white; padding: 8px; border-radius: 4px; outline: none; }
        .cyber-input:focus { border-color: var(--accent-cyan); }

        @keyframes pulse { 0% { opacity: 0.4; } 50% { opacity: 1; } 100% { opacity: 0.4; } }
        .loading-container { height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 1rem; font-family: 'Orbitron'; font-size: 1.2rem; color: var(--accent-cyan); }
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
        .stat-label { font-size: 0.6rem; color: var(--text-muted); text-transform: uppercase; display: flex; align-items: center; gap: 4px; }
        .stat-value { font-size: 1.1rem; font-weight: bold; }
      `}</style>
    </div>
  );
}

function Readout({ label, value }: { label: string, value: string }) {
  return (
    <div className="readout">
      <span>{label}</span>
      <span className="val font-mono">{value}</span>
    </div>
  );
}
