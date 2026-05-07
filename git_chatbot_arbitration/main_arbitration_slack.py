import os
import sys
import json
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from openai import OpenAI
from dotenv import load_dotenv
import re

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


def make_personalized_prompt(personality, user_name, bot_name):
    prompt = (
        f"「@は絶対に使わないでください。」あなたは、優しい学校の先生のように、第三者として人々の対立の緩和を目指す「mediator」です。"
        f"事実と意見、価値観の区別をしっかりつけて、両者の対立感情を弱めてください。"
        f"両者が納得できそうな解決策があれば提案してください。"
    )

    # user_nameを明記した性格コメント
    trait_phrases = []

    if "協調性" in personality:
        v = personality["協調性"]
        if v >= 5.5:
            trait_phrases.append(
                f"{user_name} は協調性がとても高く、相手に合わせすぎてしまう傾向があります。"
                f"自分の主張も言えるように背中を押してください。"
            )
        elif v >= 4:
            trait_phrases.append(
                f"{user_name} は協調性がやや高く、相手に合わせすぎてしまう傾向がやや見られます。"
                f"自分の主張も言えるように背中を押すことも考えてください。"
            )

    if "神経症傾向" in personality:
        v = personality["神経症傾向"]
        if v >= 5.5:
            trait_phrases.append(
                f"{user_name} は神経症傾向がとても高く、対立が強いストレスになりやすいです。"
                f"不安に寄り添いつつ、解決へ導いてください。"
            )
        elif v >= 4:
            trait_phrases.append(
                f"{user_name} は神経症傾向がやや高く、対立がストレスにつながることがあります。"
                f"不安に寄り添うことも考えてください。"
            )

    if "外向性" in personality:
        v = personality["外向性"]
        if v >= 5.5:
            trait_phrases.append(
                f"{user_name} は外向性がとても高く、自分の意見を強く主張しがちです。"
                f"相手の話もよく聞くよう促してください。"
            )
        elif v >= 4:
            trait_phrases.append(
                f"{user_name} は外向性がやや高く、自分の意見を強く主張することがあります。"
                f"相手の話もよく聞くよう促すことも検討してください。"
            )

    if "誠実性" in personality:
        v = personality["誠実性"]
        if v >= 5.5:
            trait_phrases.append(
                f"{user_name} は誠実性がとても高く、論理的に考える力がとても高いです。"
                f"論理的な提案を一緒に考えてください。"
            )
        elif v >= 4:
            trait_phrases.append(
                f"{user_name} は誠実性がやや高く、論理的に考える力がやや高いです。"
                f"論理的な提案を一緒に考えることも検討してください。"
            )


    if trait_phrases:
        prompt += "性格傾向に応じた助言として、以下も参考にしてください："
        prompt += " ".join(trait_phrases)

    prompt += "文章の長さは300〜500文字程度にしてください。"
    return prompt


# GPT返答生成
def generate_gpt_reply(user_msg, group_id, user_name):
    history = load_history(group_id)
    messages = []

    # ユーザーの中で一番最後に登場したIDを取得
    target_user_name = None
    for item in reversed(history):
        if item["role"] == "user":
            target_user_name = item["user"]
            break

    # 該当ユーザーの性格ファイルを探す
    personality_path = None
    if target_user_name:
        personality_path = os.path.join(PERSONALITY_DIR, f"{target_user_name}.json")

    if personality_path and os.path.exists(personality_path):
        with open(personality_path, "r", encoding="utf-8") as f:
            personality = json.load(f)
        system_prompt = make_personalized_prompt(personality, target_user_name, bot_name)
    else:
        system_prompt = "あなたは対立を緩和するチャットボット、「mediator」です。事実と意見、価値観の区別をしっかりつけて、両者の対立感情を弱めること、そして何より、両者が次に向けて一致できるところを見つけられるようにしてください。両者が納得できそうな解決策があれば提案してみてください。また、基本的には相手の気持ちも考えてみようと言ったような問いかけをしつつ、ユーザに反省を促した方がいいと思った際は『あなたが相手の立場だったらどう感じる？』などと自己投影を促してください。文章の長さは100文字程度にし、メンションはしないでください。"

    messages.append({"role": "system", "content": system_prompt})

    for item in history[-20:]:
        role = "assistant" if item["role"] == "mediator" else "user"

        # 名前（user_name or bot名）を取得
        name = item["user"]  # 例: "U09XXXX" や "はる" や "mediator"

        # content に話者名を追加
        content = f"{name}：{item['text']}"

        messages.append({"role": role, "content": content})

    print(messages)

    response = client.chat.completions.create(
        model="gpt-5",
        messages=messages
    )
    return response.choices[0].message.content

# メンションイベント処理
@app.event("app_mention")
def handle_mention(event, say):
    user_msg = event["text"]
    group_id = event["channel"]
    user_name = event["user"]

    # save_history(group_id, user_name, "user", user_msg) # 重複するので省く
    bot_reply = generate_gpt_reply(user_msg, group_id, user_name)
    save_history(group_id, "mediator", "mediator", bot_reply)

    say(bot_reply)

if __name__ == "__main__":
    SocketModeHandler(app, SLACK_APP_TOKEN).start()
