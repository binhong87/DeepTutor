import test from "node:test";
import assert from "node:assert/strict";

import {
  agentChatReducer,
  makeInitialSession,
} from "../lib/agent-chat-types";

test("NEW_TURN: adds a turn and sets streaming state", () => {
  const state = makeInitialSession();
  const turn = {
    id: "t1", userContent: "hello", userAttachments: [],
    assistantContent: "", steps: [], richOutputType: null as null,
    richOutputData: null, sources: [], status: "streaming" as const,
  };
  const next = agentChatReducer(state, { type: "NEW_TURN", turn });
  assert.equal(next.turns.length, 1);
  assert.equal(next.isStreaming, true);
  assert.equal(next.status, "streaming");
  assert.deepEqual(next.activeSteps, []);
});

test("STREAM_CONTENT: appends delta to the matching turn", () => {
  const state = makeInitialSession();
  const turn = {
    id: "t1", userContent: "q", userAttachments: [], assistantContent: "",
    steps: [], richOutputType: null as null, richOutputData: null,
    sources: [], status: "streaming" as const,
  };
  let s = agentChatReducer(state, { type: "NEW_TURN", turn });
  s = agentChatReducer(s, { type: "STREAM_CONTENT", turnId: "t1", delta: "Hello" });
  s = agentChatReducer(s, { type: "STREAM_CONTENT", turnId: "t1", delta: " world" });
  assert.equal(s.turns[0].assistantContent, "Hello world");
});

test("STREAM_STEP: adds a new step to activeSteps", () => {
  const state = makeInitialSession();
  const step = {
    id: "s1", type: "thinking" as const,
    label: "Reasoning…", done: false, timestamp: 1000,
  };
  const next = agentChatReducer(state, { type: "STREAM_STEP", step });
  assert.equal(next.activeSteps.length, 1);
  assert.equal(next.activeSteps[0].id, "s1");
});

test("STREAM_STEP: updates an existing step in-place", () => {
  let state = makeInitialSession();
  const step = {
    id: "s1", type: "thinking" as const,
    label: "Reasoning…", done: false, timestamp: 1000,
  };
  state = agentChatReducer(state, { type: "STREAM_STEP", step });
  state = agentChatReducer(state, {
    type: "STREAM_STEP", step: { ...step, done: true, label: "Reasoned" },
  });
  assert.equal(state.activeSteps.length, 1);
  assert.equal(state.activeSteps[0].done, true);
  assert.equal(state.activeSteps[0].label, "Reasoned");
});

test("STREAM_DONE: finalises turn, moves activeSteps into turn, clears streaming", () => {
  let state = makeInitialSession();
  const turn = {
    id: "t1", userContent: "q", userAttachments: [], assistantContent: "ans",
    steps: [], richOutputType: null as null, richOutputData: null,
    sources: [], status: "streaming" as const,
  };
  state = agentChatReducer(state, { type: "NEW_TURN", turn });
  state = agentChatReducer(state, {
    type: "STREAM_STEP",
    step: { id: "s1", type: "thinking" as const, label: "…", done: true, timestamp: 1 },
  });
  state = agentChatReducer(state, { type: "STREAM_DONE", turnId: "t1" });
  assert.equal(state.isStreaming, false);
  assert.equal(state.status, "idle");
  assert.deepEqual(state.activeSteps, []);
  assert.equal(state.turns[0].status, "done");
  assert.equal(state.turns[0].steps.length, 1);
});

test("SET_KB: updates knowledgeBaseId", () => {
  const state = makeInitialSession();
  const next = agentChatReducer(state, { type: "SET_KB", knowledgeBaseId: "kb-1" });
  assert.equal(next.knowledgeBaseId, "kb-1");
});
