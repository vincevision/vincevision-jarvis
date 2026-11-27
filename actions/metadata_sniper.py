import subprocess
import os
import json
import requests
import re
from pathlib import Path
from datetime import datetime
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS

# ── Config ────────────────────────────────────────────────────────────────────
LOG_DIR = Path.home() / "JARVIS_logs" / "metadata_sniper"

def _log(player, msg):
    if player:
        try: player.write_log(f"[SNIPER] {msg}")
        except: pass

def get_geotagging(exif):
    if not exif:
        return None
    geotagging = {}
    for (idx, tag) in TAGS.items():
        if tag == 'GPSInfo':
            if idx not in exif:
                return None
            for (t, value) in GPSTAGS.items():
                if t in exif[idx]:
                    geotagging[value] = exif[idx][t]
    return geotagging

def get_decimal_from_dms(dms, ref):
    degrees = dms[0]
    minutes = dms[1] / 60.0
    seconds = dms[2] / 3600.0
    if ref in ['S', 'W']:
        return -float(degrees + minutes + seconds)
    return float(degrees + minutes + seconds)

def get_coordinates(geotags):
    lat = get_decimal_from_dms(geotags['GPSLatitude'], geotags['GPSLatitudeRef'])
    lon = get_decimal_from_dms(geotags['GPSLongitude'], geotags['GPSLongitudeRef'])
    return (lat, lon)

def metadata_sniper(parameters: dict, player=None, speak=None) -> str:
    """
    Metadata Sniper. Extracts GPS and hardware info from images to find exact locations.
    """
    image_path = parameters.get("file_path", "")
    image_url = parameters.get("url", "")
    
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    
    # Download if URL provided
    if image_url:
        if speak: speak("Downloading remote image for analysis, sir.")
        try:
            r = requests.get(image_url, timeout=10)
            image_path = LOG_DIR / "temp_target.jpg"
            image_path.write_bytes(r.content)
            image_path = str(image_path)
        except Exception as e:
            return f"Failed to download image: {e}"

    if not image_path or not os.path.exists(image_path):
        return "Sir, please provide a valid image file path or URL."

    if speak: speak("Scanning image metadata for GPS signatures.")
    _log(player, f"Analyzing: {image_path}")

    report = []
    try:
        img = Image.open(image_path)
        exif = img._getexif()
        
        if not exif:
            return "Scan complete. No EXIF data found. The metadata has been stripped, sir."

        # Extract General Info
        report.append("--- [ DEVICE & CAPTURE INFO ] ---")
        for (idx, tag) in TAGS.items():
            if idx in exif:
                if tag in ('Make', 'Model', 'Software', 'DateTime', 'LensModel'):
                    report.append(f"{tag}: {exif[idx]}")

        # Extract GPS
        geotags = get_geotagging(exif)
        if geotags:
            lat, lon = get_coordinates(geotags)
            report.append("\n--- [ 🎯 EXACT LOCATION DETECTED ] ---")
            report.append(f"Coordinates: {lat}, {lon}")
            report.append(f"Google Maps: https://www.google.com/maps?q={lat},{lon}")
            if speak: speak("GPS coordinates found, sir. Target location locked.")
        else:
            report.append("\nGPS data not found in this specific file.")

    except Exception as e:
        return f"Sniper Error: {str(e)}"

    final_report = "\n".join(report)
    
    # Save Report
    report_file = LOG_DIR / f"sniper_report_{int(time.time())}.txt"
    report_file.write_text(final_report)

    return f"METADATA SNIPER REPORT:\n\n{final_report}\n\n[Full log: {report_file}]"

# ── Tool Declaration ──
DECLARATION = {
    "name": "metadata_sniper",
    "description": "Extracts hidden metadata and GPS coordinates from images to find exact physical locations.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "file_path": {"type": "STRING", "description": "Local path to the image"},
            "url": {"type": "STRING", "description": "Direct URL to an image"}
        },
        "required": []
    }
}