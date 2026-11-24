// Content security policy and page shell of the dashboard webview (plan
// decision D8): nothing loads from a remote origin, scripts run only with the
// per-load nonce, images are `data:` only. xterm inserts <style> elements, so
// styles also allow 'unsafe-inline'; scripts never do. No `vscode` import.
import { randomBytes } from 'crypto';

export function createNonce(): string {
  return randomBytes(16).toString('base64');
}

export function buildDashboardCsp(cspSource: string, nonce: string): string {
  return [
    "default-src 'none'",
    `script-src 'nonce-${nonce}'`,
    `style-src ${cspSource} 'unsafe-inline'`,
    `font-src ${cspSource}`,
    'img-src data:',
  ].join('; ');
}

export interface DashboardPageParts {
  cspSource: string;
  nonce: string;
  scriptUri: string;
  styleUris: string[];
}

function attribute(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
}

/** The static page: an empty root that the nonce-bearing bundle fills. */
export function dashboardHtml(parts: DashboardPageParts): string {
  const styles = parts.styleUris.map((uri) => `<link rel="stylesheet" href="${attribute(uri)}">`).join('\n  ');
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy" content="${attribute(buildDashboardCsp(parts.cspSource, parts.nonce))}">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  ${styles}
  <title>Px4-GCS</title>
</head>
<body>
  <div id="root"></div>
  <script nonce="${attribute(parts.nonce)}" src="${attribute(parts.scriptUri)}"></script>
</body>
</html>`;
}
