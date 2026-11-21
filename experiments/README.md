# RSI-Orin：原题实验模块

## 当前实验范围

2026-11-21 起使用[共用题池与 Agent 适配器方案](../docs/RSI_TECHNICAL_DESIGN.md)。原题环境、裁判、Agent 运行入口和逐题成绩分别核验，差异按影响范围验证。已有通过题与已有正式结果直接登记，当前工作集中在未结算难题。下面的历史命令仅适用于其原题集、配置和记录。

实验维护者在 `memweave_eval.actor_adapter` 登记执行端，按原生、插件、仅安装三种调用选择对应入口。普通 Harbor 作业由 `build_single_job` 或 `build_job_config` 接收该绑定。已冻结的双侧 worker 通过 `run_paired_worker` 接入，在单独进程核对原脚本摘要，沿用原题沙箱、凭据代理、裁判和清理。新驱动实现 Harbor 的安装及执行入口即可；候选的内部调用结构可以独立变化。

## 2026-11-14 停机状态与当时设计

旧wave27及自动接续已由用户停止，保留STOP、HOLD、原件、成绩、累计时间和未知用量。本次只更新文档，不启动实验、不下载题目、不清理数据。

现行[RSI技术方案v3](../docs/RSI_TECHNICAL_DESIGN.md)为20简单回归＋20难训练＋40独立验证（20普通＋20难）。新训练基线须重新按新题集标定；训练严格改善并通过通用性审查才可提交审批，审批后先回归再验证，只有验证通过才登记真实收益并晋升。验证评分与逐题证据不回流进化Agent；禁止题目特异性特判、针对性调参与伪装通用规则的过拟合。父版本与比较基线分离，未过／未判定候选完整存档。

[选择规范](../docs/experiments/RSI_SELECTION.md)和[模块边界](../docs/experiments/RSI_EXPERIMENT_MODULE.md)明确新清单及待接线要求；具体80题、基线资格、回归与验证判据尚待冻结。两组难题各自最多9/20属于入选门槛，“普通不退化＋难严格改善”仅为建议默认值。以下CLI、200题／100题和验收记录描述已有底层实现／历史契约，不是新80题可执行协议或本次运行授权。

本分支已按用户要求撤下旧指标、百分制评分器、派生题目及其专用运行入口。新的 RSI 技术方案见 [RSI_TECHNICAL_DESIGN.md](../docs/RSI_TECHNICAL_DESIGN.md)；已实现原题清单、独立并发调度、免费 Pi 基础回归及显式环境准备／分阶段运行入口；进化 Agent、节点图和共享记忆仍未实现。

保留内容：

- `suites/` 的上游来源与固定提交、`subsets/` 的原题选择清单；这些文件不包含附加题面或判定 hook。
- `configs/smoke.yaml`、`configs/baseline.yaml` 的原题环境模板，以及历史 `long-horizon-49.yaml` 配置。模板仍需完整归档身份；历史配置不构成新的运行授权。
- Harbor/Pi 软件环境准备、镜像构建与校验、原始官方产物重放、运行缓存、私有配置隔离、外置凭据传输、费用准入和停止组件。
- 仓库外已有工具、Docker/Colima 环境、镜像、原题源缓存、历史运行日志与账本。本次没有重建环境、删除历史证据或释放未知费用预留。

已删除：旧 State/工程/行为/财务派生指标与评分注册表、旧报告生成及 Campaign/配对调度接线、`cases/` 中的定制题目合同与额外协议、对应夹具/脚本/专用配置和测试。传输守卫仍记录费用与请求身份，但不再解释 State 真值、注入派生任务或追加进度消息。共享 sealed-runtime 环境组件保留，不代表任何旧派生题目可以继续使用。

`memweave-eval` 保留离线 `validate CONFIG`，新增独立的 `rsi` 子命令；旧顶层 `run`、`report`、`score-report`、`score-cases` 等入口仍已移除。不得把历史配置、日志中的派生题面或历史成绩重新用作 RSI 题库。

## 环境开发检查

已有虚拟环境与依赖锁文件继续保留：

```sh
cd experiments
uv sync --locked
uv run --locked pytest
uv run --locked ruff check src tests
uv run --locked memweave-eval --help
```

