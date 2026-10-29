import asyncio
import base64
import json
import os
import shutil
import socket
import subprocess
import time
import unittest
import urllib.request
import websockets

class TestThemeE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if not os.path.exists(cls.chrome_path):
            raise unittest.SkipTest("Google Chrome is not installed at " + cls.chrome_path)

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', 0))
                cls.port = s.getsockname()[1]
        except (PermissionError, OSError) as e:
            raise unittest.SkipTest(f"Socket networking not permitted in sandbox: {e}")

        cls.user_data_dir = f"/tmp/chrome_theme_e2e_profile_{cls.port}"
        if os.path.exists(cls.user_data_dir):
            shutil.rmtree(cls.user_data_dir)

        cls.cmd = [
            cls.chrome_path,
            "--headless=new",
            f"--remote-debugging-port={cls.port}",
            "--window-size=1280,800",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={cls.user_data_dir}",
            "http://localhost:8001"
        ]
        try:
            cls.chrome_proc = subprocess.Popen(cls.cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            time.sleep(2.5)
        except Exception as e:
            raise unittest.SkipTest(f"Failed to start headless Chrome: {e}")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'chrome_proc') and cls.chrome_proc:
            cls.chrome_proc.terminate()
            cls.chrome_proc.wait()
        if hasattr(cls, 'user_data_dir') and os.path.exists(cls.user_data_dir):
            shutil.rmtree(cls.user_data_dir, ignore_errors=True)

    def run_async(self, coro):
        return asyncio.run(coro)

    def test_full_theme_lifecycle_and_contrast(self):
        async def _test():
            try:
                tabs_url = f"http://localhost:{self.port}/json"
                req = urllib.request.urlopen(tabs_url)
                tabs = json.loads(req.read().decode())
                page_tab = next(t for t in tabs if t.get("type") == "page")
                ws_url = page_tab["webSocketDebuggerUrl"]
            except Exception as e:
                raise unittest.SkipTest(f"Cannot reach Chrome debugger endpoint: {e}")

            async with websockets.connect(ws_url) as ws:
                msg_id = 1
                async def send(method, params=None):
                    nonlocal msg_id
                    msg_id += 1
                    payload = {"id": msg_id, "method": method, "params": params or {}}
                    await ws.send(json.dumps(payload))
                    while True:
                        resp = json.loads(await ws.recv())
                        if resp.get("id") == msg_id:
                            return resp.get("result", {})

                await send("Page.enable")
                await send("Runtime.enable")
                await asyncio.sleep(1)

                # =============================================================
                # Stage 1: Initial Light Theme Verification
                # =============================================================
                res_init = await send("Runtime.evaluate", {
                    "expression": """({
                        htmlTheme: document.documentElement.getAttribute('data-theme'),
                        bodyTheme: document.body.getAttribute('data-theme'),
                        bodyBg: window.getComputedStyle(document.body).backgroundColor,
                        bodyColor: window.getComputedStyle(document.body).color,
                        themeIcon: document.getElementById('theme-icon') ? document.getElementById('theme-icon').innerText.trim() : null,
                        headerBg: window.getComputedStyle(document.querySelector('.chat-header')).backgroundColor,
                        sidebarBg: window.getComputedStyle(document.querySelector('.sidebar')).backgroundColor,
                        formBg: window.getComputedStyle(document.querySelector('#chat-form')).backgroundColor
                    })""",
                    "returnByValue": True
                })
                init = res_init.get("result", {}).get("value")
                self.assertIsNotNone(init)
                self.assertEqual(init["htmlTheme"], "light")
                self.assertEqual(init["bodyTheme"], "light")
                self.assertEqual(init["themeIcon"], "☀️")
                self.assertIn(init["bodyBg"], ["rgb(224, 242, 254)", "rgba(224, 242, 254, 1)"])
                self.assertEqual(init["bodyColor"], "rgb(12, 74, 110)")
                self.assertIn("240, 249, 255", init["headerBg"])

                # Capture Light Screenshot
                snap_light = await send("Page.captureScreenshot")
                if "data" in snap_light:
                    with open("/tmp/screenshot_theme_light.png", "wb") as f:
                        f.write(base64.b64decode(snap_light["data"]))

                # =============================================================
                # Stage 2: Click Theme Toggle -> Switch to Dark Theme
                # =============================================================
                await send("Runtime.evaluate", {
                    "expression": "document.getElementById('theme-toggle-btn').click();"
                })
                await asyncio.sleep(0.4)

                res_dark = await send("Runtime.evaluate", {
                    "expression": """({
                        htmlTheme: document.documentElement.getAttribute('data-theme'),
                        bodyTheme: document.body.getAttribute('data-theme'),
                        localStored: localStorage.getItem('dimension_theme'),
                        bodyBg: window.getComputedStyle(document.body).backgroundColor,
                        bodyColor: window.getComputedStyle(document.body).color,
                        themeIcon: document.getElementById('theme-icon') ? document.getElementById('theme-icon').innerText.trim() : null,
                        headerBg: window.getComputedStyle(document.querySelector('.chat-header')).backgroundColor,
                        headerBrandColor: window.getComputedStyle(document.querySelector('.header-brand-name')).color,
                        heroTitleColor: window.getComputedStyle(document.querySelector('.welcome-hero-title')).color,
                        queryInputColor: window.getComputedStyle(document.querySelector('#query-input')).color,
                        sendBtnBg: window.getComputedStyle(document.querySelector('.send-btn')).backgroundColor,
                        sendBtnColor: window.getComputedStyle(document.querySelector('.send-btn')).color
                    })""",
                    "returnByValue": True
                })
                dark = res_dark.get("result", {}).get("value")
                self.assertIsNotNone(dark)
                self.assertEqual(dark["htmlTheme"], "dark")
                self.assertEqual(dark["bodyTheme"], "dark")
                self.assertEqual(dark["localStored"], "dark")
                self.assertEqual(dark["themeIcon"], "🌙")
                self.assertIn(dark["bodyBg"], ["rgb(9, 13, 18)", "rgba(9, 13, 18, 1)"])
                self.assertEqual(dark["bodyColor"], "rgb(241, 245, 249)")
                self.assertEqual(dark["headerBrandColor"], "rgb(241, 245, 249)")
                self.assertEqual(dark["heroTitleColor"], "rgb(241, 245, 249)")
                self.assertEqual(dark["queryInputColor"], "rgb(241, 245, 249)")
                self.assertEqual(dark["sendBtnBg"], "rgb(56, 189, 248)")
                self.assertEqual(dark["sendBtnColor"], "rgb(9, 13, 18)")
                self.assertIn("15, 23, 42", dark["headerBg"])

                # Capture Dark Screenshot
                snap_dark = await send("Page.captureScreenshot")
                if "data" in snap_dark:
                    with open("/tmp/screenshot_theme_dark.png", "wb") as f:
                        f.write(base64.b64decode(snap_dark["data"]))

                # =============================================================
                # Stage 3: Reload Page -> Verify Dark Theme Persistence
                # =============================================================
                await send("Page.reload")
                await asyncio.sleep(1.2)

                res_dark_reload = await send("Runtime.evaluate", {
                    "expression": """({
                        htmlTheme: document.documentElement.getAttribute('data-theme'),
                        bodyTheme: document.body.getAttribute('data-theme'),
                        localStored: localStorage.getItem('dimension_theme'),
                        bodyBg: window.getComputedStyle(document.body).backgroundColor,
                        bodyColor: window.getComputedStyle(document.body).color,
                        themeIcon: document.getElementById('theme-icon') ? document.getElementById('theme-icon').innerText.trim() : null
                    })""",
                    "returnByValue": True
                })
                dark_reload = res_dark_reload.get("result", {}).get("value")
                self.assertIsNotNone(dark_reload)
                self.assertEqual(dark_reload["htmlTheme"], "dark")
                self.assertEqual(dark_reload["bodyTheme"], "dark")
                self.assertEqual(dark_reload["localStored"], "dark")
                self.assertEqual(dark_reload["themeIcon"], "🌙")
                self.assertIn(dark_reload["bodyBg"], ["rgb(9, 13, 18)", "rgba(9, 13, 18, 1)"])
                self.assertEqual(dark_reload["bodyColor"], "rgb(241, 245, 249)")

                # =============================================================
                # Stage 4: Rapid Toggle Stress Test (6 cycles)
                # =============================================================
                # Starting in Dark:
                # 1: Light
                # 2: Dark
                # 3: Light
                # 4: Dark
                # 5: Light
                # 6: Dark
                for _ in range(6):
                    await send("Runtime.evaluate", {
                        "expression": "document.getElementById('theme-toggle-btn').click();"
                    })
                    await asyncio.sleep(0.06)

                await asyncio.sleep(0.3)

                res_rapid = await send("Runtime.evaluate", {
                    "expression": """({
                        htmlTheme: document.documentElement.getAttribute('data-theme'),
                        bodyTheme: document.body.getAttribute('data-theme'),
                        localStored: localStorage.getItem('dimension_theme'),
                        themeIcon: document.getElementById('theme-icon').innerText.trim(),
                        bodyBg: window.getComputedStyle(document.body).backgroundColor
                    })""",
                    "returnByValue": True
                })
                rapid = res_rapid.get("result", {}).get("value")
                self.assertIsNotNone(rapid)
                self.assertEqual(rapid["htmlTheme"], "dark")
                self.assertEqual(rapid["bodyTheme"], "dark")
                self.assertEqual(rapid["localStored"], "dark")
                self.assertEqual(rapid["themeIcon"], "🌙")
                self.assertIn(rapid["bodyBg"], ["rgb(9, 13, 18)", "rgba(9, 13, 18, 1)"])

                # =============================================================
                # Stage 5: Toggle Back to Light Theme
                # =============================================================
                await send("Runtime.evaluate", {
                    "expression": "document.getElementById('theme-toggle-btn').click();"
                })
                await asyncio.sleep(0.4)

                res_light = await send("Runtime.evaluate", {
                    "expression": """({
                        htmlTheme: document.documentElement.getAttribute('data-theme'),
                        bodyTheme: document.body.getAttribute('data-theme'),
                        localStored: localStorage.getItem('dimension_theme'),
                        bodyBg: window.getComputedStyle(document.body).backgroundColor,
                        bodyColor: window.getComputedStyle(document.body).color,
                        themeIcon: document.getElementById('theme-icon') ? document.getElementById('theme-icon').innerText.trim() : null
                    })""",
                    "returnByValue": True
                })
                light = res_light.get("result", {}).get("value")
                self.assertIsNotNone(light)
                self.assertEqual(light["htmlTheme"], "light")
                self.assertEqual(light["bodyTheme"], "light")
                self.assertEqual(light["localStored"], "light")
                self.assertEqual(light["themeIcon"], "☀️")
                self.assertIn(light["bodyBg"], ["rgb(224, 242, 254)", "rgba(224, 242, 254, 1)"])
                self.assertEqual(light["bodyColor"], "rgb(12, 74, 110)")

                # =============================================================
                # Stage 6: Reload Page -> Verify Light Theme Persistence
                # =============================================================
                await send("Page.reload")
                await asyncio.sleep(1.2)

                res_light_reload = await send("Runtime.evaluate", {
                    "expression": """({
                        htmlTheme: document.documentElement.getAttribute('data-theme'),
                        bodyTheme: document.body.getAttribute('data-theme'),
                        localStored: localStorage.getItem('dimension_theme'),
                        themeIcon: document.getElementById('theme-icon') ? document.getElementById('theme-icon').innerText.trim() : null
                    })""",
                    "returnByValue": True
                })
                light_reload = res_light_reload.get("result", {}).get("value")
                self.assertIsNotNone(light_reload)
                self.assertEqual(light_reload["htmlTheme"], "light")
                self.assertEqual(light_reload["bodyTheme"], "light")
                self.assertEqual(light_reload["localStored"], "light")
                self.assertEqual(light_reload["themeIcon"], "☀️")

        self.run_async(_test())

if __name__ == "__main__":
    unittest.main()
