# 物流报价 Workflow

可直接由 Agent 调用的确定性计算模块，运行环境为 Node.js 18+。运行和测试均使用 Node 标准库，无需安装额外依赖。

## 文件与入口

| 文件 | 用途 |
| --- | --- |
| `logistics-quote.mjs` | 纯函数 `calculateLogisticsQuote(input)` 与版本信息 `meta`，可用于 Node 和浏览器 |
| `logistics-quote.d.mts` | TypeScript 输入、输出和配置类型 |
| `logistics-quote.cli.mjs` | 单次 JSON 命令行调用 |
| `logistics-quote.tool.json` | 通用 Agent 工具定义：`name`、`description`、`parameters`（JSON Schema） |
| `logistics-package-plan.mjs` | 多包裹合并/逐包报价优先级决策 Workflow |
| `logistics-quote.example.json` | 可直接运行的合成费率示例，仅用于验证调用 |
| `logistics-quote.test.mjs` | 原十组样例及输入、金额、抛比、错误和 CLI 回归测试 |

以下命令在项目根目录执行。

## 立即运行

```powershell
node workflows/logistics-quote.cli.mjs workflows/logistics-quote.example.json

# 也支持标准输入（UTF-8，允许 BOM）
Get-Content -Raw workflows/logistics-quote.example.json | node workflows/logistics-quote.cli.mjs

# 读取工具参数定义
node workflows/logistics-quote.cli.mjs --schema

# 运行实际断言测试
node --test workflows/logistics-quote.test.mjs
node --test workflows/logistics-package-plan.test.mjs
```

示例输入为实重 5kg、首重 1kg/12 元、续重 4.8 元/kg、成本加价 2 元、减免 10%。结果：计费重 5kg，基础运费 31.20 元，调整后 33.20 元，总价和平台支付均为 **29.88 元**，剩余应付 0 元。

CLI 每次读取一个完整 JSON 文档并退出，标准输出只有一行 JSON。它是进程调用接口。退出码：`0` 为全部计算成功；`1` 为输入、报价配置或计算业务失败（包含部分失败）；`2` 为 JSON 格式、文件读取或命令参数错误。调用方在非零退出码时也应解析 stdout，获取缺失字段或承运商错误。

## JavaScript / TypeScript 调用

```javascript
import { calculateLogisticsQuote } from './workflows/logistics-quote.mjs';

const result = calculateLogisticsQuote({
  weight_kg: 5,
  quote_config: {
    price_basis: 'cost',
    carriers: {
      中通快递: {
        volume_ratio: 8000,
        price_table: { first_weight: 1, first_weight_price: 12, continued_weight_price: 4.8 },
        markup_cost: 2,
        discount_rate: 10,
        payment_mode: 'direct',
      },
    },
  },
});

if (!result.success) {
  console.error(result.reason, result.missing_fields, result.errors);
} else {
  console.log(result.quotes[0].total_price); // 29.88
}
```

TypeScript 可从同一路径导入 `LogisticsInput`、`QuoteConfig`、`VolumeRatioRule`、`CarrierQuote`、`QuoteResult` 等类型。前端原路径 `frontend/utils/logisticsCalculator.ts` 继续可用，它重导出本模块。模块不会读取 localStorage、数据库、环境变量或网络。

## 接到 Agent 的工具执行器

工具名为 `logistics_quote`。将 JSON 文件的 `name`、`description`、`parameters` 适配到所选 Agent 框架，再把该名称映射到真实函数。工具注册本身由未来的 Agent 宿主完成。

下面是一个可以由宿主调用的最小执行器（假定文件位于项目根目录）：

```javascript
import { readFileSync } from 'node:fs';
import { calculateLogisticsQuote } from './workflows/logistics-quote.mjs';

export const definition = JSON.parse(
  readFileSync(new URL('./workflows/logistics-quote.tool.json', import.meta.url), 'utf8'),
);

export function executeTool(name, argumentsJson) {
  if (name !== definition.name) throw new Error(`Unknown tool: ${name}`);
  return calculateLogisticsQuote(JSON.parse(argumentsJson));
}
```

`parameters` 使用通用 JSON Schema，包含动态承运商键和条件约束。若 Agent 平台只支持部分 Schema，注册时按该平台要求转换；引擎在执行时仍校验输入。JSON 解析异常由宿主处理，或直接采用 CLI 的结构化错误接口。

Python Agent 也可调用同一个引擎：

```python
import json
import subprocess
from pathlib import Path

project_root = Path.cwd()  # 在项目根目录运行；集成时换成项目的明确绝对路径
workflow = project_root / "workflows" / "logistics-quote.cli.mjs"
request = json.loads((workflow.parent / "logistics-quote.example.json").read_text(encoding="utf-8"))
completed = subprocess.run(
    ["node", str(workflow)],
    input=json.dumps(request, ensure_ascii=False),
    text=True, encoding="utf-8", capture_output=True, check=False, timeout=10,
)
result = json.loads(completed.stdout)
print(completed.returncode, result)
```

