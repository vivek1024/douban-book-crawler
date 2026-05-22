"""
豆瓣关注用户读书爬虫
爬取所有关注用户的「读过」书单，统计被最多人读过的书。

用法：
  pip install playwright beautifulsoup4 lxml
  python douban_book_crawler.py

流程：
  第一次运行 → 打开浏览器，你登录豆瓣 → 爬关注列表（保存到本地）
  之后运行   → 跳过第一步，直接用缓存的书单
  断点续爬   → 每爬完一人存档，中断重跑续爬
"""

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from playwright._impl._errors import TargetClosedError
import time
import json
import os
import random
import re
import sys
from collections import Counter
import datetime

# ============================================================
# 日志：同时输出到终端和文件
# ============================================================

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "douban_crawler_log.txt")

class TeeLogger:
    """同时写入终端和日志文件"""
    def __init__(self, logpath):
        self.log = open(logpath, "a", encoding="utf-8")
        self.flush()

    def write(self, text):
        sys.__stdout__.write(text)
        self.log.write(text)

    def flush(self):
        self.log.flush()

# 重定向 print 到 TeeLogger
sys.stdout = TeeLogger(LOG_FILE)
print(f"\n{'='*60}")
print(f"启动时间: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
print(f"{'='*60}")

# ============================================================
# 配置区
# ============================================================

YOUR_UID = ""  # 改为你的豆瓣 UID（个人主页 URL 中的数字）

# 爬取延迟（秒）—— 被 ban 后调大，降低触发反爬概率
MIN_DELAY = 6.0
MAX_DELAY = 10.0

# 关注列表翻页延迟
CONTACTS_DELAY = 5.0

# 代理（Clash/Stash 等本地代理，换 IP 后修改此地址）
PROXY = "http://127.0.0.1:7890"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONTACTS_FILE = os.path.join(BASE_DIR, "douban_contacts.json")
PROGRESS_FILE = os.path.join(BASE_DIR, "douban_progress.json")
RESULT_FILE = os.path.join(BASE_DIR, "douban_result.json")


# ============================================================
# 浏览器工具
# ============================================================

# Chrome 远程调试端口（连接你手动打开的 Chrome，完全绕过自动化检测）
CDP_PORT = 9222
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"
CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
# 独立用户数据目录（不干扰你的主 Chrome 浏览会话）
CHROME_USER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                ".chrome_data")


def _port_listening():
    """检查 9222 端口是否正在监听"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.connect(("127.0.0.1", CDP_PORT))
        s.close()
        return True
    except ConnectionRefusedError:
        return False
    finally:
        s.close()


def _chrome_running():
    """检查 Chrome 进程是否在运行"""
    import subprocess
    return subprocess.call(["pgrep", "-x", "Google Chrome"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


def _try_connect(pw, timeout=20):
    """尝试连接 CDP，返回 (browser, page) 或 None"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            browser = pw.chromium.connect_over_cdp(CDP_URL)
            # 不要重用已有页面（可能卡在百度/首页），总是新建一个 tab
            ctx = browser.contexts[0] if browser.contexts else browser
            page = ctx.new_page() if hasattr(ctx, "new_page") else browser.new_page()
            return browser, page
        except Exception:
            remaining = deadline - time.time()
            if remaining > 0:
                time.sleep(min(0.5, remaining))
    return None


