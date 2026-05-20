"""
森空岛 API 客户端层
移植自: https://gitee.com/FancyCabbage/skyland-auto-sign
Copyright (c) 2023 xxyz30, MIT License

改进点 (v2.0):
- 统一的连接池管理（复用 aiohttp.ClientSession）
- 内建重试机制（指数退避）
- 签名算法完全对齐原始项目
- 凭证生命周期管理（token → grant_code → cred，含自动刷新）
- 详细的请求/响应日志（可配置级别）
"""
import asyncio
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib import parse

import aiohttp

from .security import get_d_id

try:
    from astrbot.api import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

# ==================== 常量 ====================

APP_CODE = '4ca99fa6b56cc2ba'

# API 端点
API_BASE = 'https://zonai.skland.com'
AUTH_BASE = 'https://as.hypergryph.com'

GRANT_CODE_URL = f'{AUTH_BASE}/user/oauth2/v2/grant'
CRED_CODE_URL = f'{API_BASE}/web/v1/user/auth/generate_cred_by_code'
REFRESH_TOKEN_URL = f'{API_BASE}/web/v1/auth/refresh'
BINDING_URL = f'{API_BASE}/api/v1/game/player/binding'
LOGIN_CODE_URL = f'{AUTH_BASE}/general/v1/send_phone_code'
TOKEN_PHONE_CODE_URL = f'{AUTH_BASE}/user/auth/v2/token_by_phone_code'
TOKEN_PASSWORD_URL = f'{AUTH_BASE}/user/auth/v1/token_by_phone_password'

SIGN_URL_MAPPING = {
    'arknights': f'{API_BASE}/api/v1/game/attendance',
    'endfield': f'{API_BASE}/web/v1/game/endfield/attendance',
}

# 基础请求头
_BASE_HEADERS = {
    'cred': '',
    'User-Agent': (
        'Mozilla/5.0 (Linux; Android 12; SM-A5560 Build/V417IR; wv) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/101.0.4951.61 '
        'Safari/537.36; SKLand/1.52.1'
    ),
    'Accept-Encoding': 'gzip',
    'Connection': 'close',
    'X-Requested-With': 'com.hypergryph.skland',
}

# 签名请求头模板（对齐原始 skyland-auto-sign）
_SIGN_HEADER_TEMPLATE: Optional[dict] = None


def _get_sign_header_template() -> dict:
    """懒加载签名请求头模板"""
    global _SIGN_HEADER_TEMPLATE
    if _SIGN_HEADER_TEMPLATE is None:
        _SIGN_HEADER_TEMPLATE = {
            'platform': '',
            'timestamp': '',
            'dId': '',
            'vName': '',
        }
    return _SIGN_HEADER_TEMPLATE


def _get_login_headers() -> dict:
    """获取登录用请求头（含 dId）"""
    return {
        **_BASE_HEADERS,
        'dId': get_d_id(),
    }


# ==================== 签名算法 ====================

def generate_signature(
    path: str,
    body_or_query: str,
    signing_token: str,
    t: Optional[int] = None,
) -> tuple[str, dict]:
    """生成 HMAC-SHA256 → MD5 签名

    算法：
    1. 拼接: path + body_or_query + timestamp + header_ca_json
    2. HMAC-SHA256 用 signing_token 加密
    3. MD5 哈希 → 最终签名

    Args:
        path: API 路径（不含域名）
        body_or_query: POST 的 JSON body 字符串，或 GET 的 query 字符串
        signing_token: CRED_TOKEN（cred 响应中的 token 字段）
        t: 时间戳，默认当前时间 -2 秒（补偿服务端时钟偏差）

    Returns:
        (sign, header_ca_dict)
    """
    if t is None:
        t = int(time.time()) - 2

    signing_key = signing_token.encode('utf-8')
    header_ca = json.loads(json.dumps(_get_sign_header_template()))
    header_ca['timestamp'] = str(t)
    header_ca_str = json.dumps(header_ca, separators=(',', ':'))

    plaintext = path + body_or_query + str(t) + header_ca_str
    hex_hmac = hmac.new(signing_key, plaintext.encode('utf-8'), hashlib.sha256).hexdigest()
    sign = hashlib.md5(hex_hmac.encode('utf-8')).hexdigest()

    logger.debug(f"[签名] path={path} t={t} sign={sign[:12]}…")
    return sign, header_ca


