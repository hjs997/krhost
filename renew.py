#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Weirdhost 自动续期脚本 
"""

import asyncio
import os
import random
import re
import datetime
from datetime import timezone, timedelta
import requests
from patchright.async_api import async_playwright

# =====================================================================
#                          配置区域
# =====================================================================

PROXY_SERVER = os.getenv("PROXY_SERVER", "")
WEIRDHOST_EMAIL = os.getenv("WEIRDHOST_EMAIL", "")
WEIRDHOST_PASSWORD = os.getenv("WEIRDHOST_PASSWORD", "")
LOGIN_URL = "https://hub.weirdhost.xyz/auth/login"
DASHBOARD_URL = "https://hub.weirdhost.xyz/"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# =====================================================================
#                     Telegram 推送模块
# =====================================================================

class TelegramNotifier:
    def __init__(self, bot_token=None, chat_id=None):
        self.bot_token = bot_token or TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or TELEGRAM_CHAT_ID
        self.enabled = bool(self.bot_token and self.chat_id)

    def send_message(self, message, parse_mode="HTML"):
        if not self.enabled:
            return False
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            payload = {"chat_id": self.chat_id, "text": message, "parse_mode": parse_mode}
            response = requests.post(url, json=payload, timeout=10)
            return response.json().get("ok", False)
        except Exception as e:
            print(f"❌ Telegram 推送异常: {e}")
            return False

    def send_photo(self, photo_path, caption=None):
        if not self.enabled or not os.path.exists(photo_path):
            return False
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendPhoto"
            with open(photo_path, "rb") as f:
                files = {"photo": f}
                payload = {"chat_id": self.chat_id}
                if caption:
                    payload["caption"] = caption
                response = requests.post(url, data=payload, files=files, timeout=20)
                return response.json().get("ok", False)
        except Exception as e:
            print(f"❌ Telegram 图片发送异常: {e}")
            return False

    def send_renewal_result(self, status, old_time, new_time=None, run_time=None):
        beijing_time = datetime.datetime.now(timezone(timedelta(hours=8)))
        timestamp = run_time or beijing_time.strftime("%Y-%m-%d %H:%M:%S")

        message = f"<b>🎮 Weirdhost 续期通知</b>\n\n"
        message += f"🕐 运行时间: <code>{timestamp}</code>\n"
        message += f"🖥 服务器: <code>🇰🇷 Weirdhost(KR)</code>\n\n"

        if status == "Success":
            message += f"📊 续期结果: <b>✅ 成功</b>\n"
            message += f"🕛 旧到期: <code>{old_time}</code>\n"
            message += f"🕡 新到期: <code>{new_time}</code>\n"
        elif status == "Unexpired":
            message += f"📊 续期结果: <b>ℹ️ 未到期</b>\n"
            message += f"🕛 到期时间: <code>{old_time}</code>\n"
            message += f"💡 提示: 未进入 2 天以内的续期窗口期\n"
        else:
            message += f"📊 续期结果: <b>❌ 失败</b>\n"
            message += f"🕛 到期时间: <code>{old_time}</code>\n"

        return self.send_message(message)

# =====================================================================
#                Cloudflare Turnstile 智能过盾核心函数
# =====================================================================

async def _get_turnstile_token(page):
    try:
        return await page.evaluate(
            """
            () => {
                try {
                    if (window.turnstile && typeof window.turnstile.getResponse === 'function') {
                        let t = null;
                        try { t = window.turnstile.getResponse(); } catch (e) {}
                        if (t && t.length > 20) return t;
                        for (let i = 0; i < 5; i++) {
                            try { t = window.turnstile.getResponse(String(i)); } catch (e) { t = null; }
                            if (t && t.length > 20) return t;
                        }
                    }
                } catch (e) {}
                const inputs = document.querySelectorAll(
                    'input[name="cf-turnstile-response"], input[name="g-recaptcha-response"]'
                );
                for (const el of inputs) {
                    if (el.value && el.value.length > 20) return el.value;
                }
                return null;
            }
            """
        )
    except Exception:
        return None

async def solve_modal_turnstile(page, timeout=60):
    print("🛡️ 正在检测并处理 Cloudflare Turnstile 验证...")
    start_time = asyncio.get_event_loop().time()
    last_click = 0
    clicks = 0

    while asyncio.get_event_loop().time() - start_time < timeout:
        token = await _get_turnstile_token(page)
        if token:
            print("🎉 Cloudflare Turnstile 验证通过，成功获取 Token！")
            return True

        if asyncio.get_event_loop().time() - last_click > 5:
            try:
                clicked = False
                for frame in page.frames:
                    if "challenges.cloudflare.com" in (frame.url or ""):
                        checkbox = frame.locator('input[type="checkbox"], label, .cb-lb').first
                        if await checkbox.count() > 0:
                            await checkbox.click(timeout=2000)
                            print(f"🖱️ 第 {clicks + 1} 次：直接点击了复选框")
                            clicked = True
                            break

                if not clicked:
                    frames_handles = await page.query_selector_all('iframe[src*="challenges.cloudflare.com"]')
                    for handle in frames_handles:
                        box = await handle.bounding_box()
                        if box and box['width'] > 10 and box['height'] > 10:
                            x = box['x'] + random.uniform(20, 40)
                            y = box['y'] + box['height'] / 2 + random.uniform(-5, 5)
                            
                            await page.mouse.move(x - 40, y + random.uniform(-10, 10))
                            await asyncio.sleep(0.2)
                            await page.mouse.move(x, y)
                            await asyncio.sleep(0.1)
                            await page.mouse.down()
                            await asyncio.sleep(0.08)
                            await page.mouse.up()
                            
                            print(f"🖱️ 第 {clicks + 1} 次：通过拟人化坐标偏移点击 (x={int(x)}, y={int(y)})")
                            clicked = True
                            break

                if clicked:
                    clicks += 1
                    last_click = asyncio.get_event_loop().time()
            except Exception as e:
                print(f"⚠️ 点击尝试提示: {e}")

        await asyncio.sleep(1)

    if await _get_turnstile_token(page):
        return True
    print("❌ Cloudflare 验证 Token 获取超时。")
    return False

# =====================================================================
#                Weirdhost 自动化执行主逻辑 (Async)
# =====================================================================

class WeirdhostAutomation:
    def __init__(self):
        self.email = WEIRDHOST_EMAIL
        self.password = WEIRDHOST_PASSWORD
        self.login_url = LOGIN_URL
        self.telegram = TelegramNotifier()
        
        self.old_expiry_time = None
        self.new_expiry_time = None
        self.renewal_status = "Unknown"

    async def run(self):
        print("🚀 开始 Weirdhost 自动续期流程...")

        async with async_playwright() as p:
            proxy_config = {"server": PROXY_SERVER} if PROXY_SERVER else None

            browser = await p.chromium.launch(
                headless=True,
                channel="chrome",
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--window-size=1920,1080"
                ]
            )

            # 检查是否存在本地 auth.json 凭证
            storage_path = "auth.json"
            has_auth = os.path.exists(storage_path)

            if has_auth:
                print("📂 发现本地 auth.json 凭证，正在加载以跳过登录与 CF 登录盾...")
                context = await browser.new_context(
                    storage_state=storage_path,
                    proxy=proxy_config,
                    viewport={"width": 1920, "height": 1080},
                    timezone_id="Asia/Seoul"
                )
            else:
                print("ℹ️ 未发现 auth.json 凭证，将执行标准登录流程...")
                context = await browser.new_context(
                    proxy=proxy_config,
                    viewport={"width": 1920, "height": 1080},
                    timezone_id="Asia/Seoul"
                )

            page = await context.new_page()

            try:
                if has_auth:
                    # 直接尝试访问后台
                    print(f"🌐 正在使用 Cookie 直接访问面板: {DASHBOARD_URL}")
                    await page.goto(DASHBOARD_URL, wait_until="networkidle", timeout=60000)
                    
                    # 检查是否被重定向回了登录页（说明 Cookie 失效了）
                    if "/auth/login" in page.url:
                        print("⚠️ auth.json 凭证已失效或过期，重新执行自动登录...")
                        has_auth = False

                if not has_auth:
                    if not self.email or not self.password:
                        print("❌ 错误: 未设置 WEIRDHOST_EMAIL 或 WEIRDHOST_PASSWORD 环境变量!")
                        return False

                    # 1. 访问登录页
                    print(f"🌐 正在访问登录页: {self.login_url}")
                    await page.goto(self.login_url, wait_until="domcontentloaded", timeout=60000)

                    # 1.5 处理初始页面的 CF 盾
                    print("🛡️ 检测并处理初始页面的 Cloudflare 盾...")
                    await solve_modal_turnstile(page, timeout=30)
                    await page.wait_for_load_state("networkidle")

                    # 2. 填写账号密码
                    print("📝 正在等待前端 JS 渲染登录表单...")
                    await page.wait_for_selector('input[type="email"], input[type="text"]', timeout=30000)
                    await asyncio.sleep(2)
                    
                    email_input = page.locator('input[type="email"], input[type="text"]').first
                    await email_input.fill(self.email)
                    
                    password_input = page.locator('input[type="password"]').first
                    await password_input.fill(self.password)
                    await asyncio.sleep(1)

                    # 3. 点击登录按钮
                    print("🖱️ 点击登录按钮...")
                    login_btn = page.locator('button:has-text("로그인"), button[type="submit"]').first
                    await login_btn.click()

                    # 4. 处理登录提交后的 CF 盾
                    print("🛡️ 等待跳转并处理登录后的 Cloudflare 验证...")
                    await solve_modal_turnstile(page, timeout=45)
                    await page.wait_for_load_state("networkidle")

                    # 登录成功后，立刻保存状态到 auth.json
                    await context.storage_state(path="auth.json")
                    print("💾 登录状态已成功保存到 auth.json")

                print(f"🔍 成功进入面板，当前 URL: {page.url}")

                # 5. 点击左侧'서버'(服务器)菜单
                print("🔍 进入服务器列表...")
                server_menu = page.get_by_text("서버", exact=True).first
                if await server_menu.count() > 0:
                    await server_menu.wait_for(state="visible", timeout=10000)
                    await server_menu.click()
                    await asyncio.sleep(3)

                # 6. 点击服务器条目进入控制面板
                print("🖱️ 点击服务器条目...")
                server_item = page.locator('text="나의 무료 서버"').first
                if await server_item.count() > 0:
                    await server_item.wait_for(state="visible", timeout=10000)
                    await server_item.click()
                    await asyncio.sleep(3)

                print(f"✅ 成功到达服务器控制面板: {page.url}")

                # 7. 读取到期时间
                body_content = await page.content()
                expiry_match = re.search(r"유통기한\s*(\d{4}-\d{2}-\d{2}\s*\d{2}:\d{2}:\d{2})", body_content)
                if expiry_match:
                    self.old_expiry_time = expiry_match.group(1).strip()
                    print(f"📅 当前服务器到期时间: {self.old_expiry_time}")

                # 8. 检查续期限制逻辑
                if "연장할수있어요" in body_content or "후에" in body_content:
                    print("ℹ️ 尚未到可续期时间（必须在到期 2 天以内才可以续期）")
                    self.renewal_status = "Unexpired"
                    await page.screenshot(path="weirdhost_unexpired.png")
                else:
                    print("📄 发现可续期窗口，寻找'연장하기'按钮...")
                    renew_btn = page.locator('button:has-text("연장하기"), text="연장하기"').first
                    if await renew_btn.count() > 0 and await renew_btn.is_enabled():
                        await renew_btn.click()
                        print("🖱️ 点击了'연장하기'按钮")
                        await asyncio.sleep(3)

                        # 处理二次确认框或 CF 盾
                        await solve_modal_turnstile(page, timeout=20)
                        confirm_btn = page.locator('button:has-text("확인"), button:has-text("연장")').first
                        if await confirm_btn.count() > 0:
                            await confirm_btn.click()
                            print("🎉 成功点击确认续期！")
                            await asyncio.sleep(4)

                        self.renewal_status = "Success"
                        await page.screenshot(path="weirdhost_success_tg.png")
                    else:
                        print("ℹ️ 续期按钮当前不可点击，标记为 Unexpired")
                        self.renewal_status = "Unexpired"

                self.generate_report_file()
                self.push_telegram_notifications()
                return True

            except Exception as e:
                print(f"❌ 运行过程中发生异常: {e}")
                self.renewal_status = "Failed"
                self.generate_report_file()
                self.push_telegram_notifications()
                return False
            finally:
                await browser.close()

    def generate_report_file(self):
        try:
            beijing_time = datetime.datetime.now(timezone(timedelta(hours=8)))
            current_time = beijing_time.strftime("%Y-%m-%d %H:%M:%S")
            content = f"**最后运行时间**: `{current_time}`\n\n"
            content += "**运行结果**: <br>\n"
            content += "🖥️服务器:`🇰🇷Weirdhost(KR)`<br>\n"
            if self.renewal_status == "Success":
                content += "📊续期结果:✅Success<br>\n"
                content += f"🕛️旧到期时间: `{self.old_expiry_time or 'Unknown'}`<br>\n"
                content += f"🕡️新到期时间: `{self.new_expiry_time or 'Unknown'}`<br>\n"
            elif self.renewal_status == "Unexpired":
                content += "📊续期结果:ℹ️Unexpired<br>\n"
                content += f"🕛️旧到期时间: `{self.old_expiry_time or 'Unknown'}`<br>\n"
            else:
                content += "📊续期结果:❌Failed<br>\n"
                content += f"🕛️旧到期时间: `{self.old_expiry_time or 'Unknown'}`<br>\n"

            with open("report-notify.md", "w", encoding="utf-8") as f:
                f.write(content)
        except Exception:
            pass

    def push_telegram_notifications(self):
        beijing_time = datetime.datetime.now(timezone(timedelta(hours=8)))
        current_time = beijing_time.strftime("%Y-%m-%d %H:%M:%S")

        self.telegram.send_renewal_result(
            status=self.renewal_status,
            old_time=self.old_expiry_time or "Unknown",
            new_time=self.new_expiry_time,
            run_time=current_time
        )

        if self.renewal_status == "Success" and os.path.exists("weirdhost_success_tg.png"):
            self.telegram.send_photo("weirdhost_success_tg.png", caption=f"Weirdhost 续期成功截图\n{current_time}")

if __name__ == "__main__":
    asyncio.run(WeirdhostAutomation().run())
