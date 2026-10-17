#!/usr/bin/env node
// Render a motion spec to MP4, frame by frame (.claude/skills/motion).
//
//   node .claude/skills/motion/render.mjs <spec.json> <out.mp4>   render
//   node .claude/skills/motion/render.mjs <spec.json> --check      validate only
//
// Beside <out.mp4> it writes <out>.poster.png (a still for slides and
// thumbnails), <out>.sheet.png (one frame per scene, to review) and
// <out>.txt (every on-screen word and figure with its source, for alt
// text and captions). The same approach as Claude Motion: the animation
// is code, so there is no video model and no generated footage. Needs
// Node, the frontend's Playwright (npm --prefix frontend ci) and ffmpeg.
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(HERE, '..', '..', '..')
const SIZES = new Set(['1920x1080', '1280x720', '1080x1080', '1080x1920'])
const FPS = new Set([24, 25, 30, 60])
const THEMES = ['light', 'dark', 'rta', 'rta-dark']
const TYPES = new Set(['title', 'kpis', 'bars', 'statement'])
const MAX_SECONDS = 90
const LIMITS = { title: 90, kicker: 60, subtitle: 160, heading: 110, text: 160, note: 200, label: 48, footer: 160 }

/** Every problem with a spec at once; an empty list means it can render.
 *  A figure without a source is refused: numbers in a clip must trace to
 *  a calculation, as everywhere else in this project. */
export function validate(spec) {
  const problems = []
  const need = (ok, message) => { if (!ok) problems.push(message) }
  need(spec && typeof spec === 'object', 'The spec must be a JSON object.')
  if (problems.length) return problems
  const size = `${spec.width ?? 1920}x${spec.height ?? 1080}`
  need(SIZES.has(size), `Size ${size} is not one of ${[...SIZES].join(', ')}.`)
  need(FPS.has(spec.fps ?? 30), `fps must be one of ${[...FPS].join(', ')}.`)
  need(['en', 'ar'].includes(spec.language ?? 'en'), 'language must be "en" or "ar".')
  need(THEMES.includes(spec.theme ?? 'light'), `theme must be one of ${THEMES.join(', ')}.`)
  need(Array.isArray(spec.scenes) && spec.scenes.length > 0, 'scenes must be a non-empty list.')
  if (spec.footer) need(spec.footer.length <= LIMITS.footer, `footer is over ${LIMITS.footer} characters.`)
  if (spec.poster != null) {
    need(Number.isInteger(spec.poster) && spec.poster >= 1 && spec.poster <= (spec.scenes || []).length,
      `poster must be a scene number from 1 to ${(spec.scenes || []).length}.`)
  }
  let total = 0
  const figure = (where, item) => {
    need(typeof item?.value === 'number' && Number.isFinite(item.value), `${where}: value must be a number.`)
    need(typeof item?.source === 'string' && item.source.trim().length > 0,
      `${where}: every figure needs a "source" saying where it was calculated.`)
    if (item?.format) need(['number', 'currency'].includes(item.format), `${where}: format is number or currency.`)
  }
  ;(spec.scenes || []).forEach((scene, index) => {
    const where = `scene ${index + 1}`
    need(TYPES.has(scene?.type), `${where}: type must be one of ${[...TYPES].join(', ')}.`)
    need(typeof scene?.duration === 'number' && scene.duration >= 1.5 && scene.duration <= 15,
      `${where}: duration must be 1.5 to 15 seconds.`)
    total += scene?.duration || 0
    for (const key of ['title', 'kicker', 'subtitle', 'heading', 'text', 'note']) {
      if (scene?.[key] != null) need(String(scene[key]).length <= LIMITS[key], `${where}: ${key} is over ${LIMITS[key]} characters.`)
    }
    if (scene?.type === 'title') need(Boolean(scene.title), `${where}: a title scene needs a title.`)
    if (scene?.type === 'kpis' || scene?.type === 'bars') {
      need(Boolean(scene.heading), `${where}: needs a heading.`)
      const max = scene.type === 'kpis' ? 4 : 8
      need(Array.isArray(scene.items) && scene.items.length >= 1 && scene.items.length <= max,
        `${where}: needs 1 to ${max} items.`)
      ;(scene.items || []).forEach((item, i) => {
        figure(`${where}, item ${i + 1}`, item)
        need(Boolean(item?.label) && String(item.label).length <= LIMITS.label,
          `${where}, item ${i + 1}: needs a label of at most ${LIMITS.label} characters.`)
      })
    }
    if (scene?.type === 'statement') {
      need(Boolean(scene.text), `${where}: a statement needs text.`)
      if (scene.figure) figure(`${where}, figure`, scene.figure)
    }
  })
  need(total <= MAX_SECONDS, `The clip is ${total} s; keep it to ${MAX_SECONDS} s or less.`)
  return problems
}

function withDefaults(spec) {
  return { width: 1920, height: 1080, fps: 30, language: 'en', theme: 'light', footer: '', brand: '', ...spec }
}

function fontFaces() {
  const dir = path.join(ROOT, 'frontend', 'node_modules', '@fontsource', 'fira-sans', 'files')
  return [400, 500, 600, 700].map((weight) => {
    const file = path.join(dir, `fira-sans-latin-${weight}-normal.woff2`)
    if (!fs.existsSync(file)) return ''
    const data = fs.readFileSync(file).toString('base64')
    return `@font-face{font-family:'Fira Sans';font-weight:${weight};src:url(data:font/woff2;base64,${data}) format('woff2')}`
  }).join('\n')
}

