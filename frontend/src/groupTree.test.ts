import { describe, expect, it } from "vitest";
import { buildGroupTree } from "./groupTree";
import type { Requirement, RequirementGroup } from "./types";

function group(id: string, parentId: string | null = null): RequirementGroup {
  return { id, parent_id: parentId, name: id, description: "", metadata: {} };
}

function requirement(id: string, groupId: string): Requirement {
  return {
    id, group_id: groupId, name: id, description: "", task: "presence",
    conditions: {}, acceptance: [{ metric: "accuracy", operator: ">=", value: 0.9 }], metadata: {},
  };
}

describe("buildGroupTree", () => {
  it("nests top-level groups with no parent at the root", () => {
    const tree = buildGroupTree([group("a"), group("b")], []);
    expect(tree.map((n) => n.group.id)).toEqual(["a", "b"]);
  });

  it("nests a child group under its parent, not at the root", () => {
    const tree = buildGroupTree([group("a"), group("a-1", "a")], []);
    expect(tree).toHaveLength(1);
    expect(tree[0].children.map((n) => n.group.id)).toEqual(["a-1"]);
  });

  it("supports arbitrary depth", () => {
    const tree = buildGroupTree(
      [group("a"), group("a-1", "a"), group("a-1-1", "a-1")],
      [],
    );
    expect(tree[0].children[0].children.map((n) => n.group.id)).toEqual(["a-1-1"]);
  });

  it("attaches requirements to their own group, not an ancestor or sibling", () => {
    const tree = buildGroupTree(
      [group("a"), group("b")],
      [requirement("r1", "a"), requirement("r2", "b")],
    );
    const a = tree.find((n) => n.group.id === "a")!;
    const b = tree.find((n) => n.group.id === "b")!;
    expect(a.requirements.map((r) => r.id)).toEqual(["r1"]);
    expect(b.requirements.map((r) => r.id)).toEqual(["r2"]);
  });

  it("leaves a group with no requirements as an empty array, not undefined", () => {
    const tree = buildGroupTree([group("a")], []);
    expect(tree[0].requirements).toEqual([]);
  });

  it("leaves a group with no children as an empty array, not undefined", () => {
    const tree = buildGroupTree([group("a")], []);
    expect(tree[0].children).toEqual([]);
  });
});
