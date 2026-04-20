# xiaopaw-team

极客时间《企业级多智能体设计实战》模块四第 29 课实战项目：基于 xiaopaw（17/22 课）扩展为 Manager + PM + RD + QA 四角色数字员工团队，端到端完成一个真实 toC 项目并自我进化一次。

## 状态

✅ **生产级 v1.5 装配完成**（2026-04-21）。141 个非-LLM 测试全 PASS，1 个自驱动 handshake 集成测试 PASS。

组件：
- 基础设施（继承 17/22 课）：FeishuListener + Runner + SkillLoader + Sub-Crew + Sandbox + Cron + Memory
- 团队层（29 课新增）：
  - **8 个 Python Tools**（`xiaopaw_team/tools/team_tools.py`）：`SendMail/ReadInbox/MarkDone/ReadShared/WriteShared` + Manager 独占 `CreateProject/AppendEvent/SendToHuman`
  - **feishu_bridge**（`xiaopaw_team/tools/feishu_bridge.py`）：CheckpointStore + classify（new_requirement / checkpoint_response / sop_cocreate / clarification_answer / need_discussion 五分类）
  - **tasks_store**（`xiaopaw_team/cron/tasks_store.py`）：SendMailTool 自动 schedule_wake + 4 role heartbeat 错峰（0/7/14/21s）
  - **main.py**：完整启动链（Manager asyncio.Lock / CronService dispatch_fn / 4 agent_fn）
  - **36 个角色 skill**：Manager 11 / PM 4 / RD 5 / QA 7 / shared 2 + legacy mailbox_ops / self_score
- 核心契约：SendMailTool → tasks.json → CronService → dispatch(team:role) → agent_fn_map[role] 完全自驱动，**零 Python 编排**

## 文档

完整设计文档在 **[docs/DESIGN.md](./docs/DESIGN.md)**。

- [docs/](./docs/) — 设计文档目录（含 17/22 基础模块详设）
- [docs/DESIGN.md](./docs/DESIGN.md) — **主设计文档**
- [docs/history/](./docs/history/) — 版本迭代历史

## 快速了解

- **本课是什么**：把 25-28 课讲过的机制（角色体系 / 任务链协作协议 / Human as 甲方 / 自我进化）装配起来，配一个真实 demo 项目（"小爪子日记" toC 宠物日记网站），跑通端到端 + 自我进化
- **基础来自哪里**：继承 xiaopaw-with-memory（17 课工具篇 + 22 课记忆篇）。基础设施（Listener/Runner/SkillLoader/Sub-Crew/Sandbox/Cron/Memory）完全复用，29 课只做团队层扩展
- **核心原则**：单一接口（人只和 Manager）+ 零 Python 编排（流程全写在 SOP SKILL 里）+ Skill 类型边界（reference 对话框架 / task 一次性写入 / 主 Agent Tool 协作基础设施）

## 架构速览

```
L3 团队层（29 课新增）：4 Agent + 文件邮箱 + 事件流 + 飞书桥
L2 记忆层（22 课）：Bootstrap + ctx.json + pgvector
L1 基础层（17 课）：FeishuListener + Runner + SkillLoader + Sub-Crew + Sandbox + Cron
```

详细架构图和每个模块的设计详见 [docs/DESIGN.md](./docs/DESIGN.md)。

## 启动（设计完成后）

### 首次安装

```bash
# 1. 启沙盒
docker-compose -f sandbox-docker-compose.yaml up -d

# 2. （可选）启 pgvector
docker-compose -f pgvector-docker-compose.yaml up -d

# 3. workspace 初始化为独立 git 仓库（apply_proposal 需要）
cd workspace
git init
git add .
git commit -m "workspace baseline v1.0"
cd ..

# 4. 启主进程
python -m xiaopaw_team.main
```

### 日常启动

```bash
docker-compose -f sandbox-docker-compose.yaml up -d
python -m xiaopaw_team.main
```

## 相关项目

- [xiaopaw-with-memory](../xiaopaw-with-memory/) — 17/22 课工作助手，本项目基础
- [crewai_mas_demo/m4l25-m4l28](../crewai_mas_demo/) — 25-28 课知识点演示代码