def new_browser(pw):
    """连接到 Chrome（远程调试模式），智能处理多种 macOS 场景"""

    # ─── 场景 A：端口 9222 已经有人在监听 ───
    if _port_listening():
        print(f"  检测到端口 {CDP_PORT} 已开放，正在连接…")
        result = _try_connect(pw, timeout=15)
        if result:
            browser, page = result
            print("  ✅ 已连接到正在运行的 Chrome（远程调试模式）")
            print(f"  📄 当前页面: {page.title()}")
            return browser, page
        else:
            print("  ⚠️  端口已开放但连接失败，可能 Chrome 版本不兼容或安全策略阻止")
            print("  继续尝试自动启动流程…\n")

    # ─── 场景 B：Chrome 已经在运行（但没有调试端口） ───
    if _chrome_running():
        print("  ⚠️  Chrome 正在运行，但没有开放远程调试端口 9222。")
        print("  现在启动一个独立的 Chrome 实例（不影响你的主浏览器）：")
        print(f"  用户数据目录: {CHROME_USER_DIR}")

    # ─── 启动 Chrome（带远程调试端口 + 独立用户数据目录） ───
    print(f"  🚀 启动 Chrome（独立实例，端口 {CDP_PORT}）…")
    print(f"     用户数据目录: {CHROME_USER_DIR}")
    import subprocess
    os.makedirs(CHROME_USER_DIR, exist_ok=True)
    proxy_flag = f"--proxy-server={PROXY}"
    print(f"     代理: {PROXY}")
    subprocess.Popen(
        [CHROME_BIN,
         f"--remote-debugging-port={CDP_PORT}",
         f"--user-data-dir={CHROME_USER_DIR}",
         "--no-first-run",
         "--new-window",
         proxy_flag],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    # ─── 等待 Chrome 启动并上线 ───
    print("  ⏳ 等待 Chrome 启动…", end="", flush=True)
    for i in range(60):
        time.sleep(1)
        result = _try_connect(pw, timeout=2)
        if result:
            browser, page = result
            print(f"\n  ✅ Chrome 已就绪")
            return browser, page
        if (i + 1) % 10 == 0:
            print(f" {i+1}s", end="", flush=True)

    raise RuntimeError(
        f"无法连接到 Chrome（端口 {CDP_PORT}），请手动检查：\n"
        f"  1. Chrome 是否安装在 /Applications 目录\n"
        f"  2. 是否被安全软件阻止监听端口\n"
        f"  3. 在终端执行以下命令测试：\n"
        f"     {CHROME_BIN} --remote-debugging-port={CDP_PORT} &"
    )


def go(page, url, timeout=20000, label=""):
    tag = f" [{label}]" if label else ""
    print(f"  [NAV]{tag} {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    page.wait_for_timeout(1500)
    print(f"  [NAV_OK]{tag} → {page.url}  |  title: {page.title()}")


def try_go(page, url, timeout=20000, retries=3, label=""):
    """导航，自动重试网络波动 / TargetClosed / 被 CAPTCHA 拦截则等你手动完成"""
    tag = f" [{label}]" if label else ""
    print(f"  [NAV]{tag} {url}")
    for attempt in range(1, retries + 1):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        except Exception as e:
            err = str(e)
            etype = type(e).__name__
            if any(k in err for k in ("NETWORK_CHANGED", "NETWORK", "Timeout")):
                print(f"  ⚡ 网络波动/超时, 第 {attempt}/{retries} 次重试...")
                time.sleep(3 * attempt)
                continue
            if "TargetClosed" in etype:
                raise
            raise
    page.wait_for_timeout(1500)
    cur_url = page.url
    cur_title = page.title()
    print(f"  [NAV_OK]{tag} → {cur_url}  |  title: {cur_title}")
    # 检测 CAPTCHA / IP异常 / 验证码拦截
    content = page.content()[:2000]
    url_lower = cur_url.lower()
    if ("禁止访问" in cur_title or "sorry" in url_lower
            or "验证" in content or "ip" in url_lower):
        print(f"\n⚠️  被豆瓣拦截（验证码/IP异常），请在浏览器中完成验证后按 Enter...")
        print(f"     当前 URL: {cur_url}")
        print(f"     页面标题: {cur_title}")
        input()
        go(page, url, timeout, label=f"{label}(验证后重试)")


# ============================================================
# 第一步：爬关注列表（仅首次需要浏览器）
# ============================================================

def parse_contacts(html):
    """从关注列表 HTML 提取用户"""
    soup = BeautifulSoup(html, "html.parser")
    users = []
    for h3 in soup.find_all("h3"):
        a = h3.find("a", href=re.compile(r"people/\d+"))
        if a and a.get_text(strip=True):
            m = re.search(r"people/(\d+)", a["href"])
            if m:
                users.append({"uid": m.group(1), "name": a.get_text(strip=True)})
    return users


def fetch_contacts(page):
    """翻页爬取所有关注的人"""
    print("=" * 50)
    print("爬取关注列表")
    print("=" * 50)

    # 大号登录后 URL 变为 /contacts/list，结构变为 h3 包含用户链接
    all_users = []
    start = 0
    step = 20

    for pn in range(50):
        url = f"https://www.douban.com/contacts/list?tag=0&start={start}"
        print(f"\n  第 {pn+1} 页 start={start}")
        try_go(page, url)

        users = parse_contacts(page.content())
        if not users:
            html_snippet = page.content()[:2000]
            print(f"  -> 没有找到用户，页面标题: {page.title()}")
            print(f"  -> [DEBUG] URL: {page.url}")
            print(f"  -> [DEBUG] 页面片段:\n{html_snippet[:800]}")
            break

        all_users.extend(users)
        print(f"  -> {len(users)} 人，累计 {len(all_users)}")

        # 翻页
        next_start = start + step
        html = page.content()
        if f"start={next_start}" not in html:
            all_starts = [int(m) for m in re.findall(r"start=(\d+)", html)]
            bigger = [s for s in all_starts if s > start]
            if not bigger:
                break
            start = min(bigger)
        else:
            start = next_start

        time.sleep(CONTACTS_DELAY + random.uniform(-0.5, 0.5))

    # 去重
    seen = set()
    unique = []
    for u in all_users:
        if u["uid"] not in seen:
            seen.add(u["uid"])
            unique.append(u)

    # 存盘（保存 uid→name 映射，方便后续显示读者名）
    name_map = {u["uid"]: u["name"] for u in unique}
    with open(CONTACTS_FILE, "w", encoding="utf-8") as f:
        json.dump(name_map, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 共关注 {len(name_map)} 人，已保存到 {CONTACTS_FILE}")
    for u in unique:
        print(f"     {u['uid']}  {u['name']}")
    return list(name_map.keys())


# ============================================================
# 第二步：爬书单
# ============================================================

def parse_books(html):
    """从书单页提取书籍（含评分、年份、评语）"""
    soup = BeautifulSoup(html, "html.parser")
    books = []
    for item in soup.select("li.subject-item"):
        title_tag = item.select_one("div.info h2 a")
        if not title_tag:
            continue
        title = title_tag.get_text(strip=True)
        link = title_tag.get("href", "")

        douban_id = ""
        m = re.search(r"subject/(\d+)/", link)
        if m:
            douban_id = m.group(1)

        # 评分（从 class 名提取，如 rating5-t = 5星）
        rating_tag = item.select_one("div.short-note [class*=rating]")
        rating = ""
        if rating_tag:
            for cl in rating_tag.get("class", []):
                m2 = re.search(r"rating(\d)", cl)
                if m2:
                    rating = m2.group(1)
                    break

        # 读过日期
        date_tag = item.select_one("div.short-note span.date")
        date_str = date_tag.get_text(strip=True) if date_tag else ""
        # 提取年份
        year = ""
        if date_str:
            m3 = re.search(r"(\d{4})", date_str)
            if m3:
                year = m3.group(1)

        # 评语
        comment_tag = item.select_one("p.comment-item")
        comment = comment_tag.get_text(strip=True) if comment_tag else ""

        books.append({
            "title": title,
            "link": link,
            "douban_id": douban_id,
            "rating": rating,
            "year": year,
            "comment": comment,
        })
    return books


def fetch_user_books(page, uid):
    """爬一个用户的所有读过书籍"""
    books = []
    start = 0
    for _ in range(50):
        url = (f"https://book.douban.com/people/{uid}/collect"
               f"?start={start}&sort=time&rating=all&filter=all&mode=grid")
        try_go(page, url)

        # 模拟人浏览：随机滚动
        page.evaluate("window.scrollTo(0, document.body.scrollHeight * %f)" % random.uniform(0.3, 0.8))
        page.wait_for_timeout(random.randint(400, 1200))

        items = parse_books(page.content())
        if not items:
            break
        books.extend(items)
        start += 15
        time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
    return books


# ============================================================
# 断点续爬
# ============================================================

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"completed_uids": [], "all_user_books": {}}


def save_progress(completed, books):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump({"completed_uids": completed, "all_user_books": books},
                  f, ensure_ascii=False, indent=2)


def crawl_all(page, uids, browser=None):
    print("=" * 50)
    print("爬取书单")
    print("=" * 50)

    prog = load_progress()
    done = prog.get("completed_uids", [])
    all_books = prog.get("all_user_books", {})

    pending = [u for u in uids if u not in set(done)]
    print(f"已完成 {len(done)}/{len(uids)}，待完成 {len(pending)}\n")

    if not pending:
        return all_books

    i = 0
    while i < len(pending):
        uid = pending[i]
        print(f"  [{i+1}/{len(pending)}] {uid} ...", end=" ", flush=True)
        try:
            books = fetch_user_books(page, uid)
            all_books[uid] = books
            print(f"{len(books)} 本书")
            done.append(uid)
            save_progress(done, all_books)
            i += 1
        except TargetClosedError as e:
            print(f"\n  ⚠️ 页面已关闭: {e}")
            if browser:
                contexts = getattr(browser, 'contexts', None)
                if contexts:
                    print(f"  🔄 正在重建页面并重试...")
                    page = contexts[0].new_page()
                else:
                    raise
            else:
                raise
        except Exception as e:
            print(f"\n  ❌ {type(e).__name__}: {e}")
            print(f"  已爬取 {len(done)}/{len(uids)}，跳过 {uid}")
            done.append(uid)
            save_progress(done, all_books)
            i += 1

    return all_books


# ============================================================
# 统计
# ============================================================

def aggregate(all_books):
    print("=" * 50)
    print("统计排名")
    print("=" * 50)

    counter = Counter()
    details = {}
    readers = 0

    for uid, books in all_books.items():
        if not books:
            continue
        readers += 1
        seen = set()
        for b in books:
            title = re.sub(r"[：:（(].*", "", b["title"].strip()).strip()
            if title in seen:
                continue
            seen.add(title)
            counter[title] += 1
            if title not in details:
                details[title] = {
                    "link": b["link"],
                    "douban_id": b["douban_id"],
                    "ratings": [],
                }
            if b.get("rating"):
                details[title]["ratings"].append(float(b["rating"]))

    ranked = counter.most_common()
    print(f"\n有效读者: {readers}/{len(all_books)}")
    print(f"涉及书籍: {len(ranked)}\n")

    result = []
    for rank, (title, count) in enumerate(ranked[:100], 1):
        d = details[title]
        ratings = d["ratings"]
        avg = round(sum(ratings) / len(ratings), 2) if ratings else None
        result.append({
            "rank": rank, "count": count, "title": title,
            "link": d["link"], "avg_rating": avg,
        })
        r = f"  {avg}" if avg else ""
        print(f"{rank:>4}  {count:>5}人  {title}{r}")

    output = {"total_users": len(all_books), "readers_with_books": readers,
              "total_unique_books": len(ranked), "ranking": result}
    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {RESULT_FILE}")


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    has_contacts = os.path.exists(CONTACTS_FILE)

    with sync_playwright() as pw:
        browser, page = new_browser(pw)

        try:
            # ========== 第一步：关注列表 ==========
            if has_contacts:
                with open(CONTACTS_FILE, "r") as f:
                    contacts_data = json.load(f)
                # 兼容旧格式（列表）和新格式（{uid: name} 字典）
                if isinstance(contacts_data, dict):
                    uids = list(contacts_data.keys())
                else:
                    uids = contacts_data
                if uids:
                    print(f"✅ 已有关注列表，共 {len(uids)} 人，跳过第一步")
                else:
                    uids = None
            else:
                uids = None

            if uids is None:
                print("=" * 50)
                print("【调试】检查登录状态")
                print("=" * 50)
                go(page, "https://www.douban.com/contacts/list", label="检查登录")
                print(f"  [DEBUG] 当前 URL: {page.url}")
                print(f"  [DEBUG] 页面标题: {page.title()}")

                # 被重定向到登录页 → 需要手动登录
                if "accounts" in page.url or "登录" in page.title():
                    print("\n⚠️  未登录，进入登录流程")
                    print("  (Chrome 用户数据已持久化，登录一次后续自动复用)\n")
                    login_attempt = 0
                    while True:
                        login_attempt += 1
                        print(f"--- 登录尝试 #{login_attempt} ---")
                        try:
                            try_go(page, "https://www.douban.com", label=f"去豆瓣首页(#{login_attempt})")
                        except Exception as e:
                            print(f"  ⚠️ 页面加载失败: {e}")
                            print("  正在重新打开浏览器...")
                            try:
                                browser.close()
                            except Exception:
                                pass
                            browser, page = new_browser(pw)
                            continue

                        # 检查是否被 CAPTCHA / IP异常 拦截
                        content_preview = page.content()[:3000]
                        if "验证" in content_preview or "ip" in page.url.lower():
                            print(f"\n  ⚠️ 被豆瓣验证码/IP异常拦截")
                            print(f"     当前URL: {page.url}")
                            print(f"     页面标题: {page.title()}")
                            print(f"     请完成验证后按 Enter")
                            input()
                            continue

                        print("\n  请在浏览器中完成登录后按 Enter 继续...")
                        input()

                        # 校验是否真正登录成功
                        current_url = page.url
                        current_title = page.title()
                        content_after = page.content()[:3000]

                        print(f"\n  [DEBUG] 登录验证:")
                        print(f"     URL:   {current_url}")
                        print(f"     Title: {current_title}")
                        print(f"     页面片段: {content_after[:300]}")

                        if "accounts" in current_url:
                            print(f"  ⚠️ 仍在 accounts 路径，未登录成功")
                            continue
                        if "登录" in current_title and "注册" in content_after:
                            print(f"  ⚠️ 页面仍有登录/注册字样，未登录成功")
                            continue

                        print(f"  ✅ 登录验证通过")
                        break

                    # 登录成功后再回到关注列表页
                    print(f"\n  [INFO] 登录成功，前往关注列表页...")
                    go(page, "https://www.douban.com/contacts/list", label="登录后去关注列表")

                uids = fetch_contacts(page)
                if not uids:
                    sys.exit(1)

            # ========== 第二步：爬书单 ==========
            print("\n开始爬取书单...")
            try_go(page, "https://book.douban.com/")

            # 检查是否被重定向到登录/安全验证（session 过期等情况）
            cur_url = page.url
            cur_title = page.title()
            if "accounts" in cur_url or "sec.douban" in cur_url or "登录" in cur_title:
                print(f"\n⚠️  登录状态已过期，请在浏览器中手动登录豆瓣后按 Enter...")
                print(f"     当前 URL: {cur_url}")
                input()
                try_go(page, "https://book.douban.com/", label="登录后重试")

            while True:
                try:
                    all_books = crawl_all(page, uids, browser=browser)
                    break
                except TargetClosedError:
                    print("\n  ⚠️ 浏览器已关闭，正在重新打开...")
                    try:
                        browser.close()
                    except Exception:
                        pass
                    browser, page = new_browser(pw)
                    try_go(page, "https://book.douban.com/", label="重建后回首页")

        finally:
            try:
                browser.close()
            except Exception:
                pass

    # ========== 第三步：统计 ==========
    aggregate(all_books)
    print("\n✅ 全部完成！")
