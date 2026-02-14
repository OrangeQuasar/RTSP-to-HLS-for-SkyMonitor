const hlsInstances = new Map();

function initializePlayer(video) {
  const src = video.dataset.src;
  if (!src) {
    return;
  }

  if (video.canPlayType("application/vnd.apple.mpegurl")) {
    video.src = src;
    return;
  }

  if (window.Hls) {
    const hls = new Hls({
      lowLatencyMode: true,
      backBufferLength: 30,
      // キャッシュ問題防止：m3u8の再取得を強制
      manifestLoadPolicy: {
        default: {
          maxTimeToFirstByteMs: 5000,
          maxLoadTimeMs: 30000,
          timeoutRetry: {
            maxNumRetry: 2,
            retryDelayMs: 500,
            maxRetryDelayMs: 4000,
          },
          errorRetry: {
            maxNumRetry: 2,
            retryDelayMs: 500,
            maxRetryDelayMs: 4000,
          },
        },
      },
      playlistLoadPolicy: {
        default: {
          maxTimeToFirstByteMs: 5000,
          maxLoadTimeMs: 30000,
          timeoutRetry: {
            maxNumRetry: 2,
            retryDelayMs: 500,
            maxRetryDelayMs: 4000,
          },
          errorRetry: {
            maxNumRetry: 2,
            retryDelayMs: 500,
            maxRetryDelayMs: 4000,
          },
        },
      },
    });
    hls.loadSource(src);
    hls.attachMedia(video);
    hlsInstances.set(video, hls);
  }
}

function reloadCamera(cameraId) {
  const video = document.querySelector(`.player[data-camera-id="${cameraId}"]`);
  if (!video) return;
  
  // 既存のHLS インスタンスを破棄
  const existingHls = hlsInstances.get(video);
  if (existingHls) {
    existingHls.destroy();
    hlsInstances.delete(video);
  }
  
  // ビデオ要素をリセット
  video.src = "";
  video.load();
  
  // 再初期化
  setTimeout(() => {
    initializePlayer(video);
  }, 100);
}

const players = document.querySelectorAll(".player");
players.forEach(initializePlayer);

// 各カメラのボタンにイベントリスナーを設定
const reloadBtns = document.querySelectorAll(".camera-reload-btn");
reloadBtns.forEach((btn) => {
  btn.addEventListener("click", () => {
    const cameraId = btn.dataset.cameraId;
    reloadCamera(cameraId);
  });
});

// === 録画機能 ===
let recordSessionId = null; // セッションID保持用

const recordStartBtn = document.getElementById("recordStartBtn");
const recordStopBtn = document.getElementById("recordStopBtn");

if (recordStartBtn) {
  recordStartBtn.addEventListener("click", startRecording);
}

if (recordStopBtn) {
  recordStopBtn.addEventListener("click", stopRecording);
}

async function startRecording() {
  const btn = recordStartBtn;
  
  // ボタン無効化
  btn.disabled = true;
  const originalText = btn.textContent;
  
  try {
    btn.textContent = "📹 開始中...";
    
    const response = await fetch("/api/record-start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    
    const data = await response.json();
    
    if (data.status === "success") {
      recordSessionId = data.session_id;
      btn.textContent = "✅ 録画開始";
      btn.disabled = false;
      
      // 停止ボタンを表示
      recordStartBtn.style.display = "none";
      recordStopBtn.style.display = "inline-block";
    } else {
      btn.textContent = "❌ エラー: " + (data.message || "不明なエラー");
      setTimeout(() => {
        btn.textContent = originalText;
        btn.disabled = false;
      }, 3000);
    }
  } catch (error) {
    console.error("Recording start error:", error);
    btn.textContent = `❌ エラー: ${error.message}`;
    setTimeout(() => {
      btn.textContent = originalText;
      btn.disabled = false;
    }, 3000);
  }
}

async function stopRecording() {
  const btn = recordStopBtn;
  
  if (!recordSessionId) {
    alert("セッションが見つかりません");
    return;
  }
  
  btn.disabled = true;
  const originalText = btn.textContent;
  
  try {
    btn.textContent = "⏹️ 停止中...";
    
    const response = await fetch(`/api/record-stop/${recordSessionId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    
    const data = await response.json();
    
    if (data.status === "success") {
      btn.textContent = "✅ 録画停止";
      
      // ファイルを自動ダウンロード
      if (data.files && typeof data.files === "object") {
        for (const [camId, filename] of Object.entries(data.files)) {
          downloadFile(filename);
          // ダウンロードが同時に進まないよう少し遅延させる
          await new Promise(resolve => setTimeout(resolve, 500));
        }
      }
      
      // 2秒後にボタンを元に戻す
      setTimeout(() => {
        recordSessionId = null;
        btn.textContent = originalText;
        btn.disabled = false;
        recordStopBtn.style.display = "none";
        recordStartBtn.style.display = "inline-block";
        recordStartBtn.disabled = false;
      }, 2000);
    } else {
      btn.textContent = "❌ エラー: " + (data.message || "不明なエラー");
      setTimeout(() => {
        btn.textContent = originalText;
        btn.disabled = false;
      }, 3000);
    }
  } catch (error) {
    console.error("Recording stop error:", error);
    btn.textContent = `❌ エラー: ${error.message}`;
    setTimeout(() => {
      btn.textContent = originalText;
      btn.disabled = false;
    }, 3000);
  }
}

function downloadFile(filename) {
  const link = document.createElement("a");
  link.href = `/api/download/${encodeURIComponent(filename)}`;
  link.download = filename;
  link.style.display = "none";
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}
