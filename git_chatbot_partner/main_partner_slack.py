import os
import sys
import json
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from openai import OpenAI
from dotenv import load_dotenv
import re
from slack_sdk.errors import SlackApiError

# 環境変数ロード
load_dotenv()

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# 表示名
bot_name = "ゆうと"

# 共有フォルダのhistory_utilsを読み込み
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from talkhistory.history_utils import load_history, save_history

PERSONALITY_DIR = os.path.join(os.path.dirname(__file__), "..", "personality")
os.makedirs(PERSONALITY_DIR, exist_ok=True)


# OpenAIクライアント
client = OpenAI(api_key=OPENAI_API_KEY)

# Slackアプリ初期化
app = App(token=SLACK_BOT_TOKEN)

# App 初期化の後で
from talkhistory.history_utils import set_slack_client
set_slack_client(app.client)



def resolve_display_name(user_id: str) -> str:
    try:
        info = app.client.users_info(user=user_id)
        prof = info["user"]["profile"]
        return prof.get("display_name") or prof.get("real_name") or user_id
    except Exception:
        return user_id  # 失敗時はIDのまま

# GPT返答生成
def generate_gpt_reply(user_msg, group_id, user_name):
    history = load_history(group_id)
    messages = []

    # システムプロンプト
    personality_path = os.path.join(PERSONALITY_DIR, f"{user_name}.txt")
    system_prompt = f"あなたは「{bot_name}」です。過去の会話の流れを把握した上で、{user_name}の意見は少し聞きつつも、非を認める、歩み寄るといった行動はあまりせず、しっかり自分の主張をし続けてください。{user_name}との対立も辞さない態度でいてください。タメ口でしゃべってください。文章の長さは150〜300字程度にしてください。"

    messages.append({"role": "system", "content": system_prompt})

    for item in history[-20:]:
        role = "assistant" if item["role"] == bot_name else "user"

        # 名前（user_name or bot名）を取得
        name = item["user"]  # 例: "U09XXXX" や "はる" や "mediator"

        # content に話者名を追加
        content = f"{name}：{item['text']}"

        messages.append({"role": role, "content": content})

    print(messages)

    response = client.chat.completions.create(
        model="gpt-5-2025-08-07",
        messages=messages
    )

    reply_text = response.choices[0].message.content

    # メッセージの文頭に強制メンションを追加
    arbitration_user_id = "U0954JS9FDG"
    if not reply_text.startswith(f"<@{arbitration_user_id}>"):
        reply_text = f"<@{arbitration_user_id}> {reply_text.strip()}"

    return reply_text

# メンションイベント処理
@app.event("app_mention")
def handle_mention(event, say):
    user_msg = event["text"]
    group_id = event["channel"]
    user_id = event["user"]

    save_history(group_id, user_id, "user", user_msg)

    # ★ここを追加：ID→表示名に
    user_name = resolve_display_name(user_id)

    bot_reply = generate_gpt_reply(user_msg, group_id, user_name)
    save_history(group_id, bot_name, bot_name, bot_reply)

    say(bot_reply)


if __name__ == "__main__":
    SocketModeHandler(app, SLACK_APP_TOKEN).start()
