import os
import json
import re
from slack_sdk import WebClient

SLACK_CLIENT: WebClient | None = None

def set_slack_client(client: WebClient):
    global SLACK_CLIENT
    SLACK_CLIENT = client


HISTORY_DIR = os.path.join(os.path.dirname(__file__), "histories")
os.makedirs(HISTORY_DIR, exist_ok=True)

# --- ユーザID -> 表示名 キャッシュ ---
USER_NAME_CACHE = {}
USER_MENTION_RE = re.compile(r"<@([A-Z0-9]+)>")

def resolve_display_name(user_or_name: str) -> str:
    if not user_or_name or not user_or_name.startswith("U"):
        return user_or_name
    if user_or_name in USER_NAME_CACHE:
        return USER_NAME_CACHE[user_or_name]
    try:
        if SLACK_CLIENT is None:
            return user_or_name  # クライアント未設定ならそのまま
        info = SLACK_CLIENT.users_info(user=user_or_name)
        prof = info["user"]["profile"]
        name = prof.get("display_name") or prof.get("real_name") or "不明ユーザー"
        USER_NAME_CACHE[user_or_name] = name
        return name
    except Exception:
        return user_or_name


def replace_mentions_with_names(text: str) -> str:
    """
    本文中の <@UXXXX> を @表示名 に差し替える
    """
    def _repl(m):
        uid = m.group(1)
        return "@" + resolve_display_name(uid)  # ← @ を残す
    return USER_MENTION_RE.sub(_repl, text)



def load_history(group_id):
    path = os.path.join(HISTORY_DIR, f"{group_id}.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_history(group_id, user_id, role, text):
    path = os.path.join(HISTORY_DIR, f"{group_id}.json")
    history = load_history(group_id)

    # ここでID→表示名に変換
    name = resolve_display_name(user_id)

    # 本文中の <@UXXXX> も表示名に置換
    clean_text = replace_mentions_with_names(text)

    history.append({"role": role, "user": name, "text": clean_text})

    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

