-- 001_core_events.sql (REWRITE, minimal-diff)
-- Postgres >= 13

BEGIN;

-- A. 架构
CREATE SCHEMA IF NOT EXISTS core;

-- B. 事件字典
CREATE TABLE IF NOT EXISTS core.event_type_registry (
  type            text PRIMARY KEY,
  description     text,
  version         text NOT NULL,                 -- 口径版本（新事件集固定 "2025-09"）
  required_keys   text[] DEFAULT '{}',
  optional_keys   text[] DEFAULT '{}',
  payload_example jsonb,
  created_at      timestamptz NOT NULL DEFAULT now()
);

-- 注册“沿用事件”——仅保证类型存在，不强制结构
INSERT INTO core.event_type_registry(type, description, version)
VALUES
  ('Observation','页面/应用观察与状态','legacy'),
  ('ScorePage','页面可疑度评分','legacy'),
  ('ContactExtracted','抽取到的联系方式','legacy'),
  ('RedirectSuggested','建议导流到其它平台','legacy')
ON CONFLICT (type) DO NOTHING;

-- 注册“新增事件集”——含口径与示例（强校验目标）
INSERT INTO core.event_type_registry(type, description, version, required_keys, optional_keys, payload_example)
VALUES
  ('ChatPlanIssued','下发聊天计划（必携 conv_id）','2025-09',
    ARRAY['conv_id','persona','objective','entrypoint','script','limits','stop_on_flags','evidence_snapshot','guard','idempotencyKey','version'],
    ARRAY[]::text[],
    '{
      "version":"2025-09",
      "conv_id":"00000000-0000-0000-0000-000000000000",
      "persona":"consumer","objective":"probe risk",
      "entrypoint":{"platform":"telegram","contact":{"type":"username","value":"@someone"}},
      "script":["hi","question"],
      "limits":{"max_turns":4,"wait_seconds":10},
      "stop_on_flags":["request_payment","offsite_payment"],
      "evidence_snapshot":"each_turn",
      "guard":{"ban_phrases":["验证码","银行卡","助记词"],"tone":"polite_probe"},
      "idempotencyKey":"cp_1"
    }'::jsonb),
  ('DialogueTurn','单回合对话（含 modality 与可选时长）','2025-09',
    ARRAY['conv_id','role','modality','version'],
    ARRAY['media_meta'],
    '{
      "version":"2025-09",
      "conv_id":"00000000-0000-0000-0000-000000000000",
      "role":"agent","modality":"text","media_meta":{"duration_s":0}
    }'::jsonb),

  -- ★★ 核心变更：ScoreChat 新口径（A 仅在明确违法时允许）
  ('ScoreChat','聊天会话判定：A=明确违反法律规定；B=高度怀疑；C=正常/不足','2025-09',
    ARRAY['conv_id','verdict','turn_index','rule_version','basis','version'],
    ARRAY['certainty','evidence_refs','notes'],
    '{
      "version":"2025-09",
      "conv_id":"00000000-0000-0000-0000-000000000000",
      "verdict":"B",
      "turn_index":1,
      "rule_version":"harm-v1.2",
      "basis":{
        "legal_breaches":[
          {
            "jurisdiction":"CN",
            "code":"证券法/执业资格管理办法",
            "article":"第XX条",
            "requirement":"提供证券投资建议须具备相应从业资格并在核准范围内执业",
            "observed_quote":"加入VIP群，我带你做这只股，稳赚…",
            "uri":"https://example.org/law/securities-qualification#art-xx",
            "detected_by":"llm",
            "confidence":0.82
          }
        ],
        "risk_signals":["request_payment","offsite_payment","provide_wallet"]
      }
    }'::jsonb),

  ('EvidenceStored','证据归档（文件种类/时长）','2025-09',
    ARRAY['files','version'],
    ARRAY[]::text[],
    '{
      "version":"2025-09",
      "files":[{"kind":"screenshot","duration_s":0}]
    }'::jsonb),
  ('JuryAssessment','评审团合议（A/B/C + 解释 + 法条）','2025-09',
    ARRAY['verdict','confidence','rule_version','version'],
    ARRAY['explain','model_votes','legal_digest','evidence_refs'],
    '{
      "version":"2025-09",
      "verdict":"B","confidence":0.82,"rule_version":"harm-v1.2",
      "explain":["..."],"model_votes":[{"model":"M1","verdict":"B","conf":0.82}],
      "legal_digest":[{"title":"...", "uri":"https://..."}],
      "evidence_refs":["s3://..."]
    }'::jsonb),
  ('ExplorationDecision','探索Agent决策下一步','2025-09',
    ARRAY['next_action','reason','version'],
    ARRAY['target','plan_hint'],
    '{"version":"2025-09","next_action":"open_profile","reason":"heuristic"}'::jsonb),
  ('PlanIssued','UI执行计划（探索）','2025-09',
    ARRAY['driver','steps','idempotencyKey','version'],
    ARRAY[]::text[],
    '{"version":"2025-09","driver":"desktop","steps":[{"use":"x.search","args":{"q":"foo"}}],"idempotencyKey":"p_1"}'::jsonb),
  ('KeywordProposed','关键词提案','2025-09',
    ARRAY['term','version'], ARRAY['priority'],
    '{"version":"2025-09","term":"foo","priority":0.5}'::jsonb),
  ('KeywordScheduled','关键词排程','2025-09',
    ARRAY['term','version'], ARRAY['when'],
    '{"version":"2025-09","term":"foo","when":"2025-09-13T00:00:00Z"}'::jsonb),
  ('KeywordTried','关键词执行尝试','2025-09',
    ARRAY['term','version'], ARRAY['metrics'],
    '{"version":"2025-09","term":"foo","metrics":{"pages":12}}'::jsonb),
  ('KeywordOutcome','关键词结果','2025-09',
    ARRAY['term','version'], ARRAY['precision','contact_yield','captcha_rate'],
    '{"version":"2025-09","term":"foo","precision":0.6}'::jsonb),
  ('KeywordRetired','关键词退场','2025-09',
    ARRAY['term','version'], ARRAY['reason'],
    '{"version":"2025-09","term":"foo","reason":"low precision"}'::jsonb),
  ('EntityResolved','主体合并映射','2025-09',
    ARRAY['entity_id','members','method','method_version','confidence','version'],
    ARRAY[]::text[],
    '{
      "version":"2025-09",
      "entity_id":"E123",
      "members":[{"platform":"twitter","key":"@alice"}],
      "method":"rule","method_version":"v1","confidence":0.9
    }'::jsonb),
  ('ManualAssessment','人工标注（金标）','2025-09',
    ARRAY['scope','label','annotator','scheme_version','version'],
    ARRAY['rationale'],
    '{
      "version":"2025-09",
      "scope":"conversation","label":"B","annotator":"rater01","scheme_version":"lab-v1",
      "rationale":["..."]
    }'::jsonb)
