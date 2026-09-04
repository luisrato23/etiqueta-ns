#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Servidor local para gerar etiquetas 60x40 de iPads conectados por USB.

- Le nº de serie, saude da bateria e ciclos de cada iPad via libimobiledevice.
- Serve uma interface no navegador (http://localhost:8765).
- Imprime a etiqueta em ZPL direto no spooler da ELGIN L42PRO (RAW).

Sem dependencias externas: usa apenas a biblioteca padrao do Python.
"""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import unicodedata
import plistlib
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

VERSION = "1.15.0"
GITHUB_REPO = "luisrato23/etiqueta-ns"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
BIN_DIR = os.path.join(BASE_DIR, "vendor", "libimobile")

DEFAULT_CONFIG = {
    "printer_name": "",
    "http_port": 8765,
    "bind_host": "127.0.0.1",
    "poll_interval_seconds": 3,
    "battery_poll_seconds": 8,
    "label": {
        "language": "auto",
        "dpmm": 8,
        "width_mm": 60,
        "height_mm": 40,
        "gap_dots": 24,
        "offset_x": 0,
        "offset_y": 0,
        "darkness": 10,
        "print_speed": 3,
        "strip_accents": True,
        "element_scale": 0.8,
        "show_color": True,
        "bottom_labels": True,
        "flip_180": True,
        "text_bold": False,
        "barcode_module": 2,
        "barcode_height": 150,
        "copies_default": 1,
    },
    "ui": {
        "slots": 10,
        "theme": "system",
        "scale": 100,
    },
    "diagnostics_commands": [
        ["ioregentry", "AppleSmartBattery"],
        ["ioregentry", "AppleSmartBatteryManager"],
        ["diagnostics", "GasGauge"],
        ["ioregentry", "AppleARMPMUCharger"],
    ],
}


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    path = os.path.join(BASE_DIR, "config.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                user = json.load(f)
            for k, v in user.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
        except Exception as e:
            print(f"[config] erro lendo config.json, usando padrao: {e}")
    return cfg


CONFIG = load_config()


def save_config():
    try:
        with open(os.path.join(BASE_DIR, "config.json"), "w", encoding="utf-8") as fh:
            json.dump(CONFIG, fh, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[config] nao consegui gravar: {e}")
        return False


# ------------------------------- impressoras -------------------------------

PRINTERS = []          # [{"name","driver","port"}], atualizado ao iniciar / via API
_VIRTUAL = ("pdf", "xps", "onenote", "fax", "anydesk", "document writer",
            "print to", "microsoft ", "send to ", "\\\\")


def list_windows_printers():
    try:
        p = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Printer | Select-Object Name,DriverName,PortName,PrinterStatus | "
             "ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        data = json.loads(p.stdout.strip() or "[]")
        if isinstance(data, dict):
            data = [data]
        out = []
        for d in data:
            if d.get("Name"):
                out.append({"name": d["Name"],
                            "driver": d.get("DriverName") or "",
                            "port": d.get("PortName") or "",
                            "status": str(d.get("PrinterStatus") or "")})
        return out
    except Exception as e:
        print(f"[impressoras] {e}")
        return []


BUSY_PRINTING = False


def printer_health():
    """online | busy | offline  — apenas leitura, nao mexe na impressao."""
    if BUSY_PRINTING:
        return "busy"
    name = CONFIG.get("printer_name", "")
    if not name:
        return "offline"
    for p in PRINTERS:
        if p["name"] == name:
            s = p.get("status", "").lower()
            if any(k in s for k in ("offline", "error", "unavailable", "not available")):
                return "offline"
            if any(k in s for k in ("printing", "busy", "processing", "paused",
                                    "paper", "toner", "warming")):
                return "busy"
            return "online"
    return "offline"      # configurada mas nao aparece na lista do Windows


def refresh_printers():
    global PRINTERS
    PRINTERS = list_windows_printers()
    return PRINTERS


def _printer_blob(name):
    for p in PRINTERS:
        if p["name"] == name:
            return (p["name"] + " " + p["driver"] + " " + p["port"]).lower()
    return (name or "").lower()


def autopick_printer():
    real = [p for p in PRINTERS
            if not any(v in (p["name"] + " " + p["driver"]).lower() for v in _VIRTUAL)]
    label_kw = ("elgin", "zebra", "tsc", "argox", "godex", "bematech", "label",
                "l42", "zdesigner", "etiq", "thermal", "term")
    for p in real:
        if any(k in (p["name"] + " " + p["driver"]).lower() for k in label_kw):
            return p["name"]
    if real:
        return real[0]["name"]
    return PRINTERS[0]["name"] if PRINTERS else CONFIG.get("printer_name", "")


def resolve_language():
    lang = str(CONFIG["label"].get("language", "auto")).lower()
    if lang in ("epl", "zpl"):
        return lang
    blob = _printer_blob(CONFIG.get("printer_name", ""))
    zpl_kw = ("zebra", "zpl", "zdesigner", "gk420", "gx430", "zd220", "zd230",
              "zd410", "zt230", "gc420")
    return "zpl" if any(k in blob for k in zpl_kw) else "epl"


def ensure_printer_configured():
    refresh_printers()
    names = [p["name"] for p in PRINTERS]
    if CONFIG.get("printer_name") not in names:
        pick = autopick_printer()
        if pick:
            CONFIG["printer_name"] = pick
            save_config()
            print(f"[impressoras] usando '{pick}'")


# ------------------------------- atualizacao -------------------------------

def _ver_tuple(s):
    return tuple(int(x) for x in re.findall(r"\d+", str(s or "0")))


_UPDATE_CACHE = {"ts": 0.0, "data": None}


def check_update(force=False):
    """Consulta o GitHub pela ultima release. Cacheia 1h. So leitura."""
    now = time.time()
    if not force and _UPDATE_CACHE["data"] and now - _UPDATE_CACHE["ts"] < 3600:
        return _UPDATE_CACHE["data"]
    repo = CONFIG.get("update_repo", GITHUB_REPO)
    result = {"current": VERSION, "latest": VERSION, "tag": f"v{VERSION}",
              "update_available": False, "notes": "", "checked": False}
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/releases/latest",
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": "NS-Label/" + VERSION})
        with urllib.request.urlopen(req, timeout=8) as r:
            rel = json.loads(r.read().decode("utf-8"))
        tag = str(rel.get("tag_name") or "").strip()
        latest = tag.lstrip("vV")
        result.update(
            latest=latest or VERSION, tag=tag or f"v{VERSION}",
            notes=(rel.get("body") or "").strip()[:1200],
            update_available=_ver_tuple(latest) > _ver_tuple(VERSION),
            checked=True)
    except Exception as e:
        result["error"] = str(e)[:180]
    _UPDATE_CACHE["ts"] = now
    _UPDATE_CACHE["data"] = result
    return result


_UPDATING = False

# arquivos que NUNCA sao sobrescritos por uma atualizacao
_UPDATE_SKIP = {"config.json", "server.log", "server.log.old", "update.log",
               "_last_label.txt", "_last_label.zpl", "battery_cache.json"}


def _copy_tree_over(src, dst):
    """Copia src/* -> dst/*, sobrescrevendo. Pula _UPDATE_SKIP. Best-effort."""
    fails = []
    for name in os.listdir(src):
        if name in _UPDATE_SKIP or name.startswith("_"):
            continue
        s, d = os.path.join(src, name), os.path.join(dst, name)
        try:
            if os.path.isdir(s):
                os.makedirs(d, exist_ok=True)
                fails += _copy_tree_over(s, d)
            else:
                tmp = d + ".new"
                shutil.copy2(s, tmp)
                os.replace(tmp, d)          # troca atomica
        except Exception as e:
            fails.append(f"{name}: {e}")
    return fails


def apply_update():
    """Baixa a ultima release, troca os arquivos (em Python) e reinicia."""
    global _UPDATING
    if _UPDATING:
        return False, "atualizacao ja em andamento"
    repo = CONFIG.get("update_repo", GITHUB_REPO)
    url = f"https://github.com/{repo}/releases/latest/download/Etiqueta-NS.zip"
    zpath = os.path.join(BASE_DIR, "_update.zip")
    updir = os.path.join(BASE_DIR, "_update")
    try:
        _UPDATING = True
        req = urllib.request.Request(url, headers={"User-Agent": "NS-Label/" + VERSION})
        with urllib.request.urlopen(req, timeout=90) as r, open(zpath, "wb") as f:
            shutil.copyfileobj(r, f)
        if os.path.isdir(updir):
            shutil.rmtree(updir, ignore_errors=True)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(updir)
        root = os.path.join(updir, "Etiqueta-NS")
        new_server = os.path.join(root, "server.py")
        if not os.path.isfile(new_server):
            raise RuntimeError("pacote invalido (server.py nao encontrado)")

        # 1) o novo server.py precisa pelo menos compilar
        with open(new_server, "r", encoding="utf-8") as fh:
            compile(fh.read(), "server.py", "exec")

        # 2) backup do que da pra reverter (server.py + static) p/ o restart.bat
        bkp = os.path.join(BASE_DIR, "_backup")
        shutil.rmtree(bkp, ignore_errors=True)
        os.makedirs(os.path.join(bkp, "static"), exist_ok=True)
        shutil.copy2(os.path.join(BASE_DIR, "server.py"), os.path.join(bkp, "server.py"))
        for n in ("index.html", "app.js", "style.css"):
            p = os.path.join(STATIC_DIR, n)
            if os.path.isfile(p):
                shutil.copy2(p, os.path.join(bkp, "static", n))

        # 3) troca os arquivos aqui mesmo — sem xcopy/robocopy
        fails = _copy_tree_over(root, BASE_DIR)
        for f in fails:
            print(f"[update] nao trocou {f}")
        shutil.rmtree(updir, ignore_errors=True)
        try:
            os.remove(zpath)
        except OSError:
            pass

        # 4) o .bat encerra este servidor, religa e, se nao subir, reverte
        bat = os.path.join(BASE_DIR, "restart.bat")
        port = str(CONFIG.get("http_port", 8765))
        subprocess.Popen(
            ["cmd", "/c", bat, str(os.getpid()), port], cwd=BASE_DIR,
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        return True, ("ok" + (f" ({len(fails)} arquivo(s) mantidos)" if fails else ""))
    except Exception as e:
        _UPDATING = False
        return False, str(e)[:200]


# ProductType -> nome comercial (sem acento; cai no proprio ProductType se faltar)
MODEL_NAMES = {
    "iPad6,11": "iPad (5a geracao)", "iPad6,12": "iPad (5a geracao)",
    "iPad7,5": "iPad (6a geracao)", "iPad7,6": "iPad (6a geracao)",
    "iPad7,11": "iPad (7a geracao)", "iPad7,12": "iPad (7a geracao)",
    "iPad11,6": "iPad (8a geracao)", "iPad11,7": "iPad (8a geracao)",
    "iPad12,1": "iPad (9a geracao)", "iPad12,2": "iPad (9a geracao)",
    "iPad13,18": "iPad (10a geracao)", "iPad13,19": "iPad (10a geracao)",
    "iPad15,7": "iPad (A16)", "iPad15,8": "iPad (A16)",
    "iPad4,1": "iPad Air", "iPad4,2": "iPad Air", "iPad4,3": "iPad Air",
    "iPad5,3": "iPad Air 2", "iPad5,4": "iPad Air 2",
    "iPad11,3": "iPad Air (3a geracao)", "iPad11,4": "iPad Air (3a geracao)",
    "iPad13,1": "iPad Air (4a geracao)", "iPad13,2": "iPad Air (4a geracao)",
    "iPad13,16": "iPad Air (5a geracao)", "iPad13,17": "iPad Air (5a geracao)",
    "iPad14,8": "iPad Air 11 (M2)", "iPad14,9": "iPad Air 11 (M2)",
    "iPad14,10": "iPad Air 13 (M2)", "iPad14,11": "iPad Air 13 (M2)",
    "iPad15,3": "iPad Air 11 (M3)", "iPad15,4": "iPad Air 11 (M3)",
    "iPad15,5": "iPad Air 13 (M3)", "iPad15,6": "iPad Air 13 (M3)",
    "iPad2,5": "iPad mini", "iPad2,6": "iPad mini", "iPad2,7": "iPad mini",
    "iPad4,4": "iPad mini 2", "iPad4,5": "iPad mini 2", "iPad4,6": "iPad mini 2",
    "iPad4,7": "iPad mini 3", "iPad4,8": "iPad mini 3", "iPad4,9": "iPad mini 3",
    "iPad5,1": "iPad mini 4", "iPad5,2": "iPad mini 4",
    "iPad11,1": "iPad mini (5a geracao)", "iPad11,2": "iPad mini (5a geracao)",
    "iPad14,1": "iPad mini (6a geracao)", "iPad14,2": "iPad mini (6a geracao)",
    "iPad16,1": "iPad mini (A17 Pro)", "iPad16,2": "iPad mini (A17 Pro)",
    "iPad6,3": "iPad Pro 9,7", "iPad6,4": "iPad Pro 9,7",
    "iPad6,7": "iPad Pro 12,9", "iPad6,8": "iPad Pro 12,9",
    "iPad7,1": "iPad Pro 12,9 (2a ger)", "iPad7,2": "iPad Pro 12,9 (2a ger)",
    "iPad7,3": "iPad Pro 10,5", "iPad7,4": "iPad Pro 10,5",
    "iPad8,1": "iPad Pro 11", "iPad8,2": "iPad Pro 11",
    "iPad8,3": "iPad Pro 11", "iPad8,4": "iPad Pro 11",
    "iPad8,5": "iPad Pro 12,9 (3a ger)", "iPad8,6": "iPad Pro 12,9 (3a ger)",
    "iPad8,7": "iPad Pro 12,9 (3a ger)", "iPad8,8": "iPad Pro 12,9 (3a ger)",
    "iPad8,9": "iPad Pro 11 (2a ger)", "iPad8,10": "iPad Pro 11 (2a ger)",
    "iPad8,11": "iPad Pro 12,9 (4a ger)", "iPad8,12": "iPad Pro 12,9 (4a ger)",
    "iPad13,4": "iPad Pro 11 (3a ger)", "iPad13,5": "iPad Pro 11 (3a ger)",
    "iPad13,6": "iPad Pro 11 (3a ger)", "iPad13,7": "iPad Pro 11 (3a ger)",
    "iPad13,8": "iPad Pro 12,9 (5a ger)", "iPad13,9": "iPad Pro 12,9 (5a ger)",
    "iPad13,10": "iPad Pro 12,9 (5a ger)", "iPad13,11": "iPad Pro 12,9 (5a ger)",
    "iPad14,3": "iPad Pro 11 (4a ger)", "iPad14,4": "iPad Pro 11 (4a ger)",
    "iPad14,5": "iPad Pro 12,9 (6a ger)", "iPad14,6": "iPad Pro 12,9 (6a ger)",
    "iPad16,3": "iPad Pro 11 (M4)", "iPad16,4": "iPad Pro 11 (M4)",
    "iPad16,5": "iPad Pro 13 (M4)", "iPad16,6": "iPad Pro 13 (M4)",
    "iPhone14,7": "iPhone 14", "iPhone14,8": "iPhone 14 Plus",
    "iPhone15,2": "iPhone 14 Pro", "iPhone15,3": "iPhone 14 Pro Max",
    "iPhone15,4": "iPhone 15", "iPhone15,5": "iPhone 15 Plus",
    "iPhone16,1": "iPhone 15 Pro", "iPhone16,2": "iPhone 15 Pro Max",
    "iPhone17,1": "iPhone 16 Pro", "iPhone17,2": "iPhone 16 Pro Max",
    "iPhone17,3": "iPhone 16", "iPhone17,4": "iPhone 16 Plus",
    "iPhone17,5": "iPhone 16e",
}


def marketing_name(product_type, fallback=None):
    return (MODEL_NAMES.get(product_type or "")
            or fallback or product_type or "")


# DeviceColor / DeviceEnclosureColor -> (nome, hex p/ o preview).
# Codigos antigos sao numericos; recentes vem em hex tipo "#3d3d3d".
# Mapa aproximado; ajuste em config.json -> "color_names": { "2": "Prata", ... }
COLOR_NAMES = {
    "0": ("Branco", "#ededed"),
    "1": ("Preto", "#1c1c1e"),
    "2": ("Prata", "#d6d7da"),
    "3": ("Dourado", "#f7e8c9"),
    "4": ("Rose", "#e7c5bf"),
    "5": ("Cinza-espacial", "#57575b"),
    "6": ("Vermelho", "#b23b3b"),
    "7": ("Amarelo", "#f2d14e"),
    "8": ("Azul", "#8fb6d6"),
    "9": ("Verde", "#a7bfa5"),
    "10": ("Roxo", "#b7b2d6"),
    "#3d3d3d": ("Cinza-espacial", "#3d3d3d"),
    "#1f2020": ("Cinza-espacial", "#2a2b2b"),
    "#e1e4e3": ("Prata", "#e1e4e3"),
    "#f2f2f2": ("Prata", "#f2f2f2"),
    "#efe3cd": ("Dourado", "#efe3cd"),
    "#fae7cf": ("Dourado", "#fae7cf"),
    "#faf6f2": ("Estelar", "#faf6f2"),
    "#3b4c56": ("Meia-noite", "#3b4c56"),
    "#a5aab8": ("Azul", "#a5aab8"),
    "#b9b6d3": ("Roxo", "#b9b6d3"),
    "#a6bda9": ("Verde", "#a6bda9"),
    "#ecc5c0": ("Rose", "#ecc5c0"),
    "#b40000": ("Vermelho", "#b40000"),
}


_CAP_TIERS = [8, 16, 32, 64, 128, 256, 512, 1024, 2048]


def capacity_str(total_bytes):
    """Bytes do disco -> capacidade comercial ('64 GB', '1 TB')."""
    try:
        gb = float(total_bytes) / 1e9
    except (TypeError, ValueError):
        return ""
    if gb < 4:
        return ""
    nearest = min(_CAP_TIERS, key=lambda t: abs(t - gb))
    if abs(nearest - gb) / nearest > 0.25:      # muito longe de um tier -> arredonda
        nearest = int(round(gb))
    return {1024: "1 TB", 2048: "2 TB"}.get(nearest, f"{nearest} GB")


def color_info(code):
    if not code:
        return None, None
    code = str(code).strip().lower()
    override = CONFIG.get("color_names", {})
    if code in override:
        v = override[code]
        if isinstance(v, (list, tuple)):
            return v[0], (v[1] if len(v) > 1 else None)
        return v, (code if code.startswith("#") else None)
    if code in COLOR_NAMES:
        return COLOR_NAMES[code]
    if code.startswith("#") and len(code) in (4, 7):
        return code.upper(), code            # cor desconhecida: usa o proprio hex
    return f"cor {code}", None               # codigo numerico desconhecido


def _json_default(o):
    if isinstance(o, (bytes, bytearray)):
        return o.hex()
    return str(o)

# ---------------------------------------------------------------------------
# libimobiledevice helpers
# ---------------------------------------------------------------------------

def _tool(name):
    exe = os.path.join(BIN_DIR, name + ".exe")
    if not os.path.exists(exe):
        raise FileNotFoundError(f"Nao encontrei {exe}. Extraia o vendor/libimobile.")
    return exe


def run_tool(name, args, timeout=25):
    """Roda um utilitario libimobiledevice e devolve (rc, stdout_bytes, stderr_text)."""
    try:
        p = subprocess.run(
            [_tool(name)] + args,
            capture_output=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return p.returncode, p.stdout, p.stderr.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return 124, b"", "timeout"
    except Exception as e:
        return 1, b"", str(e)


def list_udids():
    rc, out, err = run_tool("idevice_id", ["-l"], timeout=10)
    if rc != 0:
        return []
    seen = []
    for line in out.decode("utf-8", "replace").splitlines():
        u = line.strip()
        if u and u not in seen:
            seen.append(u)
    return seen


def parse_plist_or_regex(raw_bytes):
    """Tenta plist XML; se falhar, varre pares <key>/<valor> por regex."""
    data = {}
    try:
        obj = plistlib.loads(raw_bytes)
        if isinstance(obj, dict):
            return _flatten(obj)
    except Exception:
        pass
    text = raw_bytes.decode("utf-8", "replace")
    for m in re.finditer(
        r"<key>([^<]+)</key>\s*<(integer|real|string|true|false)\s*/?>(?:([^<]*)</\2>)?",
        text,
    ):
        key, typ, val = m.group(1), m.group(2), m.group(3)
        if typ == "true":
            data[key] = True
        elif typ == "false":
            data[key] = False
        elif typ in ("integer", "real"):
            try:
                data[key] = float(val) if typ == "real" else int(val)
            except (TypeError, ValueError):
                pass
        else:
            data[key] = (val or "").strip()
    return data


