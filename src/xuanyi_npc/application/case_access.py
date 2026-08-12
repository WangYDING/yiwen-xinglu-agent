"""Generic permission-filtered case catalog overlays for R5."""

from dataclasses import dataclass

from xuanyi_npc.domain.case_access import CaseAccessPolicy
from xuanyi_npc.domain.cases import CaseDefinition, InvestigationDefinition
from xuanyi_npc.domain.permissions import PermissionLevel
from xuanyi_npc.resources.runtime import read_runtime_text


@dataclass(frozen=True)
class PermissionFilteredCaseCatalog:
    base_catalog: object
    granted_permissions: frozenset[PermissionLevel]

    def __post_init__(self) -> None:
        policy = CaseAccessPolicy.model_validate_json(
            read_runtime_text("clinic/case_access_policy_v1.json")
        )
        object.__setattr__(self, "policy", policy)

    def get(self, case_id: str) -> CaseDefinition | None:
        case = self.base_catalog.get(case_id)
        if case is None:
            return None
        additions = tuple(
            item for item in self.policy.permission_investigations
            if item.case_id == case_id and item.required_permission in self.granted_permissions
        )
        if not additions:
            return case
        investigations = (*case.investigations, *(
            InvestigationDefinition(
                investigation_id=item.investigation_id,
                action_type=item.action_type,
                target_id=item.target_id,
                public_description=item.public_description,
                reveals_clue_ids=item.reveals_clue_ids,
                required_skill_id=item.required_skill_id,
                minimum_skill_level=item.minimum_skill_level,
                required_clue_ids=item.required_clue_ids,
            ) for item in additions
        ))
        requirements = list(case.normalized_investigation_requirements())
        for addition in additions:
            index = next((index for index, item in enumerate(requirements) if item.requirement_id == addition.satisfies_requirement_id), None)
            if index is None:
                raise ValueError("permission investigation references unknown requirement")
            requirement = requirements[index]
            requirements[index] = requirement.model_copy(update={
                "satisfying_investigation_ids": requirement.satisfying_investigation_ids | {addition.investigation_id}
            })
        return case.model_copy(update={"investigations": investigations, "investigation_requirements": tuple(requirements)})

    def case_ids(self) -> tuple[str, ...]:
        return self.base_catalog.case_ids()
