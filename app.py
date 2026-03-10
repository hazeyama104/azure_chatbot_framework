import os
import sys
import logging
import asyncio
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# gunicorn のロガーに相乗りしてログを出力する
# （--capture-output が効かない環境でも確実にログストリームに流れる）
gunicorn_logger = logging.getLogger("gunicorn.error")
logging.basicConfig(
    stream=sys.stderr,
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
# gunicorn 経由の場合はそのハンドラを使う
if gunicorn_logger.handlers:
    logger.handlers = gunicorn_logger.handlers
    logger.setLevel(gunicorn_logger.level)

from botbuilder.core import (
    BotFrameworkAdapter,
    BotFrameworkAdapterSettings,
    TurnContext,
)
from botbuilder.schema import Activity

from bot import IcebreakerBot

# ローカル用（App Service では環境変数が使われる）
load_dotenv()

# Flask アプリ
app = Flask(__name__)

# =========================
# Bot Framework 設定
# =========================
app_id = os.getenv("MICROSOFT_APP_ID")
app_password = os.getenv("MICROSOFT_APP_PASSWORD")
app_tenant_id = os.getenv("MicrosoftAppTenantId")
app_type = os.getenv("MicrosoftAppType")

if not app_id or not app_password:
    print("⚠️ Bot Framework 認証情報が未設定")
    settings = BotFrameworkAdapterSettings(app_id="", app_password="")
else:
    print(f"✅ Bot Framework 認証モード: {app_id[:8]}...")
    settings = BotFrameworkAdapterSettings(
        app_id=app_id,
        app_password=app_password,
        channel_auth_tenant=app_tenant_id
    )

adapter = BotFrameworkAdapter(settings)

# =========================
# event loop（重要）
# =========================
# gunicorn 環境では asyncio.run() を使わない
event_loop = asyncio.new_event_loop()
asyncio.set_event_loop(event_loop)

# =========================
# エラーハンドラ
# =========================
async def on_error(context: TurnContext, error: Exception):
    print("❌ Bot Error:", error)
    import traceback
    traceback.print_exc()

adapter.on_turn_error = on_error

# =========================
# Bot インスタンス
# =========================
bot = IcebreakerBot()

# =========================
# ルーティング
# =========================

@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "status": "running",
        "service": "Icebreaker Bot",
        "endpoint": "/api/messages"
    })

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy"})

import threading

@app.route("/api/messages", methods=["POST"])
def messages():
    """Bot Frameworkからのメッセージを処理"""
    
    # Content-Type を柔軟にチェック（charset付きにも対応）
    content_type = request.headers.get("Content-Type", "").lower()
    
    if "application/json" not in content_type:
        logger.warning(f"⚠️ Unsupported Content-Type: {content_type}")
        return jsonify({"error": "Content-Type must be application/json"}), 415

    # JSON を安全に取得
    try:
        body = request.get_json(force=True)
        logger.info(f"📨 受信メッセージ: type={body.get('type')}, from={body.get('from', {}).get('id', 'unknown')}")
    except Exception as e:
        logger.error(f"❌ JSON解析エラー: {e}")
        return jsonify({"error": "Invalid JSON"}), 400

    # Activity オブジェクトに変換
    try:
        activity = Activity().deserialize(body)
    except Exception as e:
        logger.error(f"❌ Activity変換エラー: {e}")
        return jsonify({"error": "Invalid Activity"}), 400

    auth_header = request.headers.get("Authorization", "")

    # Slack は 3秒以内にレスポンスがないと再送するため、
    # 処理をバックグラウンドスレッドで実行して即座に 200 を返す
    def process_in_background():
        try:
            coro = adapter.process_activity(activity, auth_header, bot.on_turn)
            if event_loop.is_running():
                future = asyncio.run_coroutine_threadsafe(coro, event_loop)
                future.result(timeout=30)
            else:
                event_loop.run_until_complete(coro)
            logger.info("✅ メッセージ処理完了")
        except Exception as e:
            logger.error(f"❌ 処理中エラー: {e}")
            import traceback
            traceback.print_exc()

    threading.Thread(target=process_in_background, daemon=True).start()

    # Slack に即座に 200 を返す（再送防止）
    return "", 200


# =========================
# ローカル実行用
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print("🚀 Flask Bot Framework 起動中")
    print(f"📡 http://0.0.0.0:{port}/api/messages")
    app.run(host="0.0.0.0", port=port, debug=False)