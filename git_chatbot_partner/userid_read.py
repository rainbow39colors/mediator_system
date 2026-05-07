from slack_sdk import WebClient
import os
from dotenv import load_dotenv

load_dotenv()

client = WebClient(token=os.environ["SLACK_BOT_TOKEN"])

response = client.users_list()

for user in response["members"]:
    print(f"{user['name']}: {user['id']}")
