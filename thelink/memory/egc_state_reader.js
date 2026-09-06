// Reads the EGC memory document of one project through the EGC package
// installed on this machine, so The Link never re-implements EGC's storage
// layout or its encryption.
//
//   node egc_state_reader.js <egc package dir> <project path>
//
// Prints one JSON object on stdout: { source, branch, memory, global }.
// "memory" is the project's Agent Memory Interchange document as plain text,
// "global" the user-wide appendix EGC adds to it, both null when absent.
// Read-only by construction: none of the EGC helpers used here write files,
// propagate memory into the project, or consolidate state.
'use strict';

const path = require('path');

const packageDir = process.argv[2];
const projectPath = process.argv[3];

if (!packageDir || !projectPath) {
  process.stderr.write('usage: egc_state_reader.js <egc-package-dir> <project-path>\n');
  process.exit(64);
}

function egcLib(name) {
  return require(path.join(packageDir, 'scripts', 'lib', name));
}

let branchState;
let stateCrypto;
try {
  branchState = egcLib('branch-state');
  stateCrypto = egcLib('state-crypto');
} catch (err) {
  process.stderr.write(`EGC libraries not found under ${packageDir}: ${err.message}\n`);
  process.exit(65);
}

let globalState = null;
try {
  globalState = egcLib('global-state');
} catch {
  globalState = null;
}

const stateDir = branchState.getStateDir();
const branch = branchState.detectBranch(projectPath);
const resolved = branchState.resolveStateRead(stateDir, projectPath, branch);

let memory = null;
if (resolved.source !== 'none') {
  try {
    memory = stateCrypto.readStateFileDecrypted(resolved.filePath);
  } catch {
    memory = null;
  }
}

let global = null;
if (globalState) {
  try {
    global = globalState.readGlobalAppendix(memory || '', stateCrypto);
  } catch {
    global = null;
  }
}

process.stdout.write(JSON.stringify({
  source: resolved.source,
  branch: resolved.branch || null,
  memory: memory || null,
  global: global || null,
}));
