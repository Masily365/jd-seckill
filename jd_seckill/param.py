#!/usr/bin/env python
# -*- encoding=utf8 -*-

import asyncio

from .exception import SKException
from .logger import logger
from .session import SpiderSession


class JDTdudfp:
    def __init__(self, sp: SpiderSession):
        self.cookies = sp.get_cookies()
        self.user_agent = sp.get_user_agent()
        self.spider_session = sp

        self.is_init = False
        self.jd_tdudfp = None

    def init_jd_tdudfp(self):
        self.is_init = True

        loop = asyncio.get_event_loop()
        get_future = asyncio.ensure_future(self._get())
        loop.run_until_complete(get_future)
        self.jd_tdudfp = get_future.result()

    def get(self, key):
        return self.jd_tdudfp.get(key) if self.jd_tdudfp else None

    async def _get(self):
        jd_tdudfp = None
        try:
            from pyppeteer import launch
            url = "https://www.jd.com/"
            browser = await launch(userDataDir=".user_data", autoClose=True,
                                   args=['--start-maximized', '--no-sandbox', '--disable-setuid-sandbox'])
            page = await browser.newPage()
            await page.setViewport({"width": 1920, "height": 1080})
            await page.setUserAgent(self.user_agent)
            for key, value in self.cookies.items():
                await page.setCookie({"domain": ".jd.com", "name": key, "value": value})
            await page.goto(url)
            await page.waitFor(".nickname")
            logger.info("page_title:【%s】, page_url【%s】" % (await page.title(), page.url))

            nick_name = await page.querySelectorEval(".nickname", "(element) => element.textContent")
            if not nick_name:
                logger.info("昵称获取失败！")
                # 如果未获取到用户昵称，说明可能登陆失败，放弃获取 _JdTdudfp
                return jd_tdudfp
            # 直接进入购物车找到商品经行结算
            a_href = 'https://cart.jd.com/cart_index/'
            await page.goto(a_href)
            jd_tdudfp = await page.evaluate("() => {try{return {eid:_JdEid,fp:_JdJrTdRiskFpInfo}}catch(e){}}")
            await page.close()
        except Exception as e:
            logger.info("自动获取JdTdudfp发生异常，将从配置文件读取！")
        logger.info("jd_tdudfp ：【%s】" % jd_tdudfp)
        return jd_tdudfp

    def is_init_jd_tdudfp(self):
        if self.is_init:
            logger.info('已获取_JdTdudfp')
        elif not self.is_init:
            logger.info('初始化_JdTdudfp')
            self.init_jd_tdudfp()
        else:
            raise SKException("获取_JdTdudfp失败！")
