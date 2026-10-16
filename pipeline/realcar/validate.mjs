import fs from 'fs';
import validator from 'gltf-validator';
const f = process.argv[2];
const r = await validator.validateBytes(new Uint8Array(fs.readFileSync(f)), { maxIssues: 50 });
console.log(JSON.stringify({ errors: r.issues.numErrors, warnings: r.issues.numWarnings, infos: r.issues.numInfos,
  top: r.issues.messages.filter(m => m.severity <= 1).slice(0, 12).map(m => `${m.severity} ${m.code} ${m.pointer} ${m.message}`) }, null, 1));
