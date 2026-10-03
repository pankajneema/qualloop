import { connect } from 'node:net';

// The login specs make deliberate failed sign-ins. The per-IP cap (5 failures per 15 minutes) is kept as it is; instead
// the specs clear the counters before each test, so a second run, a retry or a parallel project never turns a valid
// sign-in into a 429. The counters live in the dev stack's Redis (db 0) as `rl:*` keys, which the app ACL user may
// touch (ADR-008). SCAN, never KEYS (denied for that user). No Redis client dependency: a minimal RESP2 exchange.

const PATTERNS = ['rl:login:*', 'rl:pwreset:*'];

type Reply = string | number | null | Reply[] | Error;

function encode(args: string[]): string {
  return `*${args.length}\r\n${args.map((a) => `$${Buffer.byteLength(a)}\r\n${a}\r\n`).join('')}`;
}

/** Parses one RESP2 reply starting at `at`; returns the value and the offset after it, or null if incomplete. */
function parse(buf: Buffer, at: number): [Reply, number] | null {
  const eol = buf.indexOf('\r\n', at);
  if (eol < 0) return null;
  const type = String.fromCharCode(buf[at] ?? 0);
  const line = buf.toString('utf8', at + 1, eol);
  const next = eol + 2;
  switch (type) {
    case '+':
      return [line, next];
    case '-':
      return [new Error(line), next];
    case ':':
      return [Number(line), next];
    case '$': {
      const len = Number(line);
      if (len < 0) return [null, next];
      if (buf.length < next + len + 2) return null;
      return [buf.toString('utf8', next, next + len), next + len + 2];
    }
    case '*': {
      const count = Number(line);
      if (count < 0) return [null, next];
      const items: Reply[] = [];
      let offset = next;
      for (let i = 0; i < count; i += 1) {
        const item = parse(buf, offset);
        if (!item) return null;
        items.push(item[0]);
        offset = item[1];
      }
      return [items, offset];
    }
    default:
      throw new Error(`unexpected RESP type ${type}`);
  }
}

function redisUrl(): URL {
  const port = process.env.QL_REDIS_HOST_PORT ?? '6379';
  const password = process.env.QL_REDIS_PASSWORD ?? 'qualloop-redis-dev-only';
  return new URL(
    process.env.E2E_REDIS_URL ?? `redis://qualloop_app:${password}@127.0.0.1:${port}/0`,
  );
}

async function withRedis<T>(run: (send: (...args: string[]) => Promise<Reply>) => Promise<T>) {
  const url = redisUrl();
  const socket = connect({ host: url.hostname, port: Number(url.port || 6379) });
  let buffer = Buffer.alloc(0);
  const waiting: Array<(reply: Reply) => void> = [];
  socket.on('data', (chunk) => {
    buffer = Buffer.concat([buffer, chunk]);
    for (;;) {
      const parsed = parse(buffer, 0);
      if (!parsed) return;
      buffer = buffer.subarray(parsed[1]);
      waiting.shift()?.(parsed[0]);
    }
  });
  const failed = new Promise<never>((_, reject) => socket.once('error', reject));
  const send = (...args: string[]) =>
    Promise.race([
      new Promise<Reply>((resolve) => {
        waiting.push(resolve);
        socket.write(encode(args));
      }),
      failed,
    ]);
  try {
    const auth = await send(
      'AUTH',
      decodeURIComponent(url.username),
      decodeURIComponent(url.password),
    );
    if (auth instanceof Error) throw new Error(`Redis AUTH failed: ${auth.message}`);
    const db = url.pathname.replace('/', '') || '0';
    const selected = await send('SELECT', db);
    if (selected instanceof Error) throw new Error(`Redis SELECT failed: ${selected.message}`);
    return await run(send);
  } finally {
    socket.destroy();
  }
}

/** Delete every login / password-reset rate-limit counter of the dev stack. Returns how many keys it removed. */
export async function clearAuthRateLimits(): Promise<number> {
  return withRedis(async (send) => {
    let removed = 0;
    for (const pattern of PATTERNS) {
      let cursor = '0';
      do {
        const reply = await send('SCAN', cursor, 'MATCH', pattern, 'COUNT', '500');
        if (reply instanceof Error || !Array.isArray(reply)) {
          throw new Error(`Redis SCAN failed: ${String(reply)}`);
        }
        cursor = String(reply[0]);
        const keys = reply[1] as string[];
        if (keys.length > 0) {
          const deleted = await send('DEL', ...keys);
          if (deleted instanceof Error) throw new Error(`Redis DEL failed: ${deleted.message}`);
          removed += Number(deleted);
        }
      } while (cursor !== '0');
    }
    return removed;
  });
}
