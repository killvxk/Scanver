#!/usr/bin/env python
# encoding=utf-8
#codeby     道长且阻
#email      ydhcui@suliu.net/QQ664284092
#website    http://www.suliu.net


import time
import re
import os
import sys
import queue
import threading
import urllib.parse as urlparse
from requests import Session,Request
from core.util import CoroutinePool as ThreadPool
from core.cmsfind import AppFind
from core.log import logging
from core.base import BaseRequest,BaseWebSite,ConnectionError
import settings

APP = AppFind(settings.DATAPATH + '/appdata.json')

class Crawler(object):
    HEADBLOCK = ('#','data:','javascript:','mailto:','about:','magnet:')
    TYPEBLOCK = (
        ".3ds", ".3g2", ".3gp", ".7z", ".a", ".aac", ".adp", ".ai", ".aif", ".aiff", ".apk", ".ar", ".asf",
        ".au", ".avi", ".bak", ".bin", ".bk", ".bmp", ".btif", ".bz2", ".cab", ".caf", ".cgm", ".cmx", ".cpio", ".cr2",
        ".dat", ".deb", ".djvu", ".dll", ".dmg", ".dmp", ".dng", ".doc", ".docx", ".dot", ".dotx", ".dra", ".dsk", ".dts",
        ".dtshd", ".dvb", ".dwg", ".dxf", ".ear", ".ecelp4800", ".ecelp7470", ".ecelp9600", ".egg", ".eol", ".eot",
        ".epub", ".exe", ".f4v", ".fbs", ".fh", ".fla", ".flac", ".fli", ".flv", ".fpx", ".fst", ".fvt", ".g3", ".gif",
        ".gz", ".h261", ".h263", ".h264", ".ico", ".ief", ".image", ".img", ".ipa", ".iso", ".jar", ".jpeg", ".jpg",
        ".jpgv", ".jpm", ".jxr", ".ktx", ".lvp", ".lz", ".lzma", ".lzo", ".m3u", ".m4a", ".m4v", ".mar", ".mdi", ".mid",
        ".mj2", ".mka", ".mkv", ".mmr", ".mng", ".mov", ".movie", ".mp3", ".mp4", ".mp4a", ".mpeg", ".mpg", ".mpga",
        ".mxu", ".nef", ".npx", ".o", ".oga", ".ogg", ".ogv", ".otf", ".pbm", ".pcx", ".pdf", ".pea", ".pgm", ".pic",
        ".png", ".pnm", ".ppm", ".pps", ".ppt", ".pptx", ".ps", ".psd", ".pya", ".pyc", ".pyo", ".pyv", ".qt", ".rar",
        ".ras", ".raw", ".rgb", ".rip", ".rlc", ".rz", ".s3m", ".s7z", ".scm", ".scpt", ".sgi", ".shar", ".sil", ".smv",
        ".so", ".sub", ".swf", ".tar", ".tbz2", ".tga", ".tgz", ".tif", ".tiff", ".tlz", ".ts", ".ttf", ".uvh", ".uvi",
        ".uvm", ".uvp", ".uvs", ".uvu", ".viv", ".vob", ".war", ".wav", ".wax", ".wbmp", ".wdp", ".weba", ".webm", ".webp",
        ".whl", ".wm", ".wma", ".wmv", ".wmx", ".woff", ".woff2", ".wvx", ".xbm", ".xif", ".xls", ".xlsx", ".xlt", ".xm",
        ".xpi", ".xpm", ".xwd", ".xz", ".z", ".zip", ".zipx")
    ERR_FLAG = re.compile(r'Error|Error Page|Unauthorized|Welcome to tengine!|Welcome to OpenResty!|invalid service url|Not Found|不存在|未找到|410 Gone|looks like something went wrong|Bad Request|Welcome to nginx!', re.I)
    def __init__(self,url,headers={},threads=10,timeout=60,sleep=10,proxy={},level=False,cert=None):
        self.session = Session()
        self.settings            = {}
        self.settings['threads'] = int(threads)
        self.settings['timeout'] = int(timeout)
        self.settings['sleep']   = int(sleep)
        self.settings['proxy']   = proxy
        self.settings['level']   = level
        self.settings['headers'] = headers
        self.basereq = BaseRequest(url)
        self.website = BaseWebSite(url,proxy=self.settings['proxy'],session=self.session)
        self.pag404  = self.website.pag404
        self.block               = []#set()
        self.ISSTART             = True
        self.ReqQueue            = queue.Queue()
        self.ResQueue            = queue.Queue()
        self.SubDomain           = set()  #子域名列表
        self.Directory           = {}     #目录结构
        self.cert = cert
        self.url = url

    def reqhook(self,req):
        '''用于请求时重写hook
        x = Crawler(...)
        x.reqhook = lambda i: i
        x.run()
        '''
        return req

    def addreq(self,req):
        if req.path and req.path.lower().endswith(self.TYPEBLOCK): #去除图片等二进制文件
            return 
        if(req.scheme)and(req.netloc)and(req not in self.block):
            self.block.append(req)
            self.ReqQueue.put(req)

    def urljoin(self,url):
        if url:
            if url.upper().startswith(('//','HTTP')):
                #http://xx.cn/xx 
                #//xx.com/xx 
                if BaseRequest(url).netloc.upper() == self.basereq.netloc.upper(): #同域
                    if url.startswith('//'):
                        url = self.basereq.scheme+':'+url
                    return url
                else:
                    u = BaseRequest(url)
                    self.SubDomain.add((u.scheme,u.netloc.replace('//','')))
            elif url.startswith(('/','./','../')):
                #./xx/oo 
                #../xx/oo 
                return urlparse.urljoin(self.basereq.url,url)
            else:
                if not url.startswith(self.HEADBLOCK):
                    #javascript:void(0) ...
                    return urlparse.urljoin(self.basereq.url,url)

    def request(self,req):
        req = self.session.prepare_request(req.prepare())
        req = self.reqhook(req)
        try: 
            res = self.session.send(req,
                verify=False,
                proxies=self.settings['proxy'],
                timeout=self.settings['timeout'])
            self.ResQueue.put((req,res))
            self.parse(res)
            #app 识别
            for app in APP.find(res):
                self.website.content = app
        except ConnectionError as e:
            logging.warn(str(e))
            time.sleep(self.settings['sleep'])
        except Exception as e:
            logging.warn(str(e))

    def parse(self,response):
        content_type = response.headers.get('content-type','text')
        if content_type not in ("image","octet-stream"):
            response = response.text
            urls = set()
            urls = urls.union(set(re.findall(r"""src[\s]*:[\s]*["'](.*?)["']""",response)))
            urls = urls.union(set(re.findall(r"""src[\s]*=[\s]*["'](.*?)["']""",response)))
            urls = urls.union(set(re.findall(r"""href[\s]*:[\s]*["'](.*?)["']""",response)))
            urls = urls.union(set(re.findall(r"""href[\s]*=[\s]*["'](.*?)["']""",response)))
            urls = urls.union(set(re.findall(r"""url[\s]*:[\s]*['"](.*?)['"]""",response)))
            urls = urls.union(set(re.findall(r"""url[\s]*=[\s]*['"](.*?)['"]""",response)))
            urls = urls.union(set(re.findall(r'''['"](/[^/\*'"][A-Za-z0-9\.\\/_-]{1,255})['"]''',response)))
            urls = urls.union(set(re.findall(r"""['"]([A-Za-z0-9\.\\/_-]{1,255}[a-zA-Z]\?[a-zA-Z].*?)['"]""",response)))
            urls = urls.union(set(re.findall("""(http[s]?://(?:[-a-zA-Z0-9_]+\.)+[a-zA-Z]+(?::\d+)?(?:/[-a-zA-Z0-9_%./]+)*\??[-a-zA-Z0-9_&%=.]*)""",response)))
            for url in urls:
                if url:
                    req = BaseRequest(self.urljoin(url),session=self.session,proxy=self.settings['proxy'])
                    self.addreq(req)

            if self.settings['level']:
                posts = []
                for f in re.findall(r"""<form([\s\S]*?)</form>""",response):
                    post = {}
                    post['action'] = ''.join(re.findall(r"""action[\s]*=[\s]*["'](.*?)["']""",f)) or './'
                    post['method'] = ''.join(re.findall(r"""method[\s]*=[\s]*["'](.*?)["']""",f)) or 'POST'
                    post['data'] = {}
                    for d in re.findall(r"""<input[\s\S]*?>""",f):
                        name = ''.join(re.findall(r"""name[\s]*=[\s]*["'](.*?)["']""",d))
                        value = ''.join(re.findall(r"""value[\s]*=[\s]*["'](.*?)["']""",d))
                        if not value:value = name
                        post['data'].update({name:value})
                    posts.append(post)
                for post in posts:
                    req = BaseRequest(self.urljoin(post['action']),method=post['method'],data=post['data'],session=self.session,proxy=self.settings['proxy'])
                    self.addreq(req)

    def run1(self):
        pool = ThreadPool(self.settings['threads'])
        self.FLAG = self.settings['timeout']
        try:
            self.request(BaseRequest(self.url,headers=self.settings['headers']))
        except Exception as e:
            print(e)
            self.ISSTART = False
            return
        #5分钟后还没有任务加进来就当爬完了
        while self.ISSTART and self.FLAG > 0:
            logging.load('Reload ... Wait for %s'%self.FLAG)
            try:
                req = self.ReqQueue.get(block=False)
                pool.spawn(self.request,req)
            except queue.Empty:
                time.sleep(1)
                self.FLAG -= 1
        self.ISSTART = False
        pool.join()

if __name__ == '__main__':
    import threading

    x=Crawler('http://59.41.129.37:8080/')
    x.settings.update(
        timeout=10,
        threads=100,
        proxy={'http':'http://127.0.0.1:1111','https':'http://127.0.0.1:1111'},
        level=True)
    threading.Thread(target=x.run1).start()

    while x.ISSTART or not x.ResQueue.empty():
        try:
            q,r = x.ResQueue.get(block=False)
            print(r.status_code,q.method,q.url)
        except queue.Empty:
            pass

