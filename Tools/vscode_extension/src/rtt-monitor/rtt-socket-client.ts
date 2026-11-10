import * as net from 'net';

export type RttSocketState = 'connecting' | 'connected' | 'closed' | 'failed';
export type RttLineEnding = 'crlf' | 'lf' | 'cr' | 'none';

const ENDINGS: Record<RttLineEnding, string> = { crlf: '\r\n', lf: '\n', cr: '\r', none: '' };

export interface RttSocketEvents {
  onData(text: string): void;
  onState(state: RttSocketState, detail?: string): void;
}

/** Parses "127.0.0.1:19021"; only loopback endpoints are accepted. */
export function parseEndpoint(endpoint: string): { host: string; port: number } {
  const match = /^(127\.0\.0\.1|localhost):(\d{1,5})$/.exec(endpoint.trim());
  const port = match ? Number(match[2]) : 0;
  if (!match || port < 1 || port > 65535) { throw new Error(`RTT endpoint must be 127.0.0.1:<port>, got "${endpoint}"`); }
  return { host: '127.0.0.1', port };
}

/**
 * One TCP client of a JLinkExe RTT telnet port. JLinkExe serves a single
 * client, so a connection that closes before any data arrives usually means
 * another RTT client (μScope, telnet) already holds the port. There is no
 * reconnect loop: the owner decides when to connect again.
 */
export class RttSocketClient {
  private socket?: net.Socket;
  private received = false;
  public state: RttSocketState = 'closed';

  constructor(private readonly events: RttSocketEvents) {}

  public connect(endpoint: string, timeoutMs = 3000): void {
    this.close();
    const { host, port } = parseEndpoint(endpoint);
    this.received = false;
    this.setState('connecting');
    const socket = net.createConnection({ host, port });
    this.socket = socket;
    socket.setEncoding('utf8');
    socket.setNoDelay(true);
    socket.setTimeout(timeoutMs);
    socket.once('connect', () => { socket.setTimeout(0); if (this.socket === socket) { this.setState('connected'); } });
    socket.once('timeout', () => socket.destroy(new Error('connect timed out')));
    socket.on('data', (text: string) => {
      if (this.socket !== socket) { return; }
      this.received = true;
      this.events.onData(text);
    });
    socket.on('error', (error: NodeJS.ErrnoException) => {
      if (this.socket !== socket) { return; }
      const detail = error.code === 'ECONNREFUSED' ? 'bridge is not listening' : error.message;
      this.setState('failed', detail);
    });
    socket.on('close', () => {
      if (this.socket !== socket) { return; }
      this.socket = undefined;
      if (this.state === 'failed') { return; }
      if (!this.received) { this.setState('failed', 'port busy (another RTT client?)'); return; }
      this.setState('closed', 'bridge closed the connection');
    });
  }

  /** Sends one input line with the configured line ending. */
  public send(text: string, ending: RttLineEnding): boolean {
    if (!this.socket || this.state !== 'connected') { return false; }
    this.socket.write(text + ENDINGS[ending]);
    return true;
  }

  /** Closes without a state event; the owner already knows why it closed. */
  public close(): void {
    const socket = this.socket;
    if (!socket) { return; }
    this.socket = undefined;
    this.state = 'closed';
    socket.destroy();
  }

  private setState(state: RttSocketState, detail?: string): void {
    this.state = state;
    this.events.onState(state, detail);
  }
}
