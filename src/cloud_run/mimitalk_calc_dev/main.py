import functions_framework
from flask import make_response, jsonify
import json
import re

from google.cloud import firestore
import vertexai
from vertexai import agent_engines
import os

# --- 環境変数から設定を読み込む ---
PROJECT_ID = os.environ.get("GCP_PROJECT_ID")
LOCATION_ID = os.environ.get("GCP_LOCATION_ID")
DIAGNOSIS_AGENT_ID = os.environ.get("DIAGNOSIS_AGENT_ID")  # 診断用エージェントのID

# --- APIクライアントの初期化 ---
vertexai.init(project=PROJECT_ID, location=LOCATION_ID)
diagnosis_agent = agent_engines.get(DIAGNOSIS_AGENT_ID)
db = firestore.Client()


@functions_framework.http
def get_realtime_diagnosis(request):
    """
    会話履歴に基づいてリアルタイムの認知症リスクを分析し、JSONで返す
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

    try:
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
                conversation_history.append(
                    f"カウンセラー: {log.get('agent_text', '')}"
                )

        if not conversation_history:
            return make_response(
                jsonify({"diagnosis": "診断に必要な会話履歴がありませんでした。"}),
                200,
                headers,
            )

        conversation_text = "\n".join(conversation_history)

        # 2. 診断用エージェントにプロンプトを送信
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
        response_diag = "\n".join(result)
        print(response_diag)

        # 3. 応答からJSONを抽出してパース
        match = re.search(r"\{.*\}", response_diag, re.DOTALL)
        if match:
            diag_data = json.loads(match.group())
            diagnosis_result = {
                "risk": int(diag_data.get("risk", 0)),
                "confidence": int(diag_data.get("confidence", 0)),
            }
        else:
            raise ValueError("No JSON object found in the diagnosis agent response")

        return make_response(jsonify(diagnosis_result), 200, headers)

    except Exception as e:
        print(f"Error during diagnosis for session {session_id}: {e}")
        # エラー時もフロントエンドが処理しやすいようにデフォルト値を返す
        return make_response(
            jsonify({"risk": 0, "confidence": 0, "error": str(e)}), 500, headers
        )
