import pandas as pd
import requests
import sys

# --- CONFIG ---
INPUT_FILE  = 'feedback.xlsx'
OUTPUT_FILE = 'feedback_checked.xlsx'
USER_ID     = 'agasha123'
TOKEN       = ''
BASE_URL    = "https://maps.sinarmasforestry.com/arcgis/rest/services/PreFo/DroneSprayingVendor/FeatureServer/0/query"

def find_spk_col(df: pd.DataFrame) -> str:
    for col in df.columns:
        if col.strip().lower() == 'spknumber':
            return col
    raise KeyError(f"Could not find SPKNumber column. Available: {', '.join(df.columns)}")

def fetch_spk_info(spk: str):
    params = {
        'f': 'json',
        'where':    f"(UserID='{USER_ID}') AND (LOWER(SPKNumber) LIKE '{spk}%')",
        'resultRecordCount': 1000,
        'outFields': 'FlightID,SPKNumber,KeyID,Height,OBJECTID',
        'returnGeometry': 'false',
        'token': TOKEN
    }
    r = requests.get(BASE_URL, params=params)
    r.raise_for_status()
    js = r.json()

    feats = js.get('features', [])
    if not feats:
        return 'not_uploaded', []

    flight_ids = [f['attributes']['FlightID'] for f in feats]
    return 'uploaded', flight_ids

def main():
    df = pd.read_excel(INPUT_FILE, dtype=str)
    try:
        spk_col = find_spk_col(df)
    except KeyError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    cache   = {}
    statuses = []
    flights  = []

    for idx, raw in enumerate(df[spk_col].fillna('0'), start=1):
        spk = raw.strip()
        if spk in ('', '0'):
            status, fids = 'not_uploaded', []
        elif spk in cache:
            status, fids = cache[spk]
        else:
            try:
                status, fids = fetch_spk_info(spk)
            except Exception as err:
                status, fids = f'error: {err}', []
            cache[spk] = (status, fids)

        statuses.append(status)
        flights.append(",".join(fids))
        print(f"Row {idx}: SPK={spk or '0'} → {status} ({len(fids)} flights)")

    df['Status']    = statuses
    df['FlightIDs'] = flights
    df.to_excel(OUTPUT_FILE, index=False)
    print(f"\n✅ Done — results in {OUTPUT_FILE}")

if __name__ == '__main__':
    main()