def apply_signature(
    url: str,
    method: str,
    body: Optional[dict],
    headers: dict,
    signing_token: str,
) -> dict:
    """为请求头添加签名

    Args:
        url: 完整 URL
        method: GET 或 POST
        body: POST 的请求体，GET 时为 None
        headers: 当前请求头（会被原地修改）
        signing_token: CRED_TOKEN

    Returns:
        修改后的 headers
    """
    p = parse.urlparse(url)

    if method.upper() == 'GET':
        body_str = p.query
    else:
        body_str = json.dumps(body) if body is not None else ''

    sign, header_ca = generate_signature(p.path, body_str, signing_token)

    headers['sign'] = sign
    for key, value in header_ca.items():
        headers[key] = value

    return headers


# ==================== HTTP 客户端 ====================

@dataclass
class ApiResponse:
    """API 响应封装"""
    status_code: int
    data: dict
    raw_text: str
    elapsed_ms: float


class SkylandApiError(Exception):
    """森空岛 API 异常"""
    def __init__(self, message: str, code: Optional[int] = None, response: Optional[dict] = None):
        super().__init__(message)
        self.code = code
        self.response = response


class SkylandAuthError(SkylandApiError):
    """认证失败（token 无效/过期）"""
    pass


class SkylandRateLimitError(SkylandApiError):
    """频率限制"""
    pass


