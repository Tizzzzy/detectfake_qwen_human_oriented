"""Lean session/user helpers for the text detection task.

These are minimal re-creations of the cookie + IP utilities used by the sibling
political_decision app, without the legacy survey/video machinery. Users are
anonymous and identified only by the `political_vsave` cookie.
"""

import hashlib
import random
import time

from flask import request


USER_COOKIE = 'political_vsave'


def get_user_id():
    """Return the participant id from the cookie, minting a fresh md5 hex id if absent."""
    user_id = request.cookies.get(USER_COOKIE)
    if not user_id:
        seed = f"{random.uniform(0, 1)}{time.time()}"
        user_id = hashlib.md5(seed.encode('utf-8')).hexdigest()
    return user_id


def set_user_cookie(resp, user_id):
    """Persist the participant id on the response."""
    resp.set_cookie(USER_COOKIE, user_id)
    return resp


def get_ip_details():
    """Best-effort client IP, honoring a proxy's X-Forwarded-For header."""
    forwarded = request.headers.get('X-Forwarded-For')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr
