import { Activity, Battery, Navigation } from 'lucide-react';
import { motion } from 'framer-motion';

interface FleetStatusProps {
  drones: any[];
  activeDroneId: string | null;
  setActiveDroneId: (id: string | null) => void;
  showRtbOnly: boolean;
  setShowRtbOnly: (v: boolean) => void;
  lowBatteryPct: number;
}

export default function FleetStatus({
  drones,
  activeDroneId,
  setActiveDroneId,
  showRtbOnly,
  setShowRtbOnly,
  lowBatteryPct
}: FleetStatusProps) {
  
  const isReturningDrone = (drone: any) =>
    drone?.returning_to_base ||
    String(drone?.status_label || '').toLowerCase().includes('rtb') ||
    String(drone?.status || '').toLowerCase() === 'returning';

  const displayedDrones = showRtbOnly ? (drones || []).filter(isReturningDrone) : (drones || []);

  return (
    <section className="side-panel">
      <div className="panel-section-header glass">
        <Activity size={14} /> FLEET STATUS
        <div className="fleet-controls">
          <button className={`toggle-btn ${showRtbOnly ? 'active' : ''}`} onClick={() => setShowRtbOnly(!showRtbOnly)}>
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
                      <div className={`battery-fill ${drone.battery < lowBatteryPct ? 'critical' : ''}`} style={{ width: `${drone.battery}%` }}></div>
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
  );
}
