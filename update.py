import requests
import json
from collections import defaultdict

# --- CONFIG ---
USER_ID      = 'agasha123'

# Token that has read/query privileges
QUERY_TOKEN  = '-nVyvaNYAe2tOX8ZpxeJ2Ax8BUZ8DaAS0SVBpOJmc_xg99dBq6I0yGqEpBLluYVMmjRG5TWCoJxVCbzB_fk6cvqzyaCFLOSrn8Xd-zBdXKaVVzRexbWfMxl8yFr_3sRxg-c-sH9G7b8saMvhUKbLfaaIcfyNw8ROj8fyplvSCx0L417WZE907iOUQ1DZRtMk'

# Token that has edit/delete privileges
EDIT_TOKEN   = 'QCMVv-lXk1wIiAutBTNHY_3kXQvegJ523XmxSl8AtQ98s_e7F7h1J08xx0UG0LIkWO8a4KXjBp3HbluJBui0ZY3iouFqXX2CkvCQ0VOMM9iIJ8IGef9Pc9zojjhBKpXamsulOf1DvnKD3oc0-JJUKqSlTrto6pW5ZYRY6e2pyYpTJMCqcn_GSx7S4rX68L0B'

# Exact cookie value from your browser (no extra quotes)
COOKIE_VALUE = 'PKjupvu98fl3WydfLXZYNru3oi4WhW48JV8eW5aS1WHSKsUznbPjRZLmsENQmOfbtJGzuMIQnbo='

BASE_URL     = (
    "https://maps.sinarmasforestry.com/arcgis/rest/services/"
    "PreFo/DroneSprayingVendor/FeatureServer/0"
)

# --- SETUP SESSION WITH COOKIE & HEADERS ---
session = requests.Session()
session.headers.update({
    'Referer':    'https://maps.sinarmasforestry.com/UploadDroneManagements/',
    'Origin':     'https://maps.sinarmasforestry.com',
    'User-Agent': 'Mozilla/5.0',
    'Cookie':     f'AGS_ROLES=\"{COOKIE_VALUE}\"',
})

def fetch_features(where_clause):
    """Generic query: returns list of feature dicts."""
    params = {
        'f': 'json',
        'where': where_clause,
        'outFields': 'OBJECTID,SPKNumber,KeyID,FlightID,CRT_Date',
        'returnGeometry': 'false',
        'token': QUERY_TOKEN,
        'resultRecordCount': 10000
    }
    resp = session.get(f"{BASE_URL}/query", params=params)
    resp.raise_for_status()
    return resp.json().get('features', [])

def delete_objectid(oid):
    """Delete a single OBJECTID."""
    data = {'f':'json', 'deletes': str(oid), 'token': EDIT_TOKEN}
    r = session.post(f"{BASE_URL}/applyEdits", data=data)
    r.raise_for_status()
    return r.json()

def batch_update(updates):
    """Send one applyEdits with a list of updates."""
    payload = {
        'f': 'json',
        'token': EDIT_TOKEN,
        # ArcGIS expects JSON-encoded array under "updates"
        'updates': json.dumps(updates)
    }
    r = session.post(f"{BASE_URL}/applyEdits", data=payload)
    r.raise_for_status()
    return r.json()

def dedupe_and_split(features):
    """
    Given a list of feature dicts (with .attributes),
    return (to_keep, to_delete) based on (FlightID,SPKNumber) groups,
    keeping the one with the latest CRT_Date.
    """
    groups = defaultdict(list)
    for feat in features:
        attr = feat['attributes']
        key = (attr['FlightID'], attr['SPKNumber'])
        groups[key].append(attr)

    keep, delete = [], []
    for attrs in groups.values():
        # sort by CRT_Date desc, keep first
        sorted_by_date = sorted(attrs, key=lambda a: a['CRT_Date'], reverse=True)
        keep.append(sorted_by_date[0])
        for d in sorted_by_date[1:]:
            delete.append(d['OBJECTID'])
    return keep, delete

def main():
    # 1) FETCH all L%-SPK features
    print("Fetching features where SPKNumber LIKE 'L%' …")
    feats = fetch_features(f"(UserID='{USER_ID}') AND (SPKNumber LIKE 'L%')")
    print(f" → {len(feats)} records found")

    # 2) INITIAL de-duplication
    keep_initial, del_initial = dedupe_and_split(feats)
    print(f"Deleting {len(del_initial)} initial duplicates …")
    for oid in del_initial:
        print(" >", delete_objectid(oid))

    # 3) PREPARE updates (swap SPK↔Key on the kept records)
    updates = []
    for attr in keep_initial:
        updates.append({
            'attributes': {
                'OBJECTID':  attr['OBJECTID'],
                'SPKNumber': attr['KeyID'],       # now starts with '5'
                'KeyID':     attr['SPKNumber'],   # now starts with 'L'
                'CRT_Date':  attr['CRT_Date']     # preserve timestamp
            }
        })

    print(f"Applying {len(updates)} updates (swap SPK⇄Key) …")
    print(batch_update(updates))

    # 4) SECONDARY de-duplication on newly‐swapped SPKs
    print("Re-fetching features where SPKNumber LIKE '5%' for final de-duplication …")
    feats2 = fetch_features(f"(UserID='{USER_ID}') AND (SPKNumber LIKE '5%')")
    keep_final, del_final = dedupe_and_split(feats2)
    print(f"Deleting {len(del_final)} post-update duplicates …")
    for oid in del_final:
        print(" >", delete_objectid(oid))

    print("✅ update.py complete.")

if __name__ == '__main__':
    main()