ON CONFLICT (type) DO UPDATE
SET description     = EXCLUDED.description,
    version         = EXCLUDED.version,
    required_keys   = EXCLUDED.required_keys,
    optional_keys   = EXCLUDED.optional_keys,
    payload_example = EXCLUDED.payload_example;

-- C. 核心事实表（保持你现有列名以兼容派生脚本）
CREATE TABLE IF NOT EXISTS core.events (
  event_id      TEXT PRIMARY KEY,
  ts            TIMESTAMPTZ NOT NULL,
  run_id        TEXT,
  lead_id       TEXT,
  platform      TEXT,
  type          TEXT NOT NULL,
  payload       JSONB NOT NULL DEFAULT '{}'::jsonb,
  artifact_path TEXT,
  step_idx      INT
);

-- 事件类型外键：保证所有写入的 type 均已在注册表存在
ALTER TABLE core.events
  DROP CONSTRAINT IF EXISTS fk_events_type_registry;
ALTER TABLE core.events
  ADD CONSTRAINT fk_events_type_registry
  FOREIGN KEY (type) REFERENCES core.event_type_registry(type)
  ON UPDATE CASCADE ON DELETE RESTRICT;

-- D. 索引（与你原 001 一致，并加一个便捷部分索引）
CREATE INDEX IF NOT EXISTS idx_core_events_lead_ts     ON core.events (lead_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_core_events_type_ts     ON core.events (type, ts DESC);
CREATE INDEX IF NOT EXISTS idx_core_events_payload_gin ON core.events USING GIN (payload);
CREATE INDEX IF NOT EXISTS idx_core_events_sc_ts       ON core.events (ts DESC) WHERE type='ScoreChat';

-- E. 触发器：append-only & 新事件集最小校验
-- E1) 禁止 UPDATE/DELETE
CREATE OR REPLACE FUNCTION core.fn_events_append_only()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP IN ('UPDATE','DELETE') THEN
    RAISE EXCEPTION 'core.events 为 append-only，禁止 % 操作', TG_OP;
  END IF;
  RETURN NULL;
