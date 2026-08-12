import type { Requirement, RequirementGroup } from "./types";

export interface GroupNode {
  group: RequirementGroup;
  children: GroupNode[];
  requirements: Requirement[];
}

// Builds the group tree from the flat parent_id adjacency list - the
// wire format is flat (same as the backend's storage), the tree is a
// pure display-time derivation, never persisted or re-sent. Shared by
// ProfileDetail's plain hierarchy view and CoverageMatrix, which both
// need the identical tree shape.
export function buildGroupTree(groups: RequirementGroup[], requirements: Requirement[]): GroupNode[] {
  const childrenByParent = new Map<string | null, RequirementGroup[]>();
  for (const group of groups) {
    const key = group.parent_id;
    childrenByParent.set(key, [...(childrenByParent.get(key) ?? []), group]);
  }
  const requirementsByGroup = new Map<string, Requirement[]>();
  for (const requirement of requirements) {
    const key = requirement.group_id;
    requirementsByGroup.set(key, [...(requirementsByGroup.get(key) ?? []), requirement]);
  }

  function build(group: RequirementGroup): GroupNode {
    return {
      group,
      children: (childrenByParent.get(group.id) ?? []).map(build),
      requirements: requirementsByGroup.get(group.id) ?? [],
    };
  }

  return (childrenByParent.get(null) ?? []).map(build);
}
