from aiohttp import web
from aiohttp.web import Request, Response
from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext
from botbuilder.schema import Activity
from bot import IcebreakerBot
import os
from dotenv import load_dotenv

load_dotenv()

# Bot Frameworkの設定
app_id = os.getenv("MICROSOFT_APP_ID")
app_password = os.getenv("MICROSOFT_APP_PASSWORD")

# 開発環境: 認証情報が空の場合は認証なしモード
if not app_id or not app_password:
    print("⚠️  警告: 認証情報が設定されていません。開発モードで起動します。")
    SETTINGS = BotFrameworkAdapterSettings(app_id="", app_password="")
else:
    print(f"✅ 認証モード: App ID = {app_id[:8]}...")
    print(f"✅ Password設定: {'有' if app_password else '無'} (長さ: {len(app_password) if app_password else 0})")
    
    # Azure AD認証のテスト
    try:
        from botframework.connector.auth import MicrosoftAppCredentials
        import requests
        print("🔐 Azure AD認証をテスト中...")
        
        # 手動でトークンリクエストを送信してエラー詳細を確認
        token_url = "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token"
        data = {
            "grant_type": "client_credentials",
            "client_id": app_id,
            "client_secret": app_password,
            "scope": "https://api.botframework.com/.default"
        }
        
        response = requests.post(token_url, data=data)
        print(f"🌐 Token Response Status: {response.status_code}")
        
        if response.status_code == 200:
            print(f"✅ 認証成功: トークン取得完了")
        else:
            print(f"❌ 認証失敗: {response.text}")
            print("💡 App IDとPasswordの組み合わせを確認してください")
            
    except Exception as e:
        print(f"❌ 認証失敗: {e}")
        import traceback
        traceback.print_exc()
        print("💡 MICROSOFT_APP_PASSWORDを確認してください")
    
    SETTINGS = BotFrameworkAdapterSettings(app_id=app_id, app_password=app_password)

ADAPTER = BotFrameworkAdapter(SETTINGS)

# エラーハンドラー
async def on_error(context: TurnContext, error: Exception):
    print(f"❌ エラーが発生しました: {error}")
    import traceback
    traceback.print_exc()
    
    # エラーメッセージを送信しようとすると無限ループになるので、ログのみ
    # await context.send_activity("申し訳ございません。エラーが発生しました。")

ADAPTER.on_turn_error = on_error

# Botインスタンス
BOT = IcebreakerBot()

# デバッグ用ミドルウェア
@web.middleware
async def debug_middleware(request, handler):
    print(f"\n{'='*50}")
    print(f"受信: {request.method} {request.path}")
    print(f"Headers: {dict(request.headers)}")
    try:
        response = await handler(request)
        print(f"応答: {response.status}")
        print(f"{'='*50}\n")
        return response
    except Exception as e:
        print(f"エラー: {e}")
        print(f"{'='*50}\n")
        raise

# メッセージエンドポイント
async def messages(req: Request) -> Response:
    # Content-Typeをチェック（より柔軟に）
    content_type = req.headers.get("Content-Type", "")
    
    # JSONが含まれていればOK
    if "application/json" in content_type or "json" in content_type.lower():
        try:
            body = await req.json()
        except Exception as e:
            print(f"JSON解析エラー: {e}")
            return Response(status=400, text="Invalid JSON")
    else:
        print(f"サポートされていないContent-Type: {content_type}")
        # テキストとして受け取ってみる
        try:
            text_body = await req.text()
            print(f"受信したBody: {text_body}")
            import json
            body = json.loads(text_body)
        except Exception as e:
            print(f"テキスト解析エラー: {e}")
            return Response(status=415, text=f"Unsupported Media Type: {content_type}")

    activity = Activity().deserialize(body)
    auth_header = req.headers.get("Authorization", "")

    try:
        response = await ADAPTER.process_activity(activity, auth_header, BOT.on_turn)
        if response:
            return Response(status=response.status, text=response.body)
        return Response(status=201)
    except Exception as e:
        print(f"エラー: {e}")
        import traceback
        traceback.print_exc()
        return Response(status=500, text=str(e))

# アプリケーション起動
APP = web.Application(middlewares=[debug_middleware])
APP.router.add_post("/api/messages", messages)

if __name__ == "__main__":
    try:
        print("🚀 Bot Framework版 起動中...")
        print("エンドポイント: http://localhost:3978/api/messages")
        print("ngrok使用時: https://your-ngrok-url.ngrok-free.app/api/messages")
        print("")
        print("デバッグモード: 全てのリクエストをログ出力します")
        web.run_app(APP, host="0.0.0.0", port=3978, print=print)
    except Exception as e:
        print(f"起動エラー: {e}")