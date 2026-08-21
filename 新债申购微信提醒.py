#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新债申购提醒工具 v3
每天 10:00 和 14:00 各检查推送一次，有债才推，无债静默。
数据源: 同花顺 AKShare
推送渠道: 飞书群机器人(webhook) / 微信 PushPlus 二选一
"""

import requests
import datetime
import time
import os
import sys
import tkinter as tk
from tkinter import scrolledtext, messagebox
import threading

# ═══════════════════════════════════════════════════════════
#  配置区 — 按你选用的渠道填一项即可
# ═══════════════════════════════════════════════════════════

# 渠道 1: 飞书群机器人 (推荐)
# 获取: 飞书群 → 群设置 → 群机器人 → 添加自定义机器人 → 复制 Webhook
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "").strip()

# 渠道 2: 微信 PushPlus
# 获取: https://www.pushplus.plus/ 注册 → 密钥管理 → 生成 PushKey
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "").strip()

# 推送时间点（24小时制，每天这些整点检查）
PUSH_HOURS = [10, 14]

# 记忆文件：记录今天是否已经在这个时段推送过，避免重复
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".kzz_remind_state")
WECHAT_TITLE = "📢 今日新债申购提醒"
# ═══════════════════════════════════════════════════════════


# ─── 数据获取 ─────────────────────────────────────────────
def fetch_today_bonds():
    """从同花顺 AKShare 获取今日可申购新债"""
    try:
        import akshare as ak
        import pandas as pd

        df = ak.bond_zh_cov_info_ths()
        today = datetime.date.today().isoformat()

        df = df.dropna(subset=["申购日期"])
        df["申购日期"] = df["申购日期"].apply(
            lambda x: str(x).split(" ")[0] if pd.notna(x) else ""
        )
        today_df = df[df["申购日期"] == today].copy()

        bonds = []
        for _, row in today_df.iterrows():
            bonds.append({
                "code":     str(row.get("债券代码", "")),
                "name":     str(row.get("债券简称", "")),
                "sub_code": str(row.get("申购代码", "")),
                "amount":   str(row.get("计划发行量", "")),
                "rate":     str(row.get("中签率", "")),
                "stock":    str(row.get("正股简称", "")),
            })
        return bonds
    except Exception as e:
        return {"error": str(e)}


# ─── 消息格式化 ───────────────────────────────────────────
def format_message(bonds):
    if isinstance(bonds, dict) and "error" in bonds:
        return f"❌ 获取数据失败: {bonds['error']}\n请检查网络后重试。"

    if not bonds:
        return f"✅ 今天（{datetime.date.today().isoformat()}）没有新债申购，放心摸鱼～"

    lines = [f"📅 今日 ({datetime.date.today().isoformat()}) 有 {len(bonds)} 只新债可申购：\n"]
    for i, b in enumerate(bonds, 1):
        lines.append(
            f"{i}. {b['name']} ({b['code']})\n"
            f"   申购代码：{b['sub_code']}\n"
            f"   正股：{b['stock']}\n"
            f"   发行规模：{b['amount']} 万元\n"
            f"   中签率：{b['rate']}\n"
        )
    lines.append("⏰ 请在交易时间内（9:30-11:30 / 13:00-15:00）打开券商APP申购！")
    return "\n".join(lines)


# ─── 推送 ─────────────────────────────────────────────────
def send_feishu(text):
    if not FEISHU_WEBHOOK:
        return False, "未配置 FEISHU_WEBHOOK"
    payload = {"msg_type": "text", "content": {"text": text}}
    try:
        r = requests.post(FEISHU_WEBHOOK, json=payload, timeout=10)
        result = r.json()
        if result.get("code") == 0 or "success" in str(result).lower():
            return True, "飞书推送成功"
        return False, f"飞书返回: {result}"
    except Exception as e:
        return False, f"飞书发送失败: {e}"


def send_wechat(title, content):
    if not PUSHPLUS_TOKEN:
        return False, "未配置 PUSHPLUS_TOKEN"
    url = "https://www.pushplus.plus/send"
    payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content, "channel": "wechat"}
    try:
        r = requests.post(url, json=payload, timeout=15)
        result = r.json()
        if result.get("code") == 200:
            return True, "微信推送成功"
        return False, f"PushPlus 返回: {result}"
    except Exception as e:
        return False, f"微信发送失败: {e}"


def push_all_channels(text):
    results = []
    if FEISHU_WEBHOOK:
        ok, info = send_feishu(text)
        results.append(f"{'✅' if ok else '❌'} 飞书: {info}")
    if PUSHPLUS_TOKEN:
        ok, info = send_wechat(WECHAT_TITLE, text)
        results.append(f"{'✅' if ok else '❌'} 微信: {info}")
    if not FEISHU_WEBHOOK and not PUSHPLUS_TOKEN:
        return False, "⚠️ 未配置推送渠道！请在界面右上角编辑配置"
    return True, " | ".join(results)


# ─── 状态管理 ─────────────────────────────────────────────
def load_state():
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return set(f.read().strip().split("\n"))
    except Exception:
        pass
    return set()


def save_state(pushed_slots):
    """pushed_slots: set of strings like '2026-08-21:10'"""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(sorted(pushed_slots)))
    except Exception:
        pass


def get_pushed_today():
    """返回今天已经推送过的时段列表，如 ['10', '14']"""
    today = datetime.date.today().isoformat()
    state = load_state()
    pushed = set()
    for line in state:
        if line.startswith(today + ":"):
            pushed.add(line.split(":")[1])
    return pushed


def mark_pushed(slot_hour):
    """标记今天某个时段已推送"""
    state = load_state()
    today = datetime.date.today().isoformat()
    # 移除今天的旧记录，加上新的
    state = {s for s in state if not s.startswith(today + ":")}
    state.add(f"{today}:{slot_hour}")
    save_state(state)


# ─── 定时调度 ─────────────────────────────────────────────
def seconds_until_next_check():
    """计算距离下一次检查还有多少秒"""
    now = datetime.datetime.now()
    today_pushed = get_pushed_today()

    for hour in sorted(PUSH_HOURS):
        slot_str = str(hour)
        if slot_str in today_pushed:
            continue  # 今天这个时段已经推过了，找下一个
        next_time = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if next_time > now:
            return (next_time - now).total_seconds(), hour

    # 今天所有时段都已推送完，计算到明天第一个时段
    tomorrow = now + datetime.timedelta(days=1)
    tomorrow_pushed = set()  # 新的一天，没有推送过
    for hour in sorted(PUSH_HOURS):
        next_time = tomorrow.replace(hour=hour, minute=0, second=0, microsecond=0)
        if next_time > now:
            return (next_time - now).total_seconds(), hour
    return 3600, PUSH_HOURS[0]  # fallback: 1小时后重试


def run_scheduler(log_func, stop_event):
    """定时调度主循环"""
    while not stop_event.is_set():
        wait_secs, next_hour = seconds_until_next_check()
        next_time_str = (datetime.datetime.now() + datetime.timedelta(seconds=wait_secs)).strftime("%H:%M")
        log_func(f"⏰ 下次检查时间: {next_time_str}（{next_hour}:00）")

        # 分段等待，方便响应停止信号
        waited = 0
        while waited < wait_secs and not stop_event.is_set():
            time.sleep(min(5, wait_secs - waited))
            waited += 5

        if stop_event.is_set():
            break

        # 到点检查
        do_check(log_func, next_hour)


def do_check(log_func, scheduled_hour):
    """执行一次检查+推送"""
    now = datetime.datetime.now()
    today_pushed = get_pushed_today()

    # 防止重复（手动检查也可能触发）
    slot_key = str(scheduled_hour)
    if slot_key in today_pushed:
        log_func(f"ℹ️ {scheduled_hour}:00 时段今天已推送过，跳过。")
        return

    log_func(f"🔍 [{now.strftime('%H:%M:%S')}] 执行 {scheduled_hour}:00 检查...")

    bonds = fetch_today_bonds()
    msg   = format_message(bonds)
    log_func(f"\n{msg}\n")

    # 无论有没有债，都推送（让用户看到结果）
    log_func("正在推送...")
    ok, info = push_all_channels(msg)
    log_func(f"{'✅' if ok else '❌'} {info}")

    if ok:
        mark_pushed(slot_key)


# ─── GUI ──────────────────────────────────────────────────
class ReminderApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("新债申购提醒 v3")
        self.root.geometry("620x520")
        self.root.minsize(500, 400)

        # 标题
        top = tk.Frame(self.root, padx=10, pady=8)
        top.pack(fill=tk.X)
        tk.Label(top, text="📢 新债申购提醒", font=("Microsoft YaHei", 14, "bold")).pack(side=tk.LEFT)

        # 渠道状态（可点击编辑）
        self.channel_label = tk.Label(
            top, text=self._channel_status(),
            fg="gray", font=("Microsoft YaHei", 9), cursor="hand2"
        )
        self.channel_label.pack(side=tk.RIGHT)
        self.channel_label.bind("<Button-1>", self.on_edit_config)

        # 日志
        log_frame = tk.Frame(self.root, padx=10, pady=5)
        log_frame.pack(fill=tk.BOTH, expand=True)
        tk.Label(log_frame, text="运行日志：", anchor="w").pack(fill=tk.X)
        self.log_box = scrolledtext.ScrolledText(
            log_frame, wrap=tk.WORD, font=("Consolas", 10), height=22
        )
        self.log_box.pack(fill=tk.BOTH, expand=True)

        # 底部按钮
        btn_frame = tk.Frame(self.root, padx=10, pady=8)
        btn_frame.pack(fill=tk.X)

        self.status_label = tk.Label(btn_frame, text="● 运行中", fg="green", font=("Microsoft YaHei", 10))
        self.status_label.pack(side=tk.LEFT)

        tk.Button(btn_frame, text="🔍 立即检查", command=self.on_check_now,
                  bg="#4CAF50", fg="white", font=("Microsoft YaHei", 10),
                  width=12, height=1).pack(side=tk.RIGHT, padx=4)

        tk.Button(btn_frame, text="⏹ 停止", command=self.on_stop,
                  bg="#f44336", fg="white", font=("Microsoft YaHei", 10, "bold"),
                  width=10, height=1).pack(side=tk.RIGHT, padx=4)

        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=run_scheduler, args=(self.log, self.stop_event), daemon=True)
        self.thread.start()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _channel_status(self):
        parts = []
        if FEISHU_WEBHOOK:
            parts.append("飞书✅")
        if PUSHPLUS_TOKEN:
            parts.append("微信✅")
        if not parts:
            parts.append("未配置推送渠道")
        return "推送渠道: " + " | ".join(parts) + " (点此编辑)"

    def log(self, text):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_box.insert(tk.END, f"[{ts}] {text}\n")
        self.log_box.see(tk.END)

    def on_check_now(self):
        self.log("── 手动检查 ──")
        # 手动检查不记录到已推送状态
        now_hour = datetime.datetime.now().hour
        threading.Thread(
            target=lambda: do_check(self.log, now_hour),
            daemon=True
        ).start()

    def on_stop(self):
        self.stop_event.set()
        self.status_label.config(text="● 已停止", fg="red")
        self.log("⏹ 已停止")

    def on_edit_config(self, event=None):
        win = tk.Toplevel(self.root)
        win.title("配置推送渠道")
        win.geometry("560x240")
        win.resizable(True, True)

        tk.Label(win, text="飞书群机器人 Webhook（选填）:").pack(anchor="w", padx=12, pady=(10, 0))
        feishu_var = tk.StringVar(value=FEISHU_WEBHOOK)
        tk.Entry(win, textvariable=feishu_var, width=80).pack(padx=12, pady=3, fill=tk.X)

        tk.Label(win, text="微信 PushPlus Token（选填）:").pack(anchor="w", padx=12, pady=(8, 0))
        pushplus_var = tk.StringVar(value=PUSHPLUS_TOKEN)
        tk.Entry(win, textvariable=pushplus_var, width=80).pack(padx=12, pady=3, fill=tk.X)

        tk.Label(
            win,
            text=f"推送时间: 每天 {':'.join(str(h).zfill(2) for h in PUSH_HOURS)} 各检查一次",
            fg="gray", font=("Microsoft YaHei", 8)
        ).pack(anchor="w", padx=12, pady=(6, 0))

        tk.Label(
            win,
            text="飞书获取方式: 群设置 → 群机器人 → 添加自定义机器人 → 复制 Webhook 地址",
            fg="gray", font=("Microsoft YaHei", 8)
        ).pack(anchor="w", padx=12)

        def save():
            global FEISHU_WEBHOOK, PUSHPLUS_TOKEN
            FEISHU_WEBHOOK = feishu_var.get().strip()
            PUSHPLUS_TOKEN = pushplus_var.get().strip()
            self.channel_label.config(text=self._channel_status())
            self.log("✅ 配置已保存")
            win.destroy()

        tk.Button(win, text="保存并关闭", command=save, bg="#2196F3", fg="white",
                  font=("Microsoft YaHei", 10), width=14).pack(pady=10)

    def on_close(self):
        self.stop_event.set()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = ReminderApp()
    app.run()
