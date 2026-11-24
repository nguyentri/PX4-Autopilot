// The session report page: one self-contained HTML file with inline CSS and
// an inline SVG track. No script, no remote resource; a CSP meta tag forbids
// both, so the file stays inert wherever it is opened.
import { html, Raw } from './html-escape';
import { TrackPoint } from './session-statistics';

const CSS = `
:root { color-scheme: light dark; --fg: #1f2328; --muted: #59636e; --line: #d1d9e0; --accent: #ed6c00; --bg: #ffffff; }
@media (prefers-color-scheme: dark) { :root { --fg: #e6edf3; --muted: #9198a1; --line: #3d444d; --bg: #0d1117; } }
body { font: 14px/1.45 system-ui, sans-serif; color: var(--fg); background: var(--bg); margin: 0 auto; max-width: 1000px;
  padding: 24px 16px; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 17px; margin: 28px 0 8px; border-bottom: 1px solid var(--line); padding-bottom: 4px; }
p.note, td.empty { color: var(--muted); }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; padding: 3px 8px 3px 0; border-bottom: 1px solid var(--line); vertical-align: top; }
th { font-weight: 600; }
td.num { font-variant-numeric: tabular-nums; white-space: nowrap; }
td.time { white-space: nowrap; color: var(--muted); font-variant-numeric: tabular-nums; }
pre { white-space: pre-wrap; word-break: break-word; font: 12px/1.4 ui-monospace, monospace; border: 1px solid var(--line);
  padding: 8px; max-height: none; }
svg { border: 1px solid var(--line); max-width: 100%; height: auto; }
.sev-0, .sev-1, .sev-2, .sev-3 { color: #d1242f; font-weight: 600; }
.sev-4 { color: #bf8700; }
@media print { body { max-width: none; } }
`;

export interface Column {
  title: string;
  className?: string;
}

export function table(columns: Column[], rows: unknown[][], empty: string): Raw {
  if (!rows.length) return html`<p class="note">${empty}</p>`;
  return html`<table><thead><tr>${columns.map((c) => html`<th>${c.title}</th>`)}</tr></thead><tbody>${
    rows.map((row) => html`<tr>${row.map((cell, i) => {
      const cls = columns[i]?.className;
      return cls ? html`<td class="${cls}">${cell}</td>` : html`<td>${cell}</td>`;
    })}</tr>`)}</tbody></table>`;
}

const SVG_W = 640;
const SVG_H = 420;
const SVG_PAD = 20;

/** The track as an inline SVG polyline, north up, equal scale on both axes, home and the last position marked. */
export function trackSvg(points: TrackPoint[]): Raw {
  if (points.length < 2) return html`<p class="note">Not enough position data for a track.</p>`;
  const all = [{ east: 0, north: 0 }, ...points];
  const east = all.map((p) => p.east);
  const north = all.map((p) => p.north);
  const [minE, maxE, minN, maxN] = [Math.min(...east), Math.max(...east), Math.min(...north), Math.max(...north)];
  // One scale for both axes; spans under 1 m are drawn as 1 m so a hover does not blow up to the full frame.
  const scale = Math.min((SVG_W - 2 * SVG_PAD) / Math.max(maxE - minE, 1), (SVG_H - 2 * SVG_PAD) / Math.max(maxN - minN, 1));
  const x = (e: number): string => (SVG_PAD + (e - minE) * scale).toFixed(1);
  const y = (n: number): string => (SVG_H - SVG_PAD - (n - minN) * scale).toFixed(1);
  const line = points.map((p) => `${x(p.east)},${y(p.north)}`).join(' ');
  const last = points[points.length - 1];
  const widthM = (SVG_W - 2 * SVG_PAD) / scale;
  return html`<svg viewBox="0 0 ${SVG_W} ${SVG_H}" width="${SVG_W}" height="${SVG_H}" role="img"
 aria-label="Session track, ${points.length} points">
<polyline points="${line}" fill="none" stroke="#ed6c00" stroke-width="2" stroke-linejoin="round"/>
<circle cx="${x(0)}" cy="${y(0)}" r="5" fill="none" stroke="currentColor" stroke-width="2"/>
<circle cx="${x(last.east)}" cy="${y(last.north)}" r="4" fill="#ed6c00"/>
<text x="${SVG_PAD}" y="${SVG_H - 6}" font-size="11" fill="currentColor">Width shown: ${widthM.toFixed(0)} m. Circle: home. Dot: last position. North up.</text>
</svg>`;
}

export function page(title: string, generated: string, body: Raw): string {
  return `<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<meta name="viewport" content="width=device-width, initial-scale=1">
${html`<title>${title}</title>`}
<style>${CSS}</style></head>
<body>${html`<h1>${title}</h1><p class="note">Generated ${generated} by Px4-GCS.</p>`}
${body}
</body></html>
`;
}
