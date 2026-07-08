import requests
from django.conf import settings

DAILY_API_URL = "https://api.daily.co/v1"

def create_room(session_id):
    response = requests.post(
        f"{DAILY_API_URL}/rooms",
        headers={
            "Authorization": f"Bearer {settings.DAILY_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "name": f"clutch-session-{session_id}",
            "privacy": "private",
            "properties": {
                "max_participants": 2,
                "enable_screenshare": True,
                "exp": None,
            }
        }
    )
    response.raise_for_status()
    return response.json()


def delete_room(room_name):
    response = requests.delete(
        f"{DAILY_API_URL}/rooms/{room_name}",
        headers={
            "Authorization": f"Bearer {settings.DAILY_API_KEY}",
        }
    )
    response.raise_for_status()
    return response.json()


def create_meeting_token(room_name, user_name, is_owner=False):
    response = requests.post(
        f"{DAILY_API_URL}/meeting-tokens",
        headers={
            "Authorization": f"Bearer {settings.DAILY_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "properties": {
                "room_name": room_name,
                "user_name": user_name,
                "is_owner": is_owner,
                "enable_screenshare": True,
            }
        }
    )
    response.raise_for_status()
    return response.json()