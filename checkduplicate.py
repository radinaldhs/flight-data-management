import requests
import json
from collections import defaultdict

# --- CONFIG ---
USER_ID      = 'agasha123'

# Token with read/query privileges
QUERY_TOKEN  = ''

# Token with edit/delete privileges
EDIT_TOKEN   = ''

# Copy exactly the value of AGS_ROLES from your browser (without quotes)
COOKIE_VALUE = ''

BASE_URL     = "https://maps.sinarmasforestry.com/arcgis/rest/services/PreFo/DroneSprayingVendor/FeatureServer/0"

# --- SESSION SETUP ---
session = requests.Session()
session.headers.update({
    'Referer':    'https://maps.sinarmasforestry.com/UploadDroneManagements/',
    'Origin':     'https://maps.sinarmasforestry.com',
    'User-Agent': 'Mozilla/5.0',
    'Cookie':     f'AGS_ROLES=\"{COOKIE_VALUE}\"',
})

def fetch_all_features():
    """Fetch all features for this user, including FlightID and CRT_Date."""
    params = {
        'f': 'json',
        'where':          f"UserID='{USER_ID}'",
        'outFields':      'OBJECTID,FlightID,SPKNumber,CRT_Date',
        'returnGeometry': 'false',
        'token':          QUERY_TOKEN,
        'resultRecordCount': 10000
    }
    resp = session.get(f"{BASE_URL}/query", params=params)
    resp.raise_for_status()
    return resp.json().get('features', [])

def delete_objectid(oid):
    """Issue a single delete for OBJECTID via applyEdits."""
    data = {
        'f':       'json',
        'deletes': str(oid),
        'token':   EDIT_TOKEN
    }
    r = session.post(f"{BASE_URL}/applyEdits", data=data)
    r.raise_for_status()
    return r.json()

def main():
    # 1) Fetch everything
    print("Fetching all features…")
    features = fetch_all_features()
    print(f" → Retrieved {len(features)} records")

    # 2) Group by FlightID
    groups = defaultdict(list)
    for feat in features:
        attr = feat['attributes']
        groups[attr['FlightID']].append(attr)

    # 3) Identify duplicates (same FlightID, >1 record)
    to_delete = []
    for fid, attrs in groups.items():
        if len(attrs) <= 1:
            continue
        # Sort by CRT_Date descending, keep first
        sorted_by_date = sorted(attrs, key=lambda a: a['CRT_Date'], reverse=True)
        # Everything but the first goes to delete
        for d in sorted_by_date[1:]:
            to_delete.append(d['OBJECTID'])

    if not to_delete:
        print("No duplicate FlightID records found. Nothing to delete.")
        return

    print(f"Found {len(to_delete)} duplicate records to delete:\n{to_delete}\n")

    # 4) Delete each duplicate
    for oid in to_delete:
        print(f"> Deleting OBJECTID={oid} …", end=" ")
        resp = delete_objectid(oid)
        print(resp)

    print("\n✅ Duplicate cleanup complete.")

if __name__ == '__main__':
    main()
