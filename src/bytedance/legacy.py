# -*- coding: utf-8 -*-
"""Compatibility wrappers retained from bytedance 0.1.2."""
import hashlib
import hmac
import json
import warnings

from .base import ByteDanceError


class LegacyMethods(object):
    def _sign(self, session_key, post_body):
        '''
        用户登录态签名
        官方文档：https://microapp.bytedance.com/docs/zh-CN/mini-app/develop/server/other/user-login-sign/
        '''
        # 头条的算法里面，需要移除空格
        message = json.dumps(post_body, ensure_ascii=False, separators=(',', ':'))
        signature = hmac.new(
            session_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return signature

    def set_user_storage(self, openid, session_key, kv_list, sig_method="hmac_sha256"):
        '''
        以 key-value 形式存储用户数据到小程序平台的云存储服务。
        若开发者无内部存储服务则可接入，免费且无需申请。
        一般情况下只存储用户的基本信息，禁止写入大量不相干信息。
        kv_list的key和value都必须是string，长度小于1024字节
        单用户上限是128条数据
        官方文档：https://microapp.bytedance.com/docs/zh-CN/mini-app/develop/server/data-caching/set-user-storage
        '''
        data = {
            "kv_list":[{"key": k,"value": "%s"%v} for k,v in kv_list.items()]
        }
        sign = self._sign(session_key, data)
        params = {
            # "access_token": self.access_token,
            "openid": openid,
            "signature": sign,
            "sig_method":sig_method
        }
        return self.post('/set_user_storage', params=params, data=data)

    def remove_user_storage(self, openid, session_key, key_list, sig_method="hmac_sha256"):
        '''
        删除数据缓存
        '''
        data = {
            "key":key_list
        }
        sign = self._sign(session_key, data)
        params = {
            "openid": openid,
            "signature": sign,
            "sig_method":sig_method
        }
        return self.post('/remove_user_storage', params=params, data=data)

    def create_qrcode(self, appname=None, path=None, width=None, line_color=None, background=None, set_icon=None):
        '''
        创建二维码
        '''
        appname_list = ['toutiao', 'douyin', 'pipixia', 'huoshan']
        if appname and appname not in appname_list:
            raise ByteDanceError('目前只支持appname是如下：%s'%(str(appname_list)))
        data = {
            "access_token":self.access_token,
        }
        for key, value in (("appname", appname), ("path", path), ("width", width),
                           ("line_color", line_color), ("background", background),
                           ("set_icon", set_icon)):
            if value is not None:
                data[key] = value
        return self.post('/qrcode',data=data)

    def template_send(self, touser, template_id, form_id, data, page=None):
        '''
        发送模板消息
        https://microapp.bytedance.com/docs/zh-CN/mini-app/develop/server/model-news/send
        '''
        warnings.warn('template_send is a historical API; use marketing subscription APIs',
                      DeprecationWarning, stacklevel=2)
        data = {
            "access_token": self.access_token,
            "app_id": self.app_id,
            "data": data,
            "page": page,
            "form_id": form_id,
            "touser": touser,
            "template_id":template_id
        }
        return self.post('/game/template/send', data=data, token=False)

    def text_antidirt(self, tasks):
        '''
        文本内容安全检测
        {
            "tasks": [
                {
                "content": "要检测的文本"
                }
            ]
        }
        '''

        headers = {"X-Token": self.access_token}
        return self.post('/v2/tags/text/antidirt', data=tasks if isinstance(tasks, dict) else {'tasks': tasks}, headers=headers, prefix='')
    
    def images_antidirt(self, tasks: list, targets=None):
        '''
        图片检测
        https://microapp.bytedance.com/docs/zh-CN/mini-app/develop/server/content-security/picture-detect
        '''
        if targets is None:
            # 默认四项全部检测
            targets = ["ad", "porn", "politics", "disgusting"]
        data = {
            "targets": targets,
            "tasks": tasks
        }
        headers = {"X-Token": self.access_token}
        return self.post('/v2/tags/image/', data=data, headers=headers, prefix='')

    def subscribe_send(self, tpl_id, open_id, data, page=None):
        '''
        发送订阅消息
        https://microapp.bytedance.com/docs/zh-CN/mini-app/develop/server/subscribe-notification/notify
        '''
        # V2 uses client_token in a header; the legacy tpl_id maps to msg_id.
        body = {"msg_id": tpl_id, "open_id": open_id, "data": data}
        if page is not None:
            body["page"] = page
        return self._subscription_notify(body)
