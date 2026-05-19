"""
数美设备指纹 (dId) 生成模块
移植自: https://gitee.com/FancyCabbage/skyland-auto-sign
Copyright (c) 2023 xxyz30, MIT License

改进点 (v2.0):
- 完全异步化，移除 requests 同步调用，使用 aiohttp
- 连接超时与重试机制
- 持久化缓存，支持强制刷新
- 更好的错误降级策略
"""
import base64
import gzip
import hashlib
import json
import os
import time
import uuid
from typing import Optional

import aiohttp

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.algorithms import AES
from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
from cryptography.hazmat.primitives.ciphers.base import Cipher
from cryptography.hazmat.primitives.ciphers.modes import CBC, ECB

# AstrBot 官方日志接口（后台可见），降级使用标准 logging
try:
    from astrbot.api import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

# ==================== 常量 ====================

DEVICES_INFO_URL = "https://fp-it.portal101.cn/deviceprofile/v4"

SM_CONFIG = {
    "organization": "UWXspnCCJN4sfYlNfqps",
    "appId": "default",
    "publicKey": (
        "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCmxMNr7n8ZeT0tE1R9j/mPixoinPkeM+"
        "k4VGIn/s0k7N5rJAfnZ0eMER+QhwFvshzo0LNmeUkpR8uIlU/GEVr8mN28sKmwd2gpygqj"
        "0ePnBmOW4v0ZVwbSYK+izkhVFk2V/doLoMbWy6b+UnA8mkjvg0iYWRByfRsK2gdl7llqCwIDAQAB"
    ),
    "protocol": "https",
    "apiHost": "fp-it.portal101.cn"
}

DES_RULE = {
    "appId":       {"cipher": "DES", "is_encrypt": 1, "key": "uy7mzc4h", "obfuscated_name": "xx"},
    "box":         {"is_encrypt": 0, "obfuscated_name": "jf"},
    "canvas":      {"cipher": "DES", "is_encrypt": 1, "key": "snrn887t", "obfuscated_name": "yk"},
    "clientSize":  {"cipher": "DES", "is_encrypt": 1, "key": "cpmjjgsu", "obfuscated_name": "zx"},
    "organization":{"cipher": "DES", "is_encrypt": 1, "key": "78moqjfc", "obfuscated_name": "dp"},
    "os":          {"cipher": "DES", "is_encrypt": 1, "key": "je6vk6t4", "obfuscated_name": "pj"},
    "platform":    {"cipher": "DES", "is_encrypt": 1, "key": "pakxhcd2", "obfuscated_name": "gm"},
    "plugins":     {"cipher": "DES", "is_encrypt": 1, "key": "ioy1geet", "obfuscated_name": "sc"},
    "protocol":    {"cipher": "DES", "is_encrypt": 1, "key": "yaod0lwh", "obfuscated_name": "xt"},
    "referer":     {"cipher": "DES", "is_encrypt": 1, "key": "5cf8lp6y", "obfuscated_name": "mi"},
    "res":         {"cipher": "DES", "is_encrypt": 1, "key": "byu3333s", "obfuscated_name": "pl"},
    "status":      {"cipher": "DES", "is_encrypt": 1, "key": "6wyrmze2", "obfuscated_name": "xc"},
    "svm":         {"cipher": "DES", "is_encrypt": 1, "key": "auty7gm1", "obfuscated_name": "gg"},
    "timezone":    {"cipher": "DES", "is_encrypt": 1, "key": "c1sru5pd", "obfuscated_name": "lc"},
    "trees":       {"cipher": "DES", "is_encrypt": 1, "key": "acfs0xo4", "obfuscated_name": "pi"},
    "ua":          {"cipher": "DES", "is_encrypt": 1, "key": "k92crp1t", "obfuscated_name": "bj"},
    "url":         {"cipher": "DES", "is_encrypt": 1, "key": "y95hjkoo", "obfuscated_name": "cf"},
    "version":     {"is_encrypt": 0, "obfuscated_name": "version"},
    "vpw":         {"cipher": "DES", "is_encrypt": 1, "key": "r9924ab5", "obfuscated_name": "ca"},
    "pmf":         {"cipher": "DES", "is_encrypt": 1, "key": "x9nzj1bp", "obfuscated_name": "py"},
}

