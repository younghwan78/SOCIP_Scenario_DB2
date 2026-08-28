// Minimal implementation of the Streamlit custom-component iframe protocol.
// Kept dependency-free on purpose: the component ships with zero runtime deps.
// Protocol reference: streamlit-component-lib (componentReady / render /
// setComponentValue / setFrameHeight postMessage messages).

export interface RenderArgs {
  [key: string]: unknown
}

type RenderHandler = (args: RenderArgs) => void

function post(type: string, payload: Record<string, unknown> = {}): void {
  window.parent.postMessage({ isStreamlitMessage: true, type, ...payload }, '*')
}

export function initBridge(onRender: RenderHandler): void {
  window.addEventListener('message', (event: MessageEvent) => {
    const data = event.data
    if (!data || data.type !== 'streamlit:render') return
    onRender((data.args ?? {}) as RenderArgs)
  })
  post('streamlit:componentReady', { apiVersion: 1 })
}

export function setComponentValue(value: unknown): void {
  post('streamlit:setComponentValue', { value, dataType: 'json' })
}

export function setFrameHeight(height: number): void {
  post('streamlit:setFrameHeight', { height: Math.ceil(height) })
}
