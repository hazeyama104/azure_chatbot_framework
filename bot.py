from botbuilder.core import ActivityHandler, TurnContext
from botbuilder.schema import ChannelAccount
from openai import AzureOpenAI
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

class IcebreakerBot(ActivityHandler):
    def __init__(self):
        self.client = AzureOpenAI(
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
        )
        self.conversation_history = {}
        self.processed_activities = set()

    async def on_message_activity(self, turn_context: TurnContext):
        """メッセージを受信したときの処理"""
        # ボット自身のメッセージは無視
        if turn_context.activity.from_property.id == turn_context.activity.recipient.id:
            return
        
        # 重複チェック
        activity_id = turn_context.activity.id
        if activity_id and activity_id in self.processed_activities:
            return
        if activity_id:
            self.processed_activities.add(activity_id)
        
        # 古い履歴を削除（メモリ節約）
        if len(self.processed_activities) > 1000:
            self.processed_activities.clear()
        
        user_message = turn_context.activity.text.strip()
        conversation_id = turn_context.activity.conversation.id
        
        # 会話履歴の初期化
        if conversation_id not in self.conversation_history:
            self.conversation_history[conversation_id] = []
        
        # コマンド処理
        if user_message.lower() == "help" or user_message.lower() == "ヘルプ":
            await self.send_help_message(turn_context)
            return
        
        if user_message.lower() == "今日の質問" or user_message.lower() == "アイスブレイク":
            await self.send_daily_question(turn_context)
            return
        
        if user_message.lower().startswith("ゲーム"):
            await self.send_game_suggestion(turn_context, user_message)
            return
        
        # 通常の会話
        await self.handle_conversation(turn_context, user_message, conversation_id)

    async def on_members_added_activity(self, members_added: list[ChannelAccount], turn_context: TurnContext):
        """新しいメンバーが追加されたときの処理"""
        for member in members_added:
            if member.id != turn_context.activity.recipient.id:
                await turn_context.send_activity(
                    "👋 こんにちは！コミュニケーション活性化Botです！\n\n"
                    "使い方を知りたい場合は「ヘルプ」と入力してください。"
                )

    async def send_help_message(self, turn_context: TurnContext):
        """ヘルプメッセージを送信"""
        help_text = (
            "📖 **使い方ガイド**\n\n"
            "• `今日の質問` または `アイスブレイク` - 今日のアイスブレイク質問を表示\n"
            "• `ゲーム 5人` - 指定人数でできる5分間ゲームを提案\n"
            "• その他、何でも話しかけてください！\n\n"
            "例:\n"
            "• 「感謝メッセージを作って」\n"
            "• 「ランチで盛り上がる話題は？」\n"
            "• 「チームイベントのアイデアをください」"
        )
        await turn_context.send_activity(help_text)

    async def send_daily_question(self, turn_context: TurnContext):
        """今日のアイスブレイク質問を送信"""
        today = datetime.now().strftime("%Y-%m-%d")
        
        try:
            response = self.client.chat.completions.create(
                model=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME"),
                messages=[
                    {"role": "system", "content": "あなたは組織内のコミュニケーションを活性化するアシスタントです。"},
                    {"role": "user", "content": f"今日({today})のアイスブレイク質問を1つ教えてください。質問文のみを簡潔に返してください。"}
                ],
                max_tokens=200,
                temperature=0.9
            )
            
            question = response.choices[0].message.content.strip()
            message = f"🎯 **今日のアイスブレイク質問**\n\n{question}\n\n📅 {datetime.now().strftime('%Y年%m月%d日')}"
            await turn_context.send_activity(message)
            
        except Exception as e:
            await turn_context.send_activity(f"エラーが発生しました: {str(e)}")

    async def send_game_suggestion(self, turn_context: TurnContext, message: str):
        """5分間ゲームの提案を送信"""
        # 人数を抽出
        try:
            parts = message.split()
            participants = 5  # デフォルト
            for part in parts:
                if part.replace("人", "").isdigit():
                    participants = int(part.replace("人", ""))
                    break
        except:
            participants = 5
        
        try:
            response = self.client.chat.completions.create(
                model=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME"),
                messages=[
                    {"role": "system", "content": "あなたは会議でのアイスブレイクゲームの専門家です。"},
                    {"role": "user", "content": f"参加者{participants}人で、会議の冒頭に5分でできるアイスブレイクゲームを1つ提案してください。"}
                ],
                max_tokens=500,
                temperature=0.8
            )
            
            game = response.choices[0].message.content.strip()
            await turn_context.send_activity(f"🎮 **{participants}人用ゲーム**\n\n{game}")
            
        except Exception as e:
            await turn_context.send_activity(f"エラーが発生しました: {str(e)}")

    async def handle_conversation(self, turn_context: TurnContext, user_message: str, conversation_id: str):
        """通常の会話処理"""
        # 会話履歴に追加
        self.conversation_history[conversation_id].append({
            "role": "user",
            "content": user_message
        })
        
        # 履歴が長すぎる場合は古いものから削除
        if len(self.conversation_history[conversation_id]) > 20:
            self.conversation_history[conversation_id] = self.conversation_history[conversation_id][-20:]
        
        try:
            # Azure OpenAIで応答生成
            messages = [
                {"role": "system", "content": "あなたは組織内のコミュニケーションを活性化するアシスタントです。フレンドリーで前向きな雰囲気を大切にし、チームメンバー同士の会話を促進するようなサポートをしてください。"}
            ] + self.conversation_history[conversation_id]
            
            response = self.client.chat.completions.create(
                model=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME"),
                messages=messages,
                max_tokens=1000,
                temperature=0.7
            )
            
            bot_response = response.choices[0].message.content.strip()
            
            # 会話履歴に追加
            self.conversation_history[conversation_id].append({
                "role": "assistant",
                "content": bot_response
            })
            
            await turn_context.send_activity(bot_response)
            
        except Exception as e:
            await turn_context.send_activity(f"申し訳ございません。エラーが発生しました: {str(e)}")