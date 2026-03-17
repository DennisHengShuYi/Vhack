import React from 'react';

interface StatBoxProps {
  icon: React.ReactNode;
  label: string;
  value: string;
  color: 'cyan' | 'amber' | 'success';
}

export default function StatBox({ icon, label, value, color }: StatBoxProps) {
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
    </div>
  );
}
