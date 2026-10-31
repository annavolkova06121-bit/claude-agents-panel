import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { AgentRow } from '../types'

const PANE = 'agents-pane'
const TITLE = 'Агенты'
const agents = atom({ plugin: 'agents-pane', key: 'agents' } as const, [], {
  shape: 'agents-1',
})

const ROLES: [RegExp, string][] = [
  [/сценар|script/i, 'Сценарист'],
  [/монтаж|edit/i, 'Монтажёр'],
  [/ассист|вставк|asset/i, 'Ассистент'],
  [/директор|director/i, 'Директор'],
]

function role(row: AgentRow): string {
  for (const [re, name] of ROLES) if (re.test(row.description)) return name
  if (/haiku/i.test(row.model)) return 'Ассистент'
  if (/sonnet/i.test(row.model)) return 'Монтажёр'
  if (/opus/i.test(row.model)) return 'Сценарист'
  return row.type || 'агент'
}

function shortModel(model: string): string {
  const m = /(haiku|sonnet|opus|fable|mythos)/i.exec(model)
  return m?.[1] ? m[1].toLowerCase() : model || '?'
}

function clip(text: string, n: number): string {
  const one = text.replace(/\s+/g, ' ').trim()
  return one.length > n ? one.slice(0, n - 1) + '…' : one
}

function ago(ms: number, now: number): string {
  const s = Math.max(0, Math.round((now - ms) / 1000))
  if (s < 60) return `${s} с`
  const m = Math.floor(s / 60)
  return m < 60 ? `${m} мин` : `${Math.floor(m / 60)} ч ${m % 60} мин`
}

const STATUS: Record<string, string> = {
  pending: '…',
  running: '▶',
  waiting: '⏸',
  idle: '◦',
  completed: '✓',
  failed: '✗',
  killed: '■',
}

function hint(e: Record<string, unknown>): string {
  for (const k of ['description', 'file_path', 'path', 'pattern', 'query', 'command', 'url']) {
    const v = e[k]
    if (typeof v === 'string' && v) return clip(v, 60)
  }
  return ''
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    void $.ui.open({ id: PANE, title: TITLE })
    await $.command.register({ name: 'team', description: 'Открыть панель агентов' }).catch(() => undefined)
    await $.command.register({
      name: 'agent-say',
      description: 'Написать агенту: /agent-say <номер или имя> <текст>',
    }).catch(() => undefined)
    return next(e)
  })

  on('command.run', { command: 'team' }, async $ => {
    await $.ui.open({ id: PANE, title: TITLE }).catch(() => undefined)
    return { text: 'Панель агентов открыта.' }
  })

  on('command.run', { command: 'agent-say' }, async ($, e) => {
    const m = /^\s*(\S+)\s+([\s\S]+)$/.exec(e.args)
    if (!m) return { text: 'Формат: /agent-say <номер или имя> <текст>' }
    const who = m[1] ?? ''
    const text = m[2] ?? ''
    const list = await read($, agents)
    const n = Number(who)
    const row = Number.isInteger(n) && n >= 1 && n <= list.length
      ? list[n - 1]
      : list.find(r => role(r).toLowerCase() === who.toLowerCase() || r.description.toLowerCase().includes(who.toLowerCase()))
    const sent = await $.session.send({ to: row ? { agentId: row.id } : who, text })
    if (sent && typeof sent === 'object' && 'deny' in sent) return { text: `Не отправлено: ${String(sent.deny)}` }
    return { text: `Отправлено → ${row ? `${role(row)} (${row.description})` : who}` }
  })

  on('agent.spawn', async ($, e, next) => {
    const ran = await next(e)
    const id = 'agentId' in ran ? ran.agentId : undefined
    if (!id) return ran
    const row: AgentRow = {
      id,
      description: e.description,
      model: ('model' in ran && ran.model) || e.model || '',
      type: e.subagentType,
      task: clip(e.prompt, 400),
      startedAt: Date.now(),
      tokens: 0,
    }
    await update($, agents, list => [...list.filter(r => r.id !== id), row].slice(-30)).catch(() => undefined)
    return ran
  })

  on('tool.call', async ($, e, next) => {
    if (e.agentId) {
      const id = e.agentId
      const h = hint(e as unknown as Record<string, unknown>)
      const now = h ? `${e.tool}: ${h}` : e.tool
      await update($, agents, list =>
        list.some(r => r.id === id) ? list.map(r => (r.id === id ? { ...r, now, nowAt: Date.now() } : r)) : list,
      ).catch(() => undefined)
    }
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    if (e.agentId) {
      const id = e.agentId
      const u = e.usage
      const t = u ? u.input_tokens + u.output_tokens + u.cache_read_input_tokens + u.cache_creation_input_tokens : 0
      await update($, agents, list =>
        list.map(r => (r.id === id ? { ...r, answer: clip(e.answer, 600), now: undefined, tokens: r.tokens + t } : r)),
      ).catch(() => undefined)
    }
    return next(e)
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const list = await read($, agents)
    const live = await $.agent.list()
    const status = new Map(live.map(a => [a.id, a.status as string]))
    const now = Date.now()
    const width = Math.max(30, (e.props.bodyColumns ?? 60) - 2)
    const viewed = e.props.view?.agentId

    return (
      <Box flexDirection="column">
        <Box flexDirection="row">
          <Text bold>{list.length === 0 ? 'Агентов пока нет.' : `Агентов: ${list.length}`}</Text>
          {viewed !== undefined && <Button onPress={() => void $.ui.view({})}> ← главный чат</Button>}
        </Box>
        {list.length === 0 && <Text dimColor>Они появятся здесь, когда диспетчер их запустит.</Text>}
        {list
          .slice()
          .reverse()
          .map(r => {
            const idx = list.indexOf(r) + 1
            const st = status.get(r.id) ?? 'completed'
            return (
              <Box flexDirection="column" marginTop={1}>
                <Box flexDirection="row">
                  <Button onPress={() => void $.ui.view({ agentId: r.id })}>
                    {`${idx}. ${STATUS[st] ?? st} ${role(r)} · ${shortModel(r.model)}`}
                  </Button>
                  <Text dimColor>{`  ${ago(r.startedAt, now)}${r.tokens ? ` · ${Math.round(r.tokens / 1000)}k ток.` : ''}`}</Text>
                </Box>
                <Text>{clip(r.description, width)}</Text>
                <Text dimColor>{`Задача: ${clip(r.task, width * 2)}`}</Text>
                {r.now && (st === 'running' || st === 'pending') && <Text color="yellow">{`Сейчас: ${clip(r.now, width)}`}</Text>}
                {r.answer && <Text color="green">{`Ответ: ${clip(r.answer, width * 3)}`}</Text>}
              </Box>
            )
          })}
        {list.length > 0 && (
          <Text dimColor>{'Нажми на агента — откроется его переписка, следующее сообщение уйдёт ему. Или /agent-say 1 текст.'}</Text>
        )}
      </Box>
    )
  })
}
