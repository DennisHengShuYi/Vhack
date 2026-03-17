import React from 'react';
import { Shield, Wifi, WifiOff, Map as MapIcon, Search, CheckCircle2, RefreshCcw } from 'lucide-react';
import StatBox from './StatBox';

interface DashboardHeaderProps {
  connectionStatus: 'connected' | 'disconnected';
  stats: any;
  victimCount: number;
  setVictimCount: React.Dispatch<React.SetStateAction<number>>;
  isDeploying: boolean;
  is3DView: boolean;
  setIs3DView: React.Dispatch<React.SetStateAction<boolean>>;
  runMission: () => void;
  stopMission: () => void;
  resetMission: () => void;
}

export default function DashboardHeader({
  connectionStatus,
  stats,
  victimCount,
  setVictimCount,
  isDeploying,
  is3DView,
  setIs3DView,
  runMission,
  stopMission,
  resetMission
}: DashboardHeaderProps) {
  return (
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
        <StatBox icon={<MapIcon size={14} />} label="COVERAGE" value={`${stats?.coverage_pct ?? 0}%`} color="cyan" />
        <StatBox icon={<Search size={14} />} label="FOUND" value={`${stats?.victims_found ?? 0}/${stats?.total_victims ?? 0}`} color="amber" />
        <StatBox icon={<CheckCircle2 size={14} />} label="RESCUED" value={`${stats?.victims_rescued ?? 0}`} color="success" />
        <div className="mission-timer font-mono">{stats?.elapsed_ts ?? "00:00:00"}</div>
      </div>

      <div className="header-actions">
        {!stats?.mission_active && (
          <div className="victim-stepper">
            <span className="victim-stepper-label">SURVIVORS</span>
            <div className="stepper-control">
              <button className="stepper-btn" onClick={() => setVictimCount(c => Math.max(1, c - 1))}>−</button>
              <span className="stepper-value font-mono">{victimCount}</span>
              <button className="stepper-btn" onClick={() => setVictimCount(c => Math.min(50, c + 1))}>+</button>
            </div>
          </div>
        )}
        {stats?.mission_active ? (
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
        <button className="cyber-button secondary" onClick={resetMission} disabled={stats?.mission_active}>RESET</button>
      </div>
    </header>
  );
}
