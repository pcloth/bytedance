# 0.1.x → 1.0.0

| 项目 | 1.0.0 行为 |
| --- | --- |
| `from bytedance import ByteDance` | 保留；构造函数仍接受原有配置 |
| `code2Session(code, anonymous_code)` | 使用官方 V2 POST；继续返回扁平 session |
| `code2_session(...)` | 新增规范命名，另支持 `refresh` |
| `app.basic.log_in.code_2_session(body=...)` | 新模块返回完整官方响应，session 在 `data` 中 |
| `access_token` | 仍表示小程序应用凭证，统一返回 str；不与 client token 混用 |
| `client_token` | 新增抖音应用凭证属性 |
| `subscribe_send(tpl_id, open_id, data, page)` | 适配 V2，tpl_id 映射 msg_id，凭证改为 client_token |
| `create_qrcode(...)` | 保留旧接口与 Response 返回方式，修复 False/0/空字符串丢失；新二维码能力通过 basic 模块调用 |
| `set_user_storage/remove_user_storage` | 保留既有端点和 HMAC；平台已不在当前小程序目录中列出，使用前确认应用支持 |
| `template_send` | 保留旧模板端点，发出 DeprecationWarning；推荐订阅消息接口 |
| `text_antidirt` | 保留端点，修复任务列表未包装进 tasks 对象的问题 |
| `images_antidirt` | 保留历史批量端点；当前图片检测 V2/V3 在 basic.content_security 中 |
| `get/post/fetch` | 保留签名；不修改调用方字典，复用 Session 配置 |
| `Map` | 保留缺失字段得到空 Map 的行为；新增列表内嵌套转换，字典方法仍优先 |
| `ByteDanceError` | 仍为原异常类型，新增 code/log_id/status_code/payload/response |
| Python 版本 | 最低 3.6；移除 3.4/3.5 分类 |

SDK 能保留调用契约，无法恢复平台已停用的历史服务。历史接口不自动映射到语义不同的新接口。

## 缓存迁移

`ac_path` 继续接受文件路径，作为新缓存的基路径。实际文件使用应用、环境、凭证类型后缀，避免多小程序或沙盒相互覆盖。生产环境的小程序 token 可读取原路径中尚未过期的旧文本文件；过期后写入新 JSON 文件。旧文件不删除。给不同应用迁移旧缓存时，原路径应仍对应各自应用。

Redis 新键使用 `bytedance:<应用及环境摘要>:<类型>`；原来的两段式 token/time 键不复用。显式 Redis 模式缺失依赖或连接失败会抛错，auto 模式可以使用文件。多主机需要共享 Redis 或自己的 `token_provider`；本地文件锁只协调共享同一文件系统的进程。

## 回调与签名

主动调用接口、平台回调和前端下单采用各自的签名原文，不能互相替代。`app.signed_order` 对 `/requestOrder` 签名，并返回与签名一致的 data 字符串。主动 RSA 请求包含实际编码后的 query；响应和交易回调使用原始响应/请求 bytes。

`callbacks.parse` 要求明确指定 `trade/ecpay/webhook`，验签失败抛错。对于旧担保支付订单产生的交易回调，按文档中的 version 规则选择协议。处理回调的 HTTP 路由、业务幂等和扩展点响应数据由使用者负责。

## 覆盖依据

官方目录每篇文档均分类列入 [接口索引](API.md)。重复端点保留目录别名；当前目录未下线、但名称含 V1/V2 的独立接口仍封装。明确标记历史、不推荐的目录不新增封装。

部分目录链接已经返回空正文；能在官方旧地址、官方索引文档或 [字节跳动官方 Go SDK](https://github.com/bytedance/douyin-openapi-sdk-go) 验证的契约，单独记录证据。关键信息卡的两个空正文页面通过官方 SDK 的 ImportCardGet/ImportCardAdd 交叉实现，凭证须显式传入。无法验证的契约应列为 unresolved，不计入已实现。
