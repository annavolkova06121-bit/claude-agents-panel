import { expect, test } from 'claude-code/testing'

const PANE = {
  plugin: 'agents-pane',
  component: 'Pane',
  requestId: 'agents-pane',
  props: {
    title: 'Агенты',
    isFocused: false,
    bodyColumns: 60,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 30 },
    view: {},
  },
} as const

test('агент появляется с ролью, моделью, задачей и ответом', async ($, on) => {
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'a1' }))
  on('agent.list', () => ({
    value: [{ id: 'a1', description: 'Монтажёр: монтаж 42', type: 'general-purpose', status: 'running' }],
  }))
  on('tool.call', () => ({ result: {} }))

  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await $.agent.spawn({
    prompt: 'Загрузи скилл sf-edit и выполни его для задания 42',
    description: 'Монтажёр: монтаж 42',
    subagentType: 'general-purpose',
    model: 'sonnet',
  } as unknown as Parameters<typeof $.agent.spawn>[0])
  await $.tool.call({ tool: 'Read', file_path: 'C:/ShortsFactory/jobs/42/handoff.md', agentId: 'a1' })

  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' })
  expect((await ui.find({ type: 'Text', text: /Задача: Загрузи скилл sf-edit/ })) !== undefined).toBe(true)
  expect((await ui.find({ type: 'Text', text: /Сейчас: Read: C:\/ShortsFactory/ })) !== undefined).toBe(true)
  await ui.unmount()
})

test('пустая панель', async ($, on) => {
  on('agent.list', () => ({ value: [] }))
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text' }))?.text).toBe('Агентов пока нет.')
  await ui.unmount()
})
