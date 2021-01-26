#!/usr/bin/env python
# -*- encoding=utf8 -*-

import random
import time

from lxml import etree

from .config import global_config
from .logger import logger
from .login import QRLogin
from .param import JDTdudfp
from .session import SpiderSession
from .timer import Timer
from .util import (
    parse_json,
    send_wechat,
    wait_some_time, check_login_is_effective,
)


class JDSeckill(object):
    def __init__(self):
        self.spider_session = SpiderSession()
        self.spider_session.load_cookies_from_local()

        self.qr_login = QRLogin(self.spider_session)
        self.jd_tdudfp = JDTdudfp(self.spider_session)

        # 初始化信息
        self.sku_id = global_config.getRaw('config', 'sku_id')
        self.seckill_num = int(global_config.getRaw('config', 'seckill_num'))
        self.seckill_order_data = dict()

        self.session = self.spider_session.get_session()
        self.user_agent = self.spider_session.user_agent
        self.nick_name = self.spider_session.get_username()

        # 定时任务
        self.timers = Timer()

        # 抢购信息
        self.seckill_url_flag = True
        self.seckill_url = dict()
        self.seckill_init_info = dict()

        self.work_count = global_config.getRaw('config', 'work_count')
        self.running_flag = True

    @check_login_is_effective
    def seckill(self):
        """
        抢购
        """
        # 1.获取抢购信息-用于显示
        logger.info("STEP-1:获取抢购信息")
        logger.info('用户:{}'.format(self.nick_name))
        logger.info('商品名称:{}'.format(self.get_sku_title()))
        # 2.检测配置时间是否符合要求
        logger.info("STEP-2:检测配置时间是否符合要求")
        self.timers.seckill_can_running()
        # 3.判断当前时间是否到达抢购时间。没到达则挂起
        logger.info("STEP-3:判断当前时间是否到达抢购时间。没到达则挂起")
        self.timers.start()
        # 4.获取商品的抢购链接
        logger.info("STEP-4:获取商品的抢购链接")
        self.get_seckill_url()
        # 获取秒杀初始化信息（包括：地址，发票，token）
        logger.info("STEP-5:获取秒杀初始化信息,包括：地址，发票，token")
        self.get_seckill_init_info()
        # 访问商品抢购连接
        logger.info("STEP-6:访问商品抢购连接，结算页面，提交抢购")

        self._seckill()
        """
        TODO
        多进程进行抢购
        work_count：进程数量
        """
        # with ProcessPoolExecutor(self.work_count) as pool:
        #     for i in range(self.work_count):
        #         pool.submit(self._seckill)

    # 抢购主体逻辑
    def _seckill(self):
        while self.running_flag:
            self.timers.seckill_can_running()
            try:
                # 访问商品的抢购链接
                seckill_url_success = self.request_seckill_url()
                if not seckill_url_success:
                    continue
                while self.running_flag:
                    checkout_page_success = self.request_seckill_checkout_page()
                    if not checkout_page_success:
                        continue
                    is_success = self.submit_seckill_order()
                    if not is_success:
                        wait_some_time()
                        continue
                    else:
                        send_wechat("抢购成功")
                        self.running_flag = False
                        break
            except Exception as e:
                logger.info('抢购发生异常，稍后继续执行！e:{}'.format(e))
            wait_some_time()

    def get_sku_title(self):
        """获取商品名称"""
        url = 'https://item.jd.com/{}.html'.format(global_config.getRaw('config', 'sku_id'))
        resp = self.session.get(url).content
        x_data = etree.HTML(resp)
        sku_title = x_data.xpath('/html/head/title/text()')
        return sku_title[0]

    def get_seckill_url(self):
        """获取商品的抢购链接
        点击"抢购"按钮后，会有两次302跳转，最后到达订单结算页面
        这里返回第一次跳转后的页面url，作为商品的抢购链接
        :return: 商品的抢购链接
        """
        url = 'https://itemko.jd.com/itemShowBtn'
        payload = {
            'callback': 'jQuery{}'.format(random.randint(1000000, 9999999)),
            'skuId': self.sku_id,
            'from': 'pc',
            '_': str(int(time.time() * 1000)),
        }
        headers = {
            'User-Agent': self.user_agent,
            'Host': 'itemko.jd.com',
            'Referer': 'https://item.jd.com/{}.html'.format(self.sku_id),
        }
        finish = False
        while not finish:
            try:
                resp = self.session.get(url=url, headers=headers, params=payload)
                resp_json = parse_json(resp.text)
                logger.info("抢购链接获取 返回：{}".format(resp_json))
                if resp_json.get('url'):
                    # https://divide.jd.com/user_routing?skuId=8654289&sn=c3f4ececd8461f0e4d7267e96a91e0e0&from=pc
                    router_url = 'https:' + resp_json.get('url')
                    # https://marathon.jd.com/captcha.html?skuId=8654289&sn=c3f4ececd8461f0e4d7267e96a91e0e0&from=pc
                    seckill_url = router_url.replace('divide', 'marathon').replace('user_routing', 'captcha.html')
                    logger.info("抢购链接获取成功: {}".format(seckill_url))
                    self.seckill_url[self.sku_id] = seckill_url
                    finish = True
                    logger.info("抢购链接获取成功: 开始抢购...")
                else:
                    logger.info("抢购链接获取失败，稍后自动重试")
                    wait_some_time()
            except Exception as e:
                logger.info('获取商品的抢购链接异常'.format(e))

    # 获取秒杀初始化信息（包括：地址，发票，token）return: 初始化信息组成的dict
    def get_seckill_init_info(self):
        finish = False
        while not finish:
            url = 'https://marathon.jd.com/seckillnew/orderService/pc/init.action'
            logger.info('获取秒杀初始化信息...')
            data = {
                'sku': self.sku_id,
                'num': self.seckill_num,
                'isModifyAddress': 'false',
            }
            headers = {
                'User-Agent': self.user_agent,
                'Host': 'marathon.jd.com',
            }
            resp = self.session.post(url=url, data=data, headers=headers)
            logger.info("获取秒杀初始化信息:{}".format(resp))
            try:
                resp_json = parse_json(resp.text)
                self.seckill_init_info[self.sku_id] = resp_json
                logger.info("获取秒杀初始化信息:地址，发票，token 等:{}".format(resp_json))
                finish = True
            except Exception as e:
                logger.info('获取秒杀初始化信息失败,e:{}'.format(e))

    # 访问商品的抢购链接（用于设置cookie等）
    def request_seckill_url(self):
        logger.info('访问商品的抢购连接...')
        headers = {
            'User-Agent': self.user_agent,
            'Host': 'marathon.jd.com',
            'Referer': 'https://item.jd.com/{}.html'.format(self.sku_id),
        }
        try:
            resp = self.session.get(url=self.seckill_url.get(self.sku_id), headers=headers, allow_redirects=False)
            logger.info("访问商品的抢购链接 返回:{}".format(resp))
            return resp.ok
        except Exception as e:
            logger.info("访问商品的抢购链接 异常:{}".format(e))
            return False

    # 访问抢购订单结算页面
    def request_seckill_checkout_page(self):
        logger.info('访问抢购订单结算页面...')
        url = 'https://marathon.jd.com/seckill/seckill.action'
        payload = {
            'skuId': self.sku_id,
            'num': self.seckill_num,
            'rid': int(time.time())
        }
        headers = {
            'User-Agent': self.user_agent,
            'Host': 'marathon.jd.com',
            'Referer': 'https://item.jd.com/{}.html'.format(self.sku_id),
        }
        try:
            resp = self.session.get(url=url, params=payload, headers=headers, allow_redirects=False)
            logger.info("抢购订单结算页面 返回:{}".format(resp.ok))
            return resp.ok
        except Exception as e:
            logger.info("抢购订单结算页面 异常:{}".format(e))
            return False

    # 访问抢购订单结算页面
    def submit_seckill_order(self):
        url = 'https://marathon.jd.com/seckillnew/orderService/pc/submitOrder.action'
        payload = {
            'skuId': self.sku_id,
        }
        try:
            self.seckill_order_data[self.sku_id] = self._get_seckill_order_data()
        except Exception as e:
            logger.info('抢购失败，无法获取生成订单的基本信息，接口返回:【{}】'.format(str(e)))
            return False

        logger.info('提交抢购订单...')
        headers = {
            'User-Agent': self.user_agent,
            'Host': 'marathon.jd.com',
            'Referer': 'https://marathon.jd.com/seckill/seckill.action?skuId={0}&num={1}&rid={2}'.format(
                self.sku_id, self.seckill_num, int(time.time())),
        }
        order_data = self.seckill_order_data.get(self.sku_id)
        resp = self.session.post(url=url, params=payload, data=order_data, headers=headers)
        try:
            resp_json = parse_json(resp.text)
        except Exception as e:
            logger.info('抢购失败 异常:{}，信息：{}'.format(e, resp.text))
            return False
        # 返回信息
        # 抢购失败：
        # {'errorMessage': '很遗憾没有抢到，再接再厉哦。', 'orderId': 0, 'resultCode': 60074, 'skuId': 0, 'success': False}
        # {'errorMessage': '抱歉，您提交过快，请稍后再提交订单！', 'orderId': 0, 'resultCode': 60017, 'skuId': 0, 'success': False}
        # {'errorMessage': '系统正在开小差，请重试~~', 'orderId': 0, 'resultCode': 90013, 'skuId': 0, 'success': False}
        # 抢购成功：
        # {"appUrl":"xxxxx","orderId":820227xxxxx,"pcUrl":"xxxxx","resultCode":0,"skuId":0,"success":true,"totalMoney":"xxxxx"}
        if resp_json.get('success'):
            order_id = resp_json.get('orderId')
            total_money = resp_json.get('totalMoney')
            pay_url = 'https:' + resp_json.get('pcUrl')
            logger.info('抢购成功，订单号:{}, 总价:{}, 电脑端付款链接:{}'.format(order_id, total_money, pay_url))
            return True
        else:
            logger.info('抢购失败，返回信息:{}'.format(resp_json))
            return False

    def _get_seckill_order_data(self):
        """生成提交抢购订单所需的请求体参数
        :return: 请求体参数组成的dict
        """
        logger.info('生成提交抢购订单所需参数...')
        init_info = self.seckill_init_info.get(self.sku_id)
        default_address = init_info['addressList'][0]  # 默认地址dict
        invoice_info = init_info.get('invoiceInfo', {})  # 默认发票信息dict, 有可能不返回
        token = init_info['token']
        data = {
            'skuId': self.sku_id,
            'num': self.seckill_num,
            'addressId': default_address['id'],
            'yuShou': 'true',
            'isModifyAddress': 'false',
            'name': default_address['name'],
            'provinceId': default_address['provinceId'],
            'cityId': default_address['cityId'],
            'countyId': default_address['countyId'],
            'townId': default_address['townId'],
            'addressDetail': default_address['addressDetail'],
            'mobile': default_address['mobile'],
            'mobileKey': default_address['mobileKey'],
            'email': default_address.get('email', ''),
            'postCode': '',
            'invoiceTitle': invoice_info.get('invoiceTitle', -1),
            'invoiceCompanyName': '',
            'invoiceContent': invoice_info.get('invoiceContentType', 1),
            'invoiceTaxpayerNO': '',
            'invoiceEmail': '',
            'invoicePhone': invoice_info.get('invoicePhone', ''),
            'invoicePhoneKey': invoice_info.get('invoicePhoneKey', ''),
            'invoice': 'true' if invoice_info else 'false',
            'password': global_config.getRaw('account', 'payment_pwd'),
            'codTimeType': 3,
            'paymentType': 4,
            'areaCode': '',
            'overseas': 0,
            'phone': '',
            'eid': self.jd_tdudfp.get("eid") if self.jd_tdudfp.get("eid") else global_config.getRaw('config', 'eid'),
            'fp': self.jd_tdudfp.get("fp") if self.jd_tdudfp.get("fp") else global_config.getRaw('config', 'fp'),
            'token': token,
            'pru': ''
        }
        logger.info("order_date：%s", data)
        return data
