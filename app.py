import os
import asyncio
from flask import Flask, request, jsonify
from dotenv import load_dotenv

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

@app.route("/api/messages", methods=["POST"])
def messages():
    """Bot Frameworkからのメッセージを処理"""
    
    # Content-Type を柔軟にチェック（charset付きにも対応）
    content_type = request.headers.get("Content-Type", "").lower()
    
    if "application/json" not in content_type:
        print(f"⚠️ Unsupported Content-Type: {content_type}")
        print(f"📋 Headers: {dict(request.headers)}")
        return jsonify(
            {"error": "Content-Type must be application/json"}
        ), 415

    # JSON を安全に取得
    try:
        body = request.get_json(force=True)
        print(f"📨 受信メッセージ: type={body.get('type')}, from={body.get('from', {}).get('id', 'unknown')}")
    except Exception as e:
        print(f"❌ JSON解析エラー: {e}")
        return jsonify({"error": "Invalid JSON"}), 400

    # Activity オブジェクトに変換
    try:
        activity = Activity().deserialize(body)
    except Exception as e:
        print(f"❌ Activity変換エラー: {e}")
        return jsonify({"error": "Invalid Activity"}), 400

    auth_header = request.headers.get("Authorization", "")

    # Bot処理を実行
    try:
        coro = adapter.process_activity(
            activity,
            auth_header,
            bot.on_turn
        )

        # gunicorn 対応の安全な実行
        if event_loop.is_running():
            future = asyncio.run_coroutine_threadsafe(coro, event_loop)
            future.result(timeout=30)  # タイムアウト設定
        else:
            event_loop.run_until_complete(coro)
        
        print("✅ メッセージ処理完了")

    except Exception as e:
        print("❌ 処理中エラー:", e)
        import traceback
        traceback.print_exc()
        return jsonify({"error": "Internal Server Error"}), 500

    # Bot Frameworkは空のレスポンスを期待
    return "", 200


# =========================
# ローカル実行用
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print("🚀 Flask Bot Framework 起動中")
    print(f"📡 http://0.0.0.0:{port}/api/messages")
    app.run(host="0.0.0.0", port=port, debug=False)