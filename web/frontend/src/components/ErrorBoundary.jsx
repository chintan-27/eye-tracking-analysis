import React from 'react'

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          justifyContent: 'center', gap: 10, padding: 32, minHeight: 200,
        }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#f87171' }}>
            Component error
          </div>
          <div style={{
            fontFamily: 'var(--mono)', fontSize: 11, color: 'rgba(255,255,255,.5)',
            background: 'rgba(248,113,113,.08)', border: '1px solid rgba(248,113,113,.2)',
            borderRadius: 8, padding: '10px 16px', maxWidth: 480, whiteSpace: 'pre-wrap',
          }}>
            {String(this.state.error)}
          </div>
          <button
            className="pill"
            onClick={() => this.setState({ error: null })}
          >
            retry
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