本机现有环境位于仓库外 `~/.local/share/memweave-experiments/`，Docker endpoint 为 `unix://$HOME/.colima/memweave-eval/docker.sock`，专用工具位于该根目录的 `tools/`。本次未切换个人 Docker context、修改服务或电源设置。

旧实验设计和结果保留在 [历史资料目录](../docs/experiments/README.md)及 Git 历史。它们是归档证据，不是本分支的有效指标或新 RSI 设计要求。恢复旧评分器需显式切换历史提交；当前分支不提供复用这些定制题目的执行路径。

## 新 RSI 入口

题库和资格边界见 [RSI_SELECTION.md](../docs/experiments/RSI_SELECTION.md)，实现边界见 [RSI_EXPERIMENT_MODULE.md](../docs/experiments/RSI_EXPERIMENT_MODULE.md)，实际验证与未打通项见 [动态调度增量验证](../docs/experiments/RSI_DYNAMIC_VALIDATION_2026-11-07.md)。

```sh
cd experiments
uv run --locked memweave-eval rsi catalog
uv run --locked memweave-eval rsi environment
uv run --locked memweave-eval rsi install            # 只显示锁定安装计划
uv run --locked memweave-eval rsi install --execute  # 显式安装锁文件依赖
uv run --locked memweave-eval rsi native-check
uv run --locked memweave-eval rsi native-check --variant plugin --embedding-models /absolute/public/model/directory
```

`configs/rsi.yaml` 是待填写模板，不是运行授权。先在仓库外保存候选归档并填写精确 commit、SHA256；`rsi plan CONFIG` 检查官方题目与容量，`rsi prepare CONFIG /absolute/external/prepared` 才准备镜像、原始 oracle/nop、完整软件和合成模型代理 CLI 正反／终止控制。单题只有取得完整环境资格才能运行；部分准备不构成全题集最终封存。

用户已明确授权本实验不限总费用与总时长；`unbounded: true` 且两个全局limit为null启用该模式，仍保留原题时限、最多3次能力失败、每题8h、单请求token界限和费用账本。没有无上限授权时保持有限预算模式，并传入匹配的明确额度。

```sh
# 首次原生200题基线；已完成同题集基线时直接复用，不产生新请求。
uv run --locked memweave-eval rsi baseline CONFIG /absolute/external/prepared
# 后续默认只运行插件，原生基线不重跑。
uv run --locked memweave-eval rsi run CONFIG /absolute/external/prepared --split regression
# capability 单独运行，不把两种分母混成一个成绩。
```

正式回归／能力采用资源预算动态调度，`concurrency` 默认20是上限，可扩展；实际并发由原题CPU、RAM、磁盘峰值和安全余量决定。原生只在最开始独立运行40+160题基线，同样使用20上限及动态预算；题目不变时后续复用，不要求原生与插件同时执行。每题每版本最多3次确认的能力失败，通过即停；基础设施中断另计。每次运行新建外置结果目录；不能续用失败尝试的状态。停止方式是运行目录的 `STOP_REQUESTED` 文件或中断控制器，停止／清理收据须核验。

这一入口是底层分阶段实验，不会自动认定候选进化成功或绕过未来节点控制器。基础候选须双侧实测通过才合格；相对最好版本的回归容差尚未被设置，本模块不擅自采用示例10个百分点。正式能力门禁及基线比较由后续进化控制器对接。

### 20实例合成验收

```sh
MEMWEAVE_RSI_EMBEDDING_MODELS=/absolute/public/model/directory \
MEMWEAVE_RSI_REAL_PI_SMOKE=1 RSI_SMOKE_VARIANT=plugin \
  uv run --locked pytest tests/test_rsi_scheduler.py -k twenty_real_pi -s
```

需提供测试中声明的公开 embedding 模型路径（见测试环境变量），只使用本机确定性提供方，不读取真实 auth。该测试证明20个完整插件进程、HOME和Session隔离，不代表20个官方benchmark容器已具备资源，也不代表基础题或能力题通过。

### 动态资源预算

`resources` 可设更低的CPU／RAM／磁盘总cap，未设时使用专用Docker实测值。默认给辅助进程预留1 CPU、内存20%且至少4 GiB、空闲磁盘20%且至少20 GiB；不修改Colima。最早可容纳的题先启动，完整原题actor+重叠verifier资源预约到回收完成后释放，不因一个大题暂时等待而闲置所有空余资源。记录在每轮 `scheduling-events.json`。

