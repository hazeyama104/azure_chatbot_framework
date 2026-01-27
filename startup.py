#!/usr/bin/env python3
"""
Azure App Service用の起動ファイル
"""
import os
import sys

# 必要なモジュールをインポート
try:
    from aiohttp import web
    from app import APP
    
    if __name__ == "__main__":
        # ポート番号を取得（AzureはPORT環境変数を設定する）
        port = int(os.environ.get("PORT", 8000))
        
        print(f"🚀 Starting Bot Framework on port {port}...")
        print(f"Endpoint: http://0.0.0.0:{port}/api/messages")
        
        # アプリを起動
        web.run_app(APP, host="0.0.0.0", port=port)
        
except Exception as e:
    print(f"❌ Error starting application: {e}", file=sys.stderr)
    import traceback
    traceback.print_exc()
    sys.exit(1)