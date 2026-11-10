import { Component, type ReactNode } from 'react'
import { notify } from '../lib/status'

type Props = { pageKey: string; pageName: string; children: ReactNode }
type State = { pageKey: string; error: Error | null }

function isChunkLoadError(error: Error): boolean {
  return error.name === 'ChunkLoadError'
    || /failed to fetch dynamically imported module|importing a module script failed|error loading dynamically imported module|loading (?:css )?chunk .+ failed/i.test(error.message)
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { pageKey: this.props.pageKey, error: null }

  static getDerivedStateFromError(error: unknown) {
    return { error: error instanceof Error ? error : new Error(String(error)) }
  }

  static getDerivedStateFromProps(props: Props, state: State) {
    return props.pageKey !== state.pageKey ? { pageKey: props.pageKey, error: null } : null
  }

  private copyError = async () => {
    const error = this.state.error
    if (!error) return
    try {
      await navigator.clipboard.writeText(`${this.props.pageName}\n${error.message}\n${error.stack ?? ''}\nRoute: ${window.location.hash}`)
      notify({ kind: 'ok', text: '오류 내용을 복사했습니다.' })
    } catch {
      notify({ kind: 'error', text: '오류 내용을 복사하지 못했습니다. 클립보드 접근 권한을 확인하세요.' })
    }
  }

  render() {
    const error = this.state.error
    if (!error) return this.props.children
    // React.lazy caches rejected imports; clearing the boundary cannot retry that import.
    const needsReload = isChunkLoadError(error)
    return <section className="page page-error-boundary" role="alert">
      <h2>{this.props.pageName} 화면을 표시하지 못했습니다.</h2>
      <p>{error.message}</p>
      {needsReload && <p>화면 코드를 불러오지 못했습니다. 새로고침하여 다시 불러오세요.</p>}
      <div className="toolbar">
        <button className="btn primary" onClick={needsReload ? () => window.location.reload() : () => this.setState({ error: null })}>{needsReload ? '새로고침' : '다시 시도'}</button>
        <button className="btn" onClick={this.copyError}>오류 복사</button>
      </div>
    </section>
  }
}