BROWSER_ENV = {
    'plugins': (
        'MicrosoftEdgePDFPluginPortableDocumentFormatinternal-pdf-viewer1,'
        'MicrosoftEdgePDFViewermhjfbmdgcfjbbpaeojofohoefgiehjai1'
    ),
    'ua': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0'
    ),
    'canvas': '259ffe69',
    'timezone': -480,
    'platform': 'Win32',
    'url': 'https://www.skland.com/',
    'referer': '',
    'res': '1920_1080_24_1.25',
    'clientSize': '0_0_1080_1920_1920_1080_1920_1080',
    'status': '0011',
}

# ==================== 全局状态 ====================

_PK = serialization.load_der_public_key(base64.b64decode(SM_CONFIG['publicKey']))

_DID_CACHE_DIR: Optional[str] = None
_DID_CACHE_FILE: Optional[str] = None


def set_cache_dir(cache_dir: str):
    """设置 dId 持久化缓存目录（在插件初始化时调用）"""
    global _DID_CACHE_DIR, _DID_CACHE_FILE
    _DID_CACHE_DIR = cache_dir
    try:
        os.makedirs(cache_dir, exist_ok=True)
        _DID_CACHE_FILE = os.path.join(cache_dir, "did.cache")
    except Exception as e:
        logger.warning(f"创建 dId 缓存目录失败: {e}")


def _load_cached_did() -> str:
    """从磁盘加载缓存的 dId"""
    if _DID_CACHE_FILE and os.path.exists(_DID_CACHE_FILE):
        try:
            with open(_DID_CACHE_FILE, "r") as f:
                did = f.read().strip()
                if did and did.startswith("B"):
                    return did
        except Exception as e:
            logger.warning(f"读取 dId 缓存失败: {e}")
    return ""


def _save_did_cache(did: str):
    """将 dId 保存到磁盘缓存"""
    if _DID_CACHE_FILE and did:
        try:
            with open(_DID_CACHE_FILE, "w") as f:
                f.write(did)
            logger.info(f"dId 已缓存到磁盘: {did[:20]}...")
        except Exception as e:
            logger.warning(f"保存 dId 缓存失败: {e}")


def _generate_fallback_did() -> str:
    """生成 fallback dId（数美 API 不可用时使用）"""
    fallback = 'B' + hashlib.md5(str(uuid.uuid4()).encode()).hexdigest()
    logger.warning("数美API不可用，使用 fallback dId")
    return fallback


# ==================== 加密算法（保持不变） ====================

def _get_smid() -> str:
    """生成 SMID"""
    t = time.localtime()
    _time = '{}{:0>2d}{:0>2d}{:0>2d}{:0>2d}{:0>2d}'.format(
        t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec
    )
    uid = str(uuid.uuid4())
    v = _time + hashlib.md5(uid.encode('utf-8')).hexdigest() + '00'
    smsk_web = hashlib.md5(('smsk_web_' + v).encode('utf-8')).hexdigest()[0:14]
    return v + smsk_web + '0'


def _des_encrypt(o: dict) -> dict:
    """DES 加密规则"""
    result = {}
    for key in o:
        if key in DES_RULE:
            rule = DES_RULE[key]
            res = o[key]
            if rule['is_encrypt'] == 1:
                c = Cipher(TripleDES(rule['key'].encode('utf-8')), ECB())
                data = str(res).encode('utf-8')
                data += b'\x00' * 8
                res = base64.b64encode(c.encryptor().update(data)).decode('utf-8')
            result[rule['obfuscated_name']] = res
        else:
            result[key] = o[key]
    return result


def _aes_encrypt(v: bytes, k: bytes) -> str:
    """AES 加密"""
    iv = '0102030405060708'
    key = AES(k)
    c = Cipher(key, CBC(iv.encode('utf-8')))
    v += b'\x00'
    while len(v) % 16 != 0:
        v += b'\x00'
    return c.encryptor().update(v).hex()


def _gzip_compress(o: dict) -> bytes:
    """GZIP 压缩"""
    json_str = json.dumps(o, ensure_ascii=False)
    stream = gzip.compress(json_str.encode('utf-8'), 2, mtime=0)
    return base64.b64encode(stream)


def _compute_tn(o: dict) -> str:
    """计算 tn 值"""
    sorted_keys = sorted(o.keys())
    result_list = []
    for key in sorted_keys:
        v = o[key]
        if isinstance(v, (int, float)):
            v = str(v * 10000)
        elif isinstance(v, dict):
            v = _compute_tn(v)
        result_list.append(v)
    return ''.join(result_list)


