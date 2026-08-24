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
import asyncio
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
try:
    # cryptography >= 43: TripleDES 移至 decrepit
    from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
except ImportError:
    from cryptography.hazmat.primitives.ciphers.algorithms import TripleDES
from cryptography.hazmat.primitives.ciphers.base import Cipher
from cryptography.hazmat.primitives.ciphers.modes import CBC, ECB

# AstrBot 官方日志接口（后台可见），降级使用标准 logging
try:
    from astrbot.api import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

from .timeutil import beijing_now

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

# DES 加密规则（逐项对齐原版 FancyCabbage/skyland-auto-sign 的 SecuritySm.py）
DES_RULE = {
    "appId":       {"cipher": "DES", "is_encrypt": 1, "key": "uy7mzc4h", "obfuscated_name": "xx"},
    "box":         {"is_encrypt": 0, "obfuscated_name": "jf"},
    "canvas":      {"cipher": "DES", "is_encrypt": 1, "key": "snrn887t", "obfuscated_name": "yk"},
    "clientSize":  {"cipher": "DES", "is_encrypt": 1, "key": "cpmjjgsu", "obfuscated_name": "zx"},
    "organization":{"cipher": "DES", "is_encrypt": 1, "key": "78moqjfc", "obfuscated_name": "dp"},
    "os":          {"cipher": "DES", "is_encrypt": 1, "key": "je6vk6t4", "obfuscated_name": "pj"},
    "platform":    {"cipher": "DES", "is_encrypt": 1, "key": "pakxhcd2", "obfuscated_name": "gm"},
    "plugins":     {"cipher": "DES", "is_encrypt": 1, "key": "v51m3pzl", "obfuscated_name": "kq"},
    "pmf":         {"cipher": "DES", "is_encrypt": 1, "key": "2mdeslu3", "obfuscated_name": "vw"},
    "protocol":    {"is_encrypt": 0, "obfuscated_name": "protocol"},
    "referer":     {"cipher": "DES", "is_encrypt": 1, "key": "y7bmrjlc", "obfuscated_name": "ab"},
    "res":         {"cipher": "DES", "is_encrypt": 1, "key": "whxqm2a7", "obfuscated_name": "hf"},
    "rtype":       {"cipher": "DES", "is_encrypt": 1, "key": "x8o2h2bl", "obfuscated_name": "lo"},
    "sdkver":      {"cipher": "DES", "is_encrypt": 1, "key": "9q3dcxp2", "obfuscated_name": "sc"},
    "status":      {"cipher": "DES", "is_encrypt": 1, "key": "2jbrxxw4", "obfuscated_name": "an"},
    "subVersion":  {"cipher": "DES", "is_encrypt": 1, "key": "eo3i2puh", "obfuscated_name": "ns"},
    "svm":         {"cipher": "DES", "is_encrypt": 1, "key": "fzj3kaeh", "obfuscated_name": "qr"},
    "time":        {"cipher": "DES", "is_encrypt": 1, "key": "q2t3odsk", "obfuscated_name": "nb"},
    "timezone":    {"cipher": "DES", "is_encrypt": 1, "key": "1uv05lj5", "obfuscated_name": "as"},
    "tn":          {"cipher": "DES", "is_encrypt": 1, "key": "x9nzj1bp", "obfuscated_name": "py"},
    "trees":       {"cipher": "DES", "is_encrypt": 1, "key": "acfs0xo4", "obfuscated_name": "pi"},
    "ua":          {"cipher": "DES", "is_encrypt": 1, "key": "k92crp1t", "obfuscated_name": "bj"},
    "url":         {"cipher": "DES", "is_encrypt": 1, "key": "y95hjkoo", "obfuscated_name": "cf"},
    "version":     {"is_encrypt": 0, "obfuscated_name": "version"},
    "vpw":         {"cipher": "DES", "is_encrypt": 1, "key": "r9924ab5", "obfuscated_name": "ca"},
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
    """设置 dId 持久化缓存目录（在插件初始化时调用）

    缓存文件名带 .json 后缀（v2 格式），旧版纯文本 did.cache 会被自动作废，
    避免历史 fallback 假 dId 被永久复用导致「设备信息无效」。
    """
    global _DID_CACHE_DIR, _DID_CACHE_FILE
    _DID_CACHE_DIR = cache_dir
    try:
        os.makedirs(cache_dir, exist_ok=True)
        _DID_CACHE_FILE = os.path.join(cache_dir, "did.cache.json")
        # 清理旧版假 dId 缓存（纯文本 did.cache）
        legacy = os.path.join(cache_dir, "did.cache")
        if os.path.exists(legacy):
            try:
                os.remove(legacy)
                logger.info("已清理旧版 did.cache（可能存在 fallback 假 dId）")
            except OSError as e:
                logger.warning(f"清理旧版 did.cache 失败: {e}")
    except Exception as e:
        logger.warning(f"创建 dId 缓存目录失败: {e}")


def _load_cached_did() -> str:
    """从磁盘加载缓存的 dId（仅接受数美 API 来源，杜绝假 dId 复用）"""
    if _DID_CACHE_FILE and os.path.exists(_DID_CACHE_FILE):
        try:
            with open(_DID_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            did = data.get("did", "")
            if did and did.startswith("B") and data.get("source") == "shumei":
                return did
            # 旧格式/假 dId → 作废并删除
            logger.warning("检测到无效的 dId 缓存，已作废并触发重新获取")
            os.remove(_DID_CACHE_FILE)
        except (ValueError, OSError) as e:
            logger.warning(f"读取 dId 缓存失败: {e}")
    return ""


def get_did_meta() -> tuple[str, str]:
    """返回 (dId, 来源)，供 /skland did 展示用

    来源: shumei（数美 API，有效）| fallback（降级假指纹，无效）
    """
    if _DID_CACHE_FILE and os.path.exists(_DID_CACHE_FILE):
        try:
            with open(_DID_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            did = data.get("did", "")
            if did and did.startswith("B") and data.get("source") == "shumei":
                return did, "shumei"
        except (ValueError, OSError):
            pass
    if _DID_CACHE_DIR:
        legacy = os.path.join(_DID_CACHE_DIR, "did.cache")
        if os.path.exists(legacy):
            try:
                with open(legacy, "r", encoding="utf-8") as f:
                    did = f.read().strip()
                if did.startswith("B"):
                    return did, "legacy"
            except OSError:
                pass
    return "", ""


def _save_did_cache(did: str):
    """将数美 API 返回的真 dId 保存到磁盘（仅 shumei 来源会被持久化）"""
    if _DID_CACHE_FILE and did:
        try:
            with open(_DID_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "did": did,
                    "source": "shumei",
                    "cached_at": beijing_now().isoformat(),
                }, f, ensure_ascii=False)
            logger.info(f"dId 已缓存到磁盘: {did[:20]}...")
        except Exception as e:
            logger.warning(f"保存 dId 缓存失败: {e}")


def _generate_fallback_did() -> str:
    """生成 fallback dId（数美 API 不可用时使用，不持久化）"""
    fallback = 'B' + hashlib.md5(str(uuid.uuid4()).encode()).hexdigest()
    logger.warning("数美API不可用，使用临时 fallback dId（不落盘，请求可能被拒）")
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

async def _read_json(resp: aiohttp.ClientResponse) -> dict:
    """读取响应 JSON

    数美 API 返回 Content-Type: text/plain（body 实为 JSON），
    aiohttp 的 resp.json() 会因 mimetype 校验拒绝，故手动 text() + json.loads。
    """
    text = await resp.text()
    if not text.strip():
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning(f"数美API响应非 JSON 文本: {text[:200]}")
        return {}


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
                    data = await _read_json(resp)
                    if data.get('code') == 1100:
                        did = 'B' + data['detail']['deviceId']
                        _save_did_cache(did)
                        logger.info(f"dId 获取成功: {did[:20]}...")
                        return did
                    logger.warning(
                        f"数美API返回异常: code={data.get('code')} "
                        f"msg={data.get('message', data.get('msg', ''))} "
                        f"(attempt {attempt + 1}/2)"
                    )

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.warning(f"数美API请求失败 (attempt {attempt + 1}/2): {e}")
            except Exception as e:
                logger.warning(f"数美API解析失败 (attempt {attempt + 1}/2): {e}")

            if attempt < 1:
                await asyncio.sleep(1)
    finally:
        if close_session:
            await session.close()

    # 3. Fallback（不持久化：假 dId 落盘会被永久复用，宁可每次临时生成）
    fallback = _generate_fallback_did()
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
    return fallback
