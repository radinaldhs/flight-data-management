import os
import sys
import json
import time
import requests
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
    """3-step token generation logic with proper accounts."""
    cached = load_token_from_cache()
    if cached:
        return cached['token'], cached['cookie']

    # Step 1: Login as agasha123
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
        raise Exception("Failed step 1: agasha123 login")

    # Step 2: Generate scoped token for MapServer
    step2 = session.post(TOKEN_URL, headers=TOKEN_HEADERS, data={
        'request': 'getToken',
        'serverUrl': SERVER_URL,
        'token': step1_token,
        'referer': 'https://maps.sinarmasforestry.com',
        'f': 'json'
    }).json()
    scoped_token = step2.get('token')
    if not scoped_token:
        raise Exception("Failed step 2: scoped token")

    # Step 3: Login as fmiseditor
    step3 = session.post(TOKEN_URL, headers=TOKEN_HEADERS, data={
        'request': 'getToken',
        'username': os.getenv('GIS_USERNAME'),
        'password': os.getenv('GIS_PASSWORD'),
        'expiration': '60',
        'referer': 'https://maps.sinarmasforestry.com',
        'f': 'json'
    }).json()

    final_token = step3.get('token')
    expires = step3.get('expires')
    if not final_token or not expires:
        raise Exception("Failed step 3: final login")

    cookie = session.cookies.get_dict().get('AGS_ROLES')
    if not cookie:
        raise Exception("Failed to get AGS_ROLES cookie")

    save_token_to_cache(final_token, expires, cookie)
    return final_token, cookie


def fetch_objectids_for_spk(session, token, spk):
    params = {
        'f': 'json',
        'where': f"SPKNumber='{spk}'",
        'outFields': 'OBJECTID',
        'returnGeometry': 'false',
        'token': token,
    }
    r = session.get(f"{BASE_URL}/query", params=params)
    r.raise_for_status()
    return [f['attributes']['OBJECTID'] for f in r.json().get('features', [])]


def delete_objectid(session, token, cookie, objectid):
    headers = {
        **TOKEN_HEADERS,
        'Origin': 'https://maps.sinarmasforestry.com',
        'Cookie': f'AGS_ROLES="{cookie}"',
    }
    data = {
        'f': 'json',
        'deletes': str(objectid),
        'token': token,
    }
    r = session.post(f"{BASE_URL}/applyEdits", headers=headers, data=data)
    r.raise_for_status()
    return r.json()


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <SPKNumber>")
        sys.exit(1)

    # Check required env vars
    for var in ['GIS_AUTH_USERNAME', 'GIS_AUTH_PASSWORD', 'GIS_USERNAME', 'GIS_PASSWORD']:
        if not os.getenv(var):
            print(f"❌ Missing environment variable: {var}")
            sys.exit(1)

    session = requests.Session()

    try:
        token, cookie = get_final_token(session)
        spk = sys.argv[1]
        oids = fetch_objectids_for_spk(session, token, spk)

        if not oids:
            print(f"No features found for SPKNumber '{spk}'.")
            return

        print(f"Found {len(oids)} features for SPKNumber {spk}: {oids}")
        for oid in oids:
            print(f"> Deleting OBJECTID={oid} …", end=" ")
            resp = delete_objectid(session, token, cookie, oid)
            print(resp)

        print("\n✅ Done.")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()