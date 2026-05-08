# smart_dca

`smart_dca` is a configuration-driven Python 3.11+ project that calculates daily smart DCA multipliers and buy plans for index ETFs. The first version uses CSV/mock data and does not place broker orders.

## Install

```powershell
python -m pip install -e ".[dev]"
```

## Data Flow

- Config files live in `config/*.yaml`.
- Sample CSV files live in `data/sample`.
- SQLite data is stored at `data/smart_dca.db` by default.
- Daily outputs are written to `reports/daily`.

## Commands

```powershell
smart-dca init-db
smart-dca import-sample-data
smart-dca report --date 2026-05-08
smart-dca backtest --start 2026-05-04 --end 2026-05-08
smart-dca web
smart-dca export-site
```

You can also run the CLI as a module:

```powershell
python -m smart_dca.cli report --date 2026-05-08
```

Run the graphical local web app:

```powershell
python -m streamlit run smart_dca/web_app.py
```

Generate a static GitHub Pages site:

```powershell
python -m smart_dca.cli export-site
```

This writes:

- `docs/index.html`
- `docs/daily_plan.csv`

In GitHub, enable Pages with `Settings -> Pages -> Deploy from a branch -> main / docs`.

## Strategy

The base daily amount is:

```text
total_budget / base_trading_days
```

With the default config this is `50000 / 200 = 250 CNY`. ETF `allocation_weight` values in `config/etfs.yaml` split that base daily amount across configured ETFs. The final target amount for each ETF is:

```text
base_daily_amount * normalized_allocation_weight * final_multiplier
```

The final multiplier is based on valuation percentile, index drawdown, and price versus MA120. Missing valuation data uses a neutral valuation base of `1.0` and marks `valuation_missing = true`.

ETF execution is filtered by premium, rounded down to A-share ETF lots of 100 shares, and capped by remaining total budget. No automatic order placement is implemented.

## Outputs

Running `report` creates:

- `reports/daily/YYYY-MM-DD_report.md`
- `reports/daily/YYYY-MM-DD_plan.csv`

It also prints a Rich table in the terminal.

## Tests

```powershell
pytest
```

---

# 中文说明

`smart_dca` 是一个配置驱动的 Python 3.11+ 智能定投项目，用于计算全球主要指数 ETF 的每日定投倍率和买入计划。第一版使用 CSV/mock 数据，不连接真实券商，也不会自动下单。

## 安装

```powershell
python -m pip install -e ".[dev]"
```

## 数据流

- 配置文件位于 `config/*.yaml`。
- 样例 CSV 数据位于 `data/sample`。
- 默认 SQLite 数据库位于 `data/smart_dca.db`。
- 每日计划和报告输出到 `reports/daily`。

## 常用命令

```powershell
smart-dca init-db
smart-dca import-sample-data
smart-dca report --date 2026-05-08
smart-dca backtest --start 2026-05-04 --end 2026-05-08
smart-dca web
smart-dca export-site
```

如果 `smart-dca` 命令不在 PATH 中，也可以用模块方式运行：

```powershell
python -m smart_dca.cli report --date 2026-05-08
```

启动本地图形化页面：

```powershell
python -m streamlit run smart_dca/web_app.py
```

页面会在浏览器中显示今日计划、原因说明、指数走势、回撤图、投入金额和顺延现金。左侧可以初始化数据库、导入样例数据、选择计划日期和运行区间回测。

生成 GitHub Pages 静态展示页：

```powershell
python -m smart_dca.cli export-site
```

默认会输出：

- `docs/index.html`
- `docs/daily_plan.csv`

然后在 GitHub 仓库中打开：

```text
Settings -> Pages -> Deploy from a branch -> main / docs
```

这个静态页只负责展示，不会在线运行 Python，也不会执行真实交易。

## 策略逻辑

基础日投金额为：

```text
total_budget / base_trading_days
```

默认配置下为 `50000 / 200 = 250 CNY`。`config/etfs.yaml` 中每个 ETF 的 `allocation_weight` 用于拆分每日基础金额。每个 ETF 的目标买入金额为：

```text
base_daily_amount * normalized_allocation_weight * final_multiplier
```

最终倍率 `final_multiplier` 由估值分位数、指数回撤、价格相对 MA120 的趋势共同决定。估值数据缺失时，会用中性估值基准 `1.0`，并标记 `valuation_missing = true`。

ETF 执行计划会根据溢价进行过滤，并按 A 股 ETF 每手 100 份向下取整，同时受剩余总预算约束。系统只输出计划，不会进行真实交易。

## 输出文件

运行 `report` 会生成：

- `reports/daily/YYYY-MM-DD_report.md`
- `reports/daily/YYYY-MM-DD_plan.csv`

终端中也会打印 Rich 表格，方便快速查看今日计划。

## 测试

```powershell
pytest
```
