
# -*- coding: utf-8 -*-
# 字节跳动小程序sdk
import json, time, requests, os, hmac, hashlib

from .base import ByteDanceError, Map

DEFAULT_DIR = os.getenv("HOME", os.getcwd())
__version__ = "0.1.2"
try:
    # 用redis来多系统共用access_token
    import redis
    # 把这个关掉就继续用文件模式存密钥
    is_redis = True 
except:
    is_redis = False

class ByteDance(object):
    '''
    字节跳动sdk
    '''
    def __init__(self, **config):
        self.app_id = config['app_id']
        self.app_secret = config['app_secret']
        self.session = requests.Session()
        self.__version__ = __version__

        if config.get('mch_id'):
            # 收银台支付相关
            self.mch_id = config['mch_id']
            self.mch_secret = config['mch_secret']
            self.mch_app_id = config['mch_app_id']

        # 获取token方式，auto是redis优先，file是强制文件模式，redis是强制redis模式
        self.access_token_type = config.get('access_token_type') or 'auto'
        if self.access_token_type not in ['auto', 'redis', 'file']:
            raise ByteDanceError('access_token_type只能是auto/redis/file三选一')
        if config.get('redis'):
            self.redis_conf = config.get('redis')
        else:
            self.redis_conf = {"host":"redis","port":6379,"decode_responses":True}
        # access_token 指定文件
        ac_path = config.get('ac_path') 
        if ac_path is None:
            # 默认添加appid作为文件名，这样防止多个字节跳动小程序相互干扰token
            ac_path = os.path.join(DEFAULT_DIR, "%s.access_token" % self.app_id)
        self.ac_path = ac_path
        self.api_uri = 'https://developer.toutiao.com/api'

    def fetch(self, method, url, params=None, data=None, headers=None):
        req = requests.Request(
            method, url, params=params,
            data=data, headers=headers)
        prepped = req.prepare()
        resp = self.session.send(prepped, timeout=20)

        try:
            data = Map(resp.json())
        except:
            # 获取二维码等接口，返回原始内容
            return resp
        if data.error:
            msg = "error:%(error)d , message:%(message)s" % data
            raise ByteDanceError(msg)
        return data

    def get(self, path, params=None, token=True, prefix="/apps"):
        '''get方法获取接口信息'''
        url = "{0}{1}{2}".format(self.api_uri, prefix, path)
        params = {} if not params else params
        token and params.setdefault("access_token", self.access_token)
        return self.fetch("GET", url, params)

    def post(self, path, data, params=None, headers=None, prefix="/apps", token=True):
        url = "{0}{1}{2}".format(self.api_uri, prefix, path)
        if not params:
            params = {}
        token and params.setdefault("access_token", self.access_token)
        if not headers:
            headers = {}
        data = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        headers["Content-Type"] = "application/json"
        return self.fetch("POST", url, params=params, data=data, headers=headers)

    def _get_access_token(self):
        '''
        刷新access_token，一般情况下，用户无需自己调用这个，除非要自己集成后改写access_token属性方法
        '''
        params = {
            "grant_type": "client_credential",
            "appid": self.app_id,
            "secret": self.app_secret,
        }
        data = self.get("/token", params, False)
        return data

    @property
    def access_token(self):
        '''
        获取access_token服务端凭证
        '''
        timestamp = time.time()
        if redis and self.access_token_type in ['auto','redis']:
            # redis 模式，用appid来标记token
            r = redis.Redis(**self.redis_conf)
            access_token = r.get(f'{self.app_id}_access_token')
            access_token_time = r.get(f'{self.app_id}_access_token_invalidtime')
            if not access_token or int(float(access_token_time)) < timestamp:
                data = self._get_access_token()
                access_token = data.access_token.encode("utf-8")
                access_token_time = timestamp + data.expires_in - 600
                r.set(f'{self.app_id}_access_token',access_token)
                r.set(f'{self.app_id}_access_token_invalidtime',access_token_time)
            return access_token.strip()
        
        # 文件存token模式
        if not os.path.exists(self.ac_path) or \
                int(os.path.getmtime(self.ac_path)) < timestamp:
            data = self._get_access_token()
            access_token = data.access_token.encode("utf-8")
            with open(self.ac_path, 'wb') as fp:
                fp.write(access_token)
            os.utime(self.ac_path, (timestamp, timestamp + data.expires_in - 600))
        return open(self.ac_path).read().strip()

    def code2Session(self, code=None,anonymous_code=None):
        '''code换取session_key和openid'''
        if not code and not anonymous_code:
            raise ByteDanceError('code or anonymous_code')
        params = {
            'appid': self.app_id,
            "secret": self.app_secret,
        }
        if code:
            params['code'] = code
        if anonymous_code:
            params['anonymous_code'] = anonymous_code
        return self.get('/jscode2session', params, False)
        
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
        appname and data.setdefault("appname", appname)
        path and data.setdefault("path", path)
        width and data.setdefault("width", width)
        line_color and data.setdefault("line_color", line_color)
        background and data.setdefault("background", background)
        set_icon and data.setdefault("set_icon", set_icon)
        return self.post('/qrcode',data=data)

    def template_send(self, touser, template_id, form_id, data, page=None):
        '''
        发送模板消息
        https://microapp.bytedance.com/docs/zh-CN/mini-app/develop/server/model-news/send
        '''
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
        return self.post('/v2/tags/text/antidirt', data=tasks, headers=headers, prefix='')
    
    def images_antidirt(self, tasks: list, targets=None):
        '''
        图片检测
        https://microapp.bytedance.com/docs/zh-CN/mini-app/develop/server/content-security/picture-detect
        '''
        if not targets:
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
        data = {
            "access_token": self.access_token,
            "app_id": self.app_id,
            "tpl_id": tpl_id,
            "open_id": open_id,
            "data": data,
            "page": page
        } 
        return self.post('/subscribe_notification/developer/v1/notify', data=data, token=False)