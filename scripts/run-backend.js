#!/usr/bin/env node

const { existsSync } = require('node:fs')
const { join } = require('node:path')
const { spawn } = require('node:child_process')

const repoRoot = process.cwd()
const backendDir = join(repoRoot, 'backend')
const checkOnly = process.argv.includes('--check')

const candidates = [
  join(backendDir, '.venv', 'bin', 'python'),
  join(backendDir, '.venv', 'bin', 'python3'),
  join(backendDir, '.venv', 'Scripts', 'python.exe')
]

const pythonPath = candidates.find(p => existsSync(p))

if (!pythonPath) {
  console.error('Backend .venv Python not found.')
  console.error('Please prebuild dependencies before offline startup: npm run setup:backend')
  process.exit(1)
}

if (checkOnly) {
  console.log(`Backend python resolved: ${pythonPath}`)
  process.exit(0)
}

const child = spawn(pythonPath, ['run.py'], {
  cwd: backendDir,
  stdio: 'inherit',
  env: process.env
})

child.on('exit', (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal)
    return
  }
  process.exit(code ?? 0)
})

child.on('error', err => {
  console.error('Failed to start backend:', err.message)
  process.exit(1)
})
