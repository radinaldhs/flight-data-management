import os
import json
import time
import requests
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://maps.sinarmasforestry.com/arcgis/rest/services/PreFo/DroneSprayingVendor/FeatureServer/0"
SERVER_URL = "https://maps.sinarmasforestry.com/arcgis/rest/services/PreFo/DroneSprayingVendor/MapServer"
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

    # Step 1: Get token from agasha123
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
        raise Exception("❌ Step 1 token failed")

    # Step 2: Scope token to serverUrl
    step2 = session.post(TOKEN_URL, headers=TOKEN_HEADERS, data={
        'request': 'getToken',
        'token': step1_token,
        'serverUrl': SERVER_URL,
        'referer': 'https://maps.sinarmasforestry.com',
        'f': 'json'
    }).json()
    if 'token' not in step2:
        raise Exception("❌ Step 2 server-scoped token failed")

    # Step 3: Final token with fmiseditor
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
        raise Exception("❌ Final token (fmiseditor) failed")

    cookie = session.cookies.get_dict().get('AGS_ROLES')
    if not cookie:
        raise Exception("❌ AGS_ROLES cookie missing")

    save_token_to_cache(token, expires, cookie)
    return token, cookie


def fetch_all_features(session, token, user_id):
    params = {
        'f': 'json',
        'where': f"UserID='{user_id}'",
        'outFields': 'OBJECTID,FlightID,SPKNumber,CRT_Date',
        'returnGeometry': 'false',
        'token': token,
        'resultRecordCount': 10000,
    }
    resp = session.get(f"{BASE_URL}/query", params=params)
    resp.raise_for_status()
    return resp.json().get('features', [])


def delete_objectid(session, token, cookie, oid):
    headers = {
        **TOKEN_HEADERS,
        'Origin': 'https://maps.sinarmasforestry.com',
        'Cookie': f'AGS_ROLES="{cookie}"',
    }
    data = {
        'f': 'json',
        'deletes': str(oid),
        'token': token,
    }
    r = session.post(f"{BASE_URL}/applyEdits", headers=headers, data=data)
    r.raise_for_status()
    return r.json()


def main():
    user_id = os.getenv('GIS_USER_ID')
    if not user_id:
        print("❌ Please set GIS_USER_ID in your .env")
        return

    session = requests.Session()

    try:
        token, cookie = get_final_token(session)
        print("Fetching all features…")
        features = fetch_all_features(session, token, user_id)
        print(f" → Retrieved {len(features)} records")

        groups = defaultdict(list)
        for feat in features:
            attr = feat['attributes']
            groups[attr['FlightID']].append(attr)

        to_delete = []
        for fid, attrs in groups.items():
            if len(attrs) <= 1:
                continue
            sorted_by_date = sorted(attrs, key=lambda a: a['CRT_Date'], reverse=True)
            for d in sorted_by_date[1:]:
                to_delete.append(d['OBJECTID'])

        if not to_delete:
            print("✅ No duplicates found.")
            return

        print(f"Found {len(to_delete)} duplicates to delete:\n{to_delete}\n")

        for oid in to_delete:
            print(f"> Deleting OBJECTID={oid} …", end=" ")
            resp = delete_objectid(session, token, cookie, oid)
            print(resp)

        print("\n✅ Duplicate cleanup complete.")
    except Exception as e:
        print(f"\n❌ Error: {e}")


if __name__ == '__main__':
    main()