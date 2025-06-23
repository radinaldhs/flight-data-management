import requests
import sys

# --- CONFIG ---
USER_ID = 'agasha123'
TOKEN   = 'Q4YsJMEI-RnMmfmDewfgUKjqM-I28Xw5LEAdDpoQHBpGZas32IclUKZOW2nJRbT0wp3PF2cCog7Ib_4xkHxYnk_BUnZRnGHDemBcM490LS6ZRpTGh4epEpIPGlIZH_DncEcJv7RPbdLTzOfiJfvVc8V0nczW0CXugZIby6jMmYXu41bVX6-iXHfOANL05maZ'
FEATURE_QUERY_URL = (
    "https://maps.sinarmasforestry.com/arcgis/rest/services/"
    "PreFo/DroneSprayingVendor/FeatureServer/0/query"
)


def fetch_null_height_spks():
    """
    Query all features where Height is NULL and return their SPKNumber values.
    """
    params = {
        'f': 'json',
        'where': f"(UserID='{USER_ID}') AND Height IS NULL",
        'resultRecordCount': 10000,
        'outFields': 'SPKNumber',
        'returnGeometry': 'false',
        'token': TOKEN
    }
    resp = requests.get(FEATURE_QUERY_URL, params=params)
    resp.raise_for_status()
    data = resp.json()
    return [feat['attributes']['SPKNumber'] for feat in data.get('features', [])]


def main():
    spk_list = fetch_null_height_spks()
    unique_spks = sorted(set(spk_list))

    if not unique_spks:
        print("No SPKNumbers with NULL Height found.")
        return

    print("SPKNumbers with NULL Height:")
    for spk in unique_spks:
        print(spk)


if __name__ == '__main__':
    main()
