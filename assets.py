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


TYPE_LABELS = {
    "bank": "银行",
    "payment": "支付",
    "money_market": "货币基金",
    "fund": "基金",
}

# org = 机构/平台（中文，可自由扩展）
DEFAULT_ACCOUNTS = [
    {"id": "icbc", "name": "工商银行", "type": "bank", "org": "工商银行"},
    {"id": "abc", "name": "农业银行", "type": "bank", "org": "农业银行"},
    {"id": "whyz", "name": "芜湖扬子银行", "type": "bank", "org": "芜湖扬子银行"},
    {"id": "alipay", "name": "支付宝", "type": "payment", "org": "支付宝"},
    {"id": "wechat", "name": "微信零钱", "type": "payment", "org": "微信"},
    {"id": "alibao", "name": "余额宝", "type": "money_market", "org": "支付宝"},
    {"id": "alifund_018610", "name": "支付宝基金-018610", "type": "fund", "org": "支付宝"},
    {"id": "alifund_004388", "name": "支付宝基金-004388", "type": "fund", "org": "支付宝"},
    {"id": "wechattice", "name": "微信零钱通", "type": "money_market", "org": "微信"},
    {"id": "wechatlicai_004388", "name": "微信理财-004388", "type": "fund", "org": "微信"},
]


def load_data():
    if not DATA_FILE.exists():
        data = {"accounts": DEFAULT_ACCOUNTS, "snapshots": []}
        save_data(data)
        print(f"已创建 {DATA_FILE}")
        return data
    with open(DATA_FILE, encoding="utf-8") as f:
        return json.load(f)
    return data


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


def get_summary(snapshots, accounts, label_of):
    """按某维度汇总快照：label_of(账户) 返回该账户归属的维度列名（中文）。"""
    labels = []
    for acct in accounts:
        lab = label_of(acct)
        if lab not in labels:
            labels.append(lab)
    rows = []
    for snap in snapshots:
        sums = {lab: 0 for lab in labels}
        for acct in accounts:
            lab = label_of(acct)
            sums[lab] += snap["balances"].get(acct["id"], 0)
        rows.append([snap["date"], str(snap["total"])] + [str(sums[lab]) for lab in labels])
    return ["日期", "总计"] + labels, rows


def by_type(acct):
    return TYPE_LABELS.get(acct.get("type", ""), acct.get("type", "其他"))


def by_org(acct):
    return acct.get("org") or "未指定"


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
    print("    " + ", ".join(f"{t}({TYPE_LABELS.get(t, t)})" for t in TYPE_LABELS))
    type_ = input("  type [fund]: ").strip() or "fund"
    if type_ not in TYPE_LABELS:
        print(f"  类型无效，应为: {', '.join(TYPE_LABELS)}")
        return

    orgs = sorted({a.get("org", "") for a in data["accounts"] if a.get("org")})
    if orgs:
        print("  已有机构: " + ", ".join(orgs))
    org = input("  机构 (中文, 如 徽商银行, 可输入新机构): ").strip()
    if not org:
        print("已取消")
        return

    data["accounts"].append({"id": aid, "name": name, "type": type_, "org": org})
    save_data(data)
    print(f"\n已添加账户: {name} ({aid})")


def main():
    parser = argparse.ArgumentParser(description="资产记账程序")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("record", help="记录资产快照")

    list_parser = sub.add_parser("list", help="查看资产总表")
    list_group = list_parser.add_mutually_exclusive_group()
    list_group.add_argument("--full", action="store_true", help="显示所有账户（含余额为 0 的）")
    list_group.add_argument("--by-type", action="store_true", help="按资产类别汇总")
    list_group.add_argument("--by-org", action="store_true", help="按机构/平台汇总")

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
            header, rows = get_summary(snapshots, data["accounts"], by_type)
        elif args.by_org:
            header, rows = get_summary(snapshots, data["accounts"], by_org)
        else:
            if not args.full:
                accounts = get_active_accounts(accounts, snapshots)
            header, rows = get_list_data(data, accounts, snapshots)

        print(fmt_table(header, rows))
    elif args.cmd == "add-account":
        cmd_add_account()


if __name__ == "__main__":
    main()