END$$;

DROP TRIGGER IF EXISTS trg_events_block_ud ON core.events;
CREATE TRIGGER trg_events_block_ud
  BEFORE UPDATE OR DELETE ON core.events
  FOR EACH ROW EXECUTE FUNCTION core.fn_events_append_only();

-- E2) 新事件集校验（旧类型仅要求“存在于注册表”，不校结构）
CREATE OR REPLACE FUNCTION core.fn_events_validate_new()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  t   text := NEW.type;
  v   text := NEW.payload->>'version';
  modal text;
  verdict text;
  scope_ text;
  lbl    text;
  lb_cnt int;
BEGIN
  IF t IN (
    'ChatPlanIssued','DialogueTurn','ScoreChat','EvidenceStored','JuryAssessment',
    'ExplorationDecision','PlanIssued','KeywordProposed','KeywordScheduled',
    'KeywordTried','KeywordOutcome','KeywordRetired','EntityResolved','ManualAssessment'
  ) THEN
    IF v IS DISTINCT FROM '2025-09' THEN
      RAISE EXCEPTION 'payload.version 必须为 "2025-09"（type=%）', t;
    END IF;

    IF t = 'DialogueTurn' THEN
      IF NEW.payload ? 'conv_id' IS FALSE OR NEW.payload ? 'role' IS FALSE OR NEW.payload ? 'modality' IS FALSE THEN
        RAISE EXCEPTION 'DialogueTurn 缺少 conv_id/role/modality';
      END IF;
      modal := NEW.payload->>'modality';
      IF modal NOT IN ('text','voice','video','image','file','call') THEN
        RAISE EXCEPTION 'DialogueTurn.modality 不在允许集合';
      END IF;

    ELSIF t = 'ScoreChat' THEN
      -- ★★ 新口径：A 仅在存在明确法规违背的证据
      IF NEW.payload ? 'conv_id' IS FALSE OR NEW.payload ? 'verdict' IS FALSE
         OR NEW.payload ? 'turn_index' IS FALSE OR NEW.payload ? 'rule_version' IS FALSE
         OR NEW.payload ? 'basis' IS FALSE THEN
        RAISE EXCEPTION 'ScoreChat 缺少 conv_id/verdict/turn_index/rule_version/basis';
      END IF;
      verdict := NEW.payload->>'verdict';
      IF verdict NOT IN ('A','B','C') THEN
        RAISE EXCEPTION 'ScoreChat.verdict 必须是 A|B|C';
      END IF;
      -- basis 必须是 object；legal_breaches 若存在需为数组
      IF jsonb_typeof(NEW.payload->'basis') <> 'object' THEN
        RAISE EXCEPTION 'ScoreChat.basis 必须为对象';
      END IF;

      lb_cnt := COALESCE(jsonb_array_length(NEW.payload->'basis'->'legal_breaches'),0);
      IF verdict = 'A' AND lb_cnt < 1 THEN
        RAISE EXCEPTION 'ScoreChat(A) 需要非空 basis.legal_breaches[]';
      END IF;

      -- 可选的更严格检查：如存在 legal_breaches，要求必要字段
      IF lb_cnt > 0 AND EXISTS (
        SELECT 1 FROM jsonb_array_elements(NEW.payload->'basis'->'legal_breaches') lb
        WHERE (lb ? 'requirement') IS FALSE
           OR (lb ? 'observed_quote') IS FALSE
           OR ( (lb ? 'uri') IS FALSE AND (lb ? 'code') IS FALSE )
      ) THEN
        RAISE EXCEPTION 'ScoreChat.legal_breaches[*] 缺少 requirement/observed_quote 或 uri/code';
      END IF;

    ELSIF t = 'EvidenceStored' THEN
      IF NEW.payload ? 'files' IS FALSE OR jsonb_typeof(NEW.payload->'files') <> 'array' THEN
        RAISE EXCEPTION 'EvidenceStored.files 必须为数组';
      END IF;
      IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(NEW.payload->'files') f
        WHERE (f ? 'kind') IS FALSE
           OR (f->>'kind') NOT IN ('screenshot','screen_recording','audio','video')
      ) THEN
        RAISE EXCEPTION 'EvidenceStored.files[*].kind 缺失或非法';
      END IF;

    ELSIF t = 'JuryAssessment' THEN
      IF NEW.payload ? 'verdict' IS FALSE OR NEW.payload ? 'confidence' IS FALSE OR NEW.payload ? 'rule_version' IS FALSE THEN
        RAISE EXCEPTION 'JuryAssessment 缺少 verdict/confidence/rule_version';
      END IF;
      IF (NEW.payload->>'verdict') NOT IN ('A','B','C') THEN
        RAISE EXCEPTION 'JuryAssessment.verdict 必须是 A|B|C';
      END IF;

    ELSIF t = 'ExplorationDecision' THEN
      IF NEW.payload ? 'next_action' IS FALSE OR NEW.payload ? 'reason' IS FALSE THEN
        RAISE EXCEPTION 'ExplorationDecision 缺少 next_action/reason';
      END IF;

    ELSIF t = 'PlanIssued' THEN
      IF NEW.payload ? 'driver' IS FALSE OR NEW.payload ? 'steps' IS FALSE OR NEW.payload ? 'idempotencyKey' IS FALSE THEN
        RAISE EXCEPTION 'PlanIssued 缺少 driver/steps/idempotencyKey';
      END IF;
      IF jsonb_typeof(NEW.payload->'steps') <> 'array' THEN
        RAISE EXCEPTION 'PlanIssued.steps 必须为数组';
      END IF;

    ELSIF t = 'ChatPlanIssued' THEN
      IF NEW.payload ? 'conv_id' IS FALSE THEN
        RAISE EXCEPTION 'ChatPlanIssued 必须包含 conv_id';
      END IF;

    ELSIF t = 'EntityResolved' THEN
      IF NEW.payload ? 'entity_id' IS FALSE OR NEW.payload ? 'members' IS FALSE
         OR NEW.payload ? 'method' IS FALSE OR NEW.payload ? 'method_version' IS FALSE
         OR NEW.payload ? 'confidence' IS FALSE THEN
        RAISE EXCEPTION 'EntityResolved 缺少 entity_id/members/method/method_version/confidence';
      END IF;

    ELSIF t = 'ManualAssessment' THEN
      IF NEW.payload ? 'scope' IS FALSE OR NEW.payload ? 'label' IS FALSE
         OR NEW.payload ? 'annotator' IS FALSE OR NEW.payload ? 'scheme_version' IS FALSE THEN
        RAISE EXCEPTION 'ManualAssessment 缺少scope/label/annotator/scheme_version';
      END IF;
      scope_ := NEW.payload->>'scope';
      lbl    := NEW.payload->>'label';
      IF scope_ NOT IN ('conversation','account') THEN
        RAISE EXCEPTION 'ManualAssessment.scope 必须是 conversation|account';
      END IF;
      IF lbl NOT IN ('A','B','C') THEN
        RAISE EXCEPTION 'ManualAssessment.label 必须是 A|B|C';
      END IF;
    END IF;
  END IF;

  RETURN NEW;
END$$;

DROP TRIGGER IF EXISTS trg_events_validate_new ON core.events;
CREATE TRIGGER trg_events_validate_new
  BEFORE INSERT ON core.events
  FOR EACH ROW EXECUTE FUNCTION core.fn_events_validate_new();

COMMIT;
