# 字节跳动 / 抖音小程序 Python SDK

`bytedance 1.0.0`，支持 Python 3.6+。按抖音官方小程序服务端目录补齐基础、触达营销、支付、运营、生活服务、垂直行业及其它接口，保留 0.1.x 的 `ByteDance` 和已有调用方式。

完整接口、官方链接、鉴权类型和逐页覆盖情况见 [接口索引](docs/API.md)。接口契约随包发布，运行时不抓取文档。

## 安装

`1.0.0` 尚未发布到 PyPI，当前请使用本地源码或 `dist/` 下的 wheel。发布后的常规安装方式及本地安装命令如下。

```sh
pip install bytedance
# 按需安装共享凭证缓存、RSA/AES 能力
pip install 'bytedance[redis,crypto]'
# 本地开发
pip install -e './src[crypto]'
```

Python 3.6 会由 pip 选择仍支持该版本的依赖；新环境使用其兼容的新版本。

## 初始化与旧调用方式

```python
from bytedance import ByteDance, ByteDanceError

app = ByteDance(
    app_id='tt-your-appid',
    app_secret='your-secret',
    access_token_type='file',  # auto / redis / file，默认 auto
    ac_path='/var/cache/my-app/bytedance-token',
    timeout=20,               # 也可以传 (连接超时, 读取超时)
)

session = app.code2Session(code='前端 tt.login 返回的 code')
print(session.openid)
# 新命名别名，仍返回扁平的 session 数据
session = app.code2_session(anonymous_code='anonymous-code', refresh=False)

# 旧订阅方法已适配当前 V2 协议
app.subscribe_send('MSG-template-id', session.openid, {'物品名称': '示例'})
```

`code2Session` / `code2_session` 使用 V2 POST，但继续返回 `session.openid` 等扁平字段。新增业务模块返回官方完整响应，例如 `result.data.openid`。

已有的缓存、二维码、文本/图片检测、模板消息方法继续保留；历史接口可能受平台停止维护的影响。参见 [兼容与迁移说明](docs/COMPATIBILITY.md)。

## 新接口：统一请求字典

七个业务入口分别为 `basic`、`marketing`、`payment`、`operation`、`locallife`、`industry`、`other`。模块和方法按官方目录路径命名，将 `-` 转为 `_`，Python 关键字追加 `_`。

每个接口提供独立方法，签名统一为：

```python
method(body=None, query=None, headers=None, files=None, path_params=None, token=None)
```

```python
# 登录，保留官方响应结构
result = app.basic.log_in.code_2_session(body={'code': 'login-code'})
print(result.data.openid)

# code 换手机号
phone = app.basic.log_in.get_phone_number(body={'code': 'phone-code'})

# 订阅消息 V2，自动注入 client_token 到 access-token 请求头
app.marketing.subscribe_notification.notify_user_v2(body={
    'msg_id': 'MSG-template-id',
    'open_id': 'user-openid',
    'data': {'物品名称': '示例'},
    'notify_type': [1, 2],
    'page': 'pages/index',
})

# 上传：字段名严格按各接口文档填写；文件由调用方负责关闭
with open('poster.png', 'rb') as image:
    result = app.other.upload_material(
        body={'material_type': 1},
        files={'material_file': ('poster.png', image, 'image/png')},
    )
```

请求字典不会被 SDK 修改。`False`、`0`、空字符串和空列表原样保留；query 中的数组、对象和布尔值编码成 JSON 字符串。文件参数沿用 `requests` 的 `files` 格式，multipart boundary 由请求层生成。

### 凭证

小程序 `access_token` 与抖音 `client_token` 分别自动获取、缓存。用户授权、经营授权、服务商凭证不保存到全局应用缓存，调用时显式传入：

```python
result = app.basic.data_open.user_homepage_data.get_item_bc(
    query={'open_id': 'openid', 'date_type': 7},
    token='bus_act.your-business-token',
)
```

优先级：`token=` > 调用方在文档指定位置提供的凭证 > 自动应用凭证。对未明确凭证类型的官方契约，要求显式传入 `token`；类型见接口索引中的 `explicit`。

