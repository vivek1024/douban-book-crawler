"""
从 douban_progress.json 反转出「书 → 读者列表」，注入 douban_result.json。
同时读取 douban_contacts.json（如果是 {uid: name} 字典）来显示用户名。

用法：python3 douban_build_readers.py
"""

import json
import os
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROGRESS_FILE = os.path.join(BASE_DIR, "douban_progress.json")
CONTACTS_FILE = os.path.join(BASE_DIR, "douban_contacts.json")
RESULT_FILE = os.path.join(BASE_DIR, "douban_result.json")


def normalize_title(title):
    """与 douban_book_crawler.aggregate() 相同的标题归一化"""
    return re.sub(r"[：:（(].*", "", title.strip()).strip()


def build():
    # 1. 读取 progress
    with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
        progress = json.load(f)
    all_user_books = progress.get("all_user_books", {})
    print(f"用户数: {len(all_user_books)}")

    # 2. 读取 contacts（可能是列表或字典）
    with open(CONTACTS_FILE, "r", encoding="utf-8") as f:
        contacts = json.load(f)
    if isinstance(contacts, dict):
        uid_to_name = contacts  # {uid: name}
    else:
        uid_to_name = {}  # 只有 uid，暂无名字
    print(f"有用户名映射: {len(uid_to_name)} 人")

    # 3. 反转：按 douban_id 和归一化标题两种方式索引
    id_readers = {}    # douban_id → set of uid
    title_readers = {} # normalized_title → set of uid
    for uid, books in all_user_books.items():
        for b in books:
            did = b.get("douban_id", "")
            if did:
                id_readers.setdefault(did, set()).add(uid)
            norm = normalize_title(b.get("title", ""))
            if norm:
                title_readers.setdefault(norm, set()).add(uid)

    print(f"按 douban_id 索引: {len(id_readers)} 本")
    print(f"按标题索引: {len(title_readers)} 本")

    # 4. 注入 result
    with open(RESULT_FILE, "r", encoding="utf-8") as f:
        result = json.load(f)

    injected = 0
    for book in result.get("ranking", []):
        did = book.get("douban_id", "")
        title = book.get("title", "")

        # 优先用 douban_id 匹配，其次用归一化标题匹配
        uids = id_readers.get(did, set())
        if not uids:
            norm_title = normalize_title(title)
            uids = title_readers.get(norm_title, set())

        if uids:
            if uid_to_name:
                readers = [uid_to_name.get(uid, uid) for uid in sorted(uids)]
            else:
                readers = sorted(uids)
            book["readers"] = readers
            injected += 1
        else:
            book["readers"] = []

    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"注入 readers 字段: {injected}/{len(result['ranking'])} 本书")
    print(f"已保存: {RESULT_FILE}")


if __name__ == "__main__":
    build()