宿主负责把买家消息转换为数字参数，并从业务配置中取得真实费率。正式调用时应由宿主填入或校验 `quote_config`，避免模型生成费率。当前项目保存的是报价表摘要；按收发地查全量线路、读取浏览器报价设置和真实聊天发送仍需后续业务接入。

## 计算约定

1. 提供正实重，或完整的正长宽高；尺寸一旦填写就必须齐全。单位为 kg、cm、元。数值字符串、非有限数、负重量、非法抛比、未知字段均会失败。
2. 路由计费重 `ceil(max(实重, 长×宽×高/8000))`；小于 30 为 `express`，否则 `freight`。因此 29.01kg 向上取整后属于 `freight`。
3. 每个承运商计费重 `ceil(max(实重, 体积/承运商抛比))`。抛比优先级：自身 `volume_ratio` → `default_volume_ratios` → 内置默认。
4. 基础价格优先命中 `tiers`，其次分段续重，再次首重续重，最后 `max(minimum_price, 计费重×per_kg_price)`。无适用价格模型时返回承运商错误；零元费率有效。
5. `first_weight` 和 `continued_unit` 缺省均为 1；续重份数向上取整。所有已填写的价格参数必须有效。
6. `tiers` 默认精确命中整数计费重；表头为"N KG以内/以下"时置 `tiers_up_to=true`，取不小于计费重的最小档位，超过最大档位仍未命中则继续尝试后续价格模型。
7. 分段续重 `continued_tiers` 面向"首重30KG + 续重分档"类报价表（如百世快运）：计费重不高于 `first_weight` 时只收首重价；否则按分档上界取单价（升序取第一个满足条件的键），超过最大上界用 `overflow_continued_price`。`continued_tiers_basis` 为 `continued`（默认）时分档门槛对续重部分（计费重 − `first_weight`）；为 `total` 时分档门槛对计费总重（表头写"计费重量/总重量"的报价表）。该形态必须同时提供 `first_weight`、`first_weight_price`、`overflow_continued_price`。
8. 仅 `price_basis='cost'` 计入 `markup_cost`；始终计入 `markup_manual`。`discount_rate=10` 表示减免 10%；之后再减 `discount_amount`，总价最低为 0。加价字段允许有符号调整。
9. 金额按阶段四舍五入到分：基础价与金额配置、调整后价、折后总价、支付余额。负调整金额按绝对值四舍五入后恢复符号。
10. `direct`（默认）平台支付等于总价；`smart` 平台支付为 `min(总价,coupon_max_amount)`；`supplement` 平台支付等于 `paid_amount`。后两种模式对应金额必须显式提供，可以是 0。剩余应付 `max(总价-平台支付,0)`；已付超过总价时保留已付记录。

`sender`、`receiver` 是备注字段。`category` 是计算结果中的分类；引擎会计算传入的每个承运商，不执行地址查询或自动选择快递/物流报价表。调用方应先选好对应线路、服务类别和费率。偏远费、保价、多件等规则不在当前价格模型内，应先扩展模型与测试再接入这些报价表。

### 抛比默认值

| 承运商 | 内置规则 |
| --- | --- |
| 普通快递 | 8000 |
| 壹米滴答 | 6000 |
| 百世快运 / 百世 | 实重 ≤70kg 用 7000，否则 5000 |
| 跨越速运 / 跨越 | 6000 |
| 顺心捷达 / 含“顺心”的别名 | `carrier_payment_mode='offline'` 用 6000，其余用 5000 |
| 其余名称 | 5000；应显式提供该承运商的实际抛比 |

分段规则沿用既有前端的**实重**语义，纯体积输入实重取 0。自定义规则键使用规范名称，形态为正数、`{basis:'weight',threshold_kg,light,heavy}` 或 `{basis:'payment',offline,online}`。按线路变化的实际抛比应通过 `volume_ratio` 明确传入。

## 结果与错误处理

所有返回都有 `success`、`partial`、`quotes`、`errors`。完成路由计算后还包含 `route_weight_kg` 和 `category`。

| 状态 | 语义 |
| --- | --- |
| `success=true, partial=false` | 所有传入承运商均计算成功 |
| `success=false, partial=true` | 部分成功，成功项在 `quotes`，失败项在 `errors`；处理错误后再进行完整比较 |
| `success=false, partial=false` | 输入校验失败或全部承运商计算失败 |

每个成功报价含承运商、抛比、计费重量、基础价格、各项调整金额、总价和支付拆分。承运商失败项包含 `carrier`、`reason`、`field`、`message`。

常见错误：`missing_quote_config`、`missing_weight_or_volume`、`incomplete_dimensions`、`missing_carriers`、`invalid_number`、`unknown_field`、`price_table_invalid`、`missing_payment_amount`、`calculation_out_of_range`。承运商错误会聚合为顶层 `no_valid_quotes` 或 `partial_quote_failure`。引擎不会把空报价列表包装成成功。