可通过 `token_provider=lambda kind: ...` 接入自己的凭证中心；`kind` 为 `mini_app` 或 `client`，返回字符串/bytes，返回 `None` 时使用 SDK 缓存。Redis 配置示例：

```python
app = ByteDance(
    app_id='tt-appid', app_secret='secret',
    access_token_type='redis',
    redis={'host': '127.0.0.1', 'port': 6379, 'decode_responses': True},
)
```

`auto` 在 Redis 库缺失或连接不可用时使用文件；`redis` 模式明确报错。文件和 Redis 均按应用、环境、凭证类型隔离，刷新使用跨实例锁。`ac_path` 是缓存基路径，实际 JSON 文件追加应用/环境标识和凭证类型；仍可读取未过期的 0.1.x 旧格式文件。

### 支付、签名与回调

```python
app = ByteDance(
    app_id='tt-appid', app_secret='secret',
    private_key='-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----',
    key_version='1',
    platform_public_key='-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----',
    payment_salt='担保支付 SALT',
    callback_token='支付设置中的回调 Token',
)

# 根据接口契约选择 RSA 或担保支付签名
order = app.payment.ecpay.pay_list.pay(body={
    'out_order_no': 'your-unique-order-no',
    'total_amount': 100,
    'subject': '商品', 'body': '商品详情', 'valid_time': 900,
})

# 给前端 tt.requestOrder 使用的 data 与 byteAuthorization
frontend_arguments = app.signed_order({'outOrderNo': 'order-no', 'skuList': []})

# raw_body 必须是 Web 框架收到的原始 bytes，不可先解析、重新序列化
callback = app.callbacks.parse(raw_body, request_headers, protocol='trade')
# callback.msg 保持原始字符串；解析后的业务内容在 callback.parsed_msg
# 由业务方完成订单校验、幂等处理和落库后，构造该协议的基础应答
reply = app.callbacks.acknowledgement('trade')
```

三类回调协议：`trade` 使用平台 RSA 公钥；`ecpay` 使用回调 Token 和 SHA-1；`webhook` 使用 client secret 和原始请求体验证 `X-Douyin-Signature`。协议不得混用。部分旧交易回调随订单版本采用不同协议，须按对应文档及版本选择。需要返回业务字段的扩展点，应按文档填写应答内容，基础应答工具不代替业务响应。

底层签名、验签、AES-128-CBC 敏感数据解密可从 `bytedance.security` 导入。配置平台公钥后，对带签名的成功响应执行验签，RSA 接口要求完整签名头。

### 错误与资源

```python
try:
    result = app.basic.log_in.get_phone_number(body={'code': 'phone-code'})
except ByteDanceError as exc:
    print(exc.code, exc.log_id, exc.status_code)
    # exc.payload / exc.response 保留原始响应供业务排查
finally:
    app.close()
```

网络、HTTP 状态和业务错误统一抛出 `ByteDanceError`。业务请求默认不自动重试。JSON 响应支持字典和属性访问，列表内部也递归转换为 `Map`；与 `items/get` 等 dict 方法重名的字段使用下标访问。二维码及账单等二进制结果保留 `requests.Response`。

`environment='sandbox'` 仅允许官方已注明沙盒支持的接口；未注明支持的接口明确报错。可注入 `requests.Session`；支持 `with ByteDance(...) as app:` 自动关闭。

## 开发与验证

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
python tools/sync_official_docs.py
python tools/build_catalog.py
```

官方文档采集结果在 `docs/official_catalog.json`；人工核对差异和官方 SDK 交叉证据在 `docs/contract_overrides.json`。生成器输出静态独立方法、随包契约及接口索引。原始 HTML 只缓存到系统临时目录，不发布整篇官方文档。

离线测试覆盖全部生成方法的请求分发、独立官方契约、旧调用、缓存并发及官方签名向量。1.0.0 wheel 已在 Python 3.6 / 3.8 / 3.12 实际安装，并分别通过全部 44 项测试，另配置相同版本的 CI 矩阵。详见 [验证记录](docs/VALIDATION.md)。未提供测试应用凭证，因此不把离线通过等同于平台实际联调成功。
