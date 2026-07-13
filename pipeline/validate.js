/* validate.js — run the official Khronos glTF Validator on a GLB.
 * Usage: node pipeline/validate.js <file.glb> [reportOut.json]
 * Exit code 1 if the asset has spec ERRORS (release blocker); 0 otherwise.
 * Free / Apache-2.0 (KhronosGroup/glTF-Validator).
 */
const fs = require('fs');
const path = require('path');
const validator = require('gltf-validator');

const file = process.argv[2];
const out = process.argv[3] || file.replace(/\.(glb|gltf)$/i, '') + '_validation.json';
if (!file || !fs.existsSync(file)) { console.error('validate: missing GLB', file); process.exit(2); }

const bytes = new Uint8Array(fs.readFileSync(file));
validator.validateBytes(bytes, {
  uri: path.basename(file),
  maxIssues: 100,
  externalResourceFunction: () => Promise.reject('external resources not resolved (self-contained GLB expected)'),
}).then((report) => {
  const i = report.issues;
  fs.writeFileSync(out, JSON.stringify(report, null, 1));
  console.log(`\n===== glTF VALIDATION: ${path.basename(file)} =====`);
  console.log(`generator: ${report.info && report.info.generator}`);
  console.log(`errors=${i.numErrors} warnings=${i.numWarnings} infos=${i.numInfos} hints=${i.numHints}`);
  for (const m of i.messages.slice(0, 15)) console.log(`  [${m.severity===0?'ERROR':m.severity===1?'WARN':'INFO'}] ${m.code}: ${m.message} @ ${m.pointer||''}`);
  console.log('report ->', out);
  process.exit(i.numErrors > 0 ? 1 : 0);   // errors block release
}).catch((e) => { console.error('validate failed:', e); process.exit(2); });
