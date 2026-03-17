import { motion, AnimatePresence } from 'framer-motion';
import { AlertTriangle, Volume2, Shield, CheckCircle2, Send } from 'lucide-react';

interface VictimPopupProps {
  waitingDrone: any;
  isRecording: boolean;
  transcription: string;
  speechError: string | null;
  toggleVoiceCapture: () => void;
  respondToVictim: (droneId: string) => void;
  setTranscription: (t: string) => void;
  setOperatorMsg: (m: string) => void;
}

export default function VictimPopup({
  waitingDrone,
  isRecording,
  transcription,
  speechError,
  toggleVoiceCapture,
  respondToVictim,
  setTranscription,
  setOperatorMsg
}: VictimPopupProps) {
  return (
    <AnimatePresence>
      {waitingDrone && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="victim-popup-overlay"
        >
          <motion.div
            initial={{ scale: 0.9, y: 20, opacity: 0 }}
            animate={{ scale: 1, y: 0, opacity: 1 }}
            exit={{ scale: 0.9, y: 20, opacity: 0 }}
            className="victim-popup glass"
          >
            <div className="popup-header">
              <div className="brand">
                <AlertTriangle className="text-amber animate-pulse" size={24} />
                <div>
                  <h2>VICTIM CONTACT</h2>
                  <span className="subtitle">TRANSCEIVER CHANNEL ACTIVE</span>
                </div>
              </div>
              <div className="popup-drone-id font-mono">
                {waitingDrone.id}
              </div>
            </div>

            <div className="popup-body">
              <div className="comms-segment">
                <div className="segment-label">COMMUNICATION</div>
                
                {!isRecording && !transcription && (
                  <div className="comms-options">
                    <p className="comms-hint">Ask the survivor for additional intelligence?</p>
                    <div className="flex-row gap-2 mt-4">
                      <button className="cyber-button primary full-w" onClick={toggleVoiceCapture}>
                        <Volume2 size={16} /> SPEAK TO VICTIM
                      </button>
                      <button className="cyber-button secondary full-w" onClick={() => respondToVictim(waitingDrone.id)}>
                        <Shield size={16} /> NO, JUST RESCUE
                      </button>
                    </div>
                  </div>
                )}

                {(isRecording || transcription) && (
                  <div className="voice-interface">
                    <div className="voice-status">
                      {isRecording ? (
                        <div className="flex items-center gap-2 text-amber">
                          <div className="recording-dot"></div>
                          <span>LISTENING...</span>
                        </div>
                      ) : (
                        <div className="flex items-center gap-2 text-success">
                          <CheckCircle2 size={14} />
                          <span>READY TO SEND</span>
                        </div>
                      )}
                      <button className="reset-voice" onClick={() => { setTranscription(""); setOperatorMsg(""); if (isRecording) toggleVoiceCapture(); }}>
                        RESET
                      </button>
                    </div>

                    <div className="transcription-area font-mono">
                      {transcription || (isRecording ? "..." : "")}
                    </div>

                    {speechError && <div className="speech-error">{speechError}</div>}

                    <div className="flex-row gap-2 mt-4">
                      {isRecording ? (
                        <button className="cyber-button amber full-w" onClick={toggleVoiceCapture}>
                          STOP RECORDING
                        </button>
                      ) : (
                        <button className="cyber-button primary full-w" onClick={() => respondToVictim(waitingDrone.id)}>
                          <Send size={16} /> TRANSMIT INTEL & RESCUE
                        </button>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
