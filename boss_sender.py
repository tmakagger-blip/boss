#!/usr/bin/env python3
"""
Boss直聘批量私信工具

用法：
  # 先保存登录 cookie（浏览器会弹出，手动扫码登录）
  python boss_sender.py --save-cookies

  # 发送消息（读取 config.json 中的配置）
  python boss_sender.py --send

  # 添加用户到 users.txt 并立即发送
  python boss_sender.py --add "https://www.zhipin.com/resume/xxx.html" --send

  # 批量添加用户
  python boss_sender.py --add-file new_users.txt --send

  # 查看已发送记录
  python boss_sender.py --status
"""

import argparse
import json
import logging
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

CONFIG_PATH = Path("config.json")
DEFAULT_CONFIG = {
    "message": "你好，我看了你的简历，觉得你的背景很适合我们团队，想和你聊聊，方便的话请回复我。",
    "delay_min": 8,
    "delay_max": 20,
    "cookies_file": "cookies.json",
    "users_file": "users.txt",
    "log_file": "sent.log",
    "headless": False,
    "timeout": 30000,
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def load_config() -> dict:
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open(encoding="utf-8") as f:
            cfg = json.load(f)
        return {**DEFAULT_CONFIG, **cfg}
    return DEFAULT_CONFIG.copy()


# ---------------------------------------------------------------------------
# User list helpers
# ---------------------------------------------------------------------------

def load_users(path: str) -> list[str]:
    p = Path(path)
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").splitlines()
    users = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#"):
            users.append(line)
    return users


def add_users(path: str, new_users: list[str]) -> int:
    p = Path(path)
    existing = set(load_users(path))
    added = 0
    with p.open("a", encoding="utf-8") as f:
        for u in new_users:
            u = u.strip()
            if u and not u.startswith("#") and u not in existing:
                f.write(u + "\n")
                existing.add(u)
                added += 1
                log.info("已添加用户: %s", u)
    return added


# ---------------------------------------------------------------------------
# Sent-log helpers
# ---------------------------------------------------------------------------

def load_sent(log_file: str) -> set[str]:
    p = Path(log_file)
    if not p.exists():
        return set()
    sent = set()
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                parts = line.split("\t")
                if parts:
                    sent.add(parts[0])
    return sent


def record_sent(log_file: str, user: str, status: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"{user}\t{status}\t{ts}\n")


# ---------------------------------------------------------------------------
# Browser helpers
# ---------------------------------------------------------------------------

BOSS_HOME = "https://www.zhipin.com"
BOSS_IM = "https://www.zhipin.com/web/im/"


STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
window.chrome = {runtime: {}};
""".strip()


def make_browser(playwright, cfg: dict, storage_state=None):
    """Launch a Chromium browser with anti-detection flags."""
    launch_opts = {
        "headless": cfg["headless"],
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    }
    ctx_opts: dict = {
        "viewport": {"width": 1280, "height": 900},
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    }
    if storage_state and Path(storage_state).exists():
        ctx_opts["storage_state"] = storage_state
    browser = playwright.chromium.launch(**launch_opts)
    ctx = browser.new_context(**ctx_opts)
    ctx.add_init_script(STEALTH_SCRIPT)
    return browser, ctx


def save_cookies(cfg: dict) -> None:
    """Open browser, let user log in manually, then save storage state."""
    cookies_file = cfg["cookies_file"]
    log.info("即将打开浏览器，请手动扫码登录 Boss直聘，登录成功后请勿关闭浏览器。")
    log.info("登录完成后，脚本会自动保存 Cookie 并关闭浏览器。")

    with sync_playwright() as p:
        browser, ctx = make_browser(p, {**cfg, "headless": False})
        page = ctx.new_page()
        page.goto(BOSS_HOME, wait_until="networkidle", timeout=60000)
        log.info("请在浏览器中完成登录……")

        # Wait until the user is logged in (profile avatar appears)
        try:
            page.wait_for_selector(
                "a.nav-figure, .user-nav .figure, .nav-user-info",
                timeout=120000,
            )
            log.info("检测到登录成功！正在保存 Cookie……")
        except PWTimeout:
            log.warning("等待登录超时，尝试直接保存当前状态。")

        ctx.storage_state(path=cookies_file)
        log.info("Cookie 已保存到: %s", cookies_file)
        browser.close()


# ---------------------------------------------------------------------------
# Core send logic
# ---------------------------------------------------------------------------

def _send_to_resume_url(page, cfg: dict, url: str) -> bool:
    """
    Navigate to a resume/candidate profile page and click 立即沟通,
    then type and send the message.
    Returns True on success.
    """
    timeout = cfg["timeout"]
    message = cfg["message"]

    log.info("打开简历页: %s", url)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    except PWTimeout:
        log.error("页面加载超时: %s", url)
        return False

    # Click the 立即沟通 / 打招呼 button
    btn_selectors = [
        "a.btn-greet",
        "a.op-btn-greet",
        "button.btn-greet",
        ".op-btn-chat",
        "a[ka='greet']",
        ".job-detail-operate .btn-primary",
        "a:has-text('立即沟通')",
        "a:has-text('打招呼')",
        "button:has-text('立即沟通')",
        "button:has-text('打招呼')",
    ]
    clicked = False
    for sel in btn_selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=2000):
                btn.click(timeout=5000)
                clicked = True
                log.info("点击了沟通按钮: %s", sel)
                break
        except Exception:
            continue

    if not clicked:
        log.error("未找到沟通按钮，跳过: %s", url)
        return False

    return _fill_and_send(page, cfg)


def _send_to_im_contact(page, cfg: dict, uid: str) -> bool:
    """
    Navigate to the IM panel for an already-established contact by uid.
    """
    timeout = cfg["timeout"]
    im_url = f"{BOSS_IM}?id={uid}"
    log.info("打开聊天页: %s", im_url)
    try:
        page.goto(im_url, wait_until="domcontentloaded", timeout=timeout)
    except PWTimeout:
        log.error("IM 页面加载超时: %s", uid)
        return False

    return _fill_and_send(page, cfg)


def _fill_and_send(page, cfg: dict) -> bool:
    """
    Find the chat input box, type the message and submit.
    Returns True on success.
    """
    timeout = cfg["timeout"]
    message = cfg["message"]

    input_selectors = [
        ".chat-input-box",
        ".input-area",
        "div[contenteditable='true']",
        "textarea.chat-input",
        ".editor-input",
        "[class*='chat-input']",
        "[class*='message-input']",
    ]

    # Wait for chat dialog / input to appear
    time.sleep(2)

    input_el = None
    for sel in input_selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=3000):
                input_el = el
                log.info("找到输入框: %s", sel)
                break
        except Exception:
            continue

    if input_el is None:
        log.error("未找到聊天输入框，跳过。")
        return False

    try:
        input_el.click()
        time.sleep(0.5)
        input_el.fill(message)
        time.sleep(0.5)

        # Try send button first, then Enter
        send_selectors = [
            "button.btn-send",
            "button[type='submit']",
            ".send-btn",
            "button:has-text('发送')",
            "[class*='send']",
        ]
        sent = False
        for sel in send_selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=1500):
                    btn.click()
                    sent = True
                    break
            except Exception:
                continue

        if not sent:
            input_el.press("Enter")

        time.sleep(1)
        log.info("消息已发送。")
        return True

    except Exception as e:
        log.error("发送消息时出错: %s", e)
        return False


def _is_resume_url(url: str) -> bool:
    return re.search(r"zhipin\.com/(resume|candidate)/", url) is not None


def send_messages(cfg: dict) -> None:
    cookies_file = cfg["cookies_file"]
    users_file = cfg["users_file"]
    log_file = cfg["log_file"]
    delay_min = cfg["delay_min"]
    delay_max = cfg["delay_max"]

    if not Path(cookies_file).exists():
        log.error("Cookie 文件不存在，请先运行: python boss_sender.py --save-cookies")
        sys.exit(1)

    users = load_users(users_file)
    if not users:
        log.warning("users.txt 为空，没有用户需要发送。")
        return

    sent = load_sent(log_file)
    pending = [u for u in users if u not in sent]
    log.info("共 %d 个用户，其中 %d 个待发送，%d 个已发送。", len(users), len(pending), len(sent))

    if not pending:
        log.info("所有用户都已发送过，无需操作。")
        return

    with sync_playwright() as p:
        browser, ctx = make_browser(p, cfg, storage_state=cookies_file)
        page = ctx.new_page()

        # Quick login check
        page.goto(BOSS_HOME, wait_until="domcontentloaded", timeout=cfg["timeout"])
        if "login" in page.url or page.locator(".login-panel").is_visible(timeout=2000):
            log.error("Cookie 已失效，请重新运行 --save-cookies 登录。")
            browser.close()
            sys.exit(1)

        success_count = 0
        fail_count = 0

        for i, user in enumerate(pending, 1):
            log.info("[%d/%d] 处理: %s", i, len(pending), user)

            if _is_resume_url(user):
                ok = _send_to_resume_url(page, cfg, user)
            elif user.startswith("http"):
                # generic URL – try resume flow
                ok = _send_to_resume_url(page, cfg, user)
            else:
                # Treat as IM uid
                ok = _send_to_im_contact(page, cfg, user)

            status = "success" if ok else "failed"
            record_sent(log_file, user, status)

            if ok:
                success_count += 1
            else:
                fail_count += 1

            if i < len(pending):
                delay = random.uniform(delay_min, delay_max)
                log.info("等待 %.1f 秒后继续……", delay)
                time.sleep(delay)

        browser.close()
        log.info("发送完毕：成功 %d，失败 %d。", success_count, fail_count)


# ---------------------------------------------------------------------------
# Status report
# ---------------------------------------------------------------------------

def print_status(cfg: dict) -> None:
    users = load_users(cfg["users_file"])
    sent_map: dict[str, tuple[str, str]] = {}
    log_file = Path(cfg["log_file"])
    if log_file.exists():
        for line in log_file.read_text(encoding="utf-8").splitlines():
            parts = line.strip().split("\t")
            if len(parts) >= 3:
                sent_map[parts[0]] = (parts[1], parts[2])
            elif len(parts) == 2:
                sent_map[parts[0]] = (parts[1], "")

    total = len(users)
    sent_ok = sum(1 for u in users if sent_map.get(u, ("",))[0] == "success")
    sent_fail = sum(1 for u in users if sent_map.get(u, ("",))[0] == "failed")
    pending = total - sent_ok - sent_fail

    print(f"\n{'='*40}")
    print(f"  总用户数:  {total}")
    print(f"  已成功:    {sent_ok}")
    print(f"  已失败:    {sent_fail}")
    print(f"  待发送:    {pending}")
    print(f"{'='*40}\n")

    if sent_fail:
        print("失败列表：")
        for u in users:
            if sent_map.get(u, ("",))[0] == "failed":
                print(f"  {u}")
        print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Boss直聘批量私信工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--save-cookies",
        action="store_true",
        help="打开浏览器手动登录并保存 Cookie",
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="向 users.txt 中所有未发送的用户发送消息",
    )
    parser.add_argument(
        "--add",
        metavar="URL_OR_ID",
        nargs="+",
        help="添加一个或多个用户到 users.txt",
    )
    parser.add_argument(
        "--add-file",
        metavar="FILE",
        help="从指定文件批量添加用户到 users.txt（每行一个）",
    )
    parser.add_argument(
        "--message",
        metavar="TEXT",
        help="覆盖 config.json 中的消息内容（临时生效，不修改文件）",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="显示发送统计",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="重试所有失败的用户",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="以无头模式运行（不显示浏览器窗口）",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    cfg = load_config()

    if args.message:
        cfg["message"] = args.message
    if args.headless:
        cfg["headless"] = True

    if not any([args.save_cookies, args.send, args.add, args.add_file,
                args.status, args.retry_failed]):
        parser.print_help()
        return

    if args.save_cookies:
        save_cookies(cfg)

    if args.add:
        n = add_users(cfg["users_file"], args.add)
        log.info("成功添加 %d 个新用户。", n)

    if args.add_file:
        p = Path(args.add_file)
        if not p.exists():
            log.error("文件不存在: %s", args.add_file)
            sys.exit(1)
        lines = p.read_text(encoding="utf-8").splitlines()
        new_users = [l.strip() for l in lines if l.strip() and not l.startswith("#")]
        n = add_users(cfg["users_file"], new_users)
        log.info("从 %s 成功添加 %d 个新用户。", args.add_file, n)

    if args.retry_failed:
        # Remove failed entries from log so they will be retried
        log_file = Path(cfg["log_file"])
        if log_file.exists():
            lines = log_file.read_text(encoding="utf-8").splitlines()
            kept = [l for l in lines if not l.split("\t")[1:2] == ["failed"]]
            log_file.write_text("\n".join(kept) + "\n", encoding="utf-8")
            removed = len(lines) - len(kept)
            log.info("已清除 %d 条失败记录，它们将被重新发送。", removed)

    if args.status:
        print_status(cfg)

    if args.send:
        send_messages(cfg)


if __name__ == "__main__":
    main()