class SkylandApiClient:
    """森空岛 API 异步客户端

    特性：
    - 连接池复用
    - 自动签名
    - 可配置重试
    - 详细日志
    """

    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        retry_count: int = 2,
        retry_delay: float = 1.0,
        timeout: float = 15.0,
    ):
        self._own_session = session is None
        self._session = session
        self._retry_count = retry_count
        self._retry_delay = retry_delay
        self._timeout = timeout

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(limit=10, limit_per_host=5),
                timeout=aiohttp.ClientTimeout(total=self._timeout),
            )
        return self._session

    async def close(self):
        """关闭客户端（释放连接池）"""
        if self._own_session and self._session:
            await self._session.close()
            self._session = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    # ---- 低级请求 ----

    async def _request(
        self,
        method: str,
        url: str,
        json_data: Optional[dict] = None,
        headers: Optional[dict] = None,
        retries: Optional[int] = None,
    ) -> ApiResponse:
        """发送 HTTP 请求（带重试）"""
        if retries is None:
            retries = self._retry_count

        session = await self._get_session()
        last_error: Optional[Exception] = None

        for attempt in range(retries + 1):
            start = time.time()
            try:
                async with session.request(
                    method, url, json=json_data, headers=headers or {},
                ) as resp:
                    raw = await resp.text()
                    elapsed = (time.time() - start) * 1000

                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        raise SkylandApiError(
                            f"非 JSON 响应 (HTTP {resp.status}): {raw[:200]}",
                            code=resp.status,
                        )

                    logger.debug(f"{method} {url} → {resp.status} ({elapsed:.0f}ms)")

                    return ApiResponse(
                        status_code=resp.status,
                        data=data,
                        raw_text=raw,
                        elapsed_ms=elapsed,
                    )

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_error = e
                if attempt < retries:
                    delay = self._retry_delay * (2 ** attempt)
                    logger.warning(f"[重试 {attempt + 1}/{retries}] {method} {url}: {e}，{delay:.1f}s 后重试")
                    await asyncio.sleep(delay)
                else:
                    raise SkylandApiError(f"请求失败（已重试 {retries} 次）: {e}") from e

            except SkylandApiError:
                raise

        raise SkylandApiError(f"请求失败: {last_error}") from last_error

    async def get(self, url: str, headers: Optional[dict] = None, retries: Optional[int] = None) -> ApiResponse:
        return await self._request('GET', url, headers=headers, retries=retries)

    async def post(
        self, url: str, json_data: Optional[dict] = None, headers: Optional[dict] = None, retries: Optional[int] = None
    ) -> ApiResponse:
        return await self._request('POST', url, json_data=json_data, headers=headers, retries=retries)

    # ---- 凭证管理 ----

    async def get_grant_code(self, token: str) -> str:
        """token → grant_code"""
        logger.info("[凭证] 步骤1/2: 获取 grant_code …")
        resp = await self.post(
            GRANT_CODE_URL,
            json_data={'token': token, 'appCode': APP_CODE, 'type': 0},
            headers=_get_login_headers(),
        )
        if resp.data.get('status') != 0:
            raise SkylandAuthError(
                f"获取 grant_code 失败: {resp.data.get('msg', resp.data)}",
                code=resp.data.get('status'),
                response=resp.data,
            )
        code = resp.data['data']['code']
        logger.info(f"[凭证] grant_code 获取成功: {code[:8]}…")
        return code

    async def get_cred(self, grant_code: str) -> dict:
        """grant_code → cred"""
        logger.info("[凭证] 步骤2/2: 换取 cred …")
        resp = await self.post(
            CRED_CODE_URL,
            json_data={'code': grant_code, 'kind': 1},
            headers=_get_login_headers(),
        )
        if resp.data.get('code') != 0:
            raise SkylandAuthError(
                f"获取 cred 失败: {resp.data.get('message', resp.data)}",
                code=resp.data.get('code'),
                response=resp.data,
            )
        cred_data = resp.data['data']
        logger.info(f"[凭证] cred 获取成功 (token={cred_data.get('token', '无')[:8]}…)")
        return cred_data

    async def get_cred_by_token(self, token: str) -> dict:
        """完整流程: token → grant_code → cred"""
        logger.info("[凭证] 开始完整鉴权流程…")
        grant = await self.get_grant_code(token)
        return await self.get_cred(grant)

    async def refresh_token(self, token: str, cred: str) -> str:
        """刷新 token（使用 CRED_TOKEN 签名）"""
        headers = _BASE_HEADERS.copy()
        headers['cred'] = cred
        apply_signature(REFRESH_TOKEN_URL, 'GET', None, headers, token)
        resp = await self.get(REFRESH_TOKEN_URL, headers=headers)
        if resp.data.get('code') != 0:
            raise SkylandAuthError(
                f"刷新 token 失败: {resp.data.get('message', resp.data)}",
                code=resp.data.get('code'),
            )
        new_token = resp.data['data']['token']
        logger.info(f"[凭证] token 刷新成功: {new_token[:8]}…")
        return new_token

    # ---- 角色与签到 ----

    async def get_binding_list(self, signing_token: str, cred: str) -> list[dict]:
        """获取已绑定的游戏角色列表（展平嵌套结构，对齐原仓库）

        森空岛 API 返回两层结构:
          [{appCode: "arknights", gameName: "...", bindingList: [{uid, gameId, nickName, ...}]}, ...]

        原仓库 skyland-auto-sign 会遍历 bindingList 并将父级的 appCode 复制到子项。
        不展平会导致 sign_arknights/sign_endfield 拿不到 uid/gameId/nickName 等字段。
        """
        logger.info("[角色] 获取已绑定角色列表…")
        headers = _BASE_HEADERS.copy()
        headers['cred'] = cred
        apply_signature(BINDING_URL, 'GET', None, headers, signing_token)

        resp = await self.get(BINDING_URL, headers=headers)
        code = resp.data.get('code')
        if code != 0:
            raise SkylandAuthError(
                f"获取角色列表失败 (code={code}): {resp.data.get('message', resp.data)}",
                code=code,
                response=resp.data,
            )

        raw_list = resp.data['data']['list']

        # 展平嵌套结构（对齐原仓库 FancyCabbage/skyland-auto-sign）
        characters = []
        for item in raw_list:
            app_code = item.get('appCode', '')
            if app_code not in ('arknights', 'endfield'):
                continue
            bindings = item.get('bindingList', [])
            for binding in bindings:
                binding['appCode'] = app_code
                # 父级的 gameName/channelName 可能不在子项中，补上去
                if not binding.get('gameName'):
                    binding['gameName'] = item.get('gameName', '')
                if not binding.get('channelName'):
                    binding['channelName'] = item.get('channelName', '')
            characters.extend(bindings)

        logger.info(f"[角色] 获取到 {len(raw_list)} 个游戏，展平后 {len(characters)} 个角色")
        return characters

    @staticmethod
    def _is_already_signed_response(data: dict) -> bool:
        """判断 API 响应是否为「今日已签到」

        森空岛 API 在重复签到时返回非零 code，message 中通常包含"已签到"等字样。
        本方法通过 code + message 双重匹配来判定。
        """
        code = data.get('code')
        if code == 0:
            return False
        msg = str(data.get('message', '')).lower()
        keywords = ['已签到', '已经签到', 'already', '重复签到', '今日已签']
        return any(kw in msg for kw in keywords)

    async def sign_arknights(self, signing_token: str, cred: str, char_data: dict) -> tuple[str, str]:
        """明日方舟签到

        Returns:
            (status, message)
            status: 'signed' | 'already' | 'failed'
        """
        game_id = char_data.get('gameId')
        uid = char_data.get('uid')
        game_name = char_data.get('gameName', '明日方舟')
        channel = char_data.get('channelName', '')
        nickname = char_data.get('nickName', char_data.get('nickname', ''))

        # 参数校验：缺少必填字段时直接返回错误，不发无效请求
        if game_id is None or uid is None:
            missing = []
            if game_id is None:
                missing.append('gameId')
            if uid is None:
                missing.append('uid')
            logger.warning(
                f"[签到] 跳过 {game_name}: 缺少必填字段 {missing}，"
                f"角色原始数据: {json.dumps(char_data, ensure_ascii=False)[:200]}"
            )
            return ('failed',
                    f'❌ [{game_name}] {nickname}({channel}) 签到失败: '
                    f'角色数据不完整（缺少 {"、".join(missing)}），请尝试重新绑定')

        body = {'gameId': game_id, 'uid': uid}
        url = SIGN_URL_MAPPING['arknights']
        headers = _BASE_HEADERS.copy()
        headers['cred'] = cred
        apply_signature(url, 'POST', body, headers, signing_token)

        resp = await self.post(url, json_data=body, headers=headers)

        code = resp.data.get('code')
        if code == 0:
            awards = resp.data['data']['awards']
            result_parts = []
            for award in awards:
                res = award['resource']
                result_parts.append(f'{res["name"]}×{award.get("count", 1)}')
            return ('signed', f'✅ [{game_name}] {nickname}({channel}) 签到成功，获得: {" ".join(result_parts)}')

        if self._is_already_signed_response(resp.data):
            return ('already', f'🔄 [{game_name}] {nickname}({channel}) 今天已签到过啦')

        return ('failed', f'❌ [{game_name}] {nickname}({channel}) 签到失败: {resp.data.get("message", "未知错误")}')

    async def sign_endfield(self, signing_token: str, cred: str, char_data: dict) -> list[tuple[str, str]]:
        """终末地签到（可能多角色）

        Returns:
            [(status, message), ...]
            status: 'signed' | 'already' | 'failed'
        """
        roles: list = char_data.get('roles', [])
        game_name = char_data.get('gameName', '终末地')
        channel = char_data.get('channelName', '')
        results = []

        for role in roles:
            nickname = role.get('nickname', '')
            url = SIGN_URL_MAPPING['endfield']
            headers = _BASE_HEADERS.copy()
            headers['cred'] = cred
            headers['Content-Type'] = 'application/json'
            headers['sk-game-role'] = f'3_{role["roleId"]}_{role["serverId"]}'
            headers['referer'] = 'https://game.skland.com/'
            headers['origin'] = 'https://game.skland.com/'
            apply_signature(url, 'POST', None, headers, signing_token)

            resp = await self.post(url, headers=headers)
            j = resp.data

            code = j.get('code')
            if code == 0:
                awards_result = []
                result_data = j['data']
                info_map = result_data.get('resourceInfoMap', {})
                if 'resource' in result_data:
                    for res_item in result_data['resource']:
                        res_id = res_item['resourceId']
                        res_count = res_item.get('count', 1)
                        award_name = info_map.get(str(res_id), f'ID:{res_id}')
                        awards_result.append(f'{award_name}×{res_count}')
                msg = (
                    f'✅ [{game_name}] {nickname}({channel}) 签到成功，获得: {", ".join(awards_result)}'
                    if awards_result
                    else f'✅ [{game_name}] {nickname}({channel}) 签到成功'
                )
                results.append(('signed', msg))
            elif self._is_already_signed_response(j):
                results.append(('already', f'🔄 [{game_name}] {nickname}({channel}) 今天已签到过啦'))
            else:
                results.append(('failed', f'❌ [{game_name}] {nickname}({channel}) 签到失败: {j.get("message", "未知错误")}'))

        return results

    async def do_sign(self, signing_token: str, cred: str) -> list[dict]:
        """执行完整签到流程

        Args:
            signing_token: CRED_TOKEN（签名的密钥）
            cred: Credential 字符串

        Returns:
            [{"status": "signed"|"already"|"failed", "message": "...", "game": "arknights"}, ...]
        """
        logger.info("[签到] 开始签到流程…")
        characters = await self.get_binding_list(signing_token, cred)
        results = []

        for char in characters:
            app_code = char.get('appCode', '')
            game_name = char.get('gameName', '未知')
            try:
                if app_code == 'arknights':
                    status, msg = await self.sign_arknights(signing_token, cred, char)
                    results.append({"status": status, "message": msg, "game": game_name})
                    logger.info(f"[签到] {game_name}: {status} → {msg}")
                elif app_code == 'endfield':
                    items = await self.sign_endfield(signing_token, cred, char)
                    for status, msg in items:
                        results.append({"status": status, "message": msg, "game": game_name})
                    logger.info(f"[签到] {game_name}: {len(items)} 个角色 → {[s for s,_ in items]}")
                else:
                    results.append({"status": "skipped", "message": f'⚠️ [{game_name}] 暂不支持的签到类型: {app_code}', "game": game_name})
            except Exception as e:
                err_msg = f'❌ [{game_name}] 签到异常: {e}'
                results.append({"status": "failed", "message": err_msg, "game": game_name})
                logger.error(f"[签到] {err_msg}", exc_info=True)

        logger.info(f"[签到] 流程完成，共处理 {len(characters)} 个角色，"
                    f"新签到: {sum(1 for r in results if r['status']=='signed')}，"
                    f"已签: {sum(1 for r in results if r['status']=='already')}，"
                    f"失败: {sum(1 for r in results if r['status']=='failed')}")
        return results

    # ---- 账号验证与登录 ----

    async def verify_token(self, token: str) -> tuple[bool, str, Optional[dict]]:
        """验证 token 是否有效并获取角色信息

        Returns:
            (是否成功, 消息, cred_data 或 None)
        """
        logger.info("[验证] 开始验证 token…")
        # 解析可能的 JSON 格式 token
        raw = token
        try:
            token = parse_user_token(token)
            if len(token) != len(raw):
                logger.info(f"[验证] token 已从 JSON 格式解析")
        except Exception:
            pass

        try:
            cred_data = await self.get_cred_by_token(token)
            signing_token = cred_data.get('token', token)
            cred = cred_data.get('cred', '')

            characters = await self.get_binding_list(signing_token, cred)

            game_info = []
            for char in characters:
                game_name = char.get('gameName', '')
                nickname = char.get('nickName', '') or char.get('nickname', '')
                channel = char.get('channelName', '')
                game_info.append(f'{game_name}({nickname}@{channel})')

            info = '、'.join(game_info) if game_info else '未检测到可签到的游戏角色'
            logger.info(f"[验证] ✅ 验证成功！角色: {info}")
            return True, info, cred_data

        except SkylandAuthError as e:
            logger.error(f"[验证] ❌ 认证失败: {e}")
            return False, f'认证失败: {e}', None
        except Exception as e:
            logger.error(f"[验证] ❌ 验证失败: {type(e).__name__}: {e}")
            return False, f'验证失败: {e}', None

    async def send_login_code(self, phone: str) -> dict:
        """发送登录验证码"""
        resp = await self.post(
            LOGIN_CODE_URL,
            json_data={'phone': phone, 'type': 2},
            headers=_get_login_headers(),
        )
        return resp.data

    async def login_by_phone_code(self, phone: str, code: str) -> dict:
        """通过手机验证码登录，获取 token"""
        resp = await self.post(
            TOKEN_PHONE_CODE_URL,
            json_data={'phone': phone, 'code': code},
            headers=_get_login_headers(),
        )
        return resp.data


# ==================== 工具函数 ====================

def parse_user_token(raw: str) -> str:
    """解析用户输入的 token（支持从浏览器 localStorage 复制的 JSON 格式）

    森空岛网页 localStorage 中 token 存储格式为:
    {"token": "...", "uid": "...", "type": ...}

    直接传 token 字符串也可。
    """
    raw = raw.strip()
    if raw.startswith('{') and raw.endswith('}'):
        try:
            data = json.loads(raw)
            if 'token' in data:
                return data['token']
        except (json.JSONDecodeError, TypeError):
            pass
    return raw
