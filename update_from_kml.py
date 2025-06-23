#!/usr/bin/env python3
import os
import zipfile
import tempfile
import argparse
import requests
import xml.etree.ElementTree as ET
import json
import re

# --- CONFIG ---
FEATURE_URL = (
    "https://maps.sinarmasforestry.com/arcgis/rest/services/"
    "PreFo/DroneSprayingVendor/FeatureServer/0/query"
)
EDIT_URL = (
    "https://maps.sinarmasforestry.com/arcgis/rest/services/"
    "PreFo/DroneSprayingVendor/FeatureServer/0/applyEdits"
)

# ← your working token & cookie
TOKEN = ''
AGS_ROLES = ''

# prepare session
session = requests.Session()
session.cookies.update({"AGS_ROLES": AGS_ROLES})
session.headers.update({
    "Referer": "https://maps.sinarmasforestry.com/UploadDroneManagements/",
    "Origin":  "https://maps.sinarmasforestry.com",
    "User-Agent": "Mozilla/5.0",
})

def parse_height_only(path):
    """
    Return float(height) from a KML's <ExtendedData> or raise ValueError.
    """
    tree = ET.parse(path)
    root = tree.getroot()

    # find ExtendedData, ignoring namespace
    ext = next((el for el in root.iter() if el.tag.endswith("ExtendedData")), None)
    if ext is None:
        raise ValueError("no <ExtendedData>")

    # find Data/@name="Height" (or "height")
    for d in ext:
        if d.tag.endswith("Data") and d.attrib.get("name", "").lower() == "height":
            val = next((c.text for c in d if c.tag.endswith("value")), None)
            if val:
                return float(val.strip())
    raise ValueError("missing field: Height")

def extract_flight_id_from_filename(fn):
    """
    e.g. "T25 - 01_20250221120601_R2425380006.kml" → "R2425380006"
    """
    base = os.path.splitext(fn)[0]
    parts = base.split('_')
    if parts:
        return parts[-1]
    raise ValueError("cannot parse FlightID from filename")

def query_null_heights(spk, flight_id):
    params = {
        "f": "json",
        "where": f"SPKNumber='{spk}' AND FlightID='{flight_id}' AND Height IS NULL",
        "outFields": "OBJECTID,SPKNumber,KeyID,CRT_Date,Height",
        "returnGeometry": "false",
        "token": TOKEN
    }
    r = session.get(FEATURE_URL, params=params)
    r.raise_for_status()
    return r.json().get("features", [])

def update_height(attrs, new_height):
    # must include all non-nullable fields
    out = {
        "OBJECTID": attrs["OBJECTID"],
        "SPKNumber": attrs["SPKNumber"],
        "KeyID":     attrs["KeyID"],
        "CRT_Date":  attrs["CRT_Date"],
        "Height":    new_height
    }
    updates = [{"attributes": out}]
    payload = {
        "f":       "json",
        "token":   TOKEN,
        "updates": requests.utils.requote_uri(json.dumps(updates))
    }
    r = session.post(EDIT_URL, data=payload)
    r.raise_for_status()
    return r.json()

def main():
    p = argparse.ArgumentParser(
        description="Bulk-update Height from KMLs in ZIP for one SPKNumber"
    )
    p.add_argument("zipfile", help="ZIP containing KML files")
    p.add_argument("spk",     help="SPKNumber for all these KMLs")
    args = p.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(args.zipfile, "r") as z:
            z.extractall(tmp)

        for _, _, files in os.walk(tmp):
            for fn in files:
                if not fn.lower().endswith(".kml"):
                    continue
                path = os.path.join(tmp, fn)

                # 1) pull height
                try:
                    height = parse_height_only(path)
                except ValueError as e:
                    print(f"– skipping '{fn}': {e}")
                    continue

                # 2) pull flight_id from ExtendedData if available,
                #    else fall back to filename
                try:
                    # reuse same parse logic but for FlightID
                    tree = ET.parse(path)
                    root = tree.getroot()
                    ext = next((el for el in root.iter() if el.tag.endswith("ExtendedData")), None)
                    fid = None
                    if ext is not None:
                        # try any Data whose name endswith "FlightID" or "flight_controller_id"
                        for d in ext:
                            nm = d.attrib.get("name","").lower()
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

                # 3) query and update
                feats = query_null_heights(args.spk, fid)
                if not feats:
                    print(f" → no null-height features for FlightID={fid}")
                    continue

                for feat in feats:
                    oid = feat["attributes"]["OBJECTID"]
                    print(f" → updating OBJECTID={oid} to Height={height}")
                    resp = update_height(feat["attributes"], height)
                    print("    response:", resp)

if __name__ == "__main__":
    main()