def _flatten(d, prefix=""):
    flat = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            flat.update(_flatten(v, key + "."))
            # tambem guarda as chaves "folha" sem prefixo, util p/ bateria
            flat.update(_flatten(v, ""))
        else:
            flat[key] = v
    return flat


def get_device_info(udid):
    rec = {
        "udid": udid,
        "name": None,
        "serial": None,
        "model": None,
        "model_name": None,
        "capacity": None,
        "color_code": None,
        "color_name": None,
        "color_hex": None,
        "ios": None,
        "battery_health": None,      # % de saude (capacidade maxima)
        "cycle_count": None,
        "batt_updated": 0,           # ultima releitura da bateria (epoch)
        "batt_samples": 0,           # nº de amostras acumuladas p/ convergir
        "batt_settled": False,       # True quando o valor ja estabilizou
        "paired": True,
        "status": "ok",
        "notes": [],
        "raw_diag": {},
        "updated": time.time(),
    }

    rc, out, err = run_tool("ideviceinfo", ["-u", udid, "-x"])
    if rc != 0:
        low = err.lower()
        if "pair" in low or "trust" in low or "not paired" in low or "lockdown" in low:
            rec["paired"] = False
            rec["status"] = "pareamento"
            rec["notes"].append("Desbloqueie o iPad e toque em CONFIAR neste computador.")
        else:
            rec["status"] = "erro"
            rec["notes"].append(err.strip() or "falha ao ler o aparelho")
        return rec

    info = parse_plist_or_regex(out)
    rec["name"] = info.get("DeviceName")
    rec["serial"] = info.get("SerialNumber")
    rec["model"] = info.get("ProductType")
    rec["model_name"] = marketing_name(info.get("ProductType"),
                                       info.get("MarketingName"))
    rec["ios"] = info.get("ProductVersion")

    code = str(info.get("DeviceEnclosureColor")
               or info.get("DeviceColor") or "").strip()
    rec["color_code"] = code or None
    rec["color_name"], rec["color_hex"] = color_info(code)

    # capacidade (memoria) do aparelho
    cap_bytes = info.get("TotalDiskCapacity")
    if cap_bytes is None:
        rc2, out2, _ = run_tool(
            "ideviceinfo", ["-u", udid, "-q", "com.apple.disk_usage", "-x"])
        if rc2 == 0:
            cap_bytes = parse_plist_or_regex(out2).get("TotalDiskCapacity")
    rec["capacity"] = capacity_str(cap_bytes) or None

    # saude + ciclos via interface de diagnostico
    _fill_battery_diagnostics(udid, rec)
    rec["batt_updated"] = time.time()

    if rec["battery_health"] is None and rec["cycle_count"] is None:
        rec["notes"].append(
            "Este iPad nao entregou saude/ciclos pela interface de diagnostico "
            "(comum em iPadOS 17+). Nº de serie funciona normalmente."
        )
    return rec


