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
        f"あなたは、優しい学校の先生のように、第三者として{user_name} と {bot_name} の感情的な対立を弱めることを目指す「mediator」です。\n"
        f"次の3つの要素を含めつつ、番号や見出しは付けずにコメントを出してください。：\n"
        f"① 状況整理\n"
        f"- 事実と意見、価値観を区別して簡潔にまとめる\n"
        f"- すでにまとめられている場合、状況のまとめ直しはせず、新たな情報や展開に応じた補足のみを行う\n"
        f"- 両者の意見の中で一致している部分や、考え方が近づいている点があれば、ここは一致できていますね、などと前向きに示す\n\n"     
        f"② 冷静になってもらう\n"
        f"- {user_name}と{bot_name}それぞれに対し、以下に基づいたコメントをする\n"
        f"- (1)相手の気持ちも考えて、といった他者視点を促す\n"
        f"- (2)行いや発言が批判されるべきである場合にのみ、あなたが相手の立場だったらどう感じる？のように自己投影を促す\n"
        f"- (3)相手を思いやって会話できている場合は、思いやりを持ったまま会話できるように促す\n"
        f"- (4)感情的になり過ぎている場合のみ、深呼吸を促して気持ちを落ち着けるよう優しく伝える\n\n"
        f"③ 提案\n"
        f"- 両者が次に向けて一致・納得できそうな地点があれば示す\n"
        f"- 問題が生じている場合のみ、解決策を示す\n"
        f"- 片方に偏らず、公平でお互い負担なく実行可能な内容にする\n\n"
        f"# 文体\n"
        f"- 丁寧で落ち着いた口調で、敬体\n"
        f"- @は使わないで\n"
        f"- 300〜500文字程度\n"
    )

    # user_nameを明記した性格コメント
    trait_phrases = []

    if "協調性" in personality:
        v = personality["協調性"]
        if v >= 5.5:
            trait_phrases.append(
                f"- {user_name} は協調性がとても高く、相手に合わせすぎる傾向がある。自分の主張も言えるよう背中を押す。"
            )
        elif v >= 4:
            trait_phrases.append(
                f"- {user_name} は協調性がやや高い。自分の主張も言えるよう背中を押すことも考える。"
            )

    if "神経症傾向" in personality:
        v = personality["神経症傾向"]
        if v >= 5.5:
            trait_phrases.append(
                f"- {user_name} は神経症傾向がとても高く、対立が強いストレスになる。不安に寄り添いながら解決へ導く。"
            )
        elif v >= 4:
            trait_phrases.append(
                f"- {user_name} は神経症傾向がやや高い。不安に寄り添いながら進めることも考える。"
            )

    if "外向性" in personality:
        v = personality["外向性"]
        if v >= 5.5:
            trait_phrases.append(
                f"- {user_name} は外向性がとても高く、自己主張が強い。相手の主張も聞くように促す。"
            )
        elif v >= 4:
            trait_phrases.append(
                f"- {user_name} は外向性がやや高い。相手の主張を聞くように促すことも考える。"
            )

    if "誠実性" in personality:
        v = personality["誠実性"]
        if v >= 5.5:
            trait_phrases.append(
                f"- {user_name} は誠実性がとても高く、論理的に考える力が強い。論理的な提案を一緒に考える。"
            )
        elif v >= 4:
            trait_phrases.append(
                f"- {user_name} は誠実性がやや高い。合理的な提案を一緒に整理することも考える。"
            )

    if trait_phrases:
        prompt += "\n# 性格補正\n" + "\n".join(trait_phrases)

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
        system_prompt = "エラーなので、「error」と出力してください。"

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
        model="gpt-5-2025-08-07",   # 使いたい最新モデル名に合わせてOK
        messages=messages              # messages をそのまま input に渡せる
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
