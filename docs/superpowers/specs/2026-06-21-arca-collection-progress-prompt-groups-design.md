# Arca Collection Progress and Prompt Grouping Design

## Goal

Make long Arca Live collection runs observable, extract NovelAI prompts into meaningful sections, and group images from the same post by shared style tags. Deleting a collected post must make its source date eligible for collection again.

## Current problems

- Collection is handled by one synchronous request. Run counters are written only when an interval finishes, so the UI cannot show live progress or a useful ETA.
- Generic PNG text such as PDF or drawing-tool metadata can be treated as NovelAI metadata.
- Per-image data exposes only one prompt and one negative prompt even when NovelAI V4 metadata contains base, negative, and character captions.
- A post with several styles appears as one undifferentiated image list.
- Completed date coverage remains valid after an item is deleted, preventing that item from being discovered again.

## Collection job model

Starting a collection creates a persisted job and returns its ID immediately. The collector updates the job after each search page, post, and image. The UI polls a job-status endpoint while leaving the archive list usable.

The status response contains the lifecycle state (`queued`, `running`, `completed`, `failed`, or `interrupted`), current stage, processed and expected page/post counts, downloaded image count, saved and updated item counts, elapsed seconds, and estimated remaining seconds. The post total is allowed to be unknown until discovery finishes. ETA is shown as `계산 중` until enough completed post samples exist, then uses a rolling average of recent post durations.

On application startup, jobs left in `queued` or `running` are marked `interrupted`. Interrupted and failed jobs do not contribute completed search coverage and may be retried. Job errors retain a concise user-facing message while full exceptions remain in server logs.

## Image and NovelAI metadata validation

Downloaded candidates count as archive images only when they are linked from post content and pass image response, byte-size, and path-safety checks. Decorative page assets and unrelated linked files are ignored.

PNG text is considered NovelAI generation metadata only when it contains a recognized NovelAI parameter structure or a valid NovelAI software marker plus generation fields. Arbitrary `prompt` text from tools such as PDF or illustration software is not accepted as generation metadata.

For each valid image, extraction preserves these independent fields:

- base prompt;
- negative prompt;
- zero or more character prompts, including character position when present;
- original prompt text and raw metadata for inspection;
- existing generation parameters such as seed, sampler, steps, scale, model, and dimensions.

Legacy metadata without character captions produces an empty character-prompt list rather than inventing one. Body-text fallback remains visibly marked and is not mixed into image similarity calculations.

## Prompt normalization and style grouping

Grouping runs within one source post; images from different posts are never merged. Prompt text is tokenized on top-level commas while respecting NovelAI emphasis syntax. Comparison normalizes whitespace and equivalent weight formatting but preserves the original display text.

Character prompts and negative prompts are excluded from style similarity. The remaining base tags form a comparison set. Tags known to describe subjects, poses, expressions, framing, and transient image content receive lower weight; repeated artist, medium, rendering, color, line, and aesthetic tags receive higher weight.

Images are connected when their weighted base-tag similarity passes the configured internal threshold. Connected components become style groups. A singleton is shown as an individual image. This approach intentionally tolerates small prompt differences while avoiding a permanent, manually synchronized group table.

For each group the server returns:

- representative image and image count;
- common base tags shared across the group;
- base tags unique to each image;
- common and per-image negative tags;
- character prompts per image;
- original prompts for exact inspection and copying.

Groups are calculated when item details are requested. Edited prompts invalidate no stored group state because grouping has no persisted cache.

## Coverage invalidation after deletion

A run-to-item association records which completed search keys discovered each item. Before deleting an item, the service records a recollection invalidation for the item's posted date and every associated normalized search key.

Coverage calculation subtracts invalidated dates from completed intervals. A later request for an overlapping range searches that date again, while dates that remain covered are skipped. A successful recollection clears the matching invalidation. Existing posts and images are upserted, so reopening one date does not duplicate neighboring records.

Deletion itself performs no external request. If an item lacks a valid posted date or run association, deletion succeeds but reports that automatic coverage invalidation was unavailable.

## User interface

The collection panel shows a state badge, progress bar, current stage, page/post/image counters, elapsed time, ETA, and the final saved/updated summary. Unknown totals use an indeterminate progress state. Collection controls prevent duplicate starts, while list browsing, detail viewing, and refresh remain available.

Each post card summarizes its number of style groups and images. The detail dialog presents one section per style group and a separate section for singleton images. A group shows its representative image, member thumbnails, common tags, and per-image differences.

Prompt content uses three tabs: `베이스`, `네거티브`, and `캐릭터`. Common tags are visually emphasized, differing tags are separated by image, and original prompt text is available in a collapsed area with copy actions. All source-derived text is assigned through safe DOM text APIs.

After deletion, the UI confirms that the item was removed and its date will be searched again on the next overlapping collection request.

## API and persistence changes

- The collect endpoint creates a job and returns an accepted response with the job ID.
- A job-status endpoint returns incremental counters, timing, and lifecycle state.
- Item detail responses add structured prompt fields and computed style groups while preserving existing fields during migration.
- The schema adds persisted job progress, run-to-item associations, and coverage invalidations.
- Deletion records invalidations transactionally with database deletion; orphan file cleanup remains best effort after commit.

The implementation may run jobs in the existing application process. It does not add a distributed queue or new service dependency.

## Testing and verification

Automated tests cover:

- incremental job counters, lifecycle transitions, interruption recovery, and ETA readiness;
- rejection of generic PNG text and acceptance of valid NovelAI legacy and V4 metadata;
- base, negative, and character prompt extraction;
- weighted similarity grouping, singleton handling, and common/different tag calculation;
- grouping isolation between posts;
- deletion invalidation, coverage subtraction, successful recollection, and duplicate-safe upserts;
- API compatibility and safe frontend rendering;
- progress polling and the grouped prompt UI behavior.

Full Python and JavaScript suites, syntax checks, whitespace checks, and browser verification cover collection start, live progress, completion, grouped detail display, deletion, and subsequent recollection eligibility.
