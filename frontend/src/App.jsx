import { useCallback, useEffect, useRef, useState } from 'react'
import axios from 'axios'
import './App.css'

const UPLOAD_URL = 'http://localhost:8003/upload'

const MOCK_RESULT = `识别：我在杭州东站，朋友在西湖龙翔桥地铁站，帮我们找个中间的咖啡店。

推荐：
1. 星巴克（武林广场店）— 延安路385号，距中点约 480 米
2. Manner Coffee（延安路店）— 延安路292号，距中点约 520 米
3. % Arabica（杭州嘉里中心店）— 延安路385号嘉里中心，距中点约 610 米`

const PREFERRED_MIME_TYPES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/ogg;codecs=opus',
]

function getSupportedMimeType() {
  if (typeof MediaRecorder === 'undefined') {
    return ''
  }
  return PREFERRED_MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type)) ?? ''
}

function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) {
    return '--:--'
  }
  const totalSeconds = Math.round(seconds)
  const minutes = Math.floor(totalSeconds / 60)
  const secs = totalSeconds % 60
  return `${minutes}:${String(secs).padStart(2, '0')}`
}

function formatFileSize(bytes) {
  if (bytes < 1024) {
    return `${bytes} B`
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`
  }
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

async function measureAudioDuration(objectUrl) {
  return new Promise((resolve) => {
    const audio = new Audio()
    audio.preload = 'metadata'
    audio.onloadedmetadata = () => {
      resolve(Number.isFinite(audio.duration) ? audio.duration : null)
      audio.src = ''
    }
    audio.onerror = () => {
      resolve(null)
      audio.src = ''
    }
    audio.src = objectUrl
  })
}

async function uploadRecording(blob, fileName) {
  const formData = new FormData()
  formData.append('file', blob, fileName)

  const response = await axios.post(UPLOAD_URL, formData)
  return response.data
}

function App() {
  const [resultText] = useState(MOCK_RESULT)
  const [isRecording, setIsRecording] = useState(false)
  const [recordingPreview, setRecordingPreview] = useState(null)
  const [micError, setMicError] = useState(null)
  const [uploadStatus, setUploadStatus] = useState('idle')
  const [uploadedFilename, setUploadedFilename] = useState(null)
  const [uploadError, setUploadError] = useState(null)

  const mediaRecorderRef = useRef(null)
  const streamRef = useRef(null)
  const chunksRef = useRef([])
  const previewUrlRef = useRef(null)
  const mimeTypeRef = useRef('')
  const isStartingRef = useRef(false)

  const revokePreviewUrl = useCallback(() => {
    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current)
      previewUrlRef.current = null
    }
  }, [])

  const stopStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
  }, [])

  const finalizeRecording = useCallback(
    async (blob) => {
      revokePreviewUrl()
      const objectUrl = URL.createObjectURL(blob)
      previewUrlRef.current = objectUrl

      const duration = await measureAudioDuration(objectUrl)
      const extension = blob.type.includes('ogg') ? 'ogg' : 'webm'
      const fileName = `recording-${Date.now()}.${extension}`

      setRecordingPreview({
        url: objectUrl,
        size: blob.size,
        duration,
        mimeType: blob.type,
        fileName,
      })

      setUploadStatus('uploading')
      setUploadError(null)
      setUploadedFilename(null)

      try {
        const data = await uploadRecording(blob, fileName)
        if (data?.success && data.filename) {
          setUploadStatus('success')
          setUploadedFilename(data.filename)
        } else {
          setUploadStatus('error')
          setUploadError('上传失败：后端未返回有效文件名。')
        }
      } catch (error) {
        setUploadStatus('error')
        const message = axios.isAxiosError(error)
          ? error.response?.data?.detail ?? error.message
          : '上传失败，请确认后端已在 8003 端口启动。'
        setUploadError(typeof message === 'string' ? message : '上传失败，请稍后重试。')
      }
    },
    [revokePreviewUrl],
  )

  const startRecording = useCallback(async () => {
    if (isRecording || isStartingRef.current || mediaRecorderRef.current?.state === 'recording') {
      return
    }

    if (typeof MediaRecorder === 'undefined') {
      setMicError('当前浏览器不支持 MediaRecorder，请换用 Chrome 或 Edge。')
      return
    }

    const mimeType = getSupportedMimeType()
    if (!mimeType) {
      setMicError('当前浏览器不支持 webm 录音格式。')
      return
    }

    isStartingRef.current = true
    setMicError(null)

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      chunksRef.current = []
      mimeTypeRef.current = mimeType

      const recorder = new MediaRecorder(stream, { mimeType })
      mediaRecorderRef.current = recorder

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data)
        }
      }

      recorder.onstop = async () => {
        setIsRecording(false)
        stopStream()

        const blob = new Blob(chunksRef.current, { type: mimeTypeRef.current })
        chunksRef.current = []
        mediaRecorderRef.current = null

        if (blob.size === 0) {
          setMicError('未录到有效音频，请再试一次。')
          return
        }

        await finalizeRecording(blob)
      }

      recorder.onerror = () => {
        setIsRecording(false)
        setMicError('录音过程中发生错误，请重试。')
        stopStream()
        mediaRecorderRef.current = null
      }

      recorder.start()
      setIsRecording(true)
    } catch (error) {
      const message =
        error instanceof DOMException && error.name === 'NotAllowedError'
          ? '麦克风权限被拒绝，请在浏览器设置中允许访问麦克风。'
          : '无法启动麦克风，请检查设备与权限。'
      setMicError(message)
      stopStream()
      mediaRecorderRef.current = null
    } finally {
      isStartingRef.current = false
    }
  }, [finalizeRecording, isRecording, stopStream])

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current?.state === 'recording') {
      mediaRecorderRef.current.stop()
    }
  }, [])

  const handleRecordPointerDown = (event) => {
    event.preventDefault()
    event.currentTarget.setPointerCapture(event.pointerId)
    startRecording()
  }

  const handleRecordPointerUp = (event) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    stopRecording()
  }

  const handlePlayClick = () => {
    window.alert('播放回复功能下一步实现')
  }

  useEffect(() => {
    return () => {
      if (mediaRecorderRef.current?.state === 'recording') {
        mediaRecorderRef.current.stop()
      }
      stopStream()
      revokePreviewUrl()
    }
  }, [revokePreviewUrl, stopStream])

  return (
    <div className="app">
      <header className="app-header">
        <h1 className="app-title">语音约碰面</h1>
        <p className="app-subtitle">说出两人位置和想做的事，帮你找中间的好地点</p>
      </header>

      <main className="app-main">
        <button
          type="button"
          className={`record-button${isRecording ? ' record-button--recording' : ''}`}
          onPointerDown={handleRecordPointerDown}
          onPointerUp={handleRecordPointerUp}
          onPointerCancel={handleRecordPointerUp}
          aria-label={isRecording ? '正在录音，松开结束' : '按住说话'}
          aria-pressed={isRecording}
        >
          <span className="record-icon" />
          <span className="record-label">{isRecording ? '录音中…' : '按住说话'}</span>
        </button>

        {micError && (
          <p className="record-error" role="alert">
            {micError}
          </p>
        )}

        {recordingPreview && (
          <section className="recording-preview" aria-label="本次录音预览">
            <h2 className="recording-preview-title">本次录音</h2>
            <dl className="recording-meta">
              <div className="recording-meta-row">
                <dt>时长</dt>
                <dd>{formatDuration(recordingPreview.duration)}</dd>
              </div>
              <div className="recording-meta-row">
                <dt>大小</dt>
                <dd>{formatFileSize(recordingPreview.size)}</dd>
              </div>
              <div className="recording-meta-row">
                <dt>格式</dt>
                <dd>{recordingPreview.mimeType || 'audio/webm'}</dd>
              </div>
            </dl>
            <audio className="recording-player" controls src={recordingPreview.url}>
              您的浏览器不支持音频播放。
            </audio>
          </section>
        )}

        <section className="result-panel" aria-label="识别与推荐结果">
          <h2 className="result-panel-title">识别与推荐</h2>
          {uploadStatus === 'uploading' && (
            <p className="upload-status upload-status--loading">正在上传音频…</p>
          )}
          {uploadStatus === 'success' && uploadedFilename && (
            <p className="upload-status upload-status--success">
              上传成功，服务器文件名：{uploadedFilename}
            </p>
          )}
          {uploadStatus === 'error' && uploadError && (
            <p className="upload-status upload-status--error" role="alert">
              {uploadError}
            </p>
          )}
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
