import functions_framework
from flask import make_response

from google.cloud import speech
from google.cloud import texttospeech
from google.cloud import firestore
from google.api_core.client_options import ClientOptions
import vertexai
from vertexai import agent_engines
import uuid
import datetime
import os

# --- 環境変数から設定を読み込む ---
# デプロイ時に設定してください
PROJECT_ID = os.environ.get("GCP_PROJECT_ID")  # 環境変数から読み込む
LOCATION_ID = os.environ.get(
    "GCP_LOCATION_ID"
)  # 環境変数から読み込む (例: us-west1, global)
AGENT_ID = os.environ.get("VERTEX_AGENT_ID")  # 環境変数から読み込む

# --- APIクライアントの初期化 ---
vertexai.init(project=PROJECT_ID, location=LOCATION_ID)

remote_agent = agent_engines.get(AGENT_ID)
session = remote_agent.create_session(user_id="default_user")

speech_client = speech.SpeechClient()
tts_client = texttospeech.TextToSpeechClient()
db = firestore.Client()


@functions_framework.http
def handle_conversation(request):
    """
    HTTP Cloud Function.
    Args:
        request (flask.Request): The request object.
    Returns:
        The response text, or any set of values that can be turned into a
        Response object using `make_response`.
    """
    # --- CORS設定 ---
    # ローカルからのテストや異なるドメインでホストする場合に必要
    headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Max-Age": "3600",
    }

    # Preflightリクエスト（OPTIONSメソッド）への対応
    if request.method == "OPTIONS":
        return "", 204, headers

    # --- リクエストから音声ファイルとセッションIDを取得 ---
    audio_file = request.files.get("audio_data")
    # セッションIDはフロントエンドで生成し、会話の継続性を担保する
    session_id = request.form.get("session_id", str(uuid.uuid4()))

    if not audio_file:
        return "No audio file uploaded.", 400, headers

    # 1. Speech-to-Text: 音声をテキストに変換
    input_audio_bytes = audio_file.read()
    audio = speech.RecognitionAudio(content=input_audio_bytes)
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.WEBM_OPUS,  # フロントエンドの実装に合わせる
        sample_rate_hertz=48000,
        language_code="ja-JP",
        model="latest_long",  # 用途に応じてモデルを選択
    )

    response_stt = speech_client.recognize(config=config, audio=audio)
    user_text = (
        response_stt.results[0].alternatives[0].transcript
        if response_stt.results
        else ""
    )
    if not user_text:
        # 音声認識が空だった場合は、無言だった旨を伝える音声を返す
        user_text = ""
        agent_text = (
            "すみません、よく聞き取れませんでした。もう一度お話しいただけますか？"
        )
    else:
        # 2. Vertex AI Agent: 応答メッセージを生成

        events = remote_agent.stream_query(
            user_id="default_user",
            session_id=session["id"],
            message=user_text,
        )
        result = []
        for event in events:
            if "content" in event and "parts" in event["content"]:
                response = "\n".join(
                    [p["text"] for p in event["content"]["parts"] if "text" in p]
                )
                if response:
                    result.append(response)
        agent_text = "\n".join(result)

    # 3. Text-to-Speech: 応答メッセージを音声に変換
    synthesis_input = texttospeech.SynthesisInput(text=agent_text)
    voice = texttospeech.VoiceSelectionParams(
        language_code="ja-JP", ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3
    )
    response_tts = tts_client.synthesize_speech(
        input=synthesis_input, voice=voice, audio_config=audio_config
    )

    # 4. Firestore: 対話ログを保存
    log_doc = (
        db.collection("conversations")
        .document(session_id)
        .collection("logs")
        .document()
    )
    log_doc.set(
        {
            "user_text": user_text,
            "agent_text": agent_text,
            "timestamp": datetime.datetime.now(datetime.timezone.utc),
        }
    )

    # --- 応答音声をフロントエンドに返す ---
    response = make_response(response_tts.audio_content)
    response.headers.set("Content-Type", "audio/mpeg")
    for key, value in headers.items():
        response.headers.set(key, value)

    return response
