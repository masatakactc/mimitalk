import functions_framework
from flask import make_response, jsonify

from google.cloud import firestore
import vertexai
from vertexai import agent_engines
import os
import datetime

# --- 環境変数から設定を読み込む ---
# デプロイ時に設定してください
PROJECT_ID = os.environ.get("GCP_PROJECT_ID")
LOCATION_ID = os.environ.get("GCP_LOCATION_ID")
DIAGNOSIS_AGENT_ID = os.environ.get("DIAGNOSIS_AGENT_ID")  # 診断用エージェントのID

# --- APIクライアントの初期化 ---
vertexai.init(project=PROJECT_ID, location=LOCATION_ID)
db = firestore.Client()

# 診断用エージェントを初期化
diagnosis_agent = agent_engines.get(DIAGNOSIS_AGENT_ID)
diag_session = diagnosis_agent.create_session(user_id="default_user")


@functions_framework.http
def diagnose_conversation(request):
    """
    会話履歴に基づいて認知症の診断を行うHTTP Cloud Function.
    Args:
        request (flask.Request): JSON bodyに {"session_id": "..."} を含むリクエストオブジェクト.
    Returns:
        診断結果を含むJSONレスポンス.
    """
    # --- CORS設定 ---
    headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }
    if request.method == "OPTIONS":
        return "", 204, headers

    # --- リクエストからsession_idを取得 ---
    request_json = request.get_json(silent=True)
    if not request_json or "session_id" not in request_json:
        return make_response(jsonify({"error": "session_id is required"}), 400, headers)
    session_id = request_json["session_id"]

    # 1. Firestoreから会話ログを取得
    logs_ref = (
        db.collection("conversations")
        .document(session_id)
        .collection("logs")
        .order_by("timestamp")
    )
    docs = logs_ref.stream()
    conversation_history = []
    for doc in docs:
        log = doc.to_dict()
        if log.get("user_text"):
            conversation_history.append(f"利用者: {log.get('user_text', '')}")
            conversation_history.append(f"AI: {log.get('agent_text', '')}")

    if not conversation_history:
        return make_response(
            jsonify({"diagnosis": "診断に必要な会話履歴がありませんでした。"}),
            200,
            headers,
        )

    conversation_text = "\n".join(conversation_history)

    # 2. 診断用Vertex AI Agentにプロンプトを送信

    events = diagnosis_agent.stream_query(
        user_id="default_user",
        message=conversation_text,
    )
    result = []
    for event in events:
        if "content" in event and "parts" in event["content"]:
            response = "\n".join(
                [p["text"] for p in event["content"]["parts"] if "text" in p]
            )
            if response:
                result.append(response)
    diagnosis_result_text = "\n".join(result)
    print(diagnosis_result_text)

    # 3. 診断結果をJSONで返す
    response_data = {"diagnosis": diagnosis_result_text}
    return make_response(jsonify(response_data), 200, headers)