function ffmpeg(args, input) {
  return new Promise((resolve, reject) => {
    const child = spawn('ffmpeg', ['-hide_banner', '-loglevel', 'error', ...args], { stdio: [input ? 'pipe' : 'ignore', 'ignore', 'pipe'] })
    let errors = ''
    child.stderr.on('data', (chunk) => { errors += chunk })
    child.on('error', reject)
    child.on('close', (code) => (code === 0 ? resolve() : reject(new Error(`ffmpeg failed: ${errors.trim()}`))))
    if (input) input(child.stdin)
  })
}

async function render(spec, out) {
  const require = createRequire(path.join(ROOT, 'frontend', 'package.json'))
  const { chromium } = require('@playwright/test')
  const executablePath = process.env.PLAYWRIGHT_EXECUTABLE_PATH ||
    (fs.existsSync('/opt/pw-browsers/chromium') ? '/opt/pw-browsers/chromium' : undefined)
  const browser = await chromium.launch({ executablePath })
  try {
    const page = await browser.newPage({ viewport: { width: spec.width, height: spec.height }, deviceScaleFactor: 1 })
    const html = fs.readFileSync(path.join(HERE, 'composition.html'), 'utf8')
      .replace('/*FONTS*/', fontFaces())
      .replace('/*SPEC*/null', JSON.stringify(spec).replace(/</g, '\\u003c'))
    await page.setContent(html, { waitUntil: 'load' })
    await page.evaluate(() => document.fonts.ready)
    const { duration, scenes } = await page.evaluate(() => ({ duration: window.motion.duration, scenes: window.motion.scenes }))
    const frames = Math.round(duration * spec.fps)
    const shot = async (t) => {
      await page.evaluate((time) => window.motion.seek(time), t)
      return page.screenshot({ type: 'png' })
    }

    // Frames go straight into ffmpeg: nothing large is written to disk.
    let written = 0
    await ffmpeg(['-y', '-f', 'image2pipe', '-framerate', String(spec.fps), '-i', '-',
      '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p',
      '-movflags', '+faststart', out], async (stdin) => {
      for (let i = 0; i < frames; i++) {
        const png = await shot(i / spec.fps)
        if (!stdin.write(png)) await new Promise((resolve) => stdin.once('drain', resolve))
        written += 1
      }
      stdin.end()
    })

    const base = out.replace(/\.mp4$/i, '')
    // The poster: the scene the spec names, or the first scene with figures, fully counted up.
    const posterScene = spec.poster ? scenes[spec.poster - 1] : (scenes.find((s) => s.type !== 'title') || scenes[0])
    fs.writeFileSync(`${base}.poster.png`, await shot(Math.max(posterScene.start, posterScene.end - 0.6)))
    // The review sheet: each scene once it has settled, three to a row.
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'motion-'))
    for (const [i, s] of scenes.entries()) {
      fs.writeFileSync(path.join(tmp, `s${String(i).padStart(2, '0')}.png`), await shot(Math.max(s.start, s.end - 0.6)))
    }
    const columns = Math.min(3, scenes.length)
    const rows = Math.ceil(scenes.length / columns)
    await ffmpeg(['-y', '-pattern_type', 'glob', '-i', path.join(tmp, 's*.png'),
      '-filter_complex', `scale=640:-1,tile=${columns}x${rows}:padding=8:color=0x888888`, '-frames:v', '1', `${base}.sheet.png`])
    fs.rmSync(tmp, { recursive: true, force: true })
    fs.writeFileSync(`${base}.txt`, await page.evaluate(() => window.motion.transcript()) + '\n')
    return { frames: written, duration, scenes: scenes.length }
  } finally {
    await browser.close()
  }
}

async function main(argv) {
  const [specPath, target] = argv
  if (!specPath || !target) {
    console.error('Usage: render.mjs <spec.json> <out.mp4> | render.mjs <spec.json> --check')
    return 2
  }
  let spec
  try {
    spec = withDefaults(JSON.parse(fs.readFileSync(specPath, 'utf8')))
  } catch (error) {
    console.error(`Cannot read ${specPath}: ${error.message}`)
    return 1
  }
  const problems = validate(spec)
  if (problems.length) {
    console.error(`${problems.length} problem(s) in ${specPath}:\n- ${problems.join('\n- ')}`)
    return 1
  }
  const seconds = spec.scenes.reduce((sum, s) => sum + s.duration, 0)
  const figures = spec.scenes.reduce((n, s) => n + (s.items?.length || 0) + (s.figure ? 1 : 0), 0)
  if (target === '--check') {
    console.log(`OK: ${spec.scenes.length} scenes, ${seconds} s, ${figures} figures, each with a source.`)
    return 0
  }
  const started = Date.now()
  const result = await render(spec, path.resolve(target))
  console.log(`Wrote ${target}: ${result.frames} frames, ${result.duration} s at ${spec.fps} fps, ` +
    `${spec.width}x${spec.height}, ${result.scenes} scenes, in ${((Date.now() - started) / 1000).toFixed(1)} s.`)
  return 0
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main(process.argv.slice(2)).then((code) => process.exit(code), (error) => {
    console.error(error.message || error)
    process.exit(1)
  })
}
