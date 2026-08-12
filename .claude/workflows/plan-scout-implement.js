export const meta = {
  name: 'plan-scout-implement',
  description: 'Fable plans, Sonnet scouts the codebase, Opus implements — with an Opus-only fast path for trivial edits',
  whenToUse:
    'Any non-trivial change in this repo: features, refactors, bug fixes that touch more than one file or need codebase context. ' +
    'Trivial single-file 2-3 line edits are auto-routed straight to Opus. ' +
    'args: the task as a string, or {task, mode} where mode is "auto" (default) | "quick" | "full".',
  phases: [
    { title: 'Triage', detail: 'classify: trivial single-file edit vs full pipeline', model: 'haiku' },
    { title: 'Plan', detail: 'draft the approach and the open questions', model: 'fable' },
    { title: 'Scout', detail: 'answer each question with file:line facts', model: 'sonnet' },
    { title: 'Implement', detail: 'write the code against plan + scout report', model: 'opus' },
  ],
}

// ---------------------------------------------------------------- input
const input = typeof args === 'string' ? { task: args } : (args || {})
const task = (input.task || '').trim()
const mode = input.mode || 'auto'
const MAX_SCOUTS = 5

if (!task) {
  return { error: 'No task given. Pass args as a task string, or {task, mode}.' }
}

// House rule for this repo: never launch the app/server from inside a workflow.
const HOUSE_RULES = `
Repo notes:
- movielister = Python backend (backend/app, manage.py, main.py) + Vite/TS frontend (frontend/src).
- NEVER start the server, run main.py/manage.py as a service, or launch the app. The user does that themselves.
  One-shot commands (tests, type checks, linters, python -c) are fine.
`.trim()

// ---------------------------------------------------------------- schemas
const TRIAGE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['quick', 'reason'],
  properties: {
    quick: {
      type: 'boolean',
      description:
        'true ONLY if this is a single-file change of roughly 2-3 lines with no design decisions and no hunting for context',
    },
    reason: { type: 'string', description: 'one sentence' },
    file: { type: 'string', description: 'if quick, the file the change lands in' },
  },
}

const PLAN_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['approach', 'steps', 'questions'],
  properties: {
    approach: { type: 'string', description: 'the chosen approach in 2-5 sentences, and why' },
    steps: {
      type: 'array',
      description: 'ordered implementation steps, each independently checkable',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['step'],
        properties: {
          step: { type: 'string' },
          rationale: { type: 'string' },
        },
      },
    },
    questions: {
      type: 'array',
      description:
        'concrete things about THIS codebase the implementer must know before writing code. Each must be answerable by reading files.',
      maxItems: 8,
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['question'],
        properties: {
          question: { type: 'string' },
          whereToLook: { type: 'string', description: 'paths/symbols/patterns to start from' },
          whyItMatters: { type: 'string' },
        },
      },
    },
    risks: { type: 'array', items: { type: 'string' } },
  },
}

const SCOUT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['answer', 'evidence'],
  properties: {
    answer: { type: 'string', description: 'direct answer; say "not found" plainly if it is not there' },
    evidence: {
      type: 'array',
      description: 'file:line citations backing the answer, with the relevant snippet or signature',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['path'],
        properties: {
          path: { type: 'string' },
          lines: { type: 'string', description: 'e.g. "42" or "88-104"' },
          note: { type: 'string' },
        },
      },
    },
    conventions: {
      type: 'array',
      description: 'existing patterns the new code should match (naming, error handling, imports, tests)',
      items: { type: 'string' },
    },
    gotchas: { type: 'array', items: { type: 'string' } },
  },
}

// ---------------------------------------------------------------- 1. triage
let quick = mode === 'quick'

if (mode === 'auto') {
  phase('Triage')
  const t = await agent(
    `${HOUSE_RULES}

Classify this task. Do NOT implement it.

TASK: ${task}

Answer one question: is this a trivial single-file edit of about 2-3 lines — a typo, a constant, a flag, a one-line
guard, an obvious off-by-one — that needs no design decision and no searching for context?

Look at the repo only as much as you need to decide (a grep or one Read is usually plenty).
When in doubt, answer quick=false: the cost of over-planning a small change is much lower than the cost of
under-planning a real one.`,
    { label: 'triage', phase: 'Triage', model: 'haiku', effort: 'low', schema: TRIAGE_SCHEMA },
  )
  quick = !!(t && t.quick)
  log(t ? `triage: ${quick ? 'QUICK' : 'FULL'} — ${t.reason}` : 'triage failed → falling back to FULL pipeline')
}

