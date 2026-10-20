import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

const root = process.argv[2] || "apps/web/dist";
const files = await readdir(root, { recursive: true });
const artifacts = files.filter(file => /\.(?:js|css|html)$/.test(file));
assert.ok(artifacts.length > 0, "Build the production frontend before checking its artifacts");
for (const file of artifacts) {
  const source = await readFile(path.join(root, file), "utf8");
  assert.ok(!/dev-tests|DevTestApp|\/dev-test|dt-review|manual-server-uniform-center-square-v1|Kiểm thử thủ công/.test(source),
    `Development-only code leaked into production artifact: ${file}`);
}
console.log(JSON.stringify({ passed: true, productionArtifactsChecked: artifacts.length, root }));
