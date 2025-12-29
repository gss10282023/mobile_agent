# TODO
- [x] ~~2025 9/11 配置sqlite/alembic (本地保存)~~
- [ ] ~~2025 9/12 table创建 完成最小化存储 程序意外终止后可再追溯~~
- [ ] ~~2025 9/13 全流程设计 or 判断agent接入~~
- 
- [x] 2025 9/13 转移到postgreSql，创建core table，接入
- [x] 2025 9/14 判断agent接入 or 聊天agent （接入了聊天）
- [x] 2025 9/14 去除聊天ai感
- [ ] ~~2025 9/15 优化聊天agent (考虑不用gemini flash)~~
- [ ] ~~2025 9/16 查询相关研究方向，使聊天agent适应性更强~~
- [x] 2025/9/15 考虑了一下，应该先完成discovery agent （尽可能简化）
- [ ] 2025/9/16 修正discovery agent bug，稳定探索
- [ ] 2025 9/17 修正discovery agent，存储信息
- [ ] 2025 9/18 discovery agent可交付 稳定运行版


# TODO (待完成)
## 建库与索引
- [x] 建立 core.events 表及索引
  - [x] (lead_id, ts)
  - [x] (type, ts)
  - [x] 可选：GIN(payload)

## 事件字典登记新增
- [x] ChatPlanIssued  
- [x] DialogueTurn(modality)  
- [x] ScoreChat(provisional_verdict, rule_version)  
- [x] EvidenceStored(files.kind, duration_s)  
- [x] JuryAssessment  
- [x] ExplorationDecision  
- [x] PlanIssued  
- [x] Keyword*  
- [x] EntityResolved  
- [x] ManualAssessment  

## Chat Agent（优先）
- [x] 接口：tg.open_chat / tg.send / wait / snapshot
- [x] 每回合写 DialogueTurn / ScoreChat
- [x] 遇红旗即停并写 EvidenceStored
- [x] 携带 conv_id

## Jury Lite（优先）
- [ ] /jury/eval 并行多模型 → JuryAssessment（含 legal_digest）
- [ ] 灰区/移交前触发

## UI Agent（探索）
- [x] desktop 或 emulator（UI-TARS + uiautomator2）
- [x] 支持最小原语：
  - [x] x.search
  - [x] x.open_profile
  - [x] x.open_comments
  - [x] snapshot

## TeleWatcher
- [ ] 未读检测
- [ ] 步级心跳抢占

## Derived 固定视图
- [ ] v_leads_current（增强）
- [ ] v_inbox_queue
- [ ] v_conversations
- [ ] v_attack_chains
- [ ] v_entity_map
- [ ] v_kw_stats
- [ ] v_kw_backlog

## Exploration Agent
- [ ] 读取派生视图 → 下发 PlanIssued / ChatPlanIssued
- [ ] 接入关键词事件全链路

## Schema Manager
- [ ] 派生自适应：提案 → 影子 → 原子替换 → 监控 → 回滚

## 中断恢复验证
- [ ] 事件回放可重建探索 / 聊天 / 关键词下一步
- [ ] 会话与指标计算一致

