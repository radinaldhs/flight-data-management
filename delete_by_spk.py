import sys
import requests

DELETE_TOKEN = ''

COOKIE_VALUE   = ''

BASE_URL = "https://maps.sinarmasforestry.com/arcgis/rest/services/PreFo/DroneSprayingVendor/FeatureServer/0"

def fetch_objectids_for_spk(spk):
    """Fetch all OBJECTIDs for a given SPKNumber."""
    params = {
        'f': 'json',
        'where': f"SPKNumber='{spk}'",
        'outFields': 'OBJECTID',
        'returnGeometry': 'false',
        'token': DELETE_TOKEN,
    }
    r = requests.get(f"{BASE_URL}/query", params=params)
    r.raise_for_status()
    return [feat['attributes']['OBJECTID'] for feat in r.json().get('features', [])]

def delete_objectid(objectid):
    """Delete a single OBJECTID using applyEdits."""
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
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <SPKNumber>")
        sys.exit(1)

    spk = sys.argv[1]
    oids = fetch_objectids_for_spk(spk)
    if not oids:
        print(f"No features found for SPKNumber '{spk}'.")
        return

    print(f"Found {len(oids)} features for SPKNumber {spk}: {oids}")
    for oid in oids:
        print(f"> Deleting OBJECTID={oid} …", end=" ")
        resp = delete_objectid(oid)
        print(resp)

    print("\n✅ Done.")

if __name__ == '__main__':
    main()
