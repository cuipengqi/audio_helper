import { useCallback, useEffect, useRef, useState } from 'react'
import axios from 'axios'
import './App.css'

const API_BASE = 'http://localhost:8003'
const UPLOAD_URL = `${API_BASE}/upload`
const ASR_URL = `${API_BASE}/asr`
const EXTRACT_URL = `${API_BASE}/extract`
const SEARCH_URL = `${API_BASE}/search`
const FINALIZE_URL = `${API_BASE}/finalize`

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

function getAxiosErrorMessage(error, fallback) {
  if (!axios.isAxiosError(error)) {
    return fallback
  }
  const detail = error.response?.data?.detail
  if (typeof detail === 'string') {
    return detail
  }
  return fallback
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

async function transcribeRecording(blob, fileName) {
  const formData = new FormData()
  formData.append('file', blob, fileName)

  const response = await axios.post(ASR_URL, formData)
  return response.data
}

async function extractMeetupInfo(text) {
  const response = await axios.post(EXTRACT_URL, { text })
  return response.data
}

async function searchMeetupPlaces({ address_a, address_b, category }) {
  const response = await axios.post(SEARCH_URL, {
    address_a,
    address_b,
    category,
  })
  return response.data
}

function base64ToBlob(base64, contentType) {
  const binary = atob(base64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i)
  }
  return new Blob([bytes], { type: contentType || 'audio/wav' })
}

async function finalizeMeetup(payload) {
  const response = await axios.post(FINALIZE_URL, payload)
  return response.data
}

