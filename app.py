import os
import subprocess
import hashlib
import requests
from flask import Flask, render_template, jsonify, request, Response

app = Flask(__name__)

ROOT = "/data"
VT_KEYFILE = "/config/vt_api_key"
CLAMAV_DB = "/config/clamav"
AUTH_USER = os.environ.get("AUTH_USER", "admin")
AUTH_PASS = os.environ.get("AUTH_PASS", "")


def check_auth(username, password):
    return username == AUTH_USER and password == AUTH_PASS and AUTH_PASS != ""


@app.before_request
def global_auth():
    auth = request.authorization
    if not auth or not check_auth(auth.username, auth.password):
        return Response(
            "Authentication required", 401,
            {"WWW-Authenticate": 'Basic realm="FileGuard"'}
        )


def safe_path(rel_path):
    rel_path = rel_path.lstrip("/")
    full = os.path.normpath(os.path.join(ROOT, rel_path))
    if not full.startswith(ROOT):
        raise ValueError("Invalid path")
    return full


@app.route("/")
@app.route("/browse/")
@app.route("/browse/<path:rel_path>")
def browse(rel_path=""):
    full = safe_path(rel_path)
    if not os.path.isdir(full):
        return "Not a directory", 400

    entries = []
    for name in sorted(os.listdir(full)):
        entry_full = os.path.join(full, name)
        entries.append({
            "name": name,
            "is_dir": os.path.isdir(entry_full),
            "rel_path": os.path.join(rel_path, name) if rel_path else name,
        })
    entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))

    parent = os.path.dirname(rel_path) if rel_path else None

    breadcrumbs = [{"name": "FileGuard", "path": ""}]
    if rel_path:
        parts = rel_path.split("/")
        acc = []
        for part in parts:
            acc.append(part)
            breadcrumbs.append({"name": part, "path": "/".join(acc)})

    return render_template("browse.html", entries=entries, rel_path=rel_path, parent=parent, breadcrumbs=breadcrumbs)


@app.route("/api/compress")
def api_compress():
    rel_path = request.args.get("path", "")
    try:
        full = safe_path(rel_path)
    except ValueError:
        return jsonify({"ok": False, "error": "invalid path"}), 400

    if not os.path.exists(full):
        return jsonify({"ok": False, "error": "path does not exist"}), 400

    out_path = full.rstrip("/") + ".zip"
    if os.path.exists(out_path):
        return jsonify({"ok": False, "error": f"a .zip with that name already exists"}), 400

    parent_dir = os.path.dirname(full)
    target_name = os.path.basename(full.rstrip("/"))

    try:
        result = subprocess.run(
            ["zip", "-r", out_path, target_name],
            cwd=parent_dir, capture_output=True, text=True, timeout=1800
        )
        if result.returncode != 0 or not os.path.exists(out_path):
            return jsonify({"ok": False, "error": (result.stderr or result.stdout)[-2000:]}), 500
        out_rel = os.path.relpath(out_path, ROOT)
        return jsonify({"ok": True, "output_path": out_rel})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "compression timed out after 30 minutes"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/extract")
def api_extract():
    rel_path = request.args.get("path", "")
    try:
        full = safe_path(rel_path)
    except ValueError:
        return jsonify({"ok": False, "error": "invalid path"}), 400

    if not os.path.isfile(full):
        return jsonify({"ok": False, "error": "not a file"}), 400

    lower = full.lower()
    if lower.endswith(".tar.gz") or lower.endswith(".tgz"):
        base = full[:-7] if lower.endswith(".tar.gz") else full[:-4]
        cmd = ["tar", "-xzf", full, "-C"]
    elif lower.endswith(".tar"):
        base = full[:-4]
        cmd = ["tar", "-xf", full, "-C"]
    elif lower.endswith(".zip"):
        base, _ = os.path.splitext(full)
        cmd = ["unzip", "-o", full, "-d"]
    elif lower.endswith(".7z"):
        base, _ = os.path.splitext(full)
        cmd = ["7z", "x", full, "-y", "-o"]
    elif lower.endswith(".rar"):
        base, _ = os.path.splitext(full)
        cmd = ["unrar", "x", "-o+", full]
    else:
        return jsonify({"ok": False, "error": "unsupported archive type (.zip, .tar, .tar.gz, .tgz, .7z, .rar only)"}), 400

    out_dir = base
    if os.path.exists(out_dir):
        return jsonify({"ok": False, "error": f"folder already exists: {os.path.basename(out_dir)}"}), 400
    os.makedirs(out_dir, exist_ok=True)

    try:
        if cmd[0] == "7z":
            cmd[-1] = cmd[-1] + out_dir
        else:
            cmd.append(out_dir)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if result.returncode != 0:
            return jsonify({"ok": False, "error": (result.stderr or result.stdout)[-2000:]}), 500
        out_rel = os.path.relpath(out_dir, ROOT)
        return jsonify({"ok": True, "output_path": out_rel})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "extraction timed out after 30 minutes"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/convert")
