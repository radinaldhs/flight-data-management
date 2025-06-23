import requests
import sys

# --- CONFIG --- 
USER_ID        = 'agasha123'
QUERY_TOKEN    = ''
DELETE_TOKEN   = ''

# The cookie you saw in your browser / cURL
COOKIE_VALUE   = ''

BASE_URL       = "https://maps.sinarmasforestry.com/arcgis/rest/services/PreFo/DroneSprayingVendor/FeatureServer/0"

def fetch_zero_spk_objectids():
    """Fetch all OBJECTIDs for SPKNumber starting '0'."""
    params = {
        'f': 'json',
        'where':            f"(UserID='{USER_ID}') AND (LOWER(SPKNumber) LIKE '0')",
        'resultRecordCount': 1000,
        'outFields':        'OBJECTID',
        'returnGeometry':   'false',
        'token':            QUERY_TOKEN,
    }
    r = requests.get(f"{BASE_URL}/query", params=params)
    r.raise_for_status()
    return [feat['attributes']['OBJECTID'] for feat in r.json().get('features', [])]

def delete_objectid(objectid):
    """Delete a single OBJECTID using the EDIT token."""
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Cookie':       f'AGS_ROLES="{COOKIE_VALUE}"',
        'Referer':      'https://maps.sinarmasforestry.com/UploadDroneManagements/',
        'Origin':       'https://maps.sinarmasforestry.com',
        'User-Agent':   'Mozilla/5.0',
    }
    data = {
        'f':       'json',
        'deletes': str(objectid),
        'token':   DELETE_TOKEN,
    }
    r = requests.post(f"{BASE_URL}/applyEdits", headers=headers, data=data)
    r.raise_for_status()
    return r.json()

def main():
    oids = fetch_zero_spk_objectids()
    if not oids:
        print("No SPKNumber '0*' features found.")
        return
    
    print(f"Found {len(oids)} OBJECTIDs to delete:\n{oids}\n")
    for oid in oids:
        print(f"> Deleting OBJECTID={oid} …", end=" ")
        resp = delete_objectid(oid)
        print(resp)

    print("\n✅ All done.")

if __name__ == '__main__':
    main()
