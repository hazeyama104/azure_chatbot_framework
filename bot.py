from botbuilder.core import ActivityHandler, TurnContext
from botbuilder.schema import ChannelAccount
import os
from datetime import datetime
from dotenv import load_dotenv

# ローカル実行時の .env 読み込み（App Service 上では環境変数が優先される）
load_dotenv()


class IcebreakerBot(ActivityHandler):
    def __init__(self):
        # 🔴 起動時に AzureOpenAI を生成しない（遅延初期化）
        self.client = None
        self.conversation_history = {}
        self.processed_activities = set()

    def get_client(self):
        """
        Azure OpenAI クライアントの遅延初期化
        """
        if self.client is None:
            from openai import AzureOpenAI

            # 環境変数の読み込み（App Service の「構成」と一致させる）
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
            return

        # 重複チェック（Bot Service からの再送対策）
        activity_id = turn_context.activity.id
        if activity_id and activity_id in self.processed_activities:
            return
        if activity_id:
            self.processed_activities.add(activity_id)

        # 古い履歴を削除
        if len(self.processed_activities) > 1000:
            self.processed_activities.clear()

        user_message = (turn_context.activity.text or "").strip()
        conversation_id = turn_context.activity.conversation.id

        if not user_message:
            return

        # 会話履歴の初期化
        if conversation_id not in self.conversation_history:
            self.conversation_history[conversation_id] = []

        # コマンド処理
        if user_message.lower() in ["help", "ヘルプ", "使い方"]:
            await self.send_help_message(turn_context)
            return

        if user_message.lower() in ["今日の質問", "アイスブレイク"]:
            await self.send_daily_question(turn_context)
            return

        if user_message.lower().startswith("ゲーム"):
            await self.send_game_suggestion(turn_context, user_message)
            return

        # 通常の会話（LLM による応答）
        await self.handle_conversation(turn_context, user_message, conversation_id)

    async def on_members_added_activity(
        self, members_added: list[ChannelAccount], turn_context: TurnContext
    ):
        """新しいメンバーが追加されたときの処理"""
        for member in members_added:
            if member.id != turn_context.activity.recipient.id:
                welcome_text = (
                    "👋 こんにちは！コミュニケーション活性化Botです！\n\n"
                    "チームのアイスブレイクをお手伝いします。\n"
                    "使い方を知りたい場合は「ヘルプ」と入力してください。"
                )
                await turn_context.send_activity(welcome_text)

    async def send_help_message(self, turn_context: TurnContext):
        help_text = (
            "📖 **使い方ガイド**\n\n"
            "• `今日の質問` / `アイスブレイク` : LLMが日替わりの質問を生成します\n"
            "• `ゲーム [人数]` : 人数に合わせたアイスブレイクを提案します（例：ゲーム 5人）\n"
            "• その他、自由に話しかけてみてください！"
        )
        await turn_context.send_activity(help_text)

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

        except Exception as e:
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

        except Exception as e:
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

        except Exception as e:
            await turn_context.send_activity(
                f"申し訳ございません。AIの応答中にエラーが発生しました: {str(e)}"
            )