// ---------------------------------------------------------------- fast path
if (quick) {
  phase('Implement')
  const result = await agent(
    `${HOUSE_RULES}

Make this change now. It has been triaged as a trivial single-file edit.

TASK: ${task}

Read the target file first, make the minimal edit that matches the surrounding style, and stop.
Do not refactor anything nearby, do not add comments explaining the obvious, do not touch other files.
If it turns out to be bigger than a few lines in one file, STOP without editing and reply with
"ESCALATE: <one line on why>" so it can be re-run through the full pipeline.

Return: what you changed, as file:line plus a one-line description per edit.`,
    { label: 'implement:quick', phase: 'Implement', model: 'opus' },
  )

  const escalate = typeof result === 'string' && result.includes('ESCALATE:')
  if (!escalate) return { mode: 'quick', task, implementation: result }
  log('quick path escalated → running the full plan/scout/implement pipeline')
}

// ---------------------------------------------------------------- 2. plan (fable)
phase('Plan')
const plan = await agent(
  `${HOUSE_RULES}

You are planning a change. You do NOT write code and you do NOT do deep codebase research — a scouting team
reads the code for you next, so your job is to decide the approach and to name exactly what they must find out.

TASK: ${task}

Skim the repo enough to be grounded (directory listing, a file or two), then produce:
- approach: what to do and why, including the alternative you rejected if there was a real choice
- steps: an ordered, checkable implementation sequence
- questions: the specific facts about this codebase the implementer needs. Good questions are answerable by
  reading files ("where is the cache written and what shape is the JSON?"), not open-ended
  ("how does the app work?"). Fewer, sharper questions beat many vague ones — ${MAX_SCOUTS} or fewer is ideal.
- risks: what could break`,
  { label: 'plan', phase: 'Plan', model: 'fable', schema: PLAN_SCHEMA },
)

if (!plan) return { error: 'planning failed', task }

// ---------------------------------------------------------------- 3. scout (sonnet)
const questions = (plan.questions || []).slice(0, MAX_SCOUTS)
if ((plan.questions || []).length > MAX_SCOUTS) {
  log(`plan raised ${plan.questions.length} questions; scouting the first ${MAX_SCOUTS} and leaving the rest to the implementer`)
}

phase('Scout')
const scouted = questions.length
  ? (await parallel(
      questions.map((q, i) => () =>
        agent(
          `${HOUSE_RULES}

You are scouting this codebase to answer ONE question for an implementer who has not read the code.
Read-only: do not edit any file.

OVERALL TASK (context only): ${task}
PLANNED APPROACH (context only): ${plan.approach}

YOUR QUESTION: ${q.question}
${q.whereToLook ? `Start looking here: ${q.whereToLook}` : ''}
${q.whyItMatters ? `Why it matters: ${q.whyItMatters}` : ''}

Answer from what the files actually say, with file:line evidence for every claim. If something is not there,
say "not found" instead of guessing. Also report the local conventions the new code should imitate and any
gotcha that would trip up someone editing this area blind.`,
          { label: `scout:${i + 1}`, phase: 'Scout', model: 'sonnet', schema: SCOUT_SCHEMA },
        ).then((r) => (r ? { question: q.question, ...r } : null)),
      ),
    )).filter(Boolean)
  : []

log(`scouted ${scouted.length}/${questions.length} questions`)

// ---------------------------------------------------------------- 4. implement (opus)
const brief = scouted
  .map(
    (s, i) => `### Q${i + 1}: ${s.question}
${s.answer}
Evidence:
${(s.evidence || []).map((e) => `  - ${e.path}${e.lines ? `:${e.lines}` : ''}${e.note ? ` — ${e.note}` : ''}`).join('\n') || '  (none cited)'}
${(s.conventions || []).length ? `Conventions to match:\n${s.conventions.map((c) => `  - ${c}`).join('\n')}` : ''}
${(s.gotchas || []).length ? `Gotchas:\n${s.gotchas.map((g) => `  - ${g}`).join('\n')}` : ''}`,
  )
  .join('\n\n')

phase('Implement')
const implementation = await agent(
  `${HOUSE_RULES}

Implement this change. A planner set the direction and scouts have already read the relevant code for you.

TASK: ${task}

## Approach
${plan.approach}

## Steps
${(plan.steps || []).map((s, i) => `${i + 1}. ${s.step}${s.rationale ? ` — ${s.rationale}` : ''}`).join('\n')}

${(plan.risks || []).length ? `## Risks flagged by the planner\n${plan.risks.map((r) => `- ${r}`).join('\n')}\n` : ''}
## Scout report
${brief || '(no scouting was needed)'}

The plan and the report are inputs, not orders: verify anything load-bearing by reading the file yourself before
you rely on it, and if the code contradicts the brief, trust the code and say so in your summary.

Write the change end to end, matching the conventions above. Run whatever one-shot check is cheap and relevant
(tests, tsc, python -c import) — but never start the server or launch the app.

Return: a summary of what you changed as file:line entries, what you verified and how, and anything you
deliberately left undone.`,
  { label: 'implement', phase: 'Implement', model: 'opus' },
)

return {
  mode: 'full',
  task,
  plan: { approach: plan.approach, steps: plan.steps, risks: plan.risks },
  scoutReport: scouted,
  implementation,
}
