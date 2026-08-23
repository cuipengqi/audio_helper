import { useState } from 'react'
import './App.css'

const MOCK_RESULT = `识别：我在杭州东站，朋友在西湖龙翔桥地铁站，帮我们找个中间的咖啡店。

推荐：
1. 星巴克（武林广场店）— 延安路385号，距中点约 480 米
2. Manner Coffee（延安路店）— 延安路292号，距中点约 520 米
3. % Arabica（杭州嘉里中心店）— 延安路385号嘉里中心，距中点约 610 米`

function App() {
  const [resultText] = useState(MOCK_RESULT)

  const handleRecordClick = () => {
    window.alert('录音功能下一步实现')
  }

  const handlePlayClick = () => {
    window.alert('播放功能下一步实现')
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1 className="app-title">语音约碰面</h1>
        <p className="app-subtitle">说出两人位置和想做的事，帮你找中间的好地点</p>
      </header>

      <main className="app-main">
        <button
          type="button"
          className="record-button"
          onClick={handleRecordClick}
          aria-label="开始录音"
        >
          <span className="record-icon" />
          <span className="record-label">按住说话</span>
        </button>

        <section className="result-panel" aria-label="识别与推荐结果">
          <h2 className="result-panel-title">识别与推荐</h2>
          <div className="result-content">{resultText}</div>
        </section>

        <button
          type="button"
          className="play-button"
          onClick={handlePlayClick}
          aria-label="播放语音回复"
        >
          <span className="play-icon" />
          <span>播放回复</span>
        </button>
      </main>
    </div>
  )
}

export default App
