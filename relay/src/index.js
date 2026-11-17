// Zook relay: passes sealed messages between one Mac ("host") and its paired devices.
// It never sees message content (everything in `d` is end-to-end encrypted) and stores nothing
// except a hash of the host's room key, so nobody else can claim to be that Mac.
//
// WebSocket endpoints:
//   /v1/room/<roomId>/host    header or query `key`: the room key chosen by the Mac
//   /v1/room/<roomId>/device
// Frames are JSON text:
//   device -> relay: {"d": "<sealed>"}            relay -> host:   {"c": "<conn>", "d": "<sealed>"}
//   host -> relay:   {"c": "<conn>", "d": "..."}  relay -> device: {"d": "<sealed>"}
//   relay -> host:   {"c": "<conn>", "event": "open" | "close"}
//   relay -> device: {"event": "host", "online": true | false}

const ROOM_ID = /^[a-f0-9]{32,64}$/;
const MAX_FRAME = 900 * 1024;  // stay under the platform's WebSocket message limit
const MAX_DEVICES = 20;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const match = url.pathname.match(/^\/v1\/room\/([^/]+)\/(host|device)$/);
    if (url.pathname === '/') return new Response('zook-relay ok\n');
    if (!match || !ROOM_ID.test(match[1])) return new Response('not found', {status: 404});
    if (request.headers.get('Upgrade') !== 'websocket') return new Response('expected websocket', {status: 426});
    return env.ROOMS.get(env.ROOMS.idFromName(match[1])).fetch(request);
  },
};

async function sha256(text) {
  const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return [...new Uint8Array(bytes)].map(b => b.toString(16).padStart(2, '0')).join('');
}

export class Room {
  constructor(state) {
    this.state = state;
    this.host = null;
    this.devices = new Map();  // conn id -> socket
  }

  async fetch(request) {
    const url = new URL(request.url);
    const role = url.pathname.endsWith('/host') ? 'host' : 'device';
    if (role === 'host') {
      const key = request.headers.get('X-Zook-Room-Key') || url.searchParams.get('key') || '';
      if (key.length < 32) return new Response('room key required', {status: 401});
      const hash = await sha256(key), known = await this.state.storage.get('hostKeyHash');
      if (known && known !== hash) return new Response('this room belongs to another host', {status: 403});
      if (!known) await this.state.storage.put('hostKeyHash', hash);
    } else if (this.devices.size >= MAX_DEVICES) return new Response('too many devices', {status: 429});

    const pair = new WebSocketPair(), server = pair[1];
    server.accept();
    if (role === 'host') this.acceptHost(server); else this.acceptDevice(server);
    return new Response(null, {status: 101, webSocket: pair[0]});
  }

  send(socket, message) { try { socket.send(JSON.stringify(message)); } catch (_) {} }

  acceptHost(socket) {
    if (this.host) { try { this.host.close(4000, 'replaced by a newer connection'); } catch (_) {} }
    this.host = socket;
    for (const [conn, device] of this.devices) { this.send(device, {event: 'host', online: true}); this.send(socket, {c: conn, event: 'open'}); }
    socket.addEventListener('message', event => {
      if (typeof event.data !== 'string' || event.data.length > MAX_FRAME) return;
      let message; try { message = JSON.parse(event.data); } catch (_) { return; }
      const device = this.devices.get(message.c);
      if (!device) return;
      if (message.event === 'close') { try { device.close(4001, 'closed by host'); } catch (_) {} return; }
      if (typeof message.d === 'string') this.send(device, {d: message.d});
    });
    const gone = () => {
      if (this.host !== socket) return;
      this.host = null;
      for (const device of this.devices.values()) this.send(device, {event: 'host', online: false});
    };
    socket.addEventListener('close', gone); socket.addEventListener('error', gone);
  }

  acceptDevice(socket) {
    const conn = crypto.randomUUID();
    this.devices.set(conn, socket);
    this.send(socket, {event: 'host', online: !!this.host});
    if (this.host) this.send(this.host, {c: conn, event: 'open'});
    socket.addEventListener('message', event => {
      if (typeof event.data !== 'string' || event.data.length > MAX_FRAME) return;
      let message; try { message = JSON.parse(event.data); } catch (_) { return; }
      if (typeof message.d !== 'string') return;
      if (this.host) this.send(this.host, {c: conn, d: message.d}); else this.send(socket, {event: 'host', online: false});
    });
    const gone = () => {
      if (!this.devices.delete(conn)) return;
      if (this.host) this.send(this.host, {c: conn, event: 'close'});
    };
    socket.addEventListener('close', gone); socket.addEventListener('error', gone);
  }
}
