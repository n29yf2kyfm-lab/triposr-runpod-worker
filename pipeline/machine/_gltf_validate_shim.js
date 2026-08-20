#!/usr/bin/env node
/*
 * Thin CLI shim over the OFFICIAL Khronos glTF-Validator.
 *
 * The `gltf-validator` npm package (Khronos Group, Apache-2.0, Dart-compiled to
 * JS) ships a LIBRARY only -- its package.json has "bin": null, so there is no
 * `gltf-validator` command on PATH after a global install. This file supplies
 * the missing CLI.
 *
 * NOTE FOR FUTURE AGENTS: `gltf-transform` is NOT a validator. It is a glTF
 * transform/optimise toolkit. Its `validate` subcommand does not exist and its
 * `inspect` output is not a conformance report. Do not conflate the two.
 *
 * Usage:  node _gltf_validate_shim.js <file.glb|file.gltf> [maxIssues]
 * Output: the raw Khronos validation report as JSON on stdout.
 */
'use strict';

const fs = require('fs');
const path = require('path');

let validator;
try {
  validator = require('gltf-validator');
} catch (e) {
  // Global installs are not on Node's default resolution path.
  const candidates = [
    '/opt/node22/lib/node_modules/gltf-validator',
    '/usr/lib/node_modules/gltf-validator',
    '/usr/local/lib/node_modules/gltf-validator',
  ];
  for (const c of candidates) {
    try { validator = require(c); break; } catch (_) { /* keep looking */ }
  }
  if (!validator) {
    console.error('FATAL: cannot resolve the gltf-validator package. ' +
                  'Install it with:  npm install -g gltf-validator');
    process.exit(2);
  }
}

const target = process.argv[2];
const maxIssues = process.argv[3] ? parseInt(process.argv[3], 10) : 0;

if (!target) {
  console.error('usage: node _gltf_validate_shim.js <file.glb> [maxIssues]');
  process.exit(2);
}
if (!fs.existsSync(target)) {
  console.error('FATAL: no such file: ' + target);
  process.exit(2);
}

const bytes = new Uint8Array(fs.readFileSync(target));
const baseDir = path.dirname(path.resolve(target));

validator
  .validateBytes(bytes, {
    uri: path.basename(target),
    maxIssues: maxIssues,
    // Resolve external .bin / image files sitting next to a .gltf so that a
    // non-embedded asset is validated in full rather than silently skipped.
    externalResourceFunction: (uri) =>
      new Promise((resolve, reject) => {
        const p = path.resolve(baseDir, decodeURIComponent(uri));
        fs.readFile(p, (err, data) => {
          if (err) reject(err.toString());
          else resolve(new Uint8Array(data));
        });
      }),
  })
  .then((report) => {
    report.validatorPackageVersion = validator.version();
    process.stdout.write(JSON.stringify(report, null, 2));
    process.exit(0);
  })
  .catch((err) => {
    console.error('VALIDATION_THREW: ' + err);
    process.exit(3);
  });
