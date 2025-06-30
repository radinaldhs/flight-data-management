import os
import json
import time
import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://maps.sinarmasforestry.com/arcgis/rest/services/PreFo/DroneSprayingVendor/FeatureServer/0"
QUERY_URL = f"{BASE_URL}/query"
SERVER_URL = BASE_URL.replace('/FeatureServer/0', '/MapServer')
TOKEN_URL = "https://maps.sinarmasforestry.com/portal/sharing/rest/generateToken"
TOKEN_CACHE_FILE = ".token_cache.json"

TOKEN_HEADERS = {
    'Content-Type': 'application/x-www-form-urlencoded',
    'Referer': 'https://maps.sinarmasforestry.com/UploadDroneManagements/',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36',
    'sec-ch-ua': '"Google Chrome";v="137", "Chromium";v="137", "Not/A)Brand";v="24"',
    'sec-ch-ua-platform': '"macOS"',
    'sec-ch-ua-mobile': '?0',
}


def load_token_from_cache():
    if not os.path.exists(TOKEN_CACHE_FILE):
        return None
    try:
        with open(TOKEN_CACHE_FILE, 'r') as f:
            cached = json.load(f)
            if time.time() * 1000 < cached.get("expires", 0):
                return cached
    except Exception:
        pass
    return None


def save_token_to_cache(token, expires, cookie):
    with open(TOKEN_CACHE_FILE, 'w') as f:
        json.dump({
            "token": token,
            "expires": expires,
            "cookie": cookie,
        }, f)


def get_final_token(session):
    cached = load_token_from_cache()
    if cached:
        return cached['token'], cached['cookie']

    step1 = session.post(TOKEN_URL, headers=TOKEN_HEADERS, data={
        'request': 'getToken',
        'username': os.getenv('GIS_AUTH_USERNAME'),
        'password': os.getenv('GIS_AUTH_PASSWORD'),
        'expiration': '60',
        'referer': 'https://maps.sinarmasforestry.com',
        'f': 'json'
    }).json()
    step1_token = step1.get('token')
    if not step1_token:
        raise Exception("❌ Step 1 failed: agasha123 login")

    step2 = session.post(TOKEN_URL, headers=TOKEN_HEADERS, data={
        'request': 'getToken',
        'token': step1_token,
        'serverUrl': SERVER_URL,
        'referer': 'https://maps.sinarmasforestry.com',
        'f': 'json'
    }).json()
    if 'token' not in step2:
        raise Exception("❌ Step 2 failed: scoped token")

    step3 = session.post(TOKEN_URL, headers=TOKEN_HEADERS, data={
        'request': 'getToken',
        'username': os.getenv('GIS_USERNAME'),
        'password': os.getenv('GIS_PASSWORD'),
        'expiration': '60',
        'referer': 'https://maps.sinarmasforestry.com',
        'f': 'json'
    }).json()

    token = step3.get('token')
    expires = step3.get('expires')
    if not token or not expires:
        raise Exception("❌ Step 3 failed: fmiseditor login")

    cookie = session.cookies.get_dict().get('AGS_ROLES')
    if not cookie:
        raise Exception("❌ AGS_ROLES cookie not found")

    save_token_to_cache(token, expires, cookie)
    return token, cookie


def fetch_null_height_spks(session, token, user_id):
    params = {
        'f': 'json',
        'where': f"(UserID='{user_id}') AND Height IS NULL",
        'resultRecordCount': 10000,
        'outFields': 'SPKNumber',
        'returnGeometry': 'false',
        'token': token
    }
    r = session.get(QUERY_URL, params=params)
    r.raise_for_status()
    return [feat['attributes']['SPKNumber'] for feat in r.json().get('features', [])]


def main():
    user_id = os.getenv('GIS_USER_ID')
    if not user_id:
        print("❌ Please set GIS_USER_ID in your .env")
        return

    session = requests.Session()
    try:
        token, _ = get_final_token(session)
        spks = fetch_null_height_spks(session, token, user_id)
        unique_spks = sorted(set(spks))

        if not unique_spks:
            print("✅ No SPKNumbers with NULL Height found.")
            return

        print("SPKNumbers with NULL Height:")
        for spk in unique_spks:
            print(spk)
    except Exception as e:
        print(f"\n❌ Error: {e}")


if __name__ == '__main__':
    main()