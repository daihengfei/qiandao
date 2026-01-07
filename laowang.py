from asyncio.log import logger
import base64
import os
import random
import re
import sys
import time
import requests
from DrissionPage import ChromiumPage, ChromiumOptions
from PIL import Image
from io import BytesIO
import cv2
import numpy as np

# 缺口识别参数配置池
# MATCH_STRATEGIES = [
#     {
#         "name": "Sobel Gradient",
#         "method": "sobel",      # 新增方法字段
#         "blur": 3,
#         "clahe": False
#     },

#     {
#         "name": "Sobel CLAHE",
#         "method": "sobel",
#         "blur": 3,
#         "clahe": True
#     },

#     {
#         "name": "Standard Edge", 
#         "method": "canny",
#         "blur": 3,
#         "canny": (50, 150),
#         "dilate": 1,
#         "clahe": False
#     },
    
#     {
#         "name": "Sensitive Edge",
#         "method": "canny",
#         "blur": 5,
#         "canny": (20, 60),
#         "dilate": 1,
#         "clahe": False
#     },

#     {
#         "name": "Grayscale Direct",
#         "method": "gray",
#         "blur": 0,
#         "clahe": False
#     }
# ]

class LaoWangSign:
    proxies = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}
    retry_count = 0

    def __init__(
        self,
        hostname,
        username,
        password,
        cookie,
        questionid="0",
        answer=None,
        proxies=None,
    ):
        self.session = requests.session()
        self.hostname = hostname
        self.username = username
        self.password = password
        self.cookie = cookie
        self.questionid = questionid
        self.answer = answer
        if proxies:
            self.proxies = proxies

    @classmethod
    def user_sign(
        cls,
        hostname,
        username,
        password,
        cookie,
        questionid="0",
        answer=None,
        proxies=None,
    ):
        user = LaoWangSign(
            hostname, username, password, cookie, questionid, answer, proxies
        )
        # 尝试处理验证码
        user.check_verity_code()

        return user

    def check_verity_code(self):
        # # 使用DrissionPage访问页面
        # 配置选项
        co = ChromiumOptions()
        co.set_proxy("http://127.0.0.1:7890")
        co.set_argument("--disable-gpu")  # 禁用 GPU（服务器通常没有）
        co.set_argument("--disable-dev-shm-usage")  # 解决共享内存不足崩溃
        co.headless(True)
        co.set_argument('--headless=new')
        co.set_argument("--no-sandbox")  # 解决 root 用户运行崩溃
        # co.set_argument('--window-size=1920,1080')
        # 设置 User-Agent
        co.set_user_agent(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
        )
        page = ChromiumPage(co)
        try:
            # page.run_cdp('Network.clearBrowserCookies')
            page.get(f"https://{self.hostname}")
            page.set.cookies(self.cookie)
            print("正在访问...")
            page.get(f"https://{self.hostname}/plugin.php?id=k_misign:sign")

            page.wait.load_start()

            # 检查是否还在验证页
            if (
                "Just a moment" in page.title
                or "正在验证" in page.html
                or "验证您是真人" in page.html
            ):
                print("遇到验证盾，等待通过...")
                time.sleep(10) 

            # 获取真实标题
            print("当前标题:", page.title)
            self.retry_count = 0
            if "action=login" in page.html:
                print("⚠️ 当前用户未登录")
                login = self.login(page)
                if login:
                    print("✅ 登录成功")
                    time.sleep(5)
                    if '每日签到老王论坛' not in page.title:
                        print("⚠️ 当前页面不是每日签到页面, 即将跳转到签到页面...")
                        page.get(f"https://{self.hostname}/plugin.php?id=k_misign:sign")
                        time.sleep(5)
                else:
                    print("❌ 登录失败")
                    return False

            sign_button = page.ele(
                'css:a.J_chkitot[href*="operation=qiandao"]', timeout=5
            )
            if sign_button:
                print("✅ 找到签到按钮")
                sign_button.click()
                print("👆 已点击签到按钮，等待签到结果...")
                time.sleep(2)
                result = self.click_tncode(page)
                if result:
                    if page.wait.ele_displayed("#submit-btn", timeout=5):
                        submit = page.ele("#submit-btn", timeout=10)
                        print("👆 提交表单...")
                        submit.click()
                        time.sleep(10)
                        if '<span class="btn btnvisted"></span>' in page.html:
                            print("✅ 签到成功！")
                            self.parse_person_info(page)
                        else:
                            print("❌ 签到失败！")
                        time.sleep(20)
                        return True
                    else:
                        print("❌ 没有找到提交按钮")
            else:
                time.sleep(5)
                if '<span class="btn btnvisted"></span>' in page.html:
                    print("✅ 已签到")
                    self.parse_person_info(page)
                else:
                    print("❌ 未找到签到按钮")
            return False
        except Exception as e:
            print(f"验证码识别失败: {e}")
            return False
        finally:
            if "page" in locals():
                page.quit()

    def click_tncode(self, page: ChromiumPage) -> bool:
        # 点击验证按钮
        if page.wait.ele_displayed("#tncode", timeout=15):
            print("✅ 找到验证按钮")
            btn = page.ele("#tncode", timeout=10)
            btn.click()
            print("👆 已点击按钮，等待滑块弹出...")

            return self.verify_captcha(page, retry=True)
        else:
            print("❌ 超时：没有找到 #tncode 按钮")
        return False

    def verify_captcha(self, page: ChromiumPage, retry=False) -> bool:
        self.retry_count = self.retry_count + 1
        print(f"开始第{self.retry_count}次验证滑块...")
        if page.wait.ele_displayed(".slide_block", timeout=10):
            print("🧩 滑块已弹出，准备识别和滑动...")
            # 获取滑块元素
            slider = page.ele(".slide_block", timeout=10)
            time.sleep(1)
            print("👆 滑块已点击，🧩 获取缺口图片...")
            if page.wait.ele_displayed(".tncode_canvas_bg", timeout=5):
                print("🎭 执行假动作：点击滑块，触发缺口显示...")
                slider.click()
                print("💤 等待5S，让页面渲染缺口")
                time.sleep(5)
                bg_ele = page.ele(".tncode_canvas_bg", timeout=10)
                mark_ele = page.ele(".tncode_canvas_mark", timeout=10)  # 获取小滑块画布
                if bg_ele:
                    print("🖼️ 正在保存验证码背景图...")
                    print("🖼️ 通过 JS 获取原生 Canvas 数据...")
                    # 注入 JS 代码
                    js_bg = "return document.querySelector('.tncode_canvas_bg').toDataURL('image/png');"
                    js_mark = "return document.querySelector('.tncode_canvas_mark').toDataURL('image/png');"
                    # 执行并获取结果
                    b64_bg = page.run_js(js_bg)
                    b64_mark = page.run_js(js_mark)
                    if b64_bg and b64_mark:
                        # 解码 Base64
                        img_bytes = base64.b64decode(b64_bg.split(",")[1])
                        mark_bytes = base64.b64decode(b64_mark.split(",")[1])

                        print(f"💾 保存成功, {len(img_bytes)} bytes")
                        # 2. 调用OpenCV 识别
                        captcha_img = Image.open(BytesIO(img_bytes))
                        captcha_img.save("bg.png")
                        mark_img = Image.open(BytesIO(mark_bytes))
                        mark_img.save("mark.png")
                        # 计算缺口位置
                        # distance, confidence = self.get_gap_by_template_match("bg.png", "mark.png")
                        distance = self.get_gap_by_template_match("mark.png", "bg.png")

                        print(f"已计算缺口位置{distance}")
                        print(f"📏 识别距离: {distance}")
                        if distance > 0:
                            print(f"🚀 继续拖动剩余距离: {distance}")
                            # 继续移动剩余距离，然后松开
                            # 生成一个随机的拖动时长，范围 0.6 ~ 1.2 秒
                            # tncode 对时间敏感，不能太快也不能太慢
                            duration = random.uniform(0.6, 1.2)

                            print(
                                f"🚀 开始智能拖动，距离: {distance}, 耗时: {duration:.2f}s"
                            )
                            page.actions.hold(slider).move(distance, duration).release()
                        else:
                            print("❌ 距离计算异常，松开鼠标")
                            page.actions.release()

                        # 验证结果检查...
                        time.sleep(3)
                        if "验证成功" in page.html:
                            print("✅ 验证通过！")
                            return True
                        else:
                            if retry and self.retry_count <= 5:
                                print("❌ 验证失败，重新验证...")
                                tncode_refresh = page.ele(".tncode_refresh", timeout=10)
                                tncode_refresh.click()
                                print("💤 点击图片刷新按钮，待 5S 后重新识别")
                                time.sleep(5)
                                return self.verify_captcha(page, retry=True)
                            else:
                                print("❌ 验证失败！")
                else:
                    print("❌ 未找到背景 Canvas")
            else:
                print("❌ 点击了按钮，但图片没有加载出来")
        else:
            print("❌ 点击了按钮，但滑块没有弹出来")

        return False
    
    def get_gap_by_template_match(self, mark_path, bg_path):
        # 使用 IMREAD_UNCHANGED 读取，以防图片包含透明通道(Alpha)
        mark = cv2.imread(mark_path, cv2.IMREAD_UNCHANGED)
        bg = cv2.imread(bg_path)
        
        if mark is None or bg is None:
            print("错误：无法读取图片")
            return

        print("Step 1: 提取滑块形状...")
        # 判断是否包含 Alpha 通道 (透明背景)
        if mark.shape[2] == 4:
            # 如果是 PNG 透明图，直接取第4个通道(Alpha)作为掩码
            print("检测到透明通道，直接使用Alpha层")
            mask = mark[:, :, 3]
        else:
            # 如果是 JPG 或黑底图，转灰度后取阈值
            print("未检测到透明通道，使用灰度阈值法")
            mark_gray = cv2.cvtColor(mark, cv2.COLOR_BGR2GRAY)
            # 只要像素值大于 10 (不是纯黑)，就认为是滑块的一部分
            _, mask = cv2.threshold(mark_gray, 10, 255, cv2.THRESH_BINARY)

        # 寻找轮廓
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            print("错误：无法提取滑块轮廓")
            return
        
        # 取最大轮廓
        c = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(c)
        print(f"   滑块尺寸: {w}x{h}")

        # 裁切掩码作为模板
        template_roi = mask[y:y+h, x:x+w]
        
        # 提取边缘Mask (Canny) 
        template_edge = cv2.Canny(template_roi, 100, 200)

        print("Step 2: 处理背景...")
        bg_gray = cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY)
        # 直方图均衡化 (增强缺口阴影对比度)
        bg_eq = cv2.equalizeHist(bg_gray)
        # 边缘检测
        bg_edge = cv2.Canny(bg_eq, 50, 200)
        
        # 锁定Y轴区域 
        search_y_start = max(0, y - 10)
        search_y_end = min(bg_edge.shape[0], y + h + 10)
        bg_strip = bg_edge[search_y_start:search_y_end, :]

        print("Step 3: 匹配中...")
        res = cv2.matchTemplate(bg_strip, template_edge, cv2.TM_CCOEFF_NORMED)
        # 屏蔽左侧区域,防止匹配到滑块起始位置
        # 屏蔽宽度设为滑块宽度的 1.2 倍
        safe_margin = int(w * 1.2)
        if res.shape[1] > safe_margin:
            res[:, :safe_margin] = -1.0
            
        # 可视化热力图
        res_vis = cv2.normalize(res, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
        
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
        best_x = max_loc[0]
        best_y = search_y_start + max_loc[1]

        print("Step 4: 输出结果...")
        result_img = bg.copy()
        cv2.rectangle(result_img, (best_x, best_y), (best_x + w, best_y + h), (0, 0, 255), 2)
        
        # 画一下搜索区域辅助线
        cv2.rectangle(result_img, (0, search_y_start), (bg.shape[1], search_y_end), (0, 255, 0), 1)
        
        print("-" * 30)
        print(f"【最终结果】")
        print(f"缺口坐标: X={best_x}")
        print("-" * 30)

        return best_x
    
    def parse_person_info(self, page: ChromiumPage):
        print("5S 后，开始解析个人资料")
        time.sleep(5)
        deanvwmy = page.ele('.deanvwmy', timeout=10)
        if deanvwmy:
            space_url = deanvwmy.link
            print(f"✅ 访问空间: {space_url}")
            page.get(space_url)   
        rmb_em = page.ele('tag:em@@text():软妹币')

        if rmb_em:
            rmb_li = rmb_em.parent()
            full_text = rmb_li.text
            
            # 使用正则提取其中的数字
            # \d+ 表示匹配连续的数字
            match = re.search(r'(\d+)', full_text)
            
            if match:
                rmb_count = match.group(1)
                print(f"💰 软妹币: {rmb_count}")
            else:
                print(f"⚠️ 正则未匹配到，原始文本为: {full_text}")
        else:
            print("❌ 未找到包含‘软妹币’的标签")

        group_label = page.ele('text:用户组')
        if group_label:
            group_info_span = group_label.next('tag:span')
            
            if group_info_span:
                # 获取名称
                group_name = group_info_span.text
                
                # 获取属性 tip
                group_tip = group_info_span.attr('tip')
                
                print(f"🔰 用户组: {group_name}")
                print(f"📝 详细Tip: {group_tip}")

    def login(self, page: ChromiumPage) -> bool:
        # 清除所有Cookie
        page.run_cdp('Network.clearBrowserCookies')
        login_url = f"https://{self.hostname}/member.php?mod=logging&action=login"
        print(f"跳转登录页: {login_url}")
        page.get(login_url)

        page.wait.load_start()

        print(page.title)

        print("📝 正在填写账号密码...")
        user_input = page.ele('css:input[id^="username_"]', timeout=10)
        if user_input:
            print("✅ 找到用户名输入框")
            user_input.input(self.username)
        else:
            print("❌ 未找到用户名输入框，请检查页面是否还在加载")
            return False
        pass_input = page.ele('css:input[id^="password3_"]', timeout=10)
        if pass_input:
            print("✅ 找到密码输入框")
            pass_input.input(self.password)
        else:
            print("❌ 未找到密码输入框，请检查页面是否还在加载")
            return False
        if self.questionid != '0':
            print("🔒 选择安全提问...")
            
            # 直接根据 value 选择
            page.ele('css:select[id^="loginquestionid_"]').select.by_value(self.questionid)
            
            # 稍微等待一下输入框显示
            ans_input = page.wait.ele_displayed('css:input[id^="loginanswer_"]')
            if ans_input:
                page.ele('css:input[id^="loginanswer_"]').input(self.answer)
        print("🛡️ 点击验证码...")
        if self.click_tncode(page):
            print("📝 提交登录表单...")
            page.ele('#captcha_submit').click()
            print("⏳ 等待登录跳转...")
            time.sleep(5)
            if "action=login" not in page.html:
                print("🎉 登录 Cookie 已写入！")
                # 双重保险：强制刷新一次，确保 Cookie 生效
                page.refresh() 
                return True
            else:
                print("❌ 登录失败")
                # 如果没等到用户菜单，检查是否有错误提示
                err_msg = page.ele('.alert_error', timeout=10)
                if err_msg:
                    print(f"❌ 登录报错: {err_msg.text}")
                else:
                    print("❌ 登录超时，未检测到登录状态变更")
        else:
            print("❌ 验证码失败")


        return False

if __name__ == '__main__':
    try:
        # laowang.vip 签到
        laowang_url = os.environ.get('LAOWANG_HOSTNAME', '')
        laowang_username = os.environ.get('LAOWANG_USERNAME', "")
        laowang_password = os.environ.get('LAOWANG_PASSWORD', "")
        laowang_cookie = os.environ.get('LAOWANG_COOKIE', "")
        laowang_password = 'base64://' + base64.b64encode(laowang_password.encode('utf-8')).decode('utf-8')
        LaoWangSign.user_sign(laowang_url, laowang_username, laowang_password, laowang_cookie)

    except Exception as e:
        logger.error(e)
        sys.exit(1)

 # def get_gap_by_template_match(self, bg_image, mark_image):
    #     """
    #     利用滑块图片(mark)作为模板，在背景(bg)中寻找缺口
    #     特性：Y轴锁定 + 纯轮廓/灰度混合 + 自适应参数重试机制
    #     """
    #     import cv2
    #     import numpy as np

    #     # 1. 图像转 OpenCV 格式
    #     bg = np.array(bg_image)
    #     mark = np.array(mark_image)

    #     if len(bg.shape) == 3 and bg.shape[2] == 4:
    #         bg = cv2.cvtColor(bg, cv2.COLOR_RGBA2BGR)
    #     elif len(bg.shape) == 3 and bg.shape[2] == 3:
    #         bg = cv2.cvtColor(bg, cv2.COLOR_RGB2BGR)

    #     debug_img = bg.copy()

    #     # =========================================================
    #     # 第一步：提取滑块坐标
    #     # =========================================================
    #     x, y, w, h = 0, 0, 0, 0
    #     valid_template_found = False

    #     if len(mark.shape) == 3 and mark.shape[2] == 4:
    #         alpha = mark[:, :, 3]
    #         _, thresh = cv2.threshold(alpha, 128, 255, cv2.THRESH_BINARY)
    #         contours, _ = cv2.findContours(
    #             thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    #         )

    #         for contour in contours:
    #             cx, cy, cw, ch = cv2.boundingRect(contour)
    #             if 35 < cw < 90 and 35 < ch < 90 and 0.7 < cw / ch < 1.4:
    #                 x, y, w, h = cx, cy, cw, ch
    #                 valid_template_found = True
    #                 cv2.rectangle(debug_img, (x, y), (x + w, y + h), (0, 255, 0), 2)
    #                 break

    #     if not valid_template_found:
    #         print("⚠️ 无法提取滑块，使用兜底逻辑")
    #         return 0

    #     # 提取滑块纯 Alpha 形状
    #     template_alpha = mark[y : y + h, x : x + w, 3]

    #     # =========================================================
    #     # 定义核心匹配函数 (支持不同参数)
    #     # =========================================================
    #     def try_match(
    #         strategy_name, blur_ksize, canny_thresh, dilate_iter, use_gray=False
    #     ):
    #         """
    #         内部函数：尝试使用指定参数进行匹配
    #         """
    #         # 1. 准备模板
    #         if use_gray:
    #             # 灰度模式：使用 mark 的灰度图作为模板
    #             # (注意：因为背景复杂，灰度模式通常不如边缘模式，仅作兜底)
    #             mark_gray = cv2.cvtColor(mark, cv2.COLOR_RGBA2GRAY)
    #             template_processed = mark_gray[y : y + h, x : x + w]
    #             bg_processed = cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY)
    #         else:
    #             # 边缘模式：制作边缘模板
    #             _, template_bin = cv2.threshold(
    #                 template_alpha, 128, 255, cv2.THRESH_BINARY
    #             )
    #             template_edge = cv2.Canny(template_bin, 100, 200)
    #             if dilate_iter > 0:
    #                 kernel = np.ones((3, 3), np.uint8)
    #                 template_processed = cv2.dilate(
    #                     template_edge, kernel, iterations=dilate_iter
    #                 )
    #             else:
    #                 template_processed = template_edge

    #             # 处理背景
    #             bg_gray = cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY)
    #             # 高斯模糊
    #             if blur_ksize > 0:
    #                 bg_blur = cv2.GaussianBlur(bg_gray, (blur_ksize, blur_ksize), 0)
    #             else:
    #                 bg_blur = bg_gray

    #             # 边缘检测
    #             bg_edge = cv2.Canny(bg_blur, canny_thresh[0], canny_thresh[1])
    #             # 膨胀
    #             if dilate_iter > 0:
    #                 kernel = np.ones((3, 3), np.uint8)
    #                 bg_processed = cv2.dilate(bg_edge, kernel, iterations=dilate_iter)
    #             else:
    #                 bg_processed = bg_edge

    #         # 2. 锁定 Y 轴搜索区域
    #         y_margin = 0  # 严格锁定
    #         x_padding = 5  # 右边距

    #         search_y_start = y
    #         search_y_end = y + h
    #         x_start = x + w
    #         x_end = bg.shape[1] - x_padding

    #         # 边界保护
    #         if search_y_end > bg_processed.shape[0]:
    #             search_y_end = bg_processed.shape[0]

    #         # 截取搜索条
    #         search_region = bg_processed[search_y_start:search_y_end, x_start:x_end]

    #         # 尺寸对齐 (防止 Canny 后尺寸微差)
    #         if search_region.shape[0] != template_processed.shape[0]:
    #             template_processed = cv2.resize(
    #                 template_processed,
    #                 (template_processed.shape[1], search_region.shape[0]),
    #             )

    #         # 3. 匹配
    #         res = cv2.matchTemplate(
    #             search_region, template_processed, cv2.TM_CCOEFF_NORMED
    #         )
    #         _, max_val, _, max_loc = cv2.minMaxLoc(res)

    #         matched_x_rel = max_loc[0]
    #         absolute_x = matched_x_rel + x_start

    #         return absolute_x, max_val

    #     # =========================================================
    #     # 第二步：自适应策略循环 (递归/重试逻辑)
    #     # =========================================================

    #     # 定义策略列表：[名称, 模糊核大小, Canny阈值, 膨胀次数, 是否灰度]
    #     strategies = [
    #         # 策略 1: 敏感模式 (抓极淡的阴影) - 之前成功的配置
    #         ("Sensitive Edge", 5, (20, 60), 1, False),
    #         # 策略 2: 标准模式 (抓清晰轮廓) - 阈值稍高，防止噪点
    #         ("Standard Edge", 3, (50, 150), 1, False),
    #         # 策略 3: 强力模式 (无模糊，直接干) - 适合纹理不多的背景
    #         ("Raw Edge", 0, (30, 100), 1, False),
    #         # 策略 4: 极简模式 (不膨胀) - 适合缺口边缘非常细的情况
    #         ("Thin Edge", 3, (40, 120), 0, False),
    #         # 策略 5: 灰度匹配兜底 (如果边缘检测彻底失效)
    #         ("Grayscale Fallback", 0, (0, 0), 0, True),
    #     ]

    #     best_result = (0, 0)  # (x, confidence)
    #     final_strategy_name = ""

    #     print(f"🧩 开始多策略匹配 (目标置信度 > 0.4)...")

    #     for strat in strategies:
    #         name, blur, canny, dilate, is_gray = strat

    #         # 执行匹配
    #         curr_x, curr_conf = try_match(name, blur, canny, dilate, is_gray)

    #         print(f"  👉 [{name}]: 置信度 {curr_conf:.2f}, 位置 {curr_x}")

    #         # 记录历史最佳
    #         if curr_conf > best_result[1]:
    #             best_result = (curr_x, curr_conf)
    #             final_strategy_name = name

    #         # 【核心逻辑】如果置信度达标，直接中断循环 (相当于递归基准条件)
    #         if curr_conf > 0.4:
    #             print(f"✅ 置信度达标，提前结束！")
    #             break

    #     # =========================================================
    #     # 第三步：处理最终结果
    #     # =========================================================

    #     final_x, final_conf = best_result
    #     print(
    #         f"🏆 最终选用 [{final_strategy_name}]: 置信度 {final_conf:.2f}, 位置 {final_x}"
    #     )

    #     # 画红框
    #     cv2.rectangle(debug_img, (final_x, y), (final_x + w, y + h), (0, 0, 255), 2)
    #     cv2.putText(
    #         debug_img,
    #         f"{final_strategy_name}: {final_conf:.2f}",
    #         (final_x, y - 5),
    #         cv2.FONT_HERSHEY_SIMPLEX,
    #         0.4,
    #         (0, 0, 255),
    #         1,
    #     )

    #     cv2.imwrite("debug_final_result.png", debug_img)

    #     real_distance = final_x - x
    #     if real_distance < 0:
    #         return final_x

    #     return real_distance, final_conf

    # def get_gap_by_template_match(self, bg_image, mark_image):
    #     import cv2
    #     import numpy as np

    #     # 1. 预处理
    #     bg = np.array(bg_image)
    #     mark = np.array(mark_image)
    #     if len(bg.shape) == 3 and bg.shape[2] == 4:
    #         bg = cv2.cvtColor(bg, cv2.COLOR_RGBA2BGR)
    #     elif len(bg.shape) == 3 and bg.shape[2] == 3:
    #         bg = cv2.cvtColor(bg, cv2.COLOR_RGB2BGR)

    #     # 提取滑块
    #     slider_x, slider_y, slider_w, slider_h = 0, 0, 0, 0
    #     if len(mark.shape) == 3 and mark.shape[2] == 4:
    #         alpha = mark[:, :, 3]
    #         _, thresh = cv2.threshold(alpha, 128, 255, cv2.THRESH_BINARY)
    #         contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    #         for contour in contours:
    #             cx, cy, cw, ch = cv2.boundingRect(contour)
    #             if 35 < cw < 90 and 35 < ch < 90 and 0.7 < cw/ch < 1.4:
    #                 slider_x, slider_y, slider_w, slider_h = cx, cy, cw, ch
    #                 break 
        
    #     if slider_w == 0: slider_x, slider_y, slider_w, slider_h = 0, 0, 60, 60

    #     # 提取模板
    #     template_alpha = mark[slider_y:slider_y+slider_h, slider_x:slider_x+slider_w, 3]
        
    #     # 准备灰度模板 (用于灰度模式)
    #     mark_gray_full = cv2.cvtColor(mark, cv2.COLOR_RGBA2GRAY)
    #     template_gray = mark_gray_full[slider_y:slider_y+slider_h, slider_x:slider_x+slider_w]

    #     # =========================================================
    #     # 定义单次匹配函数
    #     # =========================================================
    #     def run_single_match(params):
    #         bg_input = cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY)
            
    #         # 1. 预处理 (CLAHE / Blur)
    #         if params.get('clahe'):
    #             clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
    #             bg_input = clahe.apply(bg_input)
            
    #         if params.get('blur', 0) > 0:
    #             bg_input = cv2.GaussianBlur(bg_input, (params['blur'], params['blur']), 0)

    #         # 2. 根据方法生成 Search Img 和 Template Img
    #         method = params['method']
            
    #         if method == 'sobel':
    #             # --- Sobel 梯度模式 ---
    #             # 计算 x 和 y 方向的梯度
    #             grad_x = cv2.Sobel(bg_input, cv2.CV_32F, 1, 0, ksize=3)
    #             grad_y = cv2.Sobel(bg_input, cv2.CV_32F, 0, 1, ksize=3)
    #             # 计算梯度幅值 (同时包含横向和纵向特征)
    #             bg_processed = cv2.magnitude(grad_x, grad_y)
    #             # 归一化到 0-255
    #             bg_processed = cv2.normalize(bg_processed, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
                
    #             # 对模板做同样处理 (先用 Alpha 得到形状，再 Sobel)
    #             _, mask_bin = cv2.threshold(template_alpha, 128, 255, cv2.THRESH_BINARY)
    #             t_grad_x = cv2.Sobel(mask_bin, cv2.CV_32F, 1, 0, ksize=3)
    #             t_grad_y = cv2.Sobel(mask_bin, cv2.CV_32F, 0, 1, ksize=3)
    #             template_processed = cv2.magnitude(t_grad_x, t_grad_y)
    #             template_processed = cv2.normalize(template_processed, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)

    #         elif method == 'canny':
    #             # --- Canny 边缘模式 ---
    #             t1, t2 = params['canny']
    #             bg_processed = cv2.Canny(bg_input, t1, t2)
                
    #             _, mask_bin = cv2.threshold(template_alpha, 128, 255, cv2.THRESH_BINARY)
    #             template_processed = cv2.Canny(mask_bin, 100, 200)
                
    #             if params.get('dilate', 0) > 0:
    #                 kernel = np.ones((2, 2), np.uint8)
    #                 bg_processed = cv2.dilate(bg_processed, kernel, iterations=params['dilate'])
    #                 template_processed = cv2.dilate(template_processed, kernel, iterations=params['dilate'])

    #         else: # method == 'gray'
    #             # --- 灰度模式 ---
    #             bg_processed = bg_input
    #             template_processed = template_gray

    #         # 3. 区域限制 (Y轴锁定 + X轴最小距离)
    #         search_y_start = slider_y
    #         search_y_end = slider_y + slider_h
            
    #         # 【关键修改】强制 X 轴起点至少在滑块右边 25px 处
    #         # 你的上一次失败就是因为匹配到了 x=48 (紧贴滑块)，这里强制 +25 能过滤掉它
    #         min_gap_distance = 25 
    #         search_x_start = slider_x + slider_w + min_gap_distance
    #         search_x_end = bg.shape[1] - 5
            
    #         # 边界保护
    #         if search_y_end > bg_processed.shape[0]: search_y_end = bg_processed.shape[0]
    #         if search_x_start >= search_x_end: return 0, 0
            
    #         search_region = bg_processed[search_y_start:search_y_end, search_x_start:search_x_end]
            
    #         # 尺寸对齐
    #         if search_region.shape[0] != template_processed.shape[0]:
    #             template_processed = cv2.resize(template_processed, (template_processed.shape[1], search_region.shape[0]))

    #         # 4. 匹配
    #         try:
    #             res = cv2.matchTemplate(search_region, template_processed, cv2.TM_CCOEFF_NORMED)
    #             _, max_val, _, max_loc = cv2.minMaxLoc(res)
                
    #             # 如果是灰度模式，稍微降低一点它的权重，防止它抢风头
    #             if method == 'gray':
    #                 max_val -= 0.05 
                
    #             return max_loc[0] + search_x_start, max_val
    #         except:
    #             return 0, 0

    #     # =========================================================
    #     # 3. 主循环
    #     # =========================================================
    #     best_result = (0, 0)
    #     best_strategy = "None"
        
    #     print(f"🧩 启动自适应匹配 (Sobel增强版)...")
        
    #     for strat in MATCH_STRATEGIES:
    #         x_res, conf_res = run_single_match(strat)
    #         print(f"  👉 [{strat['name']:<15}]: Conf={conf_res:.2f}, X={x_res}")
            
    #         if conf_res > best_result[1]:
    #             best_result = (x_res, conf_res)
    #             best_strategy = strat['name']
            
    #         if conf_res > 0.55: # 提高一点达标门槛
    #             print(f"✅ 命中优质结果，提前结束！")
    #             break
        
    #     # =========================================================
    #     # 4. 结果返回
    #     # =========================================================
    #     final_x, final_conf = best_result
    #     print(f"🏆 最终选用 [{best_strategy}]: 置信度 {final_conf:.2f}, 位置 {final_x}")
        
    #     # 调试图
    #     debug_img = bg.copy()
    #     cv2.rectangle(debug_img, (final_x, slider_y), (final_x + slider_w, slider_y + slider_h), (0, 0, 255), 2)
    #     cv2.putText(debug_img, f"{best_strategy}:{final_conf:.2f}", (final_x, slider_y-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,0,255), 1)
    #     cv2.imwrite('debug_final_result.png', debug_img)

    #     real_distance = final_x - slider_x
    #     if real_distance < 0: return final_x, final_conf
    #     return real_distance, final_conf
