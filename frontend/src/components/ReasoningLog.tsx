import { History, Cpu } from 'lucide-react';

interface ReasoningLogProps {
  log: any[];
  logFilter: string;
  setLogFilter: (filter: 'all' | 'warn' | 'error' | 'victim_found' | 'ai') => void;
  logEndRef: React.RefObject<HTMLDivElement>;
}

export default function ReasoningLog({
  log,
  logFilter,
  setLogFilter,
  logEndRef
}: ReasoningLogProps) {
  
  const filteredLog = (log || []).filter((entry: any) => {
    if (logFilter === 'all') return true;
    return entry.level?.toLowerCase() === logFilter;
  });

  return (
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
            <div className="log-empty">
              <Cpu size={20} className="animate-pulse" />
              <span>Awaiting SENTINEL activity...</span>
            </div>
          )}
          {filteredLog.map((entry: any) => {
            const isAi = entry.level?.toLowerCase() === 'ai';
            return (
              <div key={entry.id} className={`log-entry ${entry.level.toLowerCase()} ${entry.text?.includes('**VOICE DISPATCH**') || entry.text?.includes('**INTEL DISPATCH**') ? 'ai-voice-event' : ''}`}>
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
  );
}
