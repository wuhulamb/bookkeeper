# 资产记账程序

记录和管理个人资产快照的命令行工具。

## 数据文件

资产数据存储在 `assets.json` 中，包含账户定义和按日期的余额快照。

## 命令

### record

录入当前日期的资产快照。每个账户显示上次余额作为默认值，直接回车沿用，输入 `q` 取消不保存。

```
python3 assets.py record
```

### list

查看资产总表，默认只显示最近余额不为 0 的活跃账户。

```
python3 assets.py list
python3 assets.py list --full       # 显示所有账户
python3 assets.py list --by-type    # 按类型汇总
python3 assets.py list --by-group   # 按分组汇总
```

### add-account

添加新账户（如新购入的基金）。

```
python3 assets.py add-account
```

## 数据结构

### 账户

每个账户有 `id`、`name`、`type`、`group` 四个字段：

| 字段 | 说明 | 示例 |
|---|---|---|
| id | 唯一标识，英文 | `alifund_018610` |
| name | 显示名称 | `支付宝基金-018610` |
| type | 类型 | `bank`, `fund`, `money_market`, `payment` |
| group | 归属分组 | `alipay`, `wechat`, `icbc`, `abc` |

### 快照

每次 `record` 生成一条快照，记录所有账户在当日的余额。

```json
{
  "accounts": [
    { "id": "abc", "name": "农业银行", "type": "bank", "group": "abc" }
  ],
  "snapshots": [
    {
      "date": "2025-05-11",
      "balances": { "abc": 988, "alipay": 1108 },
      "total": 45640
    }
  ]
}
```
