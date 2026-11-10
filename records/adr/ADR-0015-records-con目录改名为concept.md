---
id: ADR-0015
type: adr
status: accepted
date: 2026-11-10
phase: P2
related: [ADR-0001, ADR-0014, LOG-20261110-009]
summary: "records/con/ 目录因 Windows 保留设备名 CON 导致 Git 无法索引，改名为 records/concept/；内容逐字节不变"
---

# ADR-0015 · `records/con/` 改名为 `records/concept/`（Windows 保留设备名缺陷）

## 1. 背景

`ADR-0014` 执行首次 `git add -A` 时失败，报错：

```
error: open("records/con/CON-0001-概念层首批变更.md"): No such file or directory
error: unable to index file 'records/con/CON-0001-概念层首批变更.md'
fatal: adding files failed
```

同一路径下：

| 工具 | 结果 |
| :--- | :--- |
| Python `os.path.exists` / `open` | 成功（4086 字节可读） |
| `ls` / `sha1sum` | 成功 |
| `git hash-object` | 失败（No such file or directory） |
| `git ls-files --others` | 能列出（按索引层枚举），但无法读取内容 |

即：文件真实存在，Git 在打开路径时被系统拒绝。

## 2. 根因

`con` 是 MS-DOS 时代的**保留设备名**（控制台 `CON`），与 `PRN`、`AUX`、`NUL`、`COM1..9`、`LPT1..9` 同列。
Win32 路径解析对这类名字有特殊处理：即使作为目录名出现，打开时仍可能被导向设备而非文件系统。

这解释了「Python 能读、Git 不能读」的分裂：Python 的 `open` 走 CRT/宽字符路径，`git` 走 Win32 路径规范化，
后者把 `records\con\...` 中的 `con` 段识别为设备名。

**关键含义**：这不是本地环境的偶发问题。任何 Windows 上的克隆者都会遇到同一问题——
Git 在 checkout 时同样无法创建或写入该路径下的文件。也就是说，**只要目录叫 `con`，仓库在 Windows 上就是不可用的**，
且不会在提交时报错（提交时文件根本无法进入索引，因此远程仓库会静默缺少这两个 CON 记录）。

## 3. 决策

`records/con/` → `records/concept/`。

- 文件内容**逐字节不变**（迁移前后 SHA-256 一致，见 §5 证据）。
- 记录编号 `CON-0001` / `CON-0002` **不变**（编号是记录身份，与所在目录无关）。
- 同步修改 4 处路径引用：`SCHEMA.md` §6.2、`PLAN/01-scope-freeze.md`、`CLIO · 最终版计划书.md`（2 处）。

选 `concept` 而非 `chg`、`change`、`concept-change`：

1. 语义最准——`CON` 即 `concept`，与编号前缀自然对应，ASCII 与原 `con` 同源，降低认知成本。
2. 避开全部保留名，且不以保留名为前缀（`concept` ≠ `con`，无歧义）。
3. 不与既有目录冲突（`records/chg/` 已被「变更请求」占用，`CHG` 是另一类记录，不可混用）。

## 4. 为什么这是结构性判断而非升级事项

按 `AGENTS.md §4.1`，可自行判断的判据是「不含法律评价，只涉及结构、命名、基数、引用完整性，
且无论结论如何都不会改变任何当事人的权利义务」。本项完全落在该范围内：

- 不涉及任何法律概念、要件、因子、规则或案例；
- 不改变任何记录的内容、编号或状态；
- 不改变 `ontology/` 中任何三元组（tbox 指纹仍为 `faa7773f64001eab…`）。

故**不写 ESC**，直接写 ADR。反过来说，若把此事升级给负责人，
正是 `AGENTS.md §4.3` 所称的「过度升级」——把工程细节推给负责人会淹没真实争议。

## 5. 证据

| 检查项 | 结果 |
| :--- | :--- |
| 迁移前 SHA-256 `CON-0001` | `2f0612b4daec…` |
| 迁移后 SHA-256 `CON-0001` | `2f0612b4daec…`（一致） |
| 迁移前 SHA-256 `CON-0002` | `ef292a502e8c…` |
| 迁移后 SHA-256 `CON-0002` | `ef292a502e8c…`（一致） |
| 旧目录是否已清除 | 是（经扩展长度路径 `\\?\` 删除；常规删除被设备名解析拦截，进一步印证根因） |
| `validate.py` | 通过（0 错误 0 警告）；校验器用 `rglob` 不依赖目录名，故不受影响 |
| tbox 指纹 | `faa7773f64001eab…`，与 `PROV-0003` 登记值一致，未变 |

补充证据：常规 `rmtree` 与 `trash` 均报 `windows error 0x800704B0「指定的设备名无效」`，
必须用 `\\?\` 前缀绕过 Win32 名称规范化才能删除——这是保留设备名假设的独立验证，不是推断。

## 6. 放弃方案与代价

| 方案 | 放弃理由 |
| :--- | :--- |
| 保留 `con`，改用 `.gitmodules`/编码绕行 | 无法解决：问题在 checkout 侧，远程仓库在 Windows 上对该目录不可用；绕行方案会让协作者必须装特殊工具 |
| 改名为 `records/change/` | 与 `records/chg/`（变更请求 CHG）语义冲突，易被误认为同一类记录 |
| 改名为 `records/concepts/`（复数） | 可行但与其他目录单数命名（`adr`/`log`/`rsk`/`esc`）不一致 |
| 把 CON 记录并入 `records/log/` | 违反 `SCHEMA.md` §6.2 编号-目录对应关系；且 `CON` 与 `LOG` 是不同记录类型，合并会使门禁无法区分 |
| 只改本地路径、不改仓库 | 远程仓库仍缺该目录内容，克隆者拿到残缺记录集，属更隐蔽的错误 |

**代价（明示）**：`AGENTS.md`、`SCHEMA.md`、计划书以外的历史讨论或外部笔记若提到 `records/con/`，将失效。
本项目历史记录中出现的 `records/con/` 引用已在 §3 逐处更新；`records/log/`、`records/adr/` 内若提及，
属当时事实，保留（同 `ADR-0014 §2.3` 的处理原则：不改写历史）。

## 7. 生效约束

1. **新增记录目录须先查保留名**。今后在 `records/` 下新建目录，须避开
   `CON|PRN|AUX|NUL|COM1-9|LPT1-9`（含带扩展名形式）。此为人工门禁，`validate` 未覆盖。
2. **不得为「与旧引用一致」而恢复 `records/con/`**。
3. `CON` 记录编号规则不变，仍为 `CON-0001`，置于 `records/concept/`。

## 8. 复审触发条件

- 若 `validate.py` 增补「路径合法性检查」，须把保留设备名纳入 `E-REC` 系列错误码，
  届时本 ADR §7.1 的人工门禁可降级为机器门禁。
- 若未来需要在非 Windows 环境运行且必须与旧仓库兼容（当前无此需求），再评估是否提供兼容软链。