function App() {
  const [isRecording, setIsRecording] = useState(false)
  const [recordingPreview, setRecordingPreview] = useState(null)
  const [micError, setMicError] = useState(null)
  const [uploadStatus, setUploadStatus] = useState('idle')
  const [uploadedFilename, setUploadedFilename] = useState(null)
  const [uploadError, setUploadError] = useState(null)
  const [asrStatus, setAsrStatus] = useState('idle')
  const [recognizedText, setRecognizedText] = useState(null)
  const [asrError, setAsrError] = useState(null)
  const [extractStatus, setExtractStatus] = useState('idle')
  const [extractedInfo, setExtractedInfo] = useState(null)
  const [extractError, setExtractError] = useState(null)
  const [searchStatus, setSearchStatus] = useState('idle')
  const [searchPlaces, setSearchPlaces] = useState(null)
  const [searchMessage, setSearchMessage] = useState(null)
  const [finalizeStatus, setFinalizeStatus] = useState('idle')
  const [replyText, setReplyText] = useState(null)
  const [finalizeError, setFinalizeError] = useState(null)
  const [isReplyPlaying, setIsReplyPlaying] = useState(false)

  const mediaRecorderRef = useRef(null)
  const streamRef = useRef(null)
  const chunksRef = useRef([])
  const previewUrlRef = useRef(null)
  const replyUrlRef = useRef(null)
  const replyAudioRef = useRef(null)
  const mimeTypeRef = useRef('')
  const isStartingRef = useRef(false)

  const revokeReplyUrl = useCallback(() => {
    if (replyAudioRef.current) {
      replyAudioRef.current.pause()
      replyAudioRef.current = null
    }
    if (replyUrlRef.current) {
      URL.revokeObjectURL(replyUrlRef.current)
      replyUrlRef.current = null
    }
    setIsReplyPlaying(false)
  }, [])

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

  const playReplyAudio = useCallback(
    (audioBase64, contentType) => {
      revokeReplyUrl()
      const blob = base64ToBlob(audioBase64, contentType)
      const objectUrl = URL.createObjectURL(blob)
      replyUrlRef.current = objectUrl

      const audio = new Audio(objectUrl)
      replyAudioRef.current = audio
      audio.onended = () => setIsReplyPlaying(false)
      audio.onerror = () => setIsReplyPlaying(false)

      setIsReplyPlaying(true)
      audio.play().catch(() => {
        setIsReplyPlaying(false)
      })
    },
    [revokeReplyUrl],
  )

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
      setAsrStatus('idle')
      setRecognizedText(null)
      setAsrError(null)
      setExtractStatus('idle')
      setExtractedInfo(null)
      setExtractError(null)
      setSearchStatus('idle')
      setSearchPlaces(null)
      setSearchMessage(null)
      setFinalizeStatus('idle')
      setReplyText(null)
      setFinalizeError(null)
      revokeReplyUrl()

      try {
        const data = await uploadRecording(blob, fileName)
        if (!data?.success || !data.filename) {
          setUploadStatus('error')
          setUploadError('上传失败：后端未返回有效文件名。')
          return
        }

        setUploadStatus('success')
        setUploadedFilename(data.filename)

        setAsrStatus('loading')
        try {
          const asrData = await transcribeRecording(blob, fileName)
          if (!asrData?.text) {
            setAsrStatus('error')
            setAsrError('语音识别失败：未返回有效文字。')
            return
          }

          setAsrStatus('success')
          setRecognizedText(asrData.text)

          setExtractStatus('loading')
          try {
            const extractData = await extractMeetupInfo(asrData.text)
            if (
              extractData?.address_a &&
              extractData?.address_b &&
              extractData?.category
            ) {
              setExtractStatus('success')
              setExtractedInfo(extractData)

              setSearchStatus('loading')
              setSearchPlaces(null)
              setSearchMessage(null)
              try {
                const searchData = await searchMeetupPlaces(extractData)
                if (searchData?.places?.length && searchData?.midpoint) {
                  setSearchStatus('success')
                  setSearchPlaces(searchData.places)

                  setFinalizeStatus('loading')
                  setReplyText(null)
                  setFinalizeError(null)
                  try {
                    const finalizeData = await finalizeMeetup({
                      midpoint: searchData.midpoint,
                      places: searchData.places,
                      address_a: extractData.address_a,
                      address_b: extractData.address_b,
                      category: extractData.category,
                    })
                    if (
                      finalizeData?.reply_text &&
                      finalizeData?.audio_base64
                    ) {
                      setFinalizeStatus('success')
                      setReplyText(finalizeData.reply_text)
                      playReplyAudio(
                        finalizeData.audio_base64,
                        finalizeData.audio_content_type,
                      )
                    } else {
                      setFinalizeStatus('error')
                      setFinalizeError('播报生成失败：返回数据不完整。')
                    }
                  } catch (error) {
                    setFinalizeStatus('error')
                    setFinalizeError(
                      getAxiosErrorMessage(error, '播报生成失败，请稍后重试。'),
                    )
                  }
                } else {
                  setSearchStatus('error')
                  setSearchMessage('地点搜索失败：未返回有效地点列表。')
                }
              } catch (error) {
                setSearchStatus('error')
                setSearchMessage(
                  getAxiosErrorMessage(error, '地点搜索失败，请稍后重试。'),
                )
              }
            } else {
              setExtractStatus('error')
              setExtractError('信息提取失败：返回数据不完整。')
            }
          } catch (error) {
            setExtractStatus('error')
            setExtractError(getAxiosErrorMessage(error, '信息提取失败，请稍后重试。'))
          }
        } catch (error) {
          setAsrStatus('error')
          setAsrError(getAxiosErrorMessage(error, '语音识别失败，请稍后重试。'))
        }
      } catch (error) {
        setUploadStatus('error')
        setUploadError(getAxiosErrorMessage(error, '上传失败，请确认后端已在 8003 端口启动。'))
      }
    },
    [playReplyAudio, revokePreviewUrl, revokeReplyUrl],
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
    if (replyAudioRef.current) {
      replyAudioRef.current.currentTime = 0
      setIsReplyPlaying(true)
      replyAudioRef.current.play().catch(() => {
        setIsReplyPlaying(false)
      })
    }
  }

  useEffect(() => {
    return () => {
      if (mediaRecorderRef.current?.state === 'recording') {
        mediaRecorderRef.current.stop()
      }
      stopStream()
      revokePreviewUrl()
      revokeReplyUrl()
    }
  }, [revokePreviewUrl, revokeReplyUrl, stopStream])

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
          {asrStatus === 'loading' && (
            <p className="upload-status upload-status--loading">正在识别语音…</p>
          )}
          {asrStatus === 'error' && asrError && (
            <p className="upload-status upload-status--error" role="alert">
              {asrError}
            </p>
          )}
          {extractStatus === 'loading' && (
            <p className="upload-status upload-status--loading">正在提取地址与意图…</p>
          )}
          {extractStatus === 'error' && extractError && (
            <p className="upload-status upload-status--error" role="alert">
              {extractError}
            </p>
          )}
          {searchStatus === 'loading' && (
            <p className="upload-status upload-status--loading">正在搜索碰面地点…</p>
          )}
          {finalizeStatus === 'loading' && (
            <p className="upload-status upload-status--loading">正在生成语音播报…</p>
          )}
          {finalizeStatus === 'error' && finalizeError && (
            <p className="result-message result-message--error" role="alert">
              {finalizeError}
            </p>
          )}
          <div className="result-content">
            {recognizedText ? (
              <>
                <p className="result-label">识别</p>
                <p className="result-text">{recognizedText}</p>
              </>
            ) : (
              <p className="result-placeholder">录音完成后，识别文字会显示在这里。</p>
            )}
            {extractedInfo && (
              <dl className="extract-meta">
                <div className="extract-meta-row">
                  <dt>我的位置</dt>
                  <dd>{extractedInfo.address_a}</dd>
                </div>
                <div className="extract-meta-row">
                  <dt>朋友位置</dt>
                  <dd>{extractedInfo.address_b}</dd>
                </div>
                <div className="extract-meta-row">
                  <dt>碰面类型</dt>
                  <dd>{extractedInfo.category}</dd>
                </div>
              </dl>
            )}
            {searchStatus === 'error' && searchMessage && (
              <p className="result-message result-message--error" role="alert">
                {searchMessage}
              </p>
            )}
            {searchPlaces && searchPlaces.length > 0 && (
              <div className="places-list">
                <p className="result-label">推荐碰面地点</p>
                <ol className="places-items">
                  {searchPlaces.map((place, index) => (
                    <li key={`${place.name}-${index}`} className="places-item">
                      <span className="places-name">{place.name}</span>
                      <span className="places-address">{place.address}</span>
                    </li>
                  ))}
                </ol>
              </div>
            )}
            {replyText && (
              <>
                <p className="result-label">播报</p>
                <p className="result-text">{replyText}</p>
              </>
            )}
          </div>
        </section>

        <button
          type="button"
          className={`play-button${isReplyPlaying ? ' play-button--playing' : ''}`}
          onClick={handlePlayClick}
          disabled={!replyText || finalizeStatus !== 'success'}
          aria-label="播放语音回复"
        >
          <span className="play-icon" />
          <span>{isReplyPlaying ? '播放中…' : '播放回复'}</span>
        </button>
      </main>
    </div>
  )
}

export default App
