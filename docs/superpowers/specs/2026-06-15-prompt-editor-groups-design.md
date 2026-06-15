# Prompt Editor And Groups Design

## Goal

Make the style-generation workspace wider and replace the narrow raw prompt fields with a Canvas-inspired prompt editor. Users can edit comma-separated prompt tokens, drag tokens into named groups, and turn each group on or off before generation.

## Workspace Layout

- Widen the style-maker generation pane so prompt and generation controls do not require horizontal scrolling at the normal desktop viewport.
- Keep the weight graph/settings on the left, generated image in the center, and prompt/generation work on the right.
- Give the right pane enough width for a two-column prompt area where practical, while retaining a single-column responsive layout on smaller windows.
- Keep the existing full-window, non-page-scrolling behavior. Only pane-local content may scroll vertically.

## Prompt Editors

- Base, negative, and each character prompt use a token surface inspired by the inpainting NovelAI modal in `NAI_Image_Manager_1.0/static/canvas.*`.
- Base and negative prompts share one full-width editor area with tabs above it. The base tab is selected initially, and switching tabs changes only which editor is visible.
- Tab switching never changes prompt text, token groups, or saved state.
- Commas delimit tokens. Existing NovelAI grouping and weight syntax inside a token is preserved as text.
- Each surface provides a compact text input for adding or editing prompt text and renders parsed tokens as draggable chips.
- Token order remains stable unless the user explicitly reorders it.
- Character prompts retain add and delete controls and each character prompt owns its own token surface.

## Named Control Groups

- A group has an ID, user-editable name, enabled state, expanded state, and a list of token references.
- Tokens from base, negative, or character prompts can be dragged into a group's drop area.
- A token remains in its original prompt. Grouping adds a reference used to control inclusion; it does not move or duplicate prompt text.
- Turning a group off excludes all referenced tokens from the generation request and visually dims those chips.
- Turning a group on includes those tokens again in their original positions.
- Groups support rename, expand/collapse, ON/OFF, removing individual references, and deletion.
- The same token cannot be added to the same group twice. A token may belong to multiple groups; if any containing group is off, it is excluded.
- When prompt text changes, stale references that no longer match a token are removed during normalization.

## Persistence And Compatibility

- Continue using the single `naiArtistRater.prompts.v1` localStorage key. Saving overwrites one JSON snapshot; it does not append history.
- Extend that snapshot with prompt groups and stable character-prompt IDs.
- Existing snapshots containing only `base_prompt`, `negative_prompt`, and `character_prompts` load without data loss and receive empty groups.
- Prompt text and group state save after edits, drag/drop, rename, toggle, removal, or deletion.
- Stored groups affect generation only in the browser. Generated image records continue storing the final effective base, negative, and character prompts sent to NovelAI.

## Generation Data Flow

1. Read each token surface in visible order.
2. Collect tokens referenced by disabled groups.
3. Filter disabled tokens without changing the order of remaining tokens.
4. Join tokens with comma-space separators.
5. Send the effective base, negative, and character prompts through the existing generation request path.

## Error Handling

- Empty tokens are ignored.
- Malformed stored JSON falls back to empty prompts and one empty character prompt.
- Drag payloads with unknown fields, character IDs, or token IDs are ignored without breaking the editor.
- Deleting a character prompt removes group references belonging to it.

## Verification

- Unit tests cover parsing/joining, disabled-group filtering, duplicate prevention, stale-reference cleanup, and legacy localStorage migration.
- Frontend contract tests cover required prompt surfaces and group controls.
- Browser verification checks the desktop layout for no horizontal pane scroll, drag/drop behavior, group ON/OFF filtering, persistence after reload, and responsive fallback.