CAP_KEYS_DESIGN = ["DesignCapacity", "AppleRawDesignCapacity"]

# cache persistente da saude por nº de serie (a interface de diagnostico e instavel;
# AppleRawMaxCapacity oscila, entao guardamos o menor valor visto = como a Apple/3uTools).
_BATT_CACHE_PATH = os.path.join(BASE_DIR, "battery_cache.json")
_BATT_CACHE = None


_BATT_CACHE_LOCK = threading.RLock()   # protege leitura/gravacao do cache (2 threads)


def _batt_cache():
    global _BATT_CACHE
    if _BATT_CACHE is None:
        with _BATT_CACHE_LOCK:
            if _BATT_CACHE is None:
                try:
                    with open(_BATT_CACHE_PATH, "r", encoding="utf-8") as f:
                        _BATT_CACHE = json.load(f)
                except Exception:
                    _BATT_CACHE = {}
    return _BATT_CACHE


def _batt_cache_save():
    with _BATT_CACHE_LOCK:
        try:
            with open(_BATT_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(_BATT_CACHE, f)
        except Exception:
            pass


# trava POR APARELHO: serializa 2 chamadas ao MESMO udid (a leitura completa e a
# releitura rapida da bateria podem coincidir), mas deixa aparelhos DIFERENTES
# rodarem em paralelo de verdade — e o que faz varios iPads ficarem prontos juntos
# em vez de um de cada vez.
_DIAG_LOCKS_GUARD = threading.Lock()
_DIAG_LOCKS = {}


def _diag_lock(udid):
    with _DIAG_LOCKS_GUARD:
        lk = _DIAG_LOCKS.get(udid)
        if lk is None:
            lk = threading.Lock()
            _DIAG_LOCKS[udid] = lk
        return lk


def _diag(udid, sub_args, tries=3, timeout=20):
    """Roda idevicediagnostics repetindo (a interface falha de vez em quando)."""
    last = ""
    for _ in range(tries):
        with _diag_lock(udid):
            rc, out, err = run_tool("idevicediagnostics", ["-u", udid] + list(sub_args),
                                    timeout=timeout)
        if rc == 0 and out.strip():
            p = parse_plist_or_regex(out)
            if p:
                return p, ""
        last = (err or "").strip()[:200]
        time.sleep(0.4)
    return {}, last or "sem resposta"


# fontes uteis de consultar (design/ciclo/capacidade)
_CAP_HINT_KEYS = ("NominalChargeCapacity", "AppleRawMaxCapacity",
                  "DesignCapacity", "AppleRawDesignCapacity", "CycleCount")
# so estas dao o valor VIVO da capacidade em mAh (FullChargeCapacity vem em % em
# varios iPads -> NAO confiavel). Light poll consulta so a fonte que tem uma destas.
_LIVE_KEYS = ("NominalChargeCapacity", "AppleRawMaxCapacity")


def _fill_battery_diagnostics(udid, rec, light=False):
    """Preenche saude/ciclos. light=True: releitura rapida so da fonte que
       entrega o valor VIVO da capacidade, p/ convergir ao exato a cada poucos
       segundos sem gastar chamada USB nas fontes so de ciclo/design."""
    serial = rec.get("serial") or ""
    st = _batt_cache().get(serial, {})
    samples_done = int(st.get("samples", 0))
    have_design = bool(st.get("design"))

    all_combos = [list(c) for c in CONFIG.get("diagnostics_commands", [])]
    if light:
        # ja convergindo + design conhecido -> so a fonte do valor vivo
        pick = st.get("live_src") if (have_design and st.get("live_src")) else st.get("src")
        combos = [c.split(" ") for c in (pick or []) if c] or all_combos
    else:
        combos = all_combos

    merged = {}
    rawmax_samples = []
    good_src = set()
    live_src = set()
    # re-amostra a fonte da capacidade algumas vezes enquanto o valor nao estabilizou
    resample = 3 if (samples_done < 6) else 1

    for combo in combos:
        is_cap_src = combo[-1] in ("AppleARMPMUCharger", "AppleSmartBattery",
                                   "AppleSmartBatteryManager", "GasGauge")
        n = resample if is_cap_src else 1
        for i in range(n):
            parsed, e = _diag(udid, combo, tries=(3 if (i == 0 and not light) else 1),
                              timeout=(9 if light else 20))
            if i == 0:
                rec["raw_diag"][" ".join(combo)] = parsed if parsed else {"_erro": e}
            for k, v in parsed.items():
                merged.setdefault(k, v)
            if any(k in parsed for k in _CAP_HINT_KEYS):
                good_src.add(" ".join(combo))
            if any(k in parsed for k in _LIVE_KEYS):
                live_src.add(" ".join(combo))
            rm = parsed.get("AppleRawMaxCapacity")
            if isinstance(rm, (int, float)) and rm > 0:
                rawmax_samples.append(float(rm))
            if not parsed:
                break                      # fonte nao respondeu -> nao insiste
            if n > 1 and i < n - 1:
                time.sleep(0.25)

    if isinstance(merged.get("BatteryHealthMetadata"), dict):
        for k, v in merged["BatteryHealthMetadata"].items():
            merged.setdefault(k, v)
    if isinstance(merged.get("BatteryData"), dict):
        for k, v in merged["BatteryData"].items():
            merged.setdefault(k, v)

    # ciclos
    for key in ("CycleCount", "BatteryCycleCount"):
        if key in merged:
            try:
                rec["cycle_count"] = int(merged[key])
                break
            except (TypeError, ValueError):
                pass

    design = _first_number(merged, CAP_KEYS_DESIGN)
    nominal = _first_number(merged, ["NominalChargeCapacity"])
    rawmax = min(rawmax_samples) if rawmax_samples else None

    if serial and (good_src or live_src):
        with _BATT_CACHE_LOCK:
            cache = _batt_cache()
            cs = cache.get(serial, st)
            if good_src:
                cs["src"] = sorted(set(cs.get("src", [])) | good_src)
            if live_src:
                # leitura completa ve todas as fontes -> substitui; light so acrescenta
                cs["live_src"] = sorted(live_src) if not light else \
                    sorted(set(cs.get("live_src", [])) | live_src)
            cache[serial] = cs

    h, settled, nsamp = _health_pct(serial, design, nominal, rawmax)
    if h:
        rec["battery_health"] = h
    elif rec.get("battery_health") is None:
        for key in ("MaximumCapacityPercent", "BatteryHealthPercent", "StateOfHealth"):
            v = _first_number(merged, [key])
            if v and 1 <= round(v) <= 100:
                rec["battery_health"] = round(v)
                break
    rec["batt_samples"] = nsamp
    rec["batt_settled"] = settled


def _health_pct(serial, design, nominal, rawmax):
    """Saude acompanhando Apple/3uTools. Usa NominalChargeCapacity quando a
       interface entrega; senao o MENOR AppleRawMaxCapacity ja visto pra esse
       aparelho — esse valor oscila (picos pra cima), entao a cada releitura
       o minimo cai/estabiliza e converge pro numero exato (bateria so degrada).
       Retorna (pct, estabilizou, n_amostras)."""
    with _BATT_CACHE_LOCK:
        cache = _batt_cache()
        s = dict(cache.get(serial or "", {}))
        before = dict(s)
        if design and design > 0:
            s["design"] = design
        design = s.get("design") or design
        if not design or design <= 0:
            return None, False, int(s.get("samples", 0))

        floor = design * 0.5   # abaixo disso e leitura de unidade errada (%, mV...), nao saude
        got = False
        if nominal and nominal > floor:
            prev = s.get("nominal")
            s["nominal"] = nominal if not prev else min(prev, nominal)
            got = True
        if rawmax and rawmax > floor:
            prev = s.get("rawmax_min")
            if prev:
                if rawmax > prev * 1.15:          # salto grande -> bateria trocada
                    prev = None
                elif rawmax < prev * 0.93 and s.get("samples", 0) >= 4:
                    rawmax = None                 # leitura absurda -> descarta (glitch)
            if rawmax:
                s["rawmax_min"] = rawmax if not prev else min(prev, rawmax)
                got = True

        if got:
            s["samples"] = min(int(s.get("samples", 0)) + 1, 999)

        cap = s.get("nominal") or s.get("rawmax_min")
        pct = None
        if cap:
            p = round(100.0 * cap / design)
            if 1 <= p <= 100:
                pct = p

        # estabilizou = mesmo valor por varias releituras seguidas
        if pct == s.get("last_h"):
            s["stable"] = min(int(s.get("stable", 0)) + (1 if got else 0), 12)
        else:
            s["stable"] = 0
        s["last_h"] = pct
        settled = bool(s.get("nominal")) or (
            s.get("stable", 0) >= 6 and s.get("samples", 0) >= 10)

        if serial:
            cache[serial] = s
            if s != before:                      # so grava se algo mudou
                _batt_cache_save()
        return pct, settled, int(s.get("samples", 0))


def _first_number(d, keys):
    for k in keys:
        if k in d:
            try:
                return float(d[k])
            except (TypeError, ValueError):
                continue
    return None


def pair_device(udid):
    rc, out, err = run_tool("idevicepair", ["-u", udid, "pair"], timeout=30)
    msg = (out.decode("utf-8", "replace") + " " + err).strip()
    return rc == 0, msg


def power_device(udid, action):
    """action: shutdown | restart | sleep — via idevicediagnostics."""
    if action not in ("shutdown", "restart", "sleep"):
        return False, "acao invalida"
    rc, out, err = run_tool("idevicediagnostics", ["-u", udid, action], timeout=10)
    msg = (out.decode("utf-8", "replace") + " " + err).strip()
    if rc == 0:
        with LOCK:
            if udid in DEVICES:
                DEVICES[udid]["status"] = "desligando"
        return True, msg or "ok"
    low = msg.lower()
    if "lock" in low or "passcode" in low or "unlock" in low:
        return False, "desbloqueie o iPad e tente de novo"
    return False, msg or "falhou"

# ---------------------------------------------------------------------------
# ZPL
# ---------------------------------------------------------------------------

def _ascii(s):
    if s is None:
        return ""
    s = str(s)
    if CONFIG["label"].get("strip_accents", True):
        s = "".join(
            c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
        )
    # tira aspas/barra (quebram a string entre aspas do EPL) e controles
    s = s.replace('"', "").replace("\\", "").replace("\r", " ").replace("\n", " ")
    return s.strip()


# largura aproximada de um texto nas fontes internas EPL (pontos, 203 dpi)
_EPL_FONT_CELL = {1: 8, 2: 10, 3: 12, 4: 14, 5: 48}


def _epl_text_w(text, font, mult):
    return len(text) * _EPL_FONT_CELL.get(int(font), 12) * int(mult)


def _label_dims():
    L = CONFIG["label"]
    dpmm = L["dpmm"]
    return int(L["width_mm"] * dpmm), int(L["height_mm"] * dpmm)


def _est_code128_dots(text, narrow):
    """Largura aproximada de um Code128 (subset B) em pontos."""
    modules = 11 * (len(text) + 2) + 13   # start + dados + checksum + stop
    return modules * max(1, int(narrow))


def _fields(rec, copies):
    L = CONFIG["label"]
    if copies is None:
        copies = L.get("copies_default", 1)
    copies = max(1, min(int(copies), 50))
    serial = _ascii(rec.get("serial") or "SEM-SERIE")
    health = rec.get("battery_health")
    cycles = rec.get("cycle_count")
    model = _ascii(rec.get("model_name") or rec.get("model") or "")
    cap = _ascii(rec.get("capacity") or "")
    if cap and model:
        model = f"{model} {cap}"
    color = _ascii(rec.get("color_name") or "") if L.get("show_color", True) else ""
    return {
        "serial": serial,
        "model": model,
        "color": color,
        "health": f"{health}%" if health is not None else "N/D",
        "cycles": str(cycles) if cycles is not None else "N/D",
        "copies": copies,
    }


def _texts(f):
    """As 3 linhas de texto da etiqueta."""
    top = f["model"]
    if f["color"]:
        top = f'{top} | {f["color"]}' if top else f["color"]
    if CONFIG["label"].get("bottom_labels", True):
        bottom = f'BT {f["health"]}     CC {f["cycles"]}'
    else:
        bottom = f'{f["health"]}     {f["cycles"]}'
    return top, bottom


def _layout(rec, copies):
    """Pilha vertical centralizada:  MODELO | COR  /  codigo  /  BATERIA CICLOS."""
    L = CONFIG["label"]
    W, H = _label_dims()
    f = _fields(rec, copies)
    s = float(L.get("element_scale", 0.8))
    ox, oy = int(L.get("offset_x", 0)), int(L.get("offset_y", 0))

    top_px = max(8, round(30 * s))
    bot_px = max(8, round(30 * s))
    hr_px = max(8, round(24 * s))                      # texto do nº de serie
    bc_h = max(24, round(int(L.get("barcode_height", 150)) * s))
    module = max(1, int(L.get("barcode_module", 2)))
    gap = round(16 * s)
    pad = max(6, round(10 * s))

    total = top_px + gap + bc_h + hr_px + gap + bot_px
    y0 = max(pad, (H - total) // 2)
    y_top = y0
    y_bc = y_top + top_px + gap
    y_bot = y_bc + bc_h + hr_px + gap

    return dict(W=W, H=H, f=f, s=s, ox=ox, oy=oy, module=module,
                top_px=top_px, bot_px=bot_px, hr_px=hr_px, bc_h=bc_h,
                y_top=y_top, y_bc=y_bc, y_bot=y_bot, pad=pad)


def build_label(rec, copies=None):
    return (build_zpl(rec, copies) if resolve_language() == "zpl"
            else build_epl(rec, copies))


# --- fontes internas EPL: escolhe (font,mult) para uma altura alvo em pontos ---
_EPL_FONTS = [((1, 1), 12), ((2, 1), 16), ((3, 1), 20), ((4, 1), 24),
              ((2, 2), 32), ((3, 2), 40), ((4, 2), 48), ((3, 3), 60),
              ((4, 3), 72), ((4, 4), 96)]


def _epl_font(px):
    best = ((1, 1), 12)
    for fm, h in _EPL_FONTS:
        if h <= px:
            best = (fm, h)
    return best[0]                       # (font, mult)


def _epl_cell(font, mult):
    return _EPL_FONT_CELL.get(int(font), 12) * int(mult)


def _epl_fit(text, target_px, max_w):
    """(font,mult) do tamanho alvo, mas reduz se o texto nao couber em max_w."""
    font, mult = _epl_font(target_px)
    while mult > 1 or font > 1:
        if len(text) * _epl_cell(font, mult) <= max_w:
            break
        if mult > 1:
            mult -= 1
        else:
            font -= 1
    return font, mult


def _cen(text, cell, W, ox):
    return ox + max(0, (W - len(text) * cell) // 2)


# --------------------------- EPL2 (padrao ELGIN) ----------------------------

def build_epl(rec, copies=None):
    L = CONFIG["label"]
    g = _layout(rec, copies)
    f = g["f"]
    ox, oy, W = g["ox"], g["oy"], g["W"]
    gap = int(L.get("gap_dots", 24))
    narrow = g["module"]
    wide = max(narrow * 2, narrow + 1)
    top, bottom = _texts(f)

    tfont, tmult = _epl_fit(top, g["top_px"], W - 8)
    bfont, bmult = _epl_fit(bottom, g["bot_px"], W - 8)
    if not L.get("text_bold", False):
        # fontes EPL menores tem traco mais fino (sem multiplicador = sem "negrito")
        tfont, tmult = min(tfont, 3), 1
        bfont, bmult = min(bfont, 3), 1

    bx = L.get("barcode_x")
    if bx is None:
        bx = max(0, (W - _est_code128_dots(f["serial"], narrow)) // 2)
    bx = int(bx) + ox

    orient = "ZB" if L.get("flip_180", True) else "ZT"
    e = ["", "N", f"q{W}", f"Q{g['H']},{gap}",
         f"S{int(L['print_speed'])}", f"D{int(L['darkness'])}", orient]
    if top:
        e.append(f'A{_cen(top, _epl_cell(tfont, tmult), W, ox)},{g["y_top"] + oy},'
                 f'0,{tfont},{tmult},{tmult},N,"{top}"')
    e.append(f'B{bx},{g["y_bc"] + oy},0,1,{narrow},{wide},{g["bc_h"]},B,"{f["serial"]}"')
    e.append(f'A{_cen(bottom, _epl_cell(bfont, bmult), W, ox)},{g["y_bot"] + oy},'
             f'0,{bfont},{bmult},{bmult},N,"{bottom}"')
    e.append(f'P{f["copies"]}')
    return "\r\n".join(e) + "\r\n"


# ------------------------------- ZPL --------------------------------------

def build_zpl(rec, copies=None):
    L = CONFIG["label"]
    g = _layout(rec, copies)
    f = g["f"]
    ox, oy, W = g["ox"], g["oy"], g["W"]
    module = g["module"]
    top, bottom = _texts(f)

    bx = L.get("barcode_x")
    if bx is None:
        bx = max(0, (W - _est_code128_dots(f["serial"], module)) // 2)
    bx = int(bx) + ox

    def fit_px(text, px):
        while px > 10 and len(text) * px * 0.62 > W - 8:
            px -= 2
        return px

    z = ["^XA", "^CI28", f"^PW{W}", f"^LL{g['H']}", "^LH0,0",
         ("^POI" if L.get("flip_180", True) else "^PON"),
         f"^MD{int(L['darkness'])}", f"^PR{int(L['print_speed'])}"]
    if top:
        tp = fit_px(top, g["top_px"])
        z.append(f"^FO{ox},{g['y_top'] + oy}^FB{W},1,0,C,0"
                 f"^A0N,{tp},{tp}^FD{top}^FS")
    z.append(f"^BY{module},2.0,{g['bc_h']}")
    z.append(f"^FO{bx},{g['y_bc'] + oy}^BCN,{g['bc_h']},Y,N,N^FD{f['serial']}^FS")
    bp = fit_px(bottom, g["bot_px"])
    z.append(f"^FO{ox},{g['y_bot'] + oy}^FB{W},1,0,C,0"
             f"^A0N,{bp},{bp}^FD{bottom}^FS")
    z.append(f"^PQ{f['copies']}")
    z.append("^XZ")
    return "\r\n".join(z) + "\r\n"


# --------------------------- etiqueta de teste ---------------------------

def build_test_label():
    """Moldura + cruz no centro + marcas de canto, para calibrar posicao."""
    L = CONFIG["label"]
    W, H = _label_dims()
    ox = int(L.get("offset_x", 0))
    oy = int(L.get("offset_y", 0))
    gap = int(L.get("gap_dots", 24))
    cx, cy = W // 2 + ox, H // 2 + oy
    flip = L.get("flip_180", True)
    if resolve_language() == "zpl":
        z = ["^XA", f"^PW{W}", f"^LL{H}", "^LH0,0", ("^POI" if flip else "^PON"),
             f"^MD{int(L['darkness'])}",
             f"^FO{2+ox},{2+oy}^GB{W-4},{H-4},2^FS",
             f"^FO{cx-20},{cy}^GB40,2,2^FS", f"^FO{cx},{cy-20}^GB2,40,2^FS",
             f"^FO{8+ox},{8+oy}^A0N,22,22^FD{W}x{H} dots^FS",
             f"^FO{8+ox},{H-34+oy}^A0N,22,22^FDoffset {ox},{oy}^FS",
             "^PQ1", "^XZ"]
        return "\r\n".join(z) + "\r\n"
    e = ["", "N", f"q{W}", f"Q{H},{gap}", f"S{int(L['print_speed'])}",
         f"D{int(L['darkness'])}", ("ZB" if flip else "ZT"),
         f"X{2+ox},{2+oy},2,{W-2},{H-2}",
         f"LO{cx-20},{cy},40,2", f"LO{cx},{cy-20},2,40",
         f'A{8+ox},{8+oy},0,3,1,1,N,"{W}x{H} dots"',
         f'A{8+ox},{H-30+oy},0,3,1,1,N,"offset {ox},{oy}"',
         "P1"]
    return "\r\n".join(e) + "\r\n"


def print_raw(text):
    tmp = os.path.join(BASE_DIR, "_last_label.txt")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    ps1 = os.path.join(BASE_DIR, "raw_print.ps1")
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1,
           "-PrinterName", CONFIG["printer_name"], "-FilePath", tmp]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return p.returncode == 0, (p.stdout + "\n" + p.stderr).strip()

# ---------------------------------------------------------------------------
# Estado / poller
# ---------------------------------------------------------------------------

DEVICES = {}          # udid -> rec
LOCK = threading.Lock()
LAST_SCAN = 0.0

# le varios aparelhos AO MESMO TEMPO (cada um e uma sessao USB independente) em
# vez de um de cada vez — e o que faz N iPads ficarem prontos juntos, nao em fila.
_IO_POOL = ThreadPoolExecutor(max_workers=6, thread_name_prefix="io")


def poller():
    global LAST_SCAN
    cycle = 0
    while True:
        try:
            cycle += 1
            if cycle % 5 == 1:          # status da impressora a cada ~15 s
                refresh_printers()
            udids = list_udids()
            with LOCK:
                for u in list(DEVICES):
                    if u not in udids:
                        del DEVICES[u]
                for u in udids:
                    if u not in DEVICES:
                        DEVICES[u] = {"udid": u, "status": "lendo", "notes": [],
                                      "name": None, "serial": None, "updated": 0}
                now = time.time()
                need = [u for u in udids
                        if DEVICES[u].get("updated", 0) == 0
                        or (DEVICES[u].get("status") in ("pareamento", "erro")
                            and now - DEVICES[u]["updated"] > 8)
                        or now - DEVICES[u]["updated"] > 300]
            if need:
                futs = {_IO_POOL.submit(get_device_info, u): u for u in need}
                for fut in as_completed(futs):
                    u = futs[fut]
                    try:
                        rec = fut.result()
                    except Exception as e:
                        print(f"[poller] {u[:8]} {e}")
                        continue
                    with LOCK:
                        DEVICES[u] = rec      # aplica assim que CADA aparelho termina
            LAST_SCAN = time.time()
        except Exception as e:
            print(f"[poller] {e}")
        time.sleep(max(1, int(CONFIG.get("poll_interval_seconds", 3))))


def battery_poller():
    """Leitura CONTINUA da bateria (saude/ciclos) enquanto o aparelho esta
       conectado: re-amostra a capacidade a cada `battery_poll_seconds` sem
       parar, mesmo depois de estabilizar, entao o valor fica sempre exato e
       acompanha qualquer variacao. Roda todos os aparelhos em paralelo.
       Nao mexe no status do card nem toca som."""
    while True:
        wait = 2
        try:
            every = max(3, int(CONFIG.get("battery_poll_seconds", 8)))
            now = time.time()
            with LOCK:
                targets = [u for u, r in DEVICES.items()
                           if r.get("status") == "ok" and r.get("serial")
                           and now - r.get("batt_updated", 0) >= every]
            bases = {}
            for u in targets:
                with LOCK:
                    base = dict(DEVICES.get(u, {}))
                if base.get("serial"):
                    base["raw_diag"] = {}
                    bases[u] = base
            if bases:
                futs = {_IO_POOL.submit(_fill_battery_diagnostics, u, base, True): u
                        for u, base in bases.items()}
                for fut in as_completed(futs):
                    u = futs[fut]
                    base = bases[u]
                    try:
                        fut.result()
                    except Exception as e:
                        print(f"[batt] {u[:8]} {e}")
                        continue
                    with LOCK:
                        d = DEVICES.get(u)
                        if d and d.get("serial") == base.get("serial"):
                            d["battery_health"] = base.get("battery_health")
                            d["cycle_count"] = base.get("cycle_count")
                            d["batt_samples"] = base.get("batt_samples", 0)
                            d["batt_settled"] = base.get("batt_settled", False)
                            d["raw_diag"] = base.get("raw_diag") or d.get("raw_diag", {})
                            d["batt_updated"] = time.time()
        except Exception as e:
            print(f"[batt] {e}")
        time.sleep(wait)

# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "iPadEtiquetas/1.0"

    def log_message(self, fmt, *args):
        pass

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            # o navegador fechou a conexao no meio — normal, ignora
            self.close_connection = True

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False,
                              default=_json_default).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            self.close_connection = True

    def _read_json(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def _static(self, path):
        if path in ("/", ""):
            path = "/index.html"
        if path.startswith("/static/"):
            path = path[len("/static/"):]
        full = os.path.normpath(os.path.join(STATIC_DIR, path.lstrip("/")))
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            self._send(404, {"erro": "nao encontrado"})
            return
        ext = os.path.splitext(full)[1].lower()
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".ico": "image/x-icon",
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
        }.get(ext, "application/octet-stream")
        with open(full, "rb") as f:
            self._send(200, f.read(), ctype)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/api/devices":
            with LOCK:
                devs = [{k: v for k, v in DEVICES[key].items() if k != "raw_diag"}
                        for key in sorted(DEVICES)]
            self._send(200, {"devices": devs, "printer": CONFIG["printer_name"],
                             "language_effective": resolve_language(),
                             "printer_status": printer_health(),
                             "label": CONFIG["label"],
                             "ui": CONFIG.get("ui", {}),
                             "last_scan": LAST_SCAN})
        elif u.path == "/api/printers":
            names = [p["name"] for p in refresh_printers()]
            self._send(200, {"printers": names,
                             "current": CONFIG.get("printer_name", ""),
                             "language_effective": resolve_language()})
        elif u.path == "/api/version":
            force = (q.get("force") or [""])[0] in ("1", "true")
            self._send(200, check_update(force=force))
        elif u.path in ("/api/label", "/api/zpl"):
            udid = (q.get("udid") or [""])[0]
            copies = int((q.get("copies") or ["1"])[0])
            with LOCK:
                rec = DEVICES.get(udid)
            if not rec:
                self._send(404, {"erro": "aparelho nao esta na lista"})
                return
            self._send(200, build_label(rec, copies), "text/plain; charset=utf-8")
        elif u.path == "/api/debug":
            udid = (q.get("udid") or [""])[0]
            with LOCK:
                rec = DEVICES.get(udid)
            self._send(200, rec or {"erro": "nao encontrado"})
        elif u.path.startswith("/api/"):
            self._send(404, {"erro": "rota desconhecida"})
        else:
            self._static(u.path)

    def do_POST(self):
        global BUSY_PRINTING
        u = urlparse(self.path)
        body = self._read_json()
        if u.path == "/api/refresh":
            with LOCK:
                for r in DEVICES.values():
                    r["updated"] = 0
                    r["status"] = "lendo"      # caixa fica vermelha durante a releitura
            self._send(200, {"ok": True})
        elif u.path == "/api/pair":
            udid = body.get("udid", "")
            ok, msg = pair_device(udid)
            with LOCK:
                if udid in DEVICES:
                    DEVICES[udid]["updated"] = 0
            self._send(200, {"ok": ok, "msg": msg})
        elif u.path == "/api/power":
            action = body.get("action", "shutdown")
            ok, msg = power_device(body.get("udid", ""), action)
            self._send(200, {"ok": ok, "msg": msg})
        elif u.path == "/api/print":
            udid = body.get("udid", "")
            copies = body.get("copies", CONFIG["label"].get("copies_default", 1))
            with LOCK:
                rec = DEVICES.get(udid)
            if not rec or not rec.get("serial"):
                self._send(400, {"ok": False, "msg": "aparelho sem nº de serie lido ainda"})
                return
            data = build_label(rec, copies)
            BUSY_PRINTING = True
            try:
                ok, msg = print_raw(data)
            except Exception as e:
                ok, msg = False, str(e)
            finally:
                BUSY_PRINTING = False
            self._send(200, {"ok": ok, "msg": msg, "label": data})
        elif u.path == "/api/print-bulk":
            copies = body.get("copies", CONFIG["label"].get("copies_default", 1))
            with LOCK:
                if body.get("all"):
                    targets = [k for k in sorted(DEVICES) if DEVICES[k].get("serial")]
                else:
                    targets = [x for x in (body.get("udids") or [])
                               if x in DEVICES and DEVICES[x].get("serial")]
                recs = [dict(DEVICES[x]) for x in targets]
            results = []
            BUSY_PRINTING = True
            try:
                for rec in recs:
                    try:
                        ok, msg = print_raw(build_label(rec, copies))
                    except Exception as e:
                        ok, msg = False, str(e)
                    results.append({"udid": rec["udid"], "ok": ok, "msg": msg})
                    time.sleep(0.4)      # respiro para o spooler / impressora
            finally:
                BUSY_PRINTING = False
            self._send(200, {"results": results})
        elif u.path == "/api/update":
            ok, msg = apply_update()
            self._send(200, {"ok": ok, "msg": msg})
        elif u.path == "/api/test-print":
            BUSY_PRINTING = True
            try:
                ok, msg = print_raw(build_test_label())
            except Exception as e:
                ok, msg = False, str(e)
            finally:
                BUSY_PRINTING = False
            self._send(200, {"ok": ok, "msg": msg})
        elif u.path == "/api/config":
            # ajustes vindos da engrenagem; grava no config.json
            lbl = CONFIG["label"]
            for key in ("offset_x", "offset_y", "gap_dots", "darkness",
                        "print_speed", "barcode_module", "language",
                        "barcode_x", "element_scale", "show_color",
                        "barcode_height", "bottom_labels", "flip_180",
                        "text_bold", "width_mm", "height_mm"):
                if key in body:
                    lbl[key] = body[key]
            # tamanho da etiqueta em mm — limites de sanidade
            for k, lo, hi in (("width_mm", 10, 200), ("height_mm", 8, 200)):
                try:
                    lbl[k] = max(lo, min(hi, float(lbl.get(k, 60 if "w" in k else 40))))
                except (TypeError, ValueError):
                    lbl[k] = 60 if "w" in k else 40
            if body.get("printer_name"):
                CONFIG["printer_name"] = str(body["printer_name"])
            if isinstance(body.get("ui"), dict):
                cur = CONFIG.setdefault("ui", {})
                for k in ("slots", "theme", "scale"):
                    if k in body["ui"]:
                        cur[k] = body["ui"][k]
                try:
                    cur["slots"] = max(2, min(24, int(cur.get("slots", 10))))
                except (TypeError, ValueError):
                    cur["slots"] = 10
            ok = save_config()
            self._send(200, {"ok": ok, "label": lbl,
                             "printer": CONFIG["printer_name"],
                             "printer_status": printer_health(),
                             "ui": CONFIG.get("ui", {}),
                             "language_effective": resolve_language()})
        else:
            self._send(404, {"erro": "rota desconhecida"})


def _setup_logging():
    """Sem console (pythonw / inicio automatico): joga tudo num arquivo."""
    if sys.stdout and sys.stdout.isatty():
        return
    logpath = os.path.join(BASE_DIR, "server.log")
    try:
        if os.path.exists(logpath) and os.path.getsize(logpath) > 1_000_000:
            os.replace(logpath, logpath + ".old")
        f = open(logpath, "a", encoding="utf-8", buffering=1)
        sys.stdout = f
        sys.stderr = f
    except Exception:
        pass


class QuietServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        et = sys.exc_info()[0]
        if et and issubclass(et, (ConnectionResetError, ConnectionAbortedError,
                                  BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def _port_alive(host, port):
    try:
        with socket.create_connection((host, port), timeout=1.2):
            return True
    except OSError:
        return False


def main():
    host = str(CONFIG.get("bind_host", "127.0.0.1"))
    port = int(CONFIG.get("http_port", 8765))
    # o watchdog (Tarefa Agendada) roda de tempos em tempos; se ja estamos no ar,
    # sai em silencio p/ nao poluir o server.log.
    if _port_alive(host, port):
        return
    _setup_logging()
    print("\n--- inicio %s ---" % time.strftime("%Y-%m-%d %H:%M:%S"))
    if not os.path.isdir(BIN_DIR):
        print(f"ERRO: pasta {BIN_DIR} nao existe (binarios libimobiledevice).")
        sys.exit(1)
    try:
        httpd = QuietServer((host, port), Handler)
    except OSError as e:
        print(f"Nao consegui abrir a porta {port} ({e}). "
              f"Provavelmente o servidor ja esta rodando. Encerrando.")
        sys.exit(0)
    try:
        ensure_printer_configured()
    except Exception as e:
        print(f"[impressoras] {e}")
    threading.Thread(target=poller, daemon=True).start()
    threading.Thread(target=battery_poller, daemon=True).start()
    print("=" * 58)
    print("  Etiqueta - NS  -  http://localhost:%d" % port)
    print("  Impressora: %s  (%s)" % (CONFIG["printer_name"], resolve_language()))
    print("=" * 58)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
