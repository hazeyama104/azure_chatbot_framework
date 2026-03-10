from botbuilder.core import ActivityHandler, TurnContext
import os
import logging
from datetime import datetime
from dotenv import load_dotenv

# ローカル実行時の .env 読み込み（App Service 上では環境変数が優先される）
load_dotenv()

logger = logging.getLogger(__name__)


class IcebreakerBot(ActivityHandler):
    def __init__(self):
        # 🔴 起動時に AzureOpenAI を生成しない（遅延初期化）
        self.client = None
        self.conversation_history = {}
        self.processed_activities = set()

    BOT_NAME = "アイスブレイク考案Bot"

    def _is_mentioned(self, turn_context: TurnContext) -> bool:
        """
        メンション判定。以下のいずれかに該当する場合 True を返す。
          1. Slack DM（channel_id, conversation_type, is_group など複数条件で判定）
          2. entities にボット自身への mention が含まれている
        """
        activity = turn_context.activity
        channel_id       = getattr(activity, "channel_id", "") or ""
        conversation     = activity.conversation or {}
        conversation_type = getattr(conversation, "conversation_type", "") or ""
        is_group         = getattr(conversation, "is_group", None)

        # デバッグ用：DMかどうかの判定材料をすべてログに出す
        logger.info(
            f"🔍 メンション判定: channel_id={channel_id!r}, "
            f"conversation_type={conversation_type!r}, "
            f"is_group={is_group!r}, "
            f"entities={[e.type for e in (activity.entities or [])]}"
        )

        # Slack DM の判定（Bot Framework 経由だと複数パターンある）
        is_dm = (
            channel_id == "directmessage"           # Bot Framework Slack チャンネルの DM
            or conversation_type == "personal"       # 一般的な DM 表現
            or is_group is False                     # グループでない = DM
        )
        if is_dm:
            logger.info("✅ DM と判定 → 応答する")
            return True

        # bot_id は "B0AB1GQDAR2:T2F243HL5" 形式で来るため
        # Slack のメンション形式 <@B0AB1GQDAR2> に合わせてコロン前だけ使う
        bot_id       = activity.recipient.id or ""
        slack_bot_id = bot_id.split(":")[0]  # "B0AB1GQDAR2"
        # Bot Framework が Slack のメンションを "@表示名" に変換して渡す
        bot_name     = (activity.recipient.name or "").lower()
        text         = (activity.text or "")
        text_lower   = text.lower()
        logger.info(f"  text={text!r}, slack_bot_id={slack_bot_id!r}, bot_name={bot_name!r}")

        # デバッグ用：entitiesの詳細とテキストを出力
        for entity in (activity.entities or []):
            mentioned    = getattr(entity, "mentioned", None)
            mentioned_id = getattr(mentioned, "id", None) if mentioned else None
            logger.info(f"  entity: type={entity.type!r}, mentioned_id={mentioned_id!r}, bot_id={bot_id!r}")

        # 判定① entities の mention にボット自身が含まれる
        for entity in (activity.entities or []):
            if entity.type == "mention":
                mentioned    = getattr(entity, "mentioned", None)
                mentioned_id = getattr(mentioned, "id", None) if mentioned else None
                if mentioned_id and (
                    mentioned_id == bot_id
                    or slack_bot_id in mentioned_id
                    or mentioned_id in bot_id
                ):
                    logger.info("✅ メンションあり（entities）→ 応答する")
                    return True

        # 判定② テキスト本文にメンションが含まれる
        # Bot Framework が Slack メンションを "@表示名" 形式に変換するためそちらでも判定
        if (
            (slack_bot_id and f"<@{slack_bot_id}>" in text)  # <@B0AB1GQDAR2> 形式
            or (bot_name and f"@{bot_name}" in text_lower)    # @icebreak-bot 形式
        ):
            logger.info("✅ メンションあり（テキスト）→ 応答する")
            return True

        logger.info("⏭️ DM でもメンションでもない → スキップ")
        return False

    def _strip_mention(self, text: str, turn_context: TurnContext) -> str:
        """メッセージ本文からボットへのメンション部分を除去する"""
        bot_id       = turn_context.activity.recipient.id or ""
        slack_bot_id = bot_id.split(":")[0]
        bot_name     = (turn_context.activity.recipient.name or "").lower()

        cleaned = text
        # <@B0AB1GQDAR2> 形式
        cleaned = cleaned.replace(f"<@{slack_bot_id}>", "")
        # @icebreak-bot 形式（大文字小文字を無視して除去）
        if bot_name:
            import re
            cleaned = re.sub(rf"@{re.escape(bot_name)}", "", cleaned, flags=re.IGNORECASE)

        return cleaned.strip()

    def get_client(self):
        """
        Azure OpenAI クライアントの遅延初期化
        """
        if self.client is None:
            from openai import AzureOpenAI

            # 環境変数の読み込み
            api_key = os.getenv("AZURE_OPENAI_API_KEY")
            api_version = os.getenv("AZURE_OPENAI_API_VERSION")
            endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")

            if not all([api_key, endpoint]):
                raise ValueError("Azure OpenAI の設定（API Key または Endpoint）が不足しています。")

            self.client = AzureOpenAI(
                api_key=api_key,
                api_version=api_version,
                azure_endpoint=endpoint,
            )
        return self.client

    async def on_message_activity(self, turn_context: TurnContext):
        """メッセージを受信したときの処理"""

        # ボット自身のメッセージは無視
        if turn_context.activity.from_property.id == turn_context.activity.recipient.id:
            logger.info("⚠️ ボット自身のメッセージをスキップ")
            return

        # メンション判定：DM またはメンションがなければ無視
        if not self._is_mentioned(turn_context):
            return

        # 重複チェック
        # Slack の再送はリクエストごとに異なる activity_id が付与されるため
        # 「会話ID + テキスト + Slackタイムスタンプ」をキーにして重複を判定する
        activity = turn_context.activity
        slack_ts = (getattr(activity, "channel_data", None) or {}).get("SlackMessage", {}).get("event", {}).get("ts", "")
        dedup_key = f"{activity.conversation.id}:{activity.text}:{slack_ts}"

        if dedup_key in self.processed_activities:
            logger.info(f"⚠️ 重複メッセージをスキップ: key={dedup_key}")
            return

        self.processed_activities.add(dedup_key)
        logger.info(f"✅ 新規メッセージを処理: key={dedup_key}")

        # 古い履歴を削除
        if len(self.processed_activities) > 1000:
            self.processed_activities.clear()
            logger.info("🔄 処理済みアクティビティIDをクリア")

        user_message = (turn_context.activity.text or "").strip()
        conversation_id = turn_context.activity.conversation.id

        # メンション文字列（<@BOTID>）を除去してコマンド部分だけ取り出す
        user_message = self._strip_mention(user_message, turn_context)

        if not user_message:
            # メンションのみ・本文なし → ヘルプを返す
            logger.info("📖 メンションのみ → ヘルプ表示")
            await self.send_help_message(turn_context)
            return

        logger.info(f"📨 受信メッセージ: '{user_message[:50]}...' (会話ID: {conversation_id})")

        # 会話履歴の初期化
        if conversation_id not in self.conversation_history:
            self.conversation_history[conversation_id] = []

        # コマンド処理
        if user_message.lower() in ["help", "ヘルプ", "使い方"]:
            logger.info("📖 ヘルプコマンド実行")
            await self.send_help_message(turn_context)
            return

        if user_message.lower() in ["今日の質問", "アイスブレイク"]:
            logger.info("🎯 今日の質問コマンド実行")
            await self.send_daily_question(turn_context)
            return

        if user_message.lower().startswith("ゲーム"):
            logger.info("🎮 ゲーム提案コマンド実行")
            await self.send_game_suggestion(turn_context, user_message)
            return

        # 通常の会話（LLM による応答）
        logger.info("💬 通常会話モード")
        await self.handle_conversation(turn_context, user_message, conversation_id)

    async def send_help_message(self, turn_context: TurnContext):
        help_text = (
            "📖 **使い方ガイド**\n\n"
            "• `@アイスブレイク考案Bot 今日の質問` / `@アイスブレイク考案Bot アイスブレイク` : LLMが日替わりの質問を生成します\n"
            "• `@アイスブレイク考案Bot ゲーム [人数]` : 人数に合わせたアイスブレイクを提案します（例：ゲーム 5人）\n"
            "• その他、自由に話しかけてみてください！"
        )
        await turn_context.send_activity(help_text)
        logger.info("✅ ヘルプメッセージ送信完了")

    async def send_daily_question(self, turn_context: TurnContext):
        today = datetime.now().strftime("%Y-%m-%d")

        try:
            client = self.get_client()
            deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")

            response = client.chat.completions.create(
                model=deployment_name,
                messages=[
                    {
                        "role": "system",
                        "content": "あなたは組織内のコミュニケーションを活性化するアシスタントです。",
                    },
                    {
                        "role": "user",
                        "content": f"今日({today})のアイスブレイク質問を1つ教えてください。質問文のみを簡潔に返してください。",
                    },
                ],
                max_tokens=200,
                temperature=0.9,
            )

            question = response.choices[0].message.content.strip()
            await turn_context.send_activity(
                f"🎯 **今日のアイスブレイク質問**\n\n{question}"
            )
            logger.info("✅ 今日の質問送信完了")

        except Exception as e:
            logger.info(f"❌ OpenAI エラー: {e}")
            await turn_context.send_activity(f"OpenAI エラーが発生しました: {str(e)}")

    async def send_game_suggestion(self, turn_context: TurnContext, message: str):
        # 参加人数を抽出（デフォルト5人）
        participants = 5
        try:
            for part in message.split():
                clean_part = part.replace("人", "")
                if clean_part.isdigit():
                    participants = int(clean_part)
                    break
        except Exception:
            participants = 5

        logger.info(f"🎮 ゲーム提案: {participants}人用")

        try:
            client = self.get_client()
            deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")

            response = client.chat.completions.create(
                model=deployment_name,
                messages=[
                    {
                        "role": "system",
                        "content": "あなたは会議でのアイスブレイクゲームの専門家です。",
                    },
                    {
                        "role": "user",
                        "content": f"参加者{participants}人で、5分でできるアイスブレイクゲームを1つ提案してください。",
                    },
                ],
                max_tokens=500,
                temperature=0.8,
            )

            game = response.choices[0].message.content.strip()
            await turn_context.send_activity(
                f"🎮 **{participants}人用ゲーム**\n\n{game}"
            )
            logger.info("✅ ゲーム提案送信完了")

        except Exception as e:
            logger.info(f"❌ OpenAI エラー: {e}")
            await turn_context.send_activity(f"OpenAI エラーが発生しました: {str(e)}")

    async def handle_conversation(
        self, turn_context: TurnContext, user_message: str, conversation_id: str
    ):
        # 履歴に追加
        self.conversation_history[conversation_id].append(
            {"role": "user", "content": user_message}
        )

        # 履歴を直近20件に制限
        if len(self.conversation_history[conversation_id]) > 20:
            self.conversation_history[conversation_id] = self.conversation_history[
                conversation_id
            ][-20:]

        try:
            client = self.get_client()
            deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")

            messages = [
                {
                    "role": "system",
                    "content": "あなたは組織内のコミュニケーションを活性化する、明るく親しみやすいアシスタントです。",
                }
            ] + self.conversation_history[conversation_id]

            response = client.chat.completions.create(
                model=deployment_name,
                messages=messages,
                max_tokens=1000,
                temperature=0.7,
            )

            bot_response = response.choices[0].message.content.strip()

            # 履歴を保存
            self.conversation_history[conversation_id].append(
                {"role": "assistant", "content": bot_response}
            )

            await turn_context.send_activity(bot_response)
            logger.info("✅ 会話応答送信完了")

        except Exception as e:
            logger.info(f"❌ OpenAI エラー: {e}")
            await turn_context.send_activity(
                f"申し訳ございません。AIの応答中にエラーが発生しました: {str(e)}"
            )