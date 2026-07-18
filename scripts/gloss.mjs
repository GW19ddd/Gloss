#!/usr/bin/env node

import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const BACKEND = path.join(ROOT, "backend");
const FRONTEND = path.join(ROOT, "frontend");
const IS_WINDOWS = process.platform === "win32";
const VENV_PYTHON = path.join(
  BACKEND,
  ".venv",
  IS_WINDOWS ? "Scripts" : "bin",
  IS_WINDOWS ? "python.exe" : "python",
);

function fail(message) {
  console.error(`Gloss: ${message}`);
  process.exit(1);
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd ?? ROOT,
    env: options.env ?? process.env,
    encoding: "utf8",
    stdio: options.capture ? "pipe" : "inherit",
    shell: options.shell ?? false,
  });
  if (result.error) fail(`could not run ${command}: ${result.error.message}`);
  if (result.status !== 0) {
    if (options.capture && result.stderr) process.stderr.write(result.stderr);
    process.exit(result.status ?? 1);
  }
  return result.stdout?.trim() ?? "";
}

function cacheDir() {
  if (process.env.GLOSS_CACHE_DIR) return path.resolve(process.env.GLOSS_CACHE_DIR);
  if (IS_WINDOWS) {
    const local = process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local");
    return path.join(local, "Gloss", "cache");
  }
  return path.join(process.env.XDG_CACHE_HOME || path.join(os.homedir(), ".cache"), "gloss");
}

function setupEnv() {
  const cache = cacheDir();
  const temp = path.join(cache, "tmp");
  fs.mkdirSync(path.join(cache, "pip"), { recursive: true });
  fs.mkdirSync(path.join(cache, "npm"), { recursive: true });
  fs.mkdirSync(temp, { recursive: true });
  return {
    ...process.env,
    PIP_CACHE_DIR: path.join(cache, "pip"),
    npm_config_cache: path.join(cache, "npm"),
    TMPDIR: temp,
    TEMP: temp,
    TMP: temp,
  };
}

function parseOption(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : undefined;
}

function pythonCandidates() {
  const preferred = parseOption("--python") ?? process.env.GLOSS_PYTHON;
  if (preferred) return [{ command: preferred, prefix: [] }];
  if (IS_WINDOWS) {
    return [
      { command: "py", prefix: ["-3.12"] },
      { command: "py", prefix: ["-3.11"] },
      { command: "python", prefix: [] },
    ];
  }
  return [
    { command: "python3", prefix: [] },
    { command: "python", prefix: [] },
  ];
}

function selectPython() {
  for (const candidate of pythonCandidates()) {
    const probe = spawnSync(
      candidate.command,
      [...candidate.prefix, "-c", "import sys; print('.'.join(map(str, sys.version_info[:3])))"],
      { encoding: "utf8", shell: false },
    );
    if (probe.status !== 0) continue;
    const [major, minor] = probe.stdout.trim().split(".").map(Number);
    if (major === 3 && minor >= 11) return candidate;
  }
  fail("Python 3.11 or newer was not found. Set GLOSS_PYTHON or pass --python <path>.");
}

function packageManager() {
  const agent = process.env.npm_config_user_agent ?? "";
  return agent.startsWith("bun/") ? "bun" : "npm";
}

function packageCommand(manager) {
  if (!IS_WINDOWS) return manager;
  return manager === "npm" ? "npm.cmd" : "bun.exe";
}

function packageInvocation(manager, args) {
  if (!IS_WINDOWS) return { command: packageCommand(manager), args };
  return {
    command: process.env.ComSpec ?? process.env.COMSPEC ?? "cmd.exe",
    args: ["/d", "/s", "/c", packageCommand(manager), ...args],
  };
}

function runPackage(manager, args, options = {}) {
  const invocation = packageInvocation(manager, args);
  run(invocation.command, invocation.args, options);
}

function setup() {
  const nodeMajor = Number(process.versions.node.split(".")[0]);
  if (nodeMajor < 18) fail(`Node.js 18 or newer is required (found ${process.versions.node}).`);
  const env = setupEnv();
  if (!fs.existsSync(VENV_PYTHON)) {
    const python = selectPython();
    console.log("==> creating backend virtual environment");
    run(python.command, [...python.prefix, "-m", "venv", path.join(BACKEND, ".venv")], { env });
  }
  console.log("==> installing backend dependencies");
  run(VENV_PYTHON, ["-m", "pip", "install", "--upgrade", "pip"], { env });
  run(VENV_PYTHON, ["-m", "pip", "install", "-r", path.join(BACKEND, "requirements.txt")], { env });

  const manager = packageManager();
  console.log(`==> installing and building frontend with ${manager}`);
  if (manager === "bun") {
    runPackage(manager, ["install", "--frozen-lockfile"], { cwd: FRONTEND, env });
    runPackage(manager, ["run", "build"], { cwd: FRONTEND, env });
  } else {
    runPackage(manager, ["ci", "--no-fund", "--no-audit"], { cwd: FRONTEND, env });
    runPackage(manager, ["run", "build"], { cwd: FRONTEND, env });
  }
  console.log(`==> ready. Cache: ${cacheDir()}`);
  console.log("    Start with: npm start  (or bun run start)");
}

