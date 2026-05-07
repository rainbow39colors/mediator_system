from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn
import openai
import hashlib
import hmac
import base64
import os
import requests
import json
import re
from dotenv import load_dotenv

app = FastAPI()

# 環境変数ロード
load_dotenv()

from openai import OpenAI
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

HISTORY_DIR = "histories"
PERSONALITY_DIR = "personalities"
os.makedirs(HISTORY_DIR, exist_ok=True)
os.makedirs(PERSONALITY_DIR, exist_ok=True)

# 署名検証
def verify_signature(body, signature):
    hash = hmac.new(LINE_CHANNEL_SECRET.encode('utf-8'), body, hashlib.sha256).digest()
    expected_signature = base64.b64encode(hash).decode()
    return hmac.compare_digest(expected_signature, signature)

@app.post("/callback")
async def callback(request: Request):
    body = await request.body()
    signature = request.headers.get('x-line-signature')
    if not verify_signature(body, signature):
        return JSONResponse(status_code=403, content={"message": "Invalid signature"})

    events = (await request.json()).get("events", [])
    for event in events:
        if event["type"] == "message" and event["message"]["type"] == "text":
            user_msg = event["message"]["text"]
            reply_token = event["replyToken"]

            # グループIDの判定
            source = event["source"]
            if source["type"] == "group":
                group_id = source["groupId"]
            elif source["type"] == "room":
                group_id = source["roomId"]
            else:
                group_id = source["userId"]  # 1対1の場合

            user_id = source["userId"]

            # ユーザー発話を履歴に保存（グループ単位で）
            save_history(group_id, user_id, "user", user_msg)

            # ChatGPTで返答生成（user_idごとに性格プロンプト分岐＋会話履歴参照）
            bot_reply = generate_gpt_reply(user_msg, group_id, user_id)

            # bot発話も履歴に保存
            save_history(group_id, "bot", "bot", bot_reply)

            # LINEに返信
            reply_to_line(reply_token, bot_reply)

    return JSONResponse(content={"message": "OK"})

# 会話履歴読み込み
def load_history(group_id):
    history_path = os.path.join(HISTORY_DIR, f"{group_id}.json")
    if os.path.exists(history_path):
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

# 会話履歴保存
def save_history(group_id, user_id, role, text):
    history_path = os.path.join(HISTORY_DIR, f"{group_id}.json")
    if os.path.exists(history_path):
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                content = f.read()
                history = [] if content.strip() == "" else json.loads(content)
        except Exception as e:
            print(f"履歴読み込みエラー: {e}")
            history = []
    else:
        history = []
    # 新規発話を追加
    item = {"role": role, "text": text}
    if role == "user":
        item["user_id"] = user_id
    history.append(item)
    # 保存
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

# 性格データ推定（現在コメントアウト中）
def estimate_personality(group_id, user_id):
    ...

# システムプロンプト作成
def make_personalized_prompt(personality):
    prompt = (
        "あなたの役割は、学校の先生のように、人々の対立を緩和することです。"
        "事実と意見、価値観の区別をしっかりつけて、両者の対立感情を弱めること、そして何より、両者が次に向けて一致できるところを見つけられるようにしてください。"
        "両者が納得できそうな解決策があれば提案してみてください。また、基本的には「相手の気持ちも考えて」と言う問いかけをしつつ、ユーザに反省を促した方がいいと思った際は「あなたが相手の立場だったらどう感じる？」などと自己投影を促してください。"
    )
    if "協調性" in personality and personality["協調性"] > 0.7:
        prompt += "ユーザーは協調性が高いので、相手に合わせすぎてしまう傾向があります。自分の主張もしっかり言えるように背中を押してください。"
    if "神経症傾向" in personality and personality["神経症傾向"] > 0.7:
        prompt += "ユーザーは神経症傾向が高いので、対立がストレスになりやすいです。不安や辛さに寄り添いつつ、少しずつでも解決に向けて歩み寄れるように励ましてください。"
    if "外向性" in personality and personality["外向性"] > 0.7:
        prompt += "ユーザーは外向性が高いので、自分の意見を強く主張しがちです。相手の話もよく聞くようにアドバイスしてください。"
    if "誠実性" in personality and personality["誠実性"] > 0.7:
        prompt += "ユーザーは誠実性が高く、論理的思考が得意です。両者が納得できる論理的な解決策を一緒に考えましょう。"
    prompt += "文章の長さは100文字程度にしてください。"
    return prompt

# GPT応答生成（会話履歴参照を追加）
def generate_gpt_reply(user_input, group_id, user_id):
    # 性格データ読み込み
    pers_path = os.path.join(PERSONALITY_DIR, f"{group_id}_{user_id}.json")
    if os.path.exists(pers_path):
        with open(pers_path, "r", encoding="utf-8") as f:
            personality = json.load(f)
    else:
        personality = {}

    # システムプロンプト作成
    system_prompt = make_personalized_prompt(personality)

    # 会話履歴読み込み
    history = load_history(group_id)

    # メッセージリスト構築
    messages = [{"role": "system", "content": system_prompt}]
    for item in history:
        role = "assistant" if item["role"] == "bot" else "user"
        messages.append({"role": role, "content": item["text"]})
    # 最新ユーザー発話を追加
    messages.append({"role": "user", "content": user_input})
    print(messages)

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print("GPTエラー:", e)
        return "すみません、エラーが発生しました。"

# LINE返信処理
def reply_to_line(token, text):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }
    payload = {
        "replyToken": token,
        "messages": [{"type": "text", "text": text}]
    }
    requests.post("https://api.line.me/v2/bot/message/reply", headers=headers, json=payload)

if __name__ == "__main__":
    uvicorn.run("main_partner:app", host="0.0.0.0", port=8001, reload=True)