def _build_shumei_payload() -> dict:
    """构建数美 API 请求体"""
    uid = str(uuid.uuid4()).encode('utf-8')
    pri_id = hashlib.md5(uid).hexdigest()[0:16]
    ep = _PK.encrypt(uid, padding.PKCS1v15())
    ep = base64.b64encode(ep).decode('utf-8')

    browser = BROWSER_ENV.copy()
    current_time = int(time.time() * 1000)
    browser.update({
        'vpw': str(uuid.uuid4()),
        'svm': current_time,
        'trees': str(uuid.uuid4()),
        'pmf': current_time,
    })

    des_target = {
        **browser,
        'protocol': 102,
        'organization': SM_CONFIG['organization'],
        'appId': SM_CONFIG['appId'],
        'os': 'web',
        'version': '3.0.0',
        'sdkver': '3.0.0',
        'box': '',
        'rtype': 'all',
        'smid': _get_smid(),
        'subVersion': '1.0.0',
        'time': 0,
    }
    des_target['tn'] = hashlib.md5(_compute_tn(des_target).encode()).hexdigest()

    des_result = _aes_encrypt(_gzip_compress(_des_encrypt(des_target)), pri_id.encode('utf-8'))

    return {
        'appId': 'default',
        'compress': 2,
        'data': des_result,
        'encode': 5,
        'ep': ep,
        'organization': SM_CONFIG['organization'],
        'os': 'web',
    }


# ==================== 异步 dId 获取 ====================

async def fetch_did(session: Optional[aiohttp.ClientSession] = None) -> str:
    """异步获取设备指纹 dId

    优先级：
    1. 磁盘缓存（快速复用）
    2. 数美 API（实时获取）
    3. Fallback 生成（降级兜底）

    Args:
        session: 可复用的 aiohttp 会话，不传则内部创建

    Returns:
        dId 字符串（以 B 开头）
    """
    # 1. 检查缓存
    cached = _load_cached_did()
    if cached:
        return cached

    # 2. 尝试数美 API
    payload = _build_shumei_payload()
    close_session = False
    if session is None:
        session = aiohttp.ClientSession()
        close_session = True

    try:
        for attempt in range(2):
            try:
                async with session.post(
                    DEVICES_INFO_URL,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json()
                    if data.get('code') == 1100:
                        did = 'B' + data['detail']['deviceId']
                        _save_did_cache(did)
                        logger.info(f"dId 获取成功: {did[:20]}...")
                        return did
                    logger.warning(f"数美API返回异常: code={data.get('code')}")

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.warning(f"数美API请求失败 (attempt {attempt + 1}/2): {e}")
            except Exception as e:
                logger.warning(f"数美API解析失败 (attempt {attempt + 1}/2): {e}")

            if attempt < 1:
                await asyncio.sleep(1)
    finally:
        if close_session:
            await session.close()

    # 3. Fallback
    fallback = _generate_fallback_did()
    _save_did_cache(fallback)
    logger.warning("使用 fallback dId，森空岛API可能拒绝请求")
    return fallback


# ==================== 同步兼容接口 ====================

import asyncio as _asyncio

def get_d_id() -> str:
    """同步获取 dId（兼容旧接口，内部使用缓存优先策略）

    注意：首次调用时如果缓存不存在，会尝试同步请求数美 API。
    为避免阻塞，建议在插件 initialize() 中调用 fetch_did() 预加载。
    """
    # 优先返回缓存
    cached = _load_cached_did()
    if cached:
        return cached

    # 兼容：如果没有缓存且不在事件循环中，同步生成 fallback
    try:
        loop = _asyncio.get_running_loop()
        # 在事件循环中，不要同步阻塞
        logger.warning("dId 未缓存且在事件循环中调用同步接口，返回临时 fallback")
        return _generate_fallback_did()
    except RuntimeError:
        pass

    # 不在事件循环中，可安全执行同步请求（不推荐）
    try:
        import requests as _requests
        payload = _build_shumei_payload()
        resp = _requests.post(DEVICES_INFO_URL, json=payload, timeout=10)
        data = resp.json()
        if data.get('code') == 1100:
            did = 'B' + data['detail']['deviceId']
            _save_did_cache(did)
            return did
    except Exception as e:
        logger.warning(f"同步获取 dId 失败: {e}")

    fallback = _generate_fallback_did()
    _save_did_cache(fallback)
    return fallback
