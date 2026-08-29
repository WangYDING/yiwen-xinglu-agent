# Cross-session Memory Evaluation

## Why a separate protocol was required

The task benchmark isolates every episode with a fresh state directory, SQLite repository, player, and episode ID. It also excludes current-session retrieval. Consequently E6 observed zero Memory candidates, selected items, declared use, and accepted use. That design is correct for task reliability but cannot test cross-session Memory exposure.

## Frozen cross-session protocol

E9/E10 use the same player and Memory repository across a Session-A write and a new Session-B Agent decision while keeping episode IDs distinct. Three controls bound the interpretation:

- **Positive transfer:** persist a relevant public committed event, index it, then query from Session B.
- **Irrelevant negative:** persist an unrelated public event and observe false-positive exposure/use.
- **Empty history:** start Session B without prior Memory and require zero exposure.

The harness records expected, candidate, selected, Agent-input, declared, and runtime-accepted IDs separately, plus repository/session/player isolation and Authority/provider status.

## Results

| Evidence level | Result | Interpretation |
|---|---|---|
| Persisted | PROVEN | Session-A public committed evidence reached the production repository |
| Indexed | PROVEN | The record was available to semantic retrieval |
| Retrieved | PROVEN | Session B produced the expected relevant candidate |
| Selected | PROVEN | Projection selected it for Agent context |
| Agent-input exposure | PROVEN | The selected Memory entered real `GameNPCAgentInput` |
| Declared used | NOT OBSERVED | The real Agent declared no expected Memory ID |
| Runtime accepted used | NOT OBSERVED | With no declaration, accepted IDs remained empty |
| Behavioral benefit | NOT PROVEN | The pilot was not a powered outcome comparison |

The irrelevant negative produced one false-positive candidate/selection, but the Agent did not declare it and runtime did not accept its use. The empty-history control produced zero candidates and zero exposure. Thus the defensible result is **real-Agent cross-session exposure proven**, not “Memory improved success.”