启动前检查专用daemon没有运行或暂停的既有容器，运行持有排他控制器锁；不停止其他容器。单题超出预算时明确列出，不静默跳题或改40／160分母。磁盘、网络和未知外部负载仍需实测，不承诺绝不崩溃。

### 恢复与补测

完整结果直接复用；同一冻结版本／原题身份的中断执行先核对已完成结果及旧进程、容器、网络和代理，物理执行编号持续递增，原始记录不覆盖。每题能力失败最多3次，基础设施故障不占此计数，也没有固定故障次数上限。每题8小时从首次实际启动起算，含退避、再次排队和离线时间，不含首次排队。请求只在能证明安全的边界重试，不拼接部分流；未知原因或鉴权问题保持待检查，不盲目重跑。

整题重启退避不占资源；仍在运行的容器等待请求恢复时保留预约。显式unbounded模式不因两次unknown用量停整批，但继续保留未知费用。手动STOP、逐题截止和未确认清理的安全停准入保持。

尚未启动完整200题真实基线。补测、恢复与请求层接线曾通过807项实验回归；后续增量环境准备及代理源码能力预检已通过860项实验回归（1项opt-in跳过），此前另行完成20插件进程合成验收及完整Pi真实容器通道验证；这些不代表真实题目成绩。第一批结束必须补测未完成／超时题，不能忽略缺项作晋升判定；用户已确认独立补测批次每题新8h窗口，累计3次能力失败不重置；已1次正常失败仅余2次。当前接线保留原批、补测及累计证据，补测仍不完整则不作晋升判定。2026-11-08逐题审计及React→NodeBB单槽替换后的当前题单为46TB＋154SWE，仍为40基础／160能力。磁盘仅报告并用于执行准入，不作为选题剔除标准；takens保留选中，容量不足时等待。

### 逐题精确复用与部分准入（已批准）

完整环境资格按单题精确复用：原题／官方来源、镜像ID、Pi／插件、运行／模型配置、评测代码及完整控制、软件、生命周期、所有权和清理证据均须重新核验一致。只改其他题、排序或分组不使未变题的资格失效。稳定环境身份还绑定专用daemon、平台、固定CPU/RAM、工具版本及依赖锁；动态空闲容量、并发上限及调度预算不属于资格身份，但每次仍按当前资源准入。旧v5收据不能升级到本次代码，旧记录不覆盖。

哪道题完整环境验收且资源可满足，就先运行哪道题；其余继续等待，原生基线始终保留完整200题范围，插件阶段保留所请求的完整40或160题范围。首次实际启动前等待不启动8h时钟、不消耗能力尝试；后续波次恢复同一series，已完成结果不重跑。等待题不算初批完成，不能提前开补测；最终基线及晋升仍须必要结果齐全。当前修复冻结代码回归1144通过、1跳过，独立305通过；v7新store的4题完整环境资格已实跑通过，仍缺196题；这是环境控制而非模型成绩，正式基线状态另行记录。详见下方验收记录。

最终费用汇总使用停止后的原始账本，保留已结算小计和unknown。数值是API usage乘固定高峰费率的估算，未核对供应商账单，也未自动应用峰谷折扣；unknown预留不作为实际扣款。原始attempt快照保留，权威统计见accounting.json和results/summary-final.json。

最新实际状态（2026-11-08）：4题真实原生首波已因public Actor的NET_RAW权限偏差安全停止，记录为1通过、3 hold、196未启动；旧v6资格保留不升级；修复00ce405a的v7四题原控制、双侧合成、实际五项权限与强清理已验收通过。受限旧中断复核及真实恢复由独立执行流程处理，此处不预言恢复结果或新增模型成绩，详见[首波结果与安全STOP记录](../docs/experiments/RSI_EXPERIMENT_RESULT_2026-11-08.md)。

最新验收及剩余阻塞见 [2026-11-08实验模块验收](../docs/experiments/RSI_EXPERIMENT_RESULT_2026-11-08.md)，逐题依据见 [完整200题审计](../docs/experiments/RSI_TASK_AUDIT_2026-11-08.md)。