def api_convert():
    rel_path = request.args.get("path", "")
    try:
        full = safe_path(rel_path)
    except ValueError:
        return jsonify({"ok": False, "error": "invalid path"}), 400

    if not os.path.isfile(full):
        return jsonify({"ok": False, "error": "not a file"}), 400

    base, _ = os.path.splitext(full)
    out_path = base + ".mp4"
    if os.path.exists(out_path):
        return jsonify({"ok": False, "error": "a .mp4 with that name already exists"}), 400

    try:
        result = subprocess.run(
            ["ffmpeg", "-i", full, "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "23", "-c:a", "aac", "-b:a", "192k", out_path],
            capture_output=True, text=True, timeout=3600
        )
        if result.returncode != 0 or not os.path.exists(out_path):
            return jsonify({"ok": False, "error": result.stderr[-2000:]}), 500
        out_rel = os.path.relpath(out_path, ROOT)
        return jsonify({"ok": True, "output_path": out_rel})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "conversion timed out after 1 hour"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/clamscan")
def api_clamscan():
    rel_path = request.args.get("path", "")
    try:
        full = safe_path(rel_path)
    except ValueError:
        return jsonify({"ok": False, "error": "invalid path"}), 400

    if not os.path.isfile(full):
        return jsonify({"ok": False, "error": "not a file"}), 400

    try:
        result = subprocess.run(
            ["clamscan", "--database=" + CLAMAV_DB, full],
            capture_output=True, text=True, timeout=300
        )
        return jsonify({"ok": True, "output": result.stdout + result.stderr, "returncode": result.returncode})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/vtcheck")
def api_vtcheck():
    rel_path = request.args.get("path", "")
    try:
        full = safe_path(rel_path)
    except ValueError:
        return jsonify({"ok": False, "error": "invalid path"}), 400

    if not os.path.isfile(full):
        return jsonify({"ok": False, "error": "not a file"}), 400

    if not os.path.exists(VT_KEYFILE):
        return jsonify({"ok": False, "error": "No VirusTotal API key set at " + VT_KEYFILE}), 400

    with open(VT_KEYFILE) as f:
        api_key = f.read().strip()

    sha256 = hashlib.sha256()
    with open(full, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    file_hash = sha256.hexdigest()

    r = requests.get(
        f"https://www.virustotal.com/api/v3/files/{file_hash}",
        headers={"x-apikey": api_key},
        timeout=20,
    )

    if r.status_code == 404:
        return jsonify({
            "ok": True,
            "found": False,
            "hash": file_hash,
            "report_url": f"https://www.virustotal.com/gui/file/{file_hash}",
        })

    data = r.json()
    if "error" in data:
        return jsonify({"ok": False, "error": data["error"].get("message", "VT API error")}), 500

    stats = data["data"]["attributes"]["last_analysis_stats"]
    return jsonify({
        "ok": True,
        "found": True,
        "hash": file_hash,
        "malicious": stats.get("malicious", 0),
        "suspicious": stats.get("suspicious", 0),
        "harmless": stats.get("harmless", 0),
        "undetected": stats.get("undetected", 0),
        "report_url": f"https://www.virustotal.com/gui/file/{file_hash}",
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5060)
