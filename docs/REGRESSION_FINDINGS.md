# 1.0.0 回归问题与修复

此前反向回归复现的 4 个问题现已修复。原有断言全部保留为普通回归测试，没有跳过或标记预期失败；另补充冷缓存、重复域名覆盖、HTTP 嵌套错误和网关响应结构的用例。

## 验证结果

| 阶段 | 结果 |
| --- | --- |
| 修复前原有测试 | 44 项通过 |
| 修复前完整测试 | 50 项，46 通过、4 失败；当时的 wheel 同样复现 |
| 修复后回归文件 | 11 项通过，含原来的 4 项失败用例和 2 项对照 |
| 修复后完整测试 | 55 项通过 |

源码及重新构建的 wheel 的跨版本实测结果见 [验证记录](VALIDATION.md)。这些都是离线测试，未调用平台业务接口。

## 1. Session 默认 JSON 请求头破坏文件上传：已修复

- 触发：注入的 Session 设置 `Content-Type: application/json`，再调用 `other.upload_material(files=...)`。
- 修复前：实际请求体是 multipart，请求头仍是 JSON。
- 原因：只删除局部 headers，Session.prepare_request 会再次合并 Session 默认请求头。
- 修复：在单次请求中显式禁止继承 Content-Type，让 requests 生成与上传请求体一致的 boundary；保留共享 Session 的默认配置。
- 验证：检查上传头、请求体首尾 boundary 和 Session.headers 未被修改。
- 用例：`test_upload_overrides_session_json_content_type`。

## 2. 不支持的沙盒接口先获取凭证：已修复

- 触发：沙盒环境调用未声明沙盒支持的接口。
- 修复前：拒绝前已调用凭证提供器；冷缓存下可能发起取凭证请求，凭证错误可能掩盖真正的环境错误。
- 修复：在处理凭证之前检查接口的沙盒支持。
- 验证：凭证提供器、缓存读取/刷新及业务发送均未触发；凭证服务不可用也不影响返回正确的环境错误。
- 用例：`test_unsupported_sandbox_api_rejects_before_requesting_credentials`、`test_unsupported_sandbox_does_not_refresh_token_when_cache_is_cold`。

## 3. 旧登录入口忽略域名覆盖：已修复

- 触发：配置 `api_domains` 后调用 `code2Session`。
- 修复前：新模块登录使用覆盖域名，旧入口仍使用原域名。
- 修复：统一在请求发送层应用域名映射，新旧接口、直接 get/post/fetch 和获取应用凭证使用一致规则；移除上层的重复覆盖。
- 验证：各入口的实际请求地址、目标路径前缀正确；映射 A→B、B→C 时只应用一次，避免意外跳转到 C。
- 用例：`test_legacy_login_also_honors_domain_override`、`test_domain_override_applies_once_to_credentials_and_legacy_requests`。

## 4. HTTP 错误丢失业务错误码：已修复

- 触发：HTTP 429 的 JSON 响应包含 `err_no=10020`。
- 修复前：异常保留 HTTP 状态和 log_id，但 `code` 为 None。
- 修复：处理 HTTP 错误之前提取业务错误码，保留对应的错误消息、日志标识和原始响应；即使没有业务码，HTTP 错误也仍然抛错。
- 补充修复：网关错误可能不采用接口正常响应结构，因此 HTTP 错误优先使用接口声明字段，再识别通用平台错误字段；正常成功响应仍按接口契约判断。
- 验证：根级、嵌套及接口响应契约之外的网关错误码；没有业务码或 JSON 为列表、字符串时仍保留 HTTP 失败。
- 用例：`test_http_error_preserves_platform_business_error_code`、`test_http_error_preserves_nested_business_error_and_message`、`test_http_gateway_error_preserves_code_outside_normal_response_schema`、`test_http_error_without_business_code_remains_failure`。

## 本地验证命令

```sh
PYTHONPATH=src python -m unittest discover -s tests -p 'test_failure_regressions.py' -v
PYTHONPATH=src python -m unittest discover -s tests -v
```

预期分别为 `Ran 11 tests / OK` 和 `Ran 55 tests / OK`。
