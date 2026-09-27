import argparse
import json
import sys
from datetime import date
from pathlib import Path

try:
    import readline
except ImportError:
    pass

from rich.console import Console
from rich.table import Table


DATA_FILE = Path(__file__).parent / "assets.json"


DEFAULT_ACCOUNTS = [
    {"id": "icbc", "name": "工商银行", "type": "bank", "group": "icbc"},
    {"id": "abc", "name": "农业银行", "type": "bank", "group": "abc"},
    {"id": "alipay", "name": "支付宝", "type": "payment", "group": "alipay"},
    {"id": "wechat", "name": "微信零钱", "type": "payment", "group": "wechat"},
    {"id": "alibao", "name": "余额宝", "type": "money_market", "group": "alipay"},
    {"id": "alifund_018610", "name": "支付宝基金-018610", "type": "fund", "group": "alipay"},
    {"id": "alifund_004388", "name": "支付宝基金-004388", "type": "fund", "group": "alipay"},
    {"id": "wechattice", "name": "微信零钱通", "type": "money_market", "group": "wechat"},
    {"id": "wechatlicai_004388", "name": "微信理财-004388", "type": "fund", "group": "wechat"},
]


def load_data():
    if not DATA_FILE.exists():
        data = {"accounts": DEFAULT_ACCOUNTS, "snapshots": []}
        save_data(data)
        print(f"已创建 {DATA_FILE}")
        return data
    with open(DATA_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def get_last_balances(data):
    if not data["snapshots"]:
        return {}
    return data["snapshots"][-1]["balances"]


def cmd_record():
    data = load_data()
    accounts = data["accounts"]
    last_balances = get_last_balances(data)
    today = date.today().isoformat()

    print(f"记录日期: {today}")
    print("输入各账户余额（直接回车沿用上次值，输入 q 结束）")
    print()

    new_balances = {}
    for acct in accounts:
        default_val = last_balances.get(acct["id"], 0)
        while True:
            prompt = f"  {acct['name']} [{default_val}]: "
            raw = input(prompt).strip()
            if raw.lower() == "q":
                print("已取消，未保存")
                return
            if raw == "":
                new_balances[acct["id"]] = default_val
                break
            try:
                new_balances[acct["id"]] = int(raw)
                break
            except ValueError:
                print("  输入无效，请输入数字")

    total = sum(new_balances.values())
    snapshot = {"date": today, "balances": new_balances, "total": total}
    data["snapshots"].append(snapshot)
    save_data(data)
    print(f"\n已保存: {today} 总计 {total}")


def get_active_accounts(accounts, snapshots):
    last_balances = snapshots[-1]["balances"]
    return [a for a in accounts if last_balances.get(a["id"], 0) != 0]


def get_list_data(data, accounts, snapshots):
    header = ["日期", "总计"] + [a["name"] for a in accounts]
    rows = []
    for snap in snapshots:
        rows.append([snap["date"], str(snap["total"])] + [str(snap["balances"].get(a["id"], 0)) for a in accounts])
    return header, rows


def get_type_summary(snapshots, accounts):
    type_names = sorted(set(a["type"] for a in accounts))
    rows = []
    for snap in snapshots:
        row = [snap["date"], str(snap["total"])]
        sums = {}
        for acct in accounts:
            t = acct["type"]
            sums[t] = sums.get(t, 0) + snap["balances"].get(acct["id"], 0)
        for t in type_names:
            row.append(str(sums[t]))
        rows.append(row)
    return ["日期", "总计"] + type_names, rows


def get_group_summary(snapshots, accounts):
    group_names = sorted(set(a["group"] for a in accounts))
    rows = []
    for snap in snapshots:
        row = [snap["date"], str(snap["total"])]
        sums = {}
        for acct in accounts:
            g = acct["group"]
            sums[g] = sums.get(g, 0) + snap["balances"].get(acct["id"], 0)
        for g in group_names:
            row.append(str(sums[g]))
        rows.append(row)
    return ["日期", "总计"] + group_names, rows


def fmt_table(header, rows):
    table = Table(show_header=True, header_style="bold")
    for i, name in enumerate(header):
        justify = "left" if i == 0 else "right"
        table.add_column(name, justify=justify)

    for r in rows:
        table.add_row(*r)

    console = Console()
    with console.capture() as capture:
        console.print(table)
    return capture.get()


def cmd_list():
    data = load_data()
    accounts = data["accounts"]
    snapshots = data["snapshots"]

    if not snapshots:
        print("暂无数据")
        return

    header, rows = get_list_data(data, accounts, snapshots)
    print(fmt_table(header, rows))


def cmd_add_account():
    data = load_data()
    print("添加新账户")
    print()

    aid = input("  账户ID (英文, 如 alifund_123456): ").strip()
    if not aid:
        print("已取消")
        return
    if any(a["id"] == aid for a in data["accounts"]):
        print(f"账户 {aid} 已存在")
        return

    name = input("  名称 (如 支付宝基金-123456): ").strip()
    if not name:
        print("已取消")
        return

    print("  类型:")
    print("    bank, payment, money_market, fund")
    type_ = input("  type [fund]: ").strip() or "fund"

    print("  分组:")
    print("    abc, icbc, alipay, wechat")
    group = input("  group [alipay]: ").strip()
    if not group:
        print("已取消")
        return

    data["accounts"].append({"id": aid, "name": name, "type": type_, "group": group})
    save_data(data)
    print(f"\n已添加账户: {name} ({aid})")


def main():
    parser = argparse.ArgumentParser(description="资产记账程序")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("record", help="记录资产快照")

    list_parser = sub.add_parser("list", help="查看资产总表")
    list_parser.add_argument("--full", action="store_true", help="显示所有账户（含余额为 0 的）")
    list_parser.add_argument("--by-type", action="store_true", help="按 type 汇总")
    list_parser.add_argument("--by-group", action="store_true", help="按 group 汇总")

    sub.add_parser("add-account", help="添加新账户")

    args = parser.parse_args()

    if args.cmd == "record":
        cmd_record()
    elif args.cmd == "list":
        data = load_data()
        accounts = data["accounts"]
        snapshots = data["snapshots"]

        if not snapshots:
            print("暂无数据")
            return

        if args.by_type:
            header, rows = get_type_summary(snapshots, data["accounts"])
        elif args.by_group:
            header, rows = get_group_summary(snapshots, data["accounts"])
        else:
            if not args.full:
                accounts = get_active_accounts(accounts, snapshots)
            header, rows = get_list_data(data, accounts, snapshots)

        print(fmt_table(header, rows))
    elif args.cmd == "add-account":
        cmd_add_account()


if __name__ == "__main__":
    main()
