"""
登录鉴权API
"""

from flask import request, jsonify

from . import auth_bp
from ..config import Config
from ..utils.auth import generate_auth_token, verify_auth_token


@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''

    if not username or not password:
        return jsonify({
            "success": False,
            "error": "请输入用户名和密码"
        }), 400

    if username != Config.AUTH_USERNAME or password != Config.AUTH_PASSWORD:
        return jsonify({
            "success": False,
            "error": "用户名或密码错误"
        }), 401

    token = generate_auth_token(username)
    return jsonify({
        "success": True,
        "data": {
            "token": token,
            "username": username,
            "expires_in": Config.AUTH_TOKEN_EXPIRE_SECONDS
        }
    })


@auth_bp.route('/verify', methods=['GET'])
def verify():
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return jsonify({"success": False, "error": "未提供认证令牌"}), 401

    username = verify_auth_token(auth_header[7:])
    if not username:
        return jsonify({"success": False, "error": "认证令牌无效或已过期"}), 401

    return jsonify({
        "success": True,
        "data": {
            "username": username
        }
    })