function selectedPort() {
  return Number(parseOption("--port") ?? process.env.GLOSS_PORT ?? "8010");
}

function selectedHost() {
  return parseOption("--host") ?? process.env.GLOSS_HOST ?? "0.0.0.0";
}

function assertPrepared(requireFrontend = true) {
  if (!fs.existsSync(VENV_PYTHON)) fail("backend virtual environment is missing; run npm run setup first.");
  if (requireFrontend && !fs.existsSync(path.join(FRONTEND, "dist", "index.html"))) {
    fail("frontend build is missing; run npm run setup first.");
  }
}

function portIsFree(host, port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve(false));
    server.once("listening", () => server.close(() => resolve(true)));
    server.listen(port, host);
  });
}

async function start() {
  assertPrepared();
  const host = selectedHost();
  const port = selectedPort();
  if (!(await portIsFree(host, port))) {
    fail(`port ${port} on ${host} is already in use. Set GLOSS_PORT or pass --port <number>.`);
  }
  console.log(`Gloss: http://127.0.0.1:${port}`);
  const child = spawn(
    VENV_PYTHON,
    ["-m", "uvicorn", "app.main:app", "--host", host, "--port", String(port)],
    { cwd: BACKEND, env: process.env, stdio: "inherit", shell: false, detached: !IS_WINDOWS },
  );
  supervise([{ child, name: "backend" }]);
}

function terminate(child) {
  if (!child || !child.pid || child.exitCode !== null) return;
  if (IS_WINDOWS) {
    spawnSync("taskkill", ["/pid", String(child.pid), "/t", "/f"], { stdio: "ignore" });
  } else {
    try {
      process.kill(-child.pid, "SIGTERM");
    } catch {
      child.kill("SIGTERM");
    }
  }
}

function supervise(entries) {
  let stopping = false;
  const stop = (code = 0) => {
    if (stopping) return;
    stopping = true;
    for (const { child } of entries) terminate(child);
    process.exit(code);
  };
  process.once("SIGINT", () => stop(130));
  process.once("SIGTERM", () => stop(143));
  process.once("exit", () => {
    for (const { child } of entries) terminate(child);
  });
  for (const { child, name } of entries) {
    child.once("error", (error) => {
      console.error(`Gloss: ${name} failed to start: ${error.message}`);
      stop(1);
    });
    child.once("exit", (code, signal) => {
      if (!stopping) stop(code ?? (signal ? 1 : 0));
    });
  }
}

function dev() {
  assertPrepared(false);
  const port = selectedPort();
  const backend = spawn(
    VENV_PYTHON,
    ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(port), "--reload"],
    { cwd: BACKEND, env: process.env, stdio: "inherit", shell: false, detached: !IS_WINDOWS },
  );
  const manager = packageManager();
  const frontendInvocation = packageInvocation(manager, ["run", "dev"]);
  const frontend = spawn(frontendInvocation.command, frontendInvocation.args, {
    cwd: FRONTEND,
    env: process.env,
    stdio: "inherit",
    shell: false,
    detached: !IS_WINDOWS,
  });
  supervise([
    { child: backend, name: "backend" },
    { child: frontend, name: "frontend" },
  ]);
}

function test() {
  assertPrepared(false);
  run(VENV_PYTHON, ["-m", "pip", "install", "-r", path.join(ROOT, "tests", "requirements.txt")]);
  run(VENV_PYTHON, ["-m", "pytest", "-q"], { cwd: ROOT });
  runPackage(packageManager(), ["test"], { cwd: FRONTEND });
  runPackage(packageManager(), ["run", "build"], { cwd: FRONTEND });
}

const command = process.argv[2];
if (command === "setup") setup();
else if (command === "start") await start();
else if (command === "dev") dev();
else if (command === "test") test();
else fail("usage: node scripts/gloss.mjs <setup|start|dev|test>");
