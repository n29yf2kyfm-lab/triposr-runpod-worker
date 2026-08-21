const fs=require('fs');
const validator=require('/opt/node22/lib/node_modules/gltf-validator');
const f=process.argv[2];
const buf=fs.readFileSync(f);
validator.validateBytes(new Uint8Array(buf),{maxIssues:200})
 .then(r=>{console.log(JSON.stringify(r));})
 .catch(e=>{console.error('VALFAIL',e);process.exit(1);});
