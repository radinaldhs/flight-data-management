import os
import sys
import json
import time
import requests
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://maps.sinarmasforestry.com/arcgis/rest/services/PreFo/DroneSprayingVendor/FeatureServer/0"
SERVER_URL = BASE_URL.replace('/FeatureServer/0', '/MapServer')
QUERY_URL = f"{BASE_URL}/query"
APPLY_EDITS_URL = f"{BASE_URL}/applyEdits"
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


def fetch_features(session, token, user_id, where_clause):
    params = {
        'f': 'json',
        'where': f"(UserID='{user_id}') AND {where_clause}",
        'outFields': 'OBJECTID,SPKNumber,KeyID,FlightID,CRT_Date',
        'returnGeometry': 'false',
        'token': token,
        'resultRecordCount': 10000
    }
    r = session.get(QUERY_URL, params=params)
    r.raise_for_status()
    return r.json().get('features', [])


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
    r = session.post(APPLY_EDITS_URL, headers=headers, data=data)
    r.raise_for_status()
    return r.json()


def batch_update(session, token, cookie, updates):
    headers = {
        **TOKEN_HEADERS,
        'Origin': 'https://maps.sinarmasforestry.com',
        'Cookie': f'AGS_ROLES="{cookie}"',
    }
    payload = {
        'f': 'json',
        'token': token,
        'updates': json.dumps(updates)
    }
    r = session.post(APPLY_EDITS_URL, headers=headers, data=payload)
    r.raise_for_status()
    return r.json()


def dedupe_and_split(features):
    groups = defaultdict(list)
    for feat in features:
        attr = feat['attributes']
        key = (attr['FlightID'], attr['SPKNumber'])
        groups[key].append(attr)

    keep, delete = [], []
    for attrs in groups.values():
        sorted_by_date = sorted(attrs, key=lambda a: a['CRT_Date'], reverse=True)
        keep.append(sorted_by_date[0])
        for d in sorted_by_date[1:]:
            delete.append(d['OBJECTID'])
    return keep, delete


def main():
    user_id = os.getenv('GIS_AUTH_USERNAME')
    if not user_id:
        print("❌ Please set GIS_AUTH_USERNAME in your .env")
        return

    session = requests.Session()

    try:
        token, cookie = get_final_token(session)

        print("Fetching features where SPKNumber LIKE 'L%' …")
        feats = fetch_features(session, token, user_id, "(SPKNumber LIKE 'L%')")
        print(f" → {len(feats)} records found")

        keep_initial, del_initial = dedupe_and_split(feats)
        print(f"Deleting {len(del_initial)} initial duplicates …")
        for oid in del_initial:
            print(" >", delete_objectid(session, token, cookie, oid))

        updates = []
        for attr in keep_initial:
            updates.append({
                'attributes': {
                    'OBJECTID': attr['OBJECTID'],
                    'SPKNumber': attr['KeyID'],
                    'KeyID': attr['SPKNumber'],
                    'CRT_Date': attr['CRT_Date'],
                }
            })

        print(f"Applying {len(updates)} updates (swap SPK⇄Key) …")
        print(batch_update(session, token, cookie, updates))

        print("Re-fetching features where SPKNumber LIKE '5%' for final de-duplication …")
        feats2 = fetch_features(session, token, user_id, "(SPKNumber LIKE '5%')")
        keep_final, del_final = dedupe_and_split(feats2)
        print(f"Deleting {len(del_final)} post-update duplicates …")
        for oid in del_final:
            print(" >", delete_objectid(session, token, cookie, oid))

        print("✅ update_features_swap.py complete.")

    except Exception as e:
        print(f"\n❌ Error: {e}")


if __name__ == '__main__':
    main()