# api/index.py  —  Vercel-ready Flask app
from flask import Flask, request, jsonify
import jwt
import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import RemoveFriend_Req_pb2
from byte import Encrypt_ID, encrypt_api
import binascii
import data_pb2
import uid_generator_pb2
from datetime import datetime
import time
import urllib3
import warnings

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", category=UserWarning)

app = Flask(__name__)

# -----------------------------
# AES
# -----------------------------
AES_KEY = bytes([89, 103, 38, 116, 99, 37, 68, 69, 117, 104, 54, 37, 90, 99, 94, 56])
AES_IV  = bytes([54, 111, 121, 90, 68, 114, 50, 50, 69, 51, 121, 99, 104, 106, 77, 37])

def encrypt_message(data_bytes):
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    return cipher.encrypt(pad(data_bytes, AES.block_size))

def encrypt_message_hex(data_bytes):
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    return binascii.hexlify(cipher.encrypt(pad(data_bytes, AES.block_size))).decode()

# -----------------------------
# Server URL
# -----------------------------
def get_base_url(server_name):
    server_name = (server_name or "IND").upper()
    if server_name == "IND":
        return "https://client.ind.freefiremobile.com/"
    if server_name in {"BR", "US", "SAC", "NA"}:
        return "https://client.us.freefiremobile.com/"
    return "https://clientbp.ppmainecoonghj.com/"

def get_server_from_token(token):
    try:
        d = jwt.decode(token, options={"verify_signature": False})
        return (d.get("lock_region") or "IND").upper()
    except Exception:
        return "IND"

# -----------------------------
# Token API
# -----------------------------
TOKEN_API = "https://jwt-zihuuuu.onrender.com/token"

def get_token_from_uid_password(uid, password):
    try:
        r = requests.get(f"{TOKEN_API}?uid={uid}&password={password}", timeout=15)
        r.raise_for_status()
        data = r.json()
        item = data[0] if isinstance(data, list) and data else data
        if item.get("status") != "success" or "token" not in item:
            return None, f"Token API error: {item}"
        return item["token"], None
    except Exception as e:
        return None, f"Token API failed: {e}"

def decode_author_uid(token):
    try:
        d = jwt.decode(token, options={"verify_signature": False})
        return d.get("account_id") or d.get("sub")
    except Exception:
        return None

# -----------------------------
# Player info
# -----------------------------
def create_info_protobuf(uid):
    m = uid_generator_pb2.uid_generator()
    m.saturn_ = int(uid)
    m.garena = 1
    return m.SerializeToString()

def get_player_info(target_uid, token, server_name=None):
    try:
        if not server_name:
            server_name = get_server_from_token(token)
        enc = encrypt_message_hex(create_info_protobuf(target_uid))
        url = get_base_url(server_name) + "GetPlayerPersonalShow"
        headers = {
            'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
            'Connection': "Keep-Alive",
            'Accept-Encoding': "gzip",
            'Authorization': f"Bearer {token}",
            'Content-Type': "application/x-www-form-urlencoded",
            'Expect': "100-continue",
            'X-Unity-Version': "2018.4.11f1",
            'X-GA': "v1 1",
            'ReleaseVersion': "OB55"
        }
        r = requests.post(url, data=bytes.fromhex(enc), headers=headers, timeout=10, verify=False)
        if r.status_code != 200:
            return None
        info = data_pb2.AccountPersonalShowInfo()
        info.ParseFromString(r.content)
        return info
    except Exception as e:
        return None

def extract_player_info(info):
    if not info:
        return None
    b = info.basic_info
    return {
        'uid': b.account_id, 'nickname': b.nickname, 'level': b.level,
        'region': b.region, 'likes': b.liked,
        'release_version': b.release_version
    }

# -----------------------------
# Retry (Vercel timeout के लिए कम किया)
# -----------------------------
def retry_operation(max_retries=2, delay=1):
    def deco(func):
        def wrapper(*a, **kw):
            last = None
            for i in range(max_retries):
                try:
                    r = func(*a, **kw)
                    if r and r.get('status') == 'success':
                        return r
                except Exception as e:
                    last = e
                if i < max_retries - 1:
                    time.sleep(delay)
            return {"status": "error",
                    "message": f"All {max_retries} attempts failed",
                    "error": str(last) if last else None}
        return wrapper
    return deco

# -----------------------------
# Remove Friend
# -----------------------------
@retry_operation(max_retries=2, delay=1)
def remove_friend(author_uid, target_uid, token, server_name=None):
    if not server_name:
        server_name = get_server_from_token(token)
    player_info = get_player_info(target_uid, token, server_name)

    msg = RemoveFriend_Req_pb2.RemoveFriend()
    msg.AuthorUid = int(author_uid)
    msg.TargetUid = int(target_uid)
    enc = encrypt_message(msg.SerializeToString())

    url = get_base_url(server_name) + "RemoveFriend"
    headers = {
        'Authorization': f"Bearer {token}",
        'User-Agent': "Dalvik/2.1.0 (Linux; Android 9)",
        'Content-Type': "application/x-www-form-urlencoded",
        'X-Unity-Version': "2018.4.11f1",
        'X-GA': "v1 1",
        'ReleaseVersion': "OB55"
    }
    res = requests.post(url, data=enc, headers=headers, timeout=10, verify=False)
    if res.status_code != 200:
        raise Exception(f"HTTP {res.status_code}")

    pd = extract_player_info(player_info) if player_info else None
    return {
        "author_uid": author_uid,
        "nickname": pd['nickname'] if pd else "Unknown",
        "uid": target_uid,
        "level": pd['level'] if pd else 0,
        "likes": pd['likes'] if pd else 0,
        "region": pd['region'] if pd else "Unknown",
        "release_version": pd['release_version'] if pd else "Unknown",
        "status": "success",
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

# -----------------------------
# Add Friend
# -----------------------------
@retry_operation(max_retries=2, delay=1)
def add_friend(author_uid, target_uid, token, server_name=None):
    if not server_name:
        server_name = get_server_from_token(token)
    player_info = get_player_info(target_uid, token, server_name)

    encrypted_id = Encrypt_ID(target_uid)
    payload = f"08a7c4839f1e10{encrypted_id}1801"
    enc = encrypt_api(payload)

    url = get_base_url(server_name) + "RequestAddingFriend"
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Unity-Version": "2018.4.11f1",
        "X-GA": "v1 1",
        "ReleaseVersion": "OB55",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Dalvik/2.1.0 (Linux; Android 9)"
    }
    r = requests.post(url, headers=headers, data=bytes.fromhex(enc), timeout=10, verify=False)
    if r.status_code != 200:
        raise Exception(f"HTTP {r.status_code}")

    pd = extract_player_info(player_info) if player_info else None
    return {
        "author_uid": author_uid,
        "nickname": pd['nickname'] if pd else "Unknown",
        "uid": target_uid,
        "level": pd['level'] if pd else 0,
        "likes": pd['likes'] if pd else 0,
        "region": pd['region'] if pd else "Unknown",
        "release_version": pd['release_version'] if pd else "Unknown",
        "status": "success",
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

# -----------------------------
# Resolve token
# -----------------------------
def _resolve_token(args):
    token = args.get('token')
    uid = args.get('uid')
    password = args.get('password')

    if token:
        au = decode_author_uid(token)
        if not au:
            return None, None, "Invalid token"
        return token, au, None

    if uid and password:
        token, err = get_token_from_uid_password(uid, password)
        if err:
            return None, None, err
        au = decode_author_uid(token)
        if not au:
            return None, None, "Generated token invalid"
        return token, au, None

    return None, None, "Provide 'token' OR 'uid'+'password'"

# -----------------------------
# Routes
# -----------------------------
@app.route('/')
def home():
    return jsonify({
        "status": "running",
        "endpoints": [
            "/health",
            "/token?uid=X&password=Y",
            "/get_player_info?player_id=X&token=Y",
            "/add_friend?player_id=X&uid=Y&password=Z",
            "/remove_friend?player_id=X&token=Y"
        ]
    }), 200

@app.route('/health')
def health():
    return jsonify({"status": "healthy"}), 200

@app.route('/add_friend', methods=['GET'])
def api_add():
    pid = request.args.get('player_id')
    if not pid:
        return jsonify({"status": "failed", "message": "Missing player_id"}), 400
    token, au, err = _resolve_token(request.args)
    if err:
        return jsonify({"status": "failed", "message": err}), 400
    return jsonify(add_friend(au, pid, token, request.args.get('server_name')))

@app.route('/remove_friend', methods=['GET'])
def api_remove():
    pid = request.args.get('player_id')
    if not pid:
        return jsonify({"status": "failed", "message": "Missing player_id"}), 400
    token, au, err = _resolve_token(request.args)
    if err:
        return jsonify({"status": "failed", "message": err}), 400
    return jsonify(remove_friend(au, pid, token, request.args.get('server_name')))

@app.route('/get_player_info', methods=['GET'])
def api_info():
    pid = request.args.get('player_id')
    if not pid:
        return jsonify({"status": "failed", "message": "Missing player_id"}), 400
    token, _, err = _resolve_token(request.args)
    if err:
        return jsonify({"status": "failed", "message": err}), 400
    info = get_player_info(pid, token, request.args.get('server_name'))
    if not info:
        return jsonify({"status": "failed", "message": "Info fetch failed"}), 400
    pd = extract_player_info(info)
    if not pd:
        return jsonify({"status": "failed", "message": "Extract failed"}), 400
    pd.update({"status": "success",
               "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    return jsonify(pd)

@app.route('/token', methods=['GET'])
def api_token():
    uid = request.args.get('uid')
    pw = request.args.get('password')
    if not uid or not pw:
        return jsonify({"status": "failed", "message": "Missing uid/password"}), 400
    token, err = get_token_from_uid_password(uid, pw)
    if err:
        return jsonify({"status": "failed", "message": err}), 400
    return jsonify({"status": "success", "token": token,
                    "author_uid": decode_author_uid(token)})

# -----------------------------
# Vercel एंट्री
# -----------------------------
# ध्यान दें: Vercel पर `if __name__ == '__main__'` नहीं चलता,
# इसलिए यहाँ सिर्फ `app` वेरिएबल एक्सपोर्ट किया गया है।
# लोकल टेस्ट के लिए नीचे वाली लाइन uncomment कर सकते हैं:
# if __name__ == '__main__':
#     app.run(host='0.0.0.0', port=5001, debug=False)
