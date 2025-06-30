#!/usr/bin/env python3
import os
import sys
import json
import time
import zipfile
import tempfile
import argparse
import requests
import xml.etree.ElementTree as ET
from dotenv import load_dotenv

load_dotenv()

# --- ENDPOINTS ---
BASE_URL = "https://maps.sinarmasforestry.com/arcgis/rest/services/PreFo/DroneSprayingVendor/FeatureServer/0"
QUERY_URL = f"{BASE_URL}/query"
EDIT_URL = f"{BASE_URL}/applyEdits"
SERVER_URL = BASE_URL.replace('/FeatureServer/0', '/MapServer')
TOKEN_URL = "https://maps.sinarmasforestry.com/portal/sharing/rest/generateToken"
TOKEN_CACHE_FILE = ".token_cache.json"

TOKEN_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "Referer": "https://maps.sinarmasforestry.com/UploadDroneManagements/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
    "sec-ch-ua": '"Google Chrome";v="137", "Chromium";v="137", "Not/A)Brand";v="24"',
    "sec-ch-ua-platform": '"macOS"',
    "sec-ch-ua-mobile": "?0",
}


def load_token_from_cache():
    if not os.path.exists(TOKEN_CACHE_FILE):
        return None
    try:
        with open(TOKEN_CACHE_FILE, "r") as f:
            cached = json.load(f)
            if time.time() * 1000 < cached.get("expires", 0):
                return cached
    except Exception:
        pass
    return None


def save_token_to_cache(token, expires, cookie):
    with open(TOKEN_CACHE_FILE, "w") as f:
        json.dump({"token": token, "expires": expires, "cookie": cookie}, f)


def get_final_token(session):
    cached = load_token_from_cache()
    if cached:
        return cached["token"], cached["cookie"]

    # Step 1: agasha123
    step1 = session.post(TOKEN_URL, headers=TOKEN_HEADERS, data={
        "request": "getToken",
        "username": os.getenv("GIS_AUTH_USERNAME"),
        "password": os.getenv("GIS_AUTH_PASSWORD"),
        "expiration": "60",
        "referer": "https://maps.sinarmasforestry.com",
        "f": "json"
    }).json()
    step1_token = step1.get("token")
    if not step1_token:
        raise Exception("❌ Step 1 token failed")

    # Step 2: scoped token
    step2 = session.post(TOKEN_URL, headers=TOKEN_HEADERS, data={
        "request": "getToken",
        "token": step1_token,
        "serverUrl": SERVER_URL,
        "referer": "https://maps.sinarmasforestry.com",
        "f": "json"
    }).json()
    if "token" not in step2:
        raise Exception("❌ Step 2 scoped token failed")

    # Step 3: fmiseditor
    step3 = session.post(TOKEN_URL, headers=TOKEN_HEADERS, data={
        "request": "getToken",
        "username": os.getenv("GIS_USERNAME"),
        "password": os.getenv("GIS_PASSWORD"),
        "expiration": "60",
        "referer": "https://maps.sinarmasforestry.com",
        "f": "json"
    }).json()

    token = step3.get("token")
    expires = step3.get("expires")
    if not token or not expires:
        raise Exception("❌ Step 3 token failed")

    cookie = session.cookies.get_dict().get("AGS_ROLES")
    if not cookie:
        raise Exception("❌ AGS_ROLES cookie missing")

    save_token_to_cache(token, expires, cookie)
    return token, cookie


def parse_height_only(path):
    tree = ET.parse(path)
    root = tree.getroot()
    ext = next((el for el in root.iter() if el.tag.endswith("ExtendedData")), None)
    if ext is None:
        raise ValueError("no <ExtendedData>")
    for d in ext:
        if d.tag.endswith("Data") and d.attrib.get("name", "").lower() == "height":
            val = next((c.text for c in d if c.tag.endswith("value")), None)
            if val:
                return float(val.strip())
    raise ValueError("missing field: Height")


def extract_flight_id_from_filename(fn):
    base = os.path.splitext(fn)[0]
    parts = base.split("_")
    if parts:
        return parts[-1]
    raise ValueError("cannot parse FlightID from filename")


def query_null_heights(session, token, spk, flight_id):
    params = {
        "f": "json",
        "where": f"SPKNumber='{spk}' AND FlightID='{flight_id}' AND Height IS NULL",
        "outFields": "OBJECTID,SPKNumber,KeyID,CRT_Date,Height",
        "returnGeometry": "false",
        "token": token
    }
    r = session.get(QUERY_URL, params=params)
    r.raise_for_status()
    return r.json().get("features", [])


def update_height(session, token, cookie, attrs, new_height):
    updates = [{
        "attributes": {
            "OBJECTID": attrs["OBJECTID"],
            "SPKNumber": attrs["SPKNumber"],
            "KeyID": attrs["KeyID"],
            "CRT_Date": attrs["CRT_Date"],
            "Height": new_height
        }
    }]
    payload = {
        "f": "json",
        "token": token,
        "updates": json.dumps(updates)
    }
    headers = {
        **TOKEN_HEADERS,
        "Cookie": f'AGS_ROLES="{cookie}"',
        "Origin": "https://maps.sinarmasforestry.com"
    }
    r = session.post(EDIT_URL, headers=headers, data=payload)
    r.raise_for_status()
    return r.json()


def main():
    parser = argparse.ArgumentParser(
        description="Bulk-update Height from KMLs in ZIP for one SPKNumber"
    )
    parser.add_argument("zipfile", help="ZIP containing KML files")
    parser.add_argument("spk", help="SPKNumber for all these KMLs")
    args = parser.parse_args()

    session = requests.Session()

    try:
        token, cookie = get_final_token(session)

        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(args.zipfile, "r") as z:
                z.extractall(tmp)

            for _, _, files in os.walk(tmp):
                for fn in files:
                    if not fn.lower().endswith(".kml"):
                        continue
                    path = os.path.join(tmp, fn)

                    try:
                        height = parse_height_only(path)
                    except ValueError as e:
                        print(f"– skipping '{fn}': {e}")
                        continue

                    # Attempt to get FlightID
                    try:
                        tree = ET.parse(path)
                        root = tree.getroot()
                        ext = next((el for el in root.iter() if el.tag.endswith("ExtendedData")), None)
                        fid = None
                        if ext is not None:
                            for d in ext:
                                nm = d.attrib.get("name", "").lower()
                                if "flightid" in nm or "flight_controller_id" in nm:
                                    val = next((c.text for c in d if c.tag.endswith("value")), None)
                                    if val:
                                        fid = val.strip()
                                        break
                        if not fid:
                            raise ValueError
                    except Exception:
                        try:
                            fid = extract_flight_id_from_filename(fn)
                        except ValueError:
                            print(f"– skipping '{fn}': cannot determine FlightID")
                            continue

                    print(f"Parsed '{fn}' → FlightID={fid}, Height={height}")

                    feats = query_null_heights(session, token, args.spk, fid)
                    if not feats:
                        print(f" → no null-height features for FlightID={fid}")
                        continue

                    for feat in feats:
                        oid = feat["attributes"]["OBJECTID"]
                        print(f" → updating OBJECTID={oid} to Height={height}")
                        resp = update_height(session, token, cookie, feat["attributes"], height)
                        print("    response:", resp)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()