/**
 * Race artwork used when no licensed photograph is stored for an event.
 * It is a designed composition (kerb stripes and the round number), not a map of the circuit.
 */
export function TrackArt({ round, label }: { round: number | string; label: string }) {
  return (
    <svg viewBox="0 0 800 520" preserveAspectRatio="xMidYMid slice" role="img" aria-label={label}>
      <rect width="800" height="520" fill="var(--art-a)" />
      <defs>
        <pattern id="kerb" width="64" height="64" patternUnits="userSpaceOnUse" patternTransform="rotate(-32)">
          <rect width="32" height="64" fill="var(--red)" />
          <rect x="32" width="32" height="64" fill="var(--art-ink)" />
        </pattern>
      </defs>
      <g transform="translate(0 0)">
        <polygon points="470,-20 900,-20 900,540 250,540" fill="var(--art-b)" />
        <polygon points="520,-20 640,-20 330,540 210,540" fill="url(#kerb)" opacity="0.9" />
        <polygon points="662,-20 700,-20 390,540 352,540" fill="var(--red)" opacity="0.9" />
      </g>
      <text x="64" y="420" fontFamily="Bahnschrift, 'Arial Narrow', system-ui, sans-serif" fontWeight="800" fontSize="330" fill="none" stroke="var(--text)" strokeWidth="3" opacity="0.55">{round}</text>
    </svg>
  )
}
