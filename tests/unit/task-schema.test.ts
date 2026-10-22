import assert from "node:assert/strict";
import test from "node:test";
import { Check } from "typebox/value";
import {
  CreateSchema,
  FindSchema,
  ResumeSchema,
  StatusSchema,
} from "../../src/task/model.ts";
import { AppendSchema } from "../../src/state/model.ts";

test("approved Task input boundaries reject missing, ambiguous, empty or extra fields", () => {
  const create = {
    title: "task",
    goal: "goal",
    project_name: "project",
    summary: "summary",
    keywords: ["test"],
  };
  assert.ok(Check(CreateSchema, create));
  for (const input of [
    { ...create, keywords: [] },
    { ...create, title: " " },
    { ...create, unknown: true },
    { title: "only title" },
  ])
    assert.equal(Check(CreateSchema, input), false);
  assert.ok(Check(FindSchema, { query: "查找之前的任务" }));
  assert.equal(Check(FindSchema, { query: "query", limit: 0 }), false);
  assert.equal(Check(StatusSchema, {}), false);
  const wireSchema = JSON.parse(JSON.stringify(ResumeSchema));
  assert.equal(wireSchema.type, "object");
  assert.ok(wireSchema.properties);
  assert.ok(Check(ResumeSchema, { task_id: "task_test" }));
  assert.ok(Check(ResumeSchema, { mode: "latest_paused" }));
  assert.equal(
    Check(ResumeSchema, { task_id: "task_test", mode: "latest_paused" }),
    false,
  );
  assert.equal(Check(ResumeSchema, { query: "previous task" }), false);
  assert.equal(Check(ResumeSchema, {}), false);
  assert.equal(Check(ResumeSchema, { mode: "other" }), false);
});

test("State schema requires a nonempty batch, content, allowed types and explained evidence", () => {
  const valid = {
    type: "fact",
    content: "content",
    evidence: { U1: "user requirement" },
  };
  assert.ok(Check(AppendSchema, { items: [valid] }));
  for (const input of [
    { items: [] },
    { items: [{ ...valid, type: "plan" }] },
    { items: [{ ...valid, content: "" }] },
    { items: [{ ...valid, evidence: {} }] },
    { items: [{ ...valid, evidence: { U1: "" } }] },
  ])
    assert.equal(Check(AppendSchema, input), false);
});
