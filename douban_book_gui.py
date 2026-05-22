"""
豆瓣读书排行榜 GUI
读取 douban_result.json，按条件筛选和排序展示。
支持多级视图：排行榜 → 读者列表 → 用户书单，全部在主表格内切换。
"""

import json
import os
import random
import re
import tkinter as tk
import webbrowser
from tkinter import ttk, messagebox

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULT_FILE = os.path.join(BASE_DIR, "douban_result.json")
SOCIOLOGY_FILE = os.path.join(BASE_DIR, "douban_sociology.json")
PROGRESS_FILE = os.path.join(BASE_DIR, "douban_progress.json")
CONTACTS_FILE = os.path.join(BASE_DIR, "douban_contacts.json")


class BookRankingGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("豆瓣关注用户读书排行榜")
        self.root.geometry("900x650")
        self.root.minsize(700, 500)

        self.data = self.load_data()
        self.user_books, self.name_to_uid, self.uid_to_name = self.load_user_data()

        self.view_stack = []
        self.current_view = "ranking"

        self.build_ui()
        self.show_ranking_view()

    def load_data(self):
        if not os.path.exists(RESULT_FILE):
            return []
        with open(RESULT_FILE, "r", encoding="utf-8") as f:
            obj = json.load(f)
        books = obj.get("ranking", [])
        return self._merge_same_title_books(books)

    @staticmethod
    def _merge_same_title_books(books):
        norm_map = {}  # norm_title -> [book, ...]
        order = []
        for b in books:
            norm = re.sub(r'\s+', '', b["title"].strip())
            if norm not in norm_map:
                norm_map[norm] = []
                order.append(norm)
            norm_map[norm].append(b)

        if all(len(v) == 1 for v in norm_map.values()):
            return books

        merged = []
        for norm in order:
            group = norm_map[norm]
            if len(group) == 1:
                merged.append(group[0])
                continue
            # 用读过人数最多的条目为基底
            base = max(group, key=lambda b: len(b.get("readers", [])) or b.get("count", 0))
            # 合并读者（去重）
            all_readers = []
            seen = set()
            for b in group:
                for r in b.get("readers", []):
                    uid = r if isinstance(r, str) else r.get("uid", r) if isinstance(r, dict) else r
                    if uid not in seen:
                        seen.add(uid)
                        all_readers.append(r)
            # 加权平均评分（按各条目读者数加权）
            total_weight = 0
            weighted_sum = 0
            for b in group:
                r = b.get("avg_rating")
                if r is not None:
                    w = len(b.get("readers", [])) or b.get("count", 0) or 1
                    weighted_sum += float(r) * w
                    total_weight += w
            new_book = dict(base)
            new_book["readers"] = all_readers
            new_book["count"] = max(b.get("count", 0) for b in group)
            if total_weight > 0:
                new_book["avg_rating"] = weighted_sum / total_weight
            merged.append(new_book)
        return merged

    def load_user_data(self):
        user_books = {}
        if os.path.exists(PROGRESS_FILE):
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                user_books = json.load(f).get("all_user_books", {})
        name_to_uid = {}
        uid_to_name = {}
        if os.path.exists(CONTACTS_FILE):
            with open(CONTACTS_FILE, "r", encoding="utf-8") as f:
                contacts = json.load(f)
            if isinstance(contacts, dict):
                for uid, name in contacts.items():
                    name_to_uid[name] = uid
                    uid_to_name[uid] = name
        return user_books, name_to_uid, uid_to_name

    def build_ui(self):
        # ── 顶部容器（统计 + 导航 + 筛选，固定在表格上方）──
        self.top_frame = ttk.Frame(self.root)
        self.top_frame.pack(fill=tk.X)

        # ── 顶部统计信息 ──
        self.info_frame = ttk.Frame(self.top_frame, padding=(10, 8))
        self.info_frame.pack(fill=tk.X)
        if self.data:
            with open(RESULT_FILE, "r", encoding="utf-8") as f:
                meta = json.load(f)
            info_text = (f"总用户: {meta.get('total_users', '?')}  |  "
                         f"有效读者: {meta.get('readers_with_books', '?')}  |  "
                         f"涉及书籍: {meta.get('total_unique_books', '?')}")
            ttk.Label(self.info_frame, text=info_text,
                      font=("", 11)).pack(side=tk.LEFT)

        # ── 导航栏 ──
        self.nav_frame = ttk.Frame(self.top_frame, padding=(10, 4))
        self.back_btn = ttk.Button(self.nav_frame, text="← 返回", command=self.go_back)
        self.breadcrumb_var = tk.StringVar(value="")
        ttk.Label(self.nav_frame, textvariable=self.breadcrumb_var,
                  font=("", 11)).pack(side=tk.LEFT, padx=(10, 0))

        # ── 筛选/排序控制区 ──
        self.ctrl = ttk.LabelFrame(self.top_frame, text="筛选与排序", padding=10)
        self.ctrl.pack(fill=tk.X, padx=10, pady=(4, 4))

        ttk.Label(self.ctrl, text="读过人数 ≥").grid(row=0, column=0, sticky=tk.W)
        self.min_count_var = tk.StringVar(value="0")
        ttk.Entry(self.ctrl, textvariable=self.min_count_var,
                  width=6).grid(row=0, column=1, padx=(4, 20))

        ttk.Label(self.ctrl, text="主排序:").grid(row=0, column=2, sticky=tk.W)
        self.primary_var = tk.StringVar(value="读过人数")
        ttk.Combobox(self.ctrl, textvariable=self.primary_var,
                     values=["读过人数", "评分"],
                     state="readonly", width=10).grid(row=0, column=3, padx=(4, 20))

        ttk.Label(self.ctrl, text="次排序:").grid(row=0, column=4, sticky=tk.W)
        self.secondary_var = tk.StringVar(value="无")
        ttk.Combobox(self.ctrl, textvariable=self.secondary_var,
                     values=["无", "读过人数", "评分"],
                     state="readonly", width=10).grid(row=0, column=5, padx=(4, 20))

        self.soc_only_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.ctrl, text="仅社会学书籍",
                        variable=self.soc_only_var).grid(row=0, column=6, padx=(10, 0))

        ttk.Button(self.ctrl, text="生成排行榜",
                   command=self.show_ranking_view).grid(row=0, column=7, padx=(10, 0))

        ttk.Button(self.ctrl, text="随机五本好书",
                   command=self.random_good_books
                   ).grid(row=1, column=0, columnspan=2, pady=(8, 0), sticky=tk.W)
        ttk.Button(self.ctrl, text="随机五本社会学好书",
                   command=self.random_sociology_books
                   ).grid(row=1, column=2, columnspan=2, pady=(8, 0), sticky=tk.W)

        ttk.Label(self.ctrl, text="搜索书名:").grid(row=1, column=4, sticky=tk.W, pady=(8, 0))
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(self.ctrl, textvariable=self.search_var, width=18)
        search_entry.grid(row=1, column=5, padx=(4, 4), pady=(8, 0), sticky=tk.W)
        search_entry.bind("<Return>", lambda e: self.search_books())
        ttk.Button(self.ctrl, text="搜索",
                   command=self.search_books).grid(row=1, column=6, pady=(8, 0), sticky=tk.W)

        # ── 结果表格 ──
        tree_frame = ttk.Frame(self.root)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(4, 10))

        self.tree = ttk.Treeview(tree_frame, show="headings", selectmode="browse")
        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Motion>", self._on_motion)
        # 右键菜单（备选交互方式）
        self.ctx_menu = tk.Menu(self.root, tearoff=0)
        self.tree.bind("<Button-3>", self._on_right_click)  # macOS: Button-2 或 Control-Button-1
        self.tree.bind("<Button-2>", self._on_right_click)

        # ── 底部状态栏 ──
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(self.root, textvariable=self.status_var,
                  relief=tk.SUNKEN, anchor=tk.W,
                  padding=(8, 2)).pack(fill=tk.X, side=tk.BOTTOM)

    # ── 视图切换核心 ──

    def _configure_tree(self, columns, headings, widths):
        self.tree["columns"] = columns
        for col, heading, width in zip(columns, headings, widths):
            self.tree.heading(col, text=heading)
            self.tree.column(col, width=width, minwidth=max(40, width // 3))

    def _clear_tree(self):
        for row in self.tree.get_children():
            self.tree.delete(row)

    def _show_nav(self, breadcrumb):
        self.nav_frame.pack(fill=tk.X, padx=10, pady=(0, 0), after=self.info_frame)
        self.back_btn.pack(side=tk.LEFT)
        self.breadcrumb_var.set(breadcrumb)

    def _hide_nav(self):
        self.nav_frame.pack_forget()

    def go_back(self):
        if not self.view_stack:
            return
        view_type, context, _ = self.view_stack.pop()
        if view_type == "ranking":
            self.show_ranking_view(restore=True)
        elif view_type == "readers":
            self._show_readers_view(context["title"], context["readers"], restore=True)

    # ── 排行榜视图 ──

    def show_ranking_view(self, restore=False):
        if not restore:
            self.view_stack.clear()
        self.current_view = "ranking"
        self._hide_nav()
        self.ctrl.pack(fill=tk.X, padx=10, pady=(4, 4))

        self._configure_tree(
            columns=("rank", "title", "count", "rating", "link"),
            headings=("#", "书名", "读过人数 (双击)", "评分", "豆瓣链接"),
            widths=(45, 360, 80, 65, 280),
        )
        self._clear_tree()
        self._fill_ranking()

    def _fill_ranking(self):
        try:
            min_n = int(self.min_count_var.get())
        except ValueError:
            messagebox.showwarning("输入错误", "请输入整数")
            return

        primary = self.primary_var.get()
        secondary = self.secondary_var.get()

        filtered = [b for b in self.data if self._get_count(b) >= min_n]
        if self.soc_only_var.get():
            filtered = [b for b in filtered if "社会学" in b.get("tags", [])]

        def sort_key(book):
            count = self._get_count(book)
            rating = book.get("avg_rating") or 0
            vals = {"读过人数": -count, "评分": -rating}
            if secondary == "无":
                return (vals[primary],)
            return (vals[primary], vals[secondary])

        filtered.sort(key=sort_key)
        total_filtered = len(filtered)
        filtered = filtered[:1000]

        for i, b in enumerate(filtered, 1):
            rating_str = f"{b['avg_rating']:.2f}" if b.get("avg_rating") else "-"
            self.tree.insert("", tk.END, values=(
                i, b["title"], self._get_count(b), rating_str, b.get("link", "")
            ))

        self.status_var.set(
            f"共 {len(self.data)} 本书  |  "
            f"筛选(≥{min_n}人): {total_filtered} 本  |  "
            f"展示前 {len(filtered)} 本  |  "
            f"主排序: {primary}  次排序: {secondary}  |  "
            f"双击「读过人数」列查看读者列表"
        )

    # ── 读者视图 ──

    def _resolve_reader(self, reader_raw):
        """Resolve reader identifier to (display_name, uid)."""
        reader_raw = str(reader_raw).strip()
        # 1. Already a UID in contacts
        if reader_raw in self.uid_to_name:
            return self.uid_to_name[reader_raw], reader_raw
        # 2. Already a display name with known UID
        if reader_raw in self.name_to_uid:
            return reader_raw, self.name_to_uid[reader_raw]
        # 3. UID not in contacts but has books
        if reader_raw in self.user_books:
            return reader_raw, reader_raw
        # 4. Fallback: search contacts values for matching display name
        #    (handles case where name changed or has subtle differences)
        for uid, name in self.uid_to_name.items():
            if name.strip() == reader_raw:
                return reader_raw, uid
        return reader_raw, reader_raw

    def _show_readers_view(self, book_title, readers, restore=False):
        if not restore:
            self.view_stack.append(("ranking", {}, ""))
        self.current_view = "readers"
        self._current_book_title = book_title
        self._current_readers = readers

        self._show_nav(f"排行榜 > 《{book_title}》的读者（双击查看书单）")
        self.ctrl.pack_forget()

        self._configure_tree(
            columns=("idx", "name", "has_books"),
            headings=("#", "读者", "有书单"),
            widths=(50, 480, 80),
        )
        self._clear_tree()

        for i, raw in enumerate(readers, 1):
            display_name, uid = self._resolve_reader(raw)
            has = "✓" if uid in self.user_books else ""
            self.tree.insert("", tk.END, values=(i, display_name, has),
                             tags=(uid,))

        self.status_var.set(
            f"《{book_title}》共 {len(readers)} 人读过  |  "
            f"双击「有书单」标记为 ✓ 的读者查看其阅读记录"
        )

    # ── 用户书单视图 ──

    def _show_user_books_view(self, reader_name, books):
        self.view_stack.append(("readers", {
            "title": self._current_book_title,
            "readers": self._current_readers,
        }, ""))
        self.current_view = "user_books"

        self._show_nav(
            f"排行榜 > 《{self._current_book_title}》的读者 > {reader_name} 的书单（双击打开链接）"
        )

        def year_key(b):
            y = b.get("year", "")
            try:
                return -int(y)
            except (ValueError, TypeError):
                return 0
        books = sorted(books, key=year_key)

        self._configure_tree(
            columns=("idx", "title", "rating", "year"),
            headings=("#", "书名", "评分", "年份"),
            widths=(45, 450, 60, 80),
        )
        self._clear_tree()

        for i, b in enumerate(books, 1):
            rating = b.get("rating", "") or ""
            year = b.get("year", "") or ""
            self.tree.insert("", tk.END, values=(i, b["title"], rating, year),
                             tags=(b.get("link", ""),))

        self.status_var.set(f"{reader_name} 共读过 {len(books)} 本书  |  双击书名打开豆瓣链接")

    # ── 事件处理 ──

    def _on_double_click(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            return
        vals = self.tree.item(item, "values")

        if self.current_view == "ranking":
            col = self.tree.identify_column(event.x)
            if col == "#3":
                book_title = vals[1]
                count = vals[2]
                if count and count != "0":
                    book = next((b for b in self.data if b["title"] == book_title), None)
                    if book and book.get("readers"):
                        self._show_readers_view(book_title, book["readers"])
            else:
                link = vals[4]
                if link and link.startswith("http"):
                    webbrowser.open(link)

        elif self.current_view == "readers":
            reader_name = vals[1]
            tags = self.tree.item(item, "tags")
            uid = tags[0] if tags else reader_name
            books = self.user_books.get(uid, [])
            if not books and reader_name != uid:
                alt_uid = self.name_to_uid.get(reader_name.strip())
                if alt_uid:
                    books = self.user_books.get(alt_uid, [])
            if not books:
                messagebox.showinfo("提示",
                                    f"未找到「{reader_name}」的阅读记录\n（uid: {uid}）")
                return
            self._show_user_books_view(reader_name, books)

        elif self.current_view == "user_books":
            link = self.tree.item(item, "tags")[0] if self.tree.item(item, "tags") else ""
            if link and link.startswith("http"):
                webbrowser.open(link)

    def _on_motion(self, event):
        col = self.tree.identify_column(event.x)
        row = self.tree.identify_row(event.y)
        clickable = False
        if self.current_view == "ranking" and col == "#3" and row:
            # count column is clickable
            item = self.tree.item(row)
            count = item["values"][2] if len(item["values"]) > 2 else 0
            try:
                clickable = int(count) > 0
            except (ValueError, TypeError):
                pass
        elif self.current_view == "readers" and col == "#2" and row:
            clickable = True
        elif self.current_view == "user_books" and row:
            clickable = True
        self.tree.config(cursor="hand2" if clickable else "")

    def _on_right_click(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            return
        self.tree.selection_set(item)
        vals = self.tree.item(item, "values")

        self.ctx_menu.delete(0, tk.END)
        if self.current_view == "ranking":
            count = vals[2] if len(vals) > 2 else "0"
            if count and count != "0":
                self.ctx_menu.add_command(
                    label=f"查看《{vals[1]}》的读者",
                    command=lambda: self._open_readers_from_menu(vals[1]))
            link = vals[4] if len(vals) > 4 else ""
            if link and link.startswith("http"):
                self.ctx_menu.add_command(
                    label="在浏览器中打开豆瓣链接",
                    command=lambda: webbrowser.open(link))

        elif self.current_view == "readers":
            reader_name = vals[1]
            tags = self.tree.item(item, "tags")
            uid = tags[0] if tags else reader_name
            self.ctx_menu.add_command(
                label=f"查看「{reader_name}」的书单",
                command=lambda: self._open_user_books_from_menu(item))

        elif self.current_view == "user_books":
            tags = self.tree.item(item, "tags")
            link = tags[0] if tags else ""
            if link and link.startswith("http"):
                self.ctx_menu.add_command(
                    label="在浏览器中打开豆瓣链接",
                    command=lambda: webbrowser.open(link))

        if self.ctx_menu.index(tk.END) is not None:
            self.ctx_menu.tk_popup(event.x_root, event.y_root)

    def _open_readers_from_menu(self, book_title):
        book = next((b for b in self.data if b["title"] == book_title), None)
        if book and book.get("readers"):
            self._show_readers_view(book_title, book["readers"])

    def _open_user_books_from_menu(self, item):
        vals = self.tree.item(item, "values")
        reader_name = vals[1]
        tags = self.tree.item(item, "tags")
        uid = tags[0] if tags else reader_name
        books = self.user_books.get(uid, [])
        if not books and reader_name != uid:
            alt_uid = self.name_to_uid.get(reader_name.strip())
            if alt_uid:
                books = self.user_books.get(alt_uid, [])
        if not books:
            messagebox.showinfo("提示",
                                f"未找到「{reader_name}」的阅读记录\n（uid: {uid}）")
            return
        self._show_user_books_view(reader_name, books)

    # ── 工具方法 ──

    @staticmethod
    def _get_rating(book):
        r = book.get("avg_rating") or book.get("rating")
        if r is None:
            return 0.0
        try:
            return float(r)
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _get_count(book):
        return book.get("count", 0)

    def _show_random_picks(self, pool, label):
        candidates = [b for b in pool if self._get_rating(b) >= 4.0]
        if len(candidates) < 5:
            messagebox.showinfo("提示", f"符合条件的{label}不足5本")
            return
        picks = random.sample(candidates, 5)
        picks.sort(key=lambda b: -self._get_rating(b))

        self.view_stack.clear()
        self.current_view = "ranking"
        self._hide_nav()
        self.ctrl.pack(fill=tk.X, padx=10, pady=(4, 4))
        self._configure_tree(
            columns=("rank", "title", "count", "rating", "link"),
            headings=("#", "书名", "读过人数", "评分", "豆瓣链接"),
            widths=(45, 360, 80, 65, 280),
        )
        self._clear_tree()
        for i, b in enumerate(picks, 1):
            rating = self._get_rating(b)
            rating_str = f"{rating:.2f}" if rating else "-"
            self.tree.insert("", tk.END, values=(
                i, b["title"], self._get_count(b), rating_str, b.get("link", "")
            ))
        titles = "、".join(b["title"] for b in picks)
        self.status_var.set(f"随机{label}推荐: {titles}")

    # ── 搜索视图 ──

    def search_books(self):
        keyword = self.search_var.get().strip()
        if not keyword:
            messagebox.showinfo("提示", "请输入搜索关键词")
            return
        results = [b for b in self.data if keyword.lower() in b["title"].lower()]
        if not results:
            messagebox.showinfo("搜索结果", f"未找到包含「{keyword}」的书籍")
            return
        results.sort(key=lambda b: -self._get_count(b))
        self.view_stack.clear()
        self.current_view = "ranking"
        self._hide_nav()
        self.ctrl.pack(fill=tk.X, padx=10, pady=(4, 4))
        self._configure_tree(
            columns=("rank", "title", "count", "rating", "link"),
            headings=("#", "书名", "读过人数", "评分", "豆瓣链接"),
            widths=(45, 360, 80, 65, 280),
        )
        self._clear_tree()
        for i, b in enumerate(results, 1):
            rating_str = f"{b['avg_rating']:.2f}" if b.get("avg_rating") else "-"
            self.tree.insert("", tk.END, values=(
                i, b["title"], self._get_count(b), rating_str, b.get("link", "")
            ))
        self.status_var.set(f"搜索「{keyword}」找到 {len(results)} 本书，按读过人数排序")

    def random_good_books(self):
        self._show_random_picks(self.data, "好书")

    def random_sociology_books(self):
        if os.path.exists(SOCIOLOGY_FILE):
            with open(SOCIOLOGY_FILE, "r", encoding="utf-8") as f:
                soc = json.load(f).get("books", [])
        else:
            soc = [b for b in self.data if "社会学" in b.get("tags", [])]
        main_map = {b["douban_id"]: b for b in self.data if "douban_id" in b}
        for b in soc:
            did = b.get("douban_id", "")
            main_book = main_map.get(did)
            if main_book:
                if "count" not in b:
                    b["count"] = main_book.get("count", 0)
                if "readers" not in b:
                    b["readers"] = main_book.get("readers", [])
            else:
                b.setdefault("count", 0)
                b.setdefault("readers", [])
        self._show_random_picks(soc, "社会学好书")


def main():
    root = tk.Tk()
    BookRankingGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
