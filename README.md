# 豆瓣关注用户读书爬虫

爬取你所有豆瓣关注用户的「读过」书单，统计被最多人读过的书，并通过 GUI 交互式浏览排行榜。

## 数据流

```
douban_book_crawler.py          → douban_contacts.json  (关注列表)
  (爬虫, 登录→爬关注→爬书单)     → douban_progress.json (每个用户的读书记录)
                                 → douban_result.json   (排行榜)
                                        ↓
douban_build_readers.py          → douban_result.json   (注入读者列表)
  (反转, 书→读者列表)
                                        ↓
douban_book_gui.py               ← douban_result.json + douban_progress.json + douban_contacts.json
  (GUI, 排行榜浏览)
```

## 用户需要补充的配置

编辑 `douban_book_crawler.py`，修改以下配置：

```python
YOUR_UID = ""          # 改为你的豆瓣 UID（个人主页 URL 中的数字）
MIN_DELAY = 6.0        # 爬取延迟，被 ban 后调大
MAX_DELAY = 10.0
CONTACTS_DELAY = 5.0   # 关注列表翻页延迟
PROXY = "http://127.0.0.1:7890"  # 本地代理地址，按需修改
```

**如何找到你的 UID：** 登录豆瓣后访问 `https://www.douban.com/people/`，URL 末尾的数字串即是 UID。

## 使用方法

### 1. 安装依赖

```bash
pip install playwright beautifulsoup4 lxml
playwright install chromium
```

### 2. 运行爬虫

```bash
python douban_book_crawler.py
```

首次运行会自动打开 Chrome 浏览器，需要你在浏览器中扫码/登录豆瓣。登录后程序会自动爬取关注列表和所有人的书单。

- **断点续爬：** 每爬完一人自动存档，中断后重跑会自动从断点继续
- **被反爬拦截：** 程序会暂停并提示你在浏览器中完成验证，按 Enter 继续

### 3. 构建读者列表

爬虫完成后，运行反转脚本给排行榜注入读者信息：

```bash
python douban_build_readers.py
```

### 4. 启动 GUI 排行榜

```bash
python douban_book_gui.py
```

GUI 功能：

- 按读过人数/评分排序
- 筛选最低读过人数
- 仅显示社会学书籍
- 搜索书名
- 随机推荐五本好书 / 五本社会学好书
- **双击行**：排行榜中双击「读过人数」列查看读者列表 → 双击读者查看其个人书单
- 右键菜单：备选交互方式

## 输出文件说明

| 文件 | 用途 |
|------|------|
| `douban_contacts.json` | 关注列表（uid → 用户名映射） |
| `douban_progress.json` | 每个用户的读书记录（含书名、评分、评语、豆瓣链接） |
| `douban_result.json` | 排行榜（含排名、读过人数、评分、读者列表） |
| `douban_crawler_log.txt` | 爬虫运行日志 |
| `.chrome_data/` | Chrome 独立用户数据目录（登录会话持久化） |
