#!/usr/bin/env python
# -*- encoding=utf8 -*-
import time

from lxml import etree

from .config import global_config
from .param import JDTdudfp
from .logger import logger
from .login import QRLogin
from .session import SpiderSession
from .timer import Timer
from .util import (
    parse_json,
    send_wechat,
    wait_some_time, check_login_is_effective,
)


class JDReserve:
    """
    预约
    """

    def __init__(self):
        self.spider_session = SpiderSession()
        self.spider_session.load_cookies_from_local()

        self.qr_login = QRLogin(self.spider_session)
        self.jd_tdudfp = JDTdudfp(self.spider_session)

        # 初始化信息
        self.sku_id = global_config.getRaw('config', 'sku_id')
        self.work_count = global_config.getRaw('config', 'work_count')
        self.seckill_num = int(global_config.getRaw('config', 'seckill_num'))
        self.seckill_init_info = dict()
        self.seckill_url = dict()
        self.seckill_order_data = dict()
        self.timers = Timer()

        self.session = self.spider_session.get_session()
        self.user_agent = self.spider_session.user_agent
        self.nick_name = None

        self.running_flag = True

    @check_login_is_effective
    def reserve(self):
        """
        预约
        """
        self._reserve()

    def _reserve(self):
        """
        预约
        """
        while True:
            try:
                self.make_reserve()
                break
            except Exception as e:
                logger.info('预约发生异常!', e)
            wait_some_time()

    def make_reserve(self):
        """商品预约"""
        logger.info('商品名称:{}'.format(self.get_sku_title()))
        url = 'https://yushou.jd.com/youshouinfo.action?'
        payload = {
            'callback': 'fetchJSON',
            'sku': self.sku_id,
            '_': str(int(time.time() * 1000)),
        }
        headers = {
            'User-Agent': self.user_agent,
            'Referer': 'https://item.jd.com/{}.html'.format(self.sku_id),
        }
        resp = self.session.get(url=url, params=payload, headers=headers)
        resp_json = parse_json(resp.text)
        logger.info("商品预约 response：{}".format(resp_json))
        reserve_url = resp_json.get('url')

        while True:
            try:
                self.session.get(url='https:' + reserve_url)
                logger.info('预约成功，已获得抢购资格 / 您已成功预约过了，无需重复预约')
                if global_config.getRaw('messenger', 'server_chan_enable'):
                    success_message = "预约成功，已获得抢购资格 / 您已成功预约过了，无需重复预约"
                    send_wechat(success_message)
                break
            except Exception as e:
                logger.error('预约失败正在重试...', e)
            wait_some_time()

    def get_sku_title(self):
        """获取商品名称"""
        url = 'https://item.jd.com/{}.html'.format(global_config.getRaw('config', 'sku_id'))
        resp = self.session.get(url).content
        x_data = etree.HTML(resp)
        sku_title = x_data.xpath('/html/head/title/text()')
        return sku_title[0]