后续真实恢复完成（2026-11-08）：qutebrowser旧通过保留，Element／NodeBB恢复官方通过，batched三次正常官方0后能力失败耗尽；完整200当前3通过、1失败、196未启动，原生基线未完成，真实插件0、基础双侧0/40。两launch已结清并强清理，原8h不重置；waiting_preparation仍是初批未启动，不等于补测。已知合计27,696,265 tokens／USD0.860667084固定费率估算，旧2个unknown使总费用仍未知。分组及初始双侧校准后续安排尚未决定或实施，详见[真实恢复完成与最终结算](../docs/experiments/RSI_EXPERIMENT_RESULT_2026-11-08.md)。

### 一次性初始分组校准

`rsi calibrate CONFIG PREPARED`沿用现有插件series与调度，必须先完成原生200，并固定当前获批插件归档／模型／Pi身份；仅建立初始题集，不作晋升。新代码须新的环境资格，已有模型结果、尝试及8h记录不重置。当前196题未启动、插件未跑，尚不能形成合格40。

双侧完整200官方结果齐全后，`rsi freeze-grouping CONFIG DESTINATION`才可无模型执行地封存分组；DESTINATION为实验根目录下`calibrations/<question_set_sha256>/grouping.json`，不能覆盖不同的既有选择。配置的可选`grouping_path`读取此不可变证明，经完整重验后应用data-only分组，不改原200身份／原件／顺序。双方通过交集不足40或不能使40／160两组均具多个场景和难度时报告不足；来源及更多标签为确定性均衡目标，不设全覆盖配额。冻结后不按后续候选表现重选。

未冻结时`qualified_regression_count`为null；冻结后只计基础40，不把能力题交集算进基础资格。`supplementary_required`不再把初批未启动的waiting_preparation／capacity算作补测；原补测准入、累计失败和独立窗口规则不变。

普通`run`仍是既有experiment-stage-only接口，不作晋升；校准仅吸收本次固定插件在同200、同模型／规则下可核验的既有stage结果，不能挑选将来版本或另起series清零。本次实际插件尚未执行，须先登记且另获真实执行授权。

最终离线验收（2026-11-08 15:54 UTC）：初始校准实现独立复查后补齐历史进程terminal证据门禁，固定Node24.22.0下完整实验1199通过／1跳过、产品276通过；真实历史349份引用核验保持原生3通过／1失败／196未启动，未新增模型调用或冻结分组。详见[最终校准离线验收](../docs/experiments/RSI_EXPERIMENT_RESULT_2026-11-08.md)。

v8后续免费环境准备已为mvcc、risk、wal、vba四道新题取得当前评测器的完整资格（4/200），旧模型3通过／1失败保持。无凭据准入显示新4题可首启、192继续等待；尚无新增真实模型调用。详见同一结果文档的v8补充。


最新真实执行终态（2026-11-09 00:36 UTC）：v8四题原生波次已结算并强清理，mvcc首次通过、vba第二次通过、wal三次能力失败；risk两次能力失败后第三次在原8h截止中断，仍只累计2次能力失败。完整200当前5通过、2能力耗尽、1时间耗尽、192待环境准备，严格完成7，基线和双侧校准均未完成、插件真实执行0。562份证据引用及最终原始账本重验通过；旧4224非敏感文件和历史容器／镜像／网络保持。累计3笔未知请求仍保留，总费用未知，已知USD2.935020348仅配置峰值费率估算。原外层CLI退出码未捕获，实际进程终态及清理结算已核实。

risk补测需等完整200初批scope不再有未启动题后按既定门禁登记；不能把本波结束等同完整初批结束。已获批补测规则为新8h窗口、保留原first_started和全部历史，累计3次能力失败不重置，因此risk只剩1次能力尝试、下个物理attempt为4。下一步是既定8题的完整环境准备，不包含新真实模型调用；详见[本波最终结果、账本和观察限制](../docs/experiments/RSI_EXPERIMENT_RESULT_2026-11-08.md)。

下一批8题环境准备已于2026-11-09 01:29 UTC完整通过，v8现12/200资格，全200为8新pending、184 waiting_preparation，旧成绩不变；8题时钟仍未启动、真实模型调用0。最终Docker无运行容器，旧原件／镜像／容器／网络保全，详见结果文档最新8题准备记录。
