"""Contextual validation for the independent R2 MentorAction boundary."""

from xuanyi_npc.domain.mentor import MentorAction, MentorActionType, MentorInteractionPhase


PHASE_ACTIONS = {
    MentorInteractionPhase.LESSON_START: frozenset({MentorActionType.SPEAK}),
    MentorInteractionPhase.INVESTIGATION: frozenset(
        {MentorActionType.SPEAK, MentorActionType.ASK_REFLECTION, MentorActionType.GIVE_HINT}
    ),
    MentorInteractionPhase.CASE_COMPLETE: frozenset(
        {MentorActionType.REVIEW_PERFORMANCE, MentorActionType.RECOMMEND_FIXED_NEXT_STEP}
    ),
}


class MentorActionContractError(ValueError):
    pass


def validate_mentor_action(agent_input: object, action: MentorAction) -> None:
    """Validate public identifiers and phase without applying any state."""

    phase = agent_input.interaction_phase
    if action.action_type not in PHASE_ACTIONS[phase]:
        raise MentorActionContractError("mentor action is not allowed in this phase")
    if action.action_type not in agent_input.allowed_mentor_actions:
        raise MentorActionContractError("mentor action is outside the supplied allowance")
    hint_ids = {item.hint_id for item in agent_input.allowed_hint_cards}
    if action.hint_id is not None and action.hint_id not in hint_ids:
        raise MentorActionContractError("hint_id is not currently allowed")
    evidence_ids = {
        item.clue_id for item in agent_input.public_case_view.discovered_clues
    } if agent_input.public_case_view is not None else set()
    if agent_input.assessment_public_view is not None:
        evidence_ids.update(agent_input.assessment_public_view.public_evidence_references)
    if not set(action.referenced_public_evidence_ids).issubset(evidence_ids):
        raise MentorActionContractError("mentor referenced undiscovered evidence")
    ability_ids = {
        item.ability_id for item in agent_input.apprenticeship_public_view.abilities
    }
    if not set(action.referenced_ability_ids).issubset(ability_ids):
        raise MentorActionContractError("mentor referenced an unknown ability")
    allowed_relationships = set()
    if agent_input.assessment_public_view is not None:
        allowed_relationships = {
            item.dimension for item in agent_input.assessment_public_view.relationship_changes
        }
    if not set(action.referenced_relationship_dimensions).issubset(allowed_relationships):
        raise MentorActionContractError("mentor referenced an unsupported relationship change")
