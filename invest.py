import argparse
import json
import sys
import time
import urllib.request
from datetime import date, datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table


BASE_DIR = Path(__file__).parent
DATA_FILE = BASE_DIR / "investments.json"


def load_data():
    if not DATA_FILE.exists():
        data = {"events": []}
        save_data(data)
        print(f"已创建 {DATA_FILE}")
        return data
    with open(DATA_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def fetch_jsonp(url: str) -> dict | None:
    """请求东财 JSONP 接口并解析返回的 JSON 数据。"""
    headers = {
        "Referer": "https://fund.eastmoney.com/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8", errors="ignore")
        start = text.index("(") + 1
        end = text.rindex(")")
        return json.loads(text[start:end])
    except Exception as e:
        print(f"ERROR: 获取净值失败: {e}", file=sys.stderr)
        return None


def get_current_nav(code: str) -> tuple[float, str]:
    """从接口获取基金最新单位净值，返回 (净值, 日期)。"""
    params = f"callback=cb&fundCode={code}&pageIndex=1&pageSize=1&_={int(time.time()*1000)}"
    url = f"https://api.fund.eastmoney.com/f10/lsjz?{params}"
    data = fetch_jsonp(url)
    try:
        record = data["Data"]["LSJZList"][0]
        return float(record["DWJZ"]), record["FSRQ"]
    except (TypeError, KeyError, IndexError, ValueError):
        raise ValueError(f"基金 {code} 未获取到最新净值，请检查代码或网络")


def parse_date(s: str):
    return datetime.strptime(s, "%Y-%m-%d").date()


def parse_fee(raw: str, amount: float):
    """手续费：支持金额或带 % 的费率（按 amount 折算）。非法返回 None。"""
    if raw == "":
        return 0.0
    if raw.endswith("%"):
        try:
            rate = float(raw[:-1])
        except ValueError:
            return None
        return amount * rate / 100.0
    try:
        return float(raw)
    except ValueError:
        return None


def compute_positions(events):
    """按时间遍历，每只基金维护持仓；返回 code -> position dict 与现金流。"""
    codes = sorted({e["code"] for e in events})
    pos = {c: {"shares": 0.0, "cost": 0.0, "invested": 0.0, "withdrawn": 0.0,
               "realized": 0.0, "fee_total": 0.0} for c in codes}
    cashflows = {c: [] for c in codes}

    ordered = sorted(events, key=lambda e: (e["date"],))
    for e in ordered:
        c = e["code"]
        p = pos[c]
        fee = e.get("fee", 0.0)
        if e["action"] == "buy":
            # 申购费另算：金额即实际买入基金金额，手续费额外计入成本
            shares = e["amount"] / e["price"]
            p["shares"] += shares
            p["cost"] += e["amount"] + fee
            p["invested"] += e["amount"] + fee
            p["fee_total"] += fee
            cashflows[c].append((e["date"], -(e["amount"] + fee)))
        else:  # sell，按份额赎回
            held = p["shares"]
            if held <= 1e-9:
                raise AssertionError(f"{c} 在 {e['date']} 无持仓可卖，无法记录")
            # 卖出的份额可能与 4 位小数显示有含入差（如按显示的份额清仓），
            # 超出持仓但在容差内视为“全部赎回”，避免浮点含入误报超卖
            if e["shares"] > held + 1e-3:
                raise AssertionError(f"{c} 在 {e['date']} 卖出超出持仓份额，无法记录")
            shares = min(e["shares"], held)
            avg_cost = p["cost"] / held
            received = shares * e["price"] - fee
            p["realized"] += received - avg_cost * shares
            p["shares"] -= shares
            p["cost"] -= avg_cost * shares
            p["withdrawn"] += received
            p["fee_total"] += fee
            cashflows[c].append((e["date"], +received))
    return pos, cashflows


def xirr(cashflows):
    """资金加权年化收益率 (内部收益率按年化)。无解返回 None。"""
    flows = [(parse_date(d), cf) for d, cf in cashflows if cf != 0]
    if not flows:
        return None
    pos = sum(1 for _, cf in flows if cf > 0)
    neg = sum(1 for _, cf in flows if cf < 0)
    if not pos or not neg:
        return None
    if len({d for d, _ in flows}) < 2:
        return None
    t0 = min(d for d, _ in flows)
    times = [(d - t0).days / 365.0 for d, _ in flows]
    flows = [(t, cf) for (_, cf), t in zip(flows, times)]

    def f(r):
        return sum(cf / (1 + r) ** t for t, cf in flows)

    def df(r):
        return sum(-t * cf / (1 + r) ** (t + 1) for t, cf in flows)

    r = 0.1
    for _ in range(100):
        v = f(r)
        if abs(v) < 1e-9:
            return r
        if abs(df(r)) < 1e-15:
            break
        new_r = r - v / df(r)
        if not (-0.9999 < new_r < 10):
            break
        if abs(new_r - r) < 1e-12:
            return new_r
        r = new_r
    return None


def build_report(events):
    pos, cashflows = compute_positions(events)
    # 统一估值参考日：组合内所有基金最新的净值日，末笔清盘现金流都锚定在此
    prices = {}
    nav_dates = []
    for code in sorted(pos):
        if pos[code]["shares"] <= 1e-9:  # 已清仓，无需获取现价
            prices[code] = None
            continue
        try:
            prices[code] = get_current_nav(code)
        except ValueError as e:
            return None, str(e), None
        nav_dates.append(prices[code][1])
    reference_date = max(nav_dates) if nav_dates else date.today().isoformat()

    report = []
    for code in sorted(pos):
        p = pos[code]
        cur = prices[code]
        market = cur[0] * p["shares"] if cur else 0.0
        total_pnl = market + p["withdrawn"] - p["invested"]
        unrealized = market - p["cost"]
        realized = p["realized"]
        total_pct = total_pnl / p["invested"] if p["invested"] else 0.0
        ann = xirr(cashflows[code] + [(reference_date, market)])
        report.append({
            "code": code,
            "shares": p["shares"],
            "cost": p["cost"],
            "market": market,
            "unrealized": unrealized,
            "realized": realized,
            "total_pnl": total_pnl,
            "total_pct": total_pct,
            "annualized": ann,
            "invested": p["invested"],
        })
    return report, None, reference_date


def fmt_pct(x):
    return f"{x * 100:.2f}%" if x is not None else "N/A"


def cmd_record():
    data = load_data()
    events = data["events"]
    print("记录基金投资事件 (输入 q 取消)")
    print()

    def ask(prompt, default=""):
        raw = input(prompt).strip()
        if raw.lower() == "q":
            return None
        return raw or default

    date_s = ask("  日期 [今天]: ", "")
    if date_s is None:
        return
    if not date_s:
        date_s = date.today().isoformat()
    try:
        parse_date(date_s)
    except ValueError:
        print("  日期格式无效，应为 YYYY-MM-DD")
        return

    code = ask("  基金代码 (如 018610): ")
    if not code:
        print("已取消")
        return

    action = ask("  动作 (buy/sell) [buy]: ", "buy")
    if not action:
        return
    action = action.lower()
    if action not in ("buy", "sell"):
        print("  动作无效，应为 buy 或 sell")
        return

    price_s = ask("  单位净值: ")
    if not price_s:
        return
    try:
        price = float(price_s)
    except ValueError:
        print("  价格输入无效")
        return
    if price <= 0:
        print("  价格必须 > 0")
        return

    if action == "buy":
        amount_s = ask("  申购金额: ")
        if not amount_s:
            return
        try:
            amount = float(amount_s)
        except ValueError:
            print("  金额输入无效")
            return
        if amount <= 0:
            print("  金额必须 > 0")
            return
        shares = amount / price
        fee_base = amount
    else:  # sell 按份额赎回
        shares_s = ask("  赎回份额: ")
        if not shares_s:
            return
        try:
            shares = float(shares_s)
        except ValueError:
            print("  份额输入无效")
            return
        if shares <= 0:
            print("  份额必须 > 0")
            return
        amount = shares * price  # 毛赎回金额
        fee_base = amount

    fee_s = ask("  手续费 [0]: ", "0")
    if fee_s is None:
        return
    fee = parse_fee(fee_s, fee_base)
    if fee is None:
        print("  手续费输入无效（金额，或带 % 的费率）")
        return
    if fee < 0:
        print("  手续费不能为负")
        return
    if action == "sell" and fee >= amount:
        print("  卖出手续费需小于赎回金额")
        return

    # 卖出需校验不超持仓（按时间顺序前进校验）
    if action == "sell":
        trial = events + [{"date": date_s, "code": code, "action": "sell",
                           "price": price, "shares": shares, "fee": fee}]
        try:
            pos, _ = compute_positions(trial)
        except AssertionError as e:
            print(f"  {e}")
            return

    note = ask("  备注: ")
    if note is None:
        return
    fee_str = f" 手续费{fee:.2f}" if fee else ""
    if action == "buy":
        print(f"  确认: {date_s} {code} buy @{price} 金额{amount} 份额{shares:.4f}{fee_str}")
        ev = {"date": date_s, "code": code, "action": action, "price": price,
              "amount": amount, "fee": fee, "note": note}
    else:
        print(f"  确认: {date_s} {code} sell @{price} 份额{shares:.4f} 毛额{amount:.2f}{fee_str}")
        ev = {"date": date_s, "code": code, "action": action, "price": price,
              "shares": shares, "fee": fee, "note": note}
    events.append(ev)
    save_data(data)
    print(f"\n已保存 ({len(events)} 条事件)")


def cmd_list():
    data = load_data()
    events = data["events"]
    if not events:
        print("暂无交易数据，先运行: uv run invest.py record")
        return

    report, err, reference_date = build_report(events)
    if err:
        print(err)
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("代码", justify="left")
    table.add_column("份额", justify="right")
    table.add_column("成本", justify="right")
    table.add_column("市值", justify="right")
    table.add_column("总盈亏", justify="right")
    table.add_column("总盈亏%", justify="right")
    table.add_column("年化%", justify="right")

    total_invested = 0.0
    total_pnl = 0.0
    total_market = 0.0
    for r in report:
        total_invested += r["invested"]
        total_pnl += r["total_pnl"]
        total_market += r["market"]
        table.add_row(
            r["code"],
            f"{r['shares']:.4f}",
            f"{r['cost']:.2f}",
            f"{r['market']:.2f}",
            f"{r['total_pnl']:+.2f}",
            fmt_pct(r["total_pct"]),
            fmt_pct(r["annualized"]),
        )

    # 组合级 XIRR：合并所有基金流水，与单基金一样锚定在统一 reference_date
    pos, cashflows = compute_positions(events)
    all_cashflows = []
    for code in sorted(cashflows):
        all_cashflows.extend(cashflows[code])
    all_cashflows.append((reference_date, total_market))
    portfolio_ann = xirr(all_cashflows)

    table.add_row(
        "合计",
        "",
        "",
        f"{total_market:.2f}",
        f"{total_pnl:+.2f}",
        fmt_pct(total_pnl / total_invested if total_invested else 0.0),
        fmt_pct(portfolio_ann),
    )
    console = Console()
    with console.capture() as capture:
        console.print(table)
    print(capture.get())
    total_fee = sum(p["fee_total"] for p in compute_positions(events)[0].values())
    print(f"总投资 {total_invested:.2f}，已付手续费 {total_fee:.2f}，未实现/已实现盈亏 "
          f"{sum(r['unrealized'] for r in report):+.2f}/"
          f"{sum(r['realized'] for r in report):+.2f}")
    if portfolio_ann is not None:
        print(f"组合年化收益率: {fmt_pct(portfolio_ann)}")


def cmd_events():
    data = load_data()
    events = data["events"]
    if not events:
        print("暂无交易数据")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("#", justify="right")
    table.add_column("日期", justify="left")
    table.add_column("代码", justify="left")
    table.add_column("动作", justify="left")
    table.add_column("净值", justify="right")
    table.add_column("金额", justify="right")
    table.add_column("手续费", justify="right")
    table.add_column("份额", justify="right")
    table.add_column("备注", justify="left")

    for i, e in enumerate(events):
        if e["action"] == "buy":
            amount = e["amount"]
            shares = amount / e["price"]
        else:
            shares = e["shares"]
            amount = shares * e["price"]
        table.add_row(
            str(i),
            e["date"],
            e["code"],
            {"buy": "买入", "sell": "卖出"}.get(e["action"], e["action"]),
            f"{e['price']:.4f}",
            f"{amount:.2f}",
            f"{e.get('fee', 0.0):.2f}",
            f"{shares:.4f}",
            e.get("note", ""),
        )
    console = Console()
    with console.capture() as capture:
        console.print(table)
    print(capture.get())


def cmd_delete(index):
    data = load_data()
    events = data["events"]
    if index < 0 or index >= len(events):
        print(f"编号 {index} 无效，事件范围 0-{len(events) - 1}")
        return
    e = events[index]
    # 校验：删除后剩余事件必须仍能成立（否则拒绝，避免产生孤立的无持仓卖出）
    remaining = [ev for i2, ev in enumerate(events) if i2 != index]
    try:
        compute_positions(remaining)
    except AssertionError as ex:
        print(f"无法删除第 {index} 条：删除后会导致数据不一致——{ex}")
        return
    if e["action"] == "buy":
        desc = f"金额{e['amount']} 份额{e['amount'] / e['price']:.4f}"
    else:
        desc = f"份额{e['shares']:.4f} 毛额{e['shares'] * e['price']:.2f} 手续费{e.get('fee', 0.0):.2f}"
    confirm = input(
        f"确认删除第 {index} 条: {e['date']} {e['code']} {e['action']} "
        f"@{e['price']} {desc}? (y/N): "
    ).strip().lower()
    if confirm != "y":
        print("已取消")
        return
    del events[index]
    save_data(data)
    print(f"已删除第 {index} 条，剩余 {len(events)} 条")


def main():
    parser = argparse.ArgumentParser(description="基金投资事件记账")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("record", help="记录一笔买/卖事件")

    sub.add_parser("list", help="查看持仓盈亏报表")

    sub.add_parser("events", help="查看全部原始事件")

    del_parser = sub.add_parser("del", help="删除一条事件")
    del_parser.add_argument("index", type=int, help="事件编号 (见 events 输出)")

    args = parser.parse_args()

    if args.cmd == "record":
        cmd_record()
    elif args.cmd == "list":
        cmd_list()
    elif args.cmd == "events":
        cmd_events()
    elif args.cmd == "del":
        cmd_delete(args.index)


if __name__ == "__main__":
    main()