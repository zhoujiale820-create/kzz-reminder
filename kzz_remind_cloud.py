#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新债申购提醒 - 云端版 (GitHub Actions)
无 GUI, 纯推送逻辑, 适合定时任务环境
"""

import os
import sys
import datetime
import requests

# ─── 推送渠道配置 (通过环境变量传入) ───────────────────────
FEISHU_WEBHOOK  = os.environ.get("FEISHU_WEBHOOK", "").strip()
PUSHPLUS_TOKEN  = os.environ.get("PUSHPLUS_TOKEN", "").strip()

# 推送时间点 (24h), 用于日志
PUSH_HOURS = [10, 14]
WECHAT_TITLE = "📢 今日新债申购提醒"


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


def format_message(bonds):
    if isinstance(bonds, dict) and "error" in bonds:
        return f"❌ 获取数据失败: {bonds['error']}\n请稍后重试或检查网络。"

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


def main():
    now = datetime.datetime.now()
    # 时间门控：GitHub Actions 运行环境是 UTC
    # 北京时间 10:00-11:00 = UTC 02:00-03:00
    # 只在这个窗口内允许推送，防止积压延迟在错误时间触发
    utc_hour = now.hour
    if not (3 <= utc_hour < 4):
        print(f"[{now.strftime('%H:%M')} UTC] 不在推送窗口(UTC 02:00-03:00 = 北京时间10:00-11:00)，静默退出。")
        sys.exit(0)
    print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] 开始检查今日新债...")

    bonds = fetch_today_bonds()
    msg   = format_message(bonds)
    print(msg)

    # 推送到所有已配置的渠道
    results = []
    if FEISHU_WEBHOOK:
        ok, info = send_feishu(msg)
        results.append(f"{'✅' if ok else '❌'} 飞书: {info}")
        print(f"飞书推送: {info}")

    if PUSHPLUS_TOKEN:
        ok, info = send_wechat(WECHAT_TITLE, msg)
        results.append(f"{'✅' if ok else '❌'} 微信: {info}")
        print(f"微信推送: {info}")

    if not FEISHU_WEBHOOK and not PUSHPLUS_TOKEN:
        msg_warn = "⚠️ 未配置任何推送渠道！请在 GitHub Secrets 中设置 FEISHU_WEBHOOK 或 PUSHPLUS_TOKEN"
        print(msg_warn)
        sys.exit(1)

    print(" | ".join(results))


if __name__ == "__main__":
    main()
