export type AgentRow = {
  id: string
  description: string
  model: string
  type: string
  task: string
  startedAt: number
  now?: string
  nowAt?: number
  answer?: string
  tokens: number
}

declare module 'claude-code' {
  interface PluginState {
    'agents-pane': { agents: Shaped<AgentRow[]> }
  }
}
