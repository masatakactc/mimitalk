// TODO: 3つのCloud FunctionのURLをそれぞれ設定してください
const CONVERSATION_URL = "************************************************";
const REALTIME_DIAGNOSIS_URL =
  "************************************************";
const FINAL_REPORT_URL = "************************************************";

// --- DOM要素の取得 ---
// 会話パネル
const recordButton = document.getElementById("recordButton");
const recordButtonText = recordButton.querySelector("span");
const statusDiv = document.getElementById("status");
const avatarDiv = document.getElementById("avatar");
// 最終レポート関連
const reportButton = document.getElementById("reportButton");
const reportWrapper = document.getElementById("reportWrapper");
const reportResult = document.getElementById("reportResult");
// リアルタイム分析パネル
const riskValueEl = document.getElementById("riskValue");
const riskProgressEl = document.getElementById("riskProgress");
const confidenceValueEl = document.getElementById("confidenceValue");
const confidenceProgressEl = document.getElementById("confidenceProgress");

let mediaRecorder;
let audioChunks = [];
let isRecording = false;
let sessionId = null;

// --- イベントリスナーの設定 ---
recordButton.addEventListener("click", () => {
  isRecording ? stopRecording() : startRecording();
});
reportButton.addEventListener("click", generateFinalReport);

// --- 関数定義 ---
function generateSessionId() {
  return crypto.randomUUID();
}

async function startRecording() {
  if (!sessionId) {
    sessionId = generateSessionId();
    console.log(`New Session Started: ${sessionId}`);
    reportButton.disabled = false; // セッション開始でレポートボタンを有効化
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    isRecording = true;
    updateUI("recording");
    mediaRecorder = new MediaRecorder(stream, {
      mimeType: "audio/webm;codecs=opus",
    });
    mediaRecorder.ondataavailable = (event) => audioChunks.push(event.data);
    mediaRecorder.onstop = handleTurnEnd; // 録音停止時の処理を呼び出す
    mediaRecorder.start();
  } catch (err) {
    updateUI("error", "マイクへのアクセスが拒否されました。");
  }
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state !== "inactive") mediaRecorder.stop();
  isRecording = false;
  updateUI("processing");
}

// 録音停止（=1ターン終了）時の処理
function handleTurnEnd() {
  const audioBlob = new Blob(audioChunks, { type: "audio/webm;codecs=opus" });
  audioChunks = [];

  // 会話継続とリアルタイム分析を並行して実行
  handleConversation(audioBlob, sessionId);
  handleRealtimeDiagnosis(sessionId);
}

//【処理A】会話用Functionを呼び出し、音声を再生
async function handleConversation(audioBlob, currentSessionId) {
  const formData = new FormData();
  formData.append("audio_data", audioBlob, "recording.webm");
  formData.append("session_id", currentSessionId);
  try {
    const response = await fetch(CONVERSATION_URL, {
      method: "POST",
      body: formData,
    });
    if (!response.ok) throw new Error(`会話サーバーエラー: ${response.status}`);
    const audioResponseBlob = await response.blob();
    playAudio(audioResponseBlob);
  } catch (err) {
    console.error("会話の取得に失敗:", err);
    updateUI("error", "会話の取得に失敗しました。");
  }
}

//【処理B】リアルタイム診断用Functionを呼び出し、メーターを更新
async function handleRealtimeDiagnosis(currentSessionId) {
  try {
    const response = await fetch(REALTIME_DIAGNOSIS_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: currentSessionId }),
    });
    if (!response.ok) throw new Error(`診断サーバーエラー: ${response.status}`);
    const data = await response.json();
    updateDiagnosisMeters(data);
  } catch (err) {
    console.error("リアルタイム診断の取得に失敗:", err);
  }
}

//【処理C】最終レポート生成用Functionを呼び出し、レポートを表示
async function generateFinalReport() {
  if (!sessionId) {
    alert("まだ会話が開始されていません。");
    return;
  }
  updateUI("reporting");
  reportWrapper.style.display = "block";
  reportResult.textContent = "診断レポートを生成しています...";
  try {
    const response = await fetch(FINAL_REPORT_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    });
    if (!response.ok)
      throw new Error(`レポートサーバーエラー: ${response.status}`);
    const data = await response.json();
    reportResult.textContent = data.diagnosis; // 'diagnosis'はバックエンドのJSONキーに合わせる
    updateUI("ready");
  } catch (err) {
    console.error("最終レポートの生成に失敗:", err);
    reportResult.textContent = "エラー：レポートを生成できませんでした。";
    updateUI("error", "レポート生成に失敗しました。");
  }
}

// --- ヘルパー関数 ---
function playAudio(blob) {
  const audioUrl = URL.createObjectURL(blob);
  const audio = new Audio(audioUrl);
  audio.onplay = () => {
    updateUI("speaking");
  };
  audio.onended = () => {
    updateUI("ready");
    URL.revokeObjectURL(audioUrl);
  };
  audio.play();
}

function updateDiagnosisMeters(diagnosis) {
  riskValueEl.textContent = diagnosis.risk ?? "--";
  riskProgressEl.value = parseInt(diagnosis.risk) || 0;
  confidenceValueEl.textContent = diagnosis.confidence ?? "--";
  confidenceProgressEl.value = parseInt(diagnosis.confidence) || 0;
}

function updateUI(state, message = "") {
  recordButton.disabled = false;
  reportButton.disabled = !sessionId; // セッションIDがなければ無効

  switch (state) {
    case "recording":
      statusDiv.textContent = "録音中...";
      recordButton.classList.add("recording");
      recordButtonText.textContent = "こたえおわる";
      reportButton.disabled = true;
      break;
    case "processing":
      statusDiv.textContent = "音声処理と分析中...";
      recordButton.disabled = true;
      reportButton.disabled = true;
      break;
    case "speaking":
      statusDiv.textContent = "アバターが応答中...";
      recordButton.disabled = true;
      reportButton.disabled = true;
      avatarDiv.classList.add("speaking");
      break;
    case "reporting": // レポート生成中の状態
      statusDiv.textContent = "最終レポートを生成中...";
      recordButton.disabled = true;
      reportButton.disabled = true;
      break;
    case "ready":
      statusDiv.textContent = "準備完了";
      recordButton.classList.remove("recording");
      recordButtonText.textContent = "こたえはじめる";
      avatarDiv.classList.remove("speaking");
      break;
    case "error":
      statusDiv.textContent = message || "エラーが発生しました";
      recordButton.classList.remove("recording");
      recordButtonText.textContent = "再度試す";
      avatarDiv.classList.remove("speaking");
      break;
  }
}
