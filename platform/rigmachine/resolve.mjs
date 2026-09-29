// Ask the LIVE resolver logic (platform/resolver/index.ts, unchanged) which
// catalogue car matches a decoded vehicle. Prints the resolver's JSON reply.
//   node --experimental-strip-types resolve.mjs '{"make":"Audi","model":"RS6","year":2021}'
// The registration is never an input here, exactly as in the resolver.
import { handler } from '../resolver/index.ts';
const body = process.argv[2] || '{}';
const res = await handler(new Request('http://local/resolve?device=desktop', { method: 'POST', body }));
process.stdout.write(await res.text());
