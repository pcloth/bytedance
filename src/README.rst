字节跳动 / 抖音小程序 Python SDK
============================================================

bytedance 1.0.0，支持 Python 3.6 及以上版本。

覆盖小程序服务端基础能力、触达营销、支付、运营、生活服务、垂直行业及其它接口。
保留 ByteDance、code2Session 等已有调用方式。接口契约随包发布，运行时不抓取文档。

安装
----

1.0.0 已发布到 `PyPI <https://pypi.org/project/bytedance/1.0.0/>`_。

.. code-block:: sh

   pip install bytedance
   pip install 'bytedance[redis,crypto]'

使用
----

.. code-block:: python

   from bytedance import ByteDance

   app = ByteDance(app_id='tt-appid', app_secret='secret', access_token_type='file')
   session = app.code2Session(code='login-code')
   print(session.openid)

   result = app.basic.log_in.code_2_session(body={'code': 'login-code'})
   print(result.data.openid)

   app.marketing.subscribe_notification.notify_user_v2(body={
       'msg_id': 'MSG-template-id',
       'open_id': 'openid',
       'data': {'物品名称': '示例'},
   })
   app.close()

新增接口提供独立方法，统一接受 body、query、headers、files、path_params 字典以及可选 token。
新增模块保留官方完整响应，旧登录方法继续返回扁平 session 对象。
应用级凭证自动缓存，用户、经营和服务商授权凭证显式传入。

完整接口、鉴权类型、迁移及回调接入说明见项目文档：

* `项目 README <https://github.com/pcloth/bytedance/blob/master/README.MD>`_
* `接口索引 <https://github.com/pcloth/bytedance/blob/master/docs/API.md>`_
* `兼容说明 <https://github.com/pcloth/bytedance/blob/master/docs/COMPATIBILITY.md>`_

测试使用离线契约与官方签名向量，不要求真实应用凭证，也不执行交易。
