---
name: gg-blender-reference-workflow
description: Create and improve 3D models in GG AI DESKTOP Blender EXT from just a description or an image. Generate coherent visual references, build original editable geometry through live Blender MCP, inspect multi-view renders against frozen references, correct mismatches autonomously, and reuse evidence from tested corrections. Use for actual Blender modeling, sculpting, reference-based asset creation, and improving this workflow. Do not use for OSINT world simulation, physics integration, or general discussion of AI model training.
---

# GG Blender reference workflow

The user supplies a description or an image. You do the visual feedback and
corrections. Do not require a reference pack, modeling instructions, manual
scores, or approval after every modeling step. Ask only when a material choice
cannot be resolved from the user's intent, or an actual tool/authority gate
requires it. This skill gives a procedure, never new action authority.

The shared journal/tool is `gg-model` in the GoldGoblins
workspace. Each call performs one finite operation, using the existing live
Blender sidecar. JSON payloads belong in an input file or stdin, never shell
interpolation of a user's description. The journal and asset files live in
private task storage outside the published source tree. Both chat motors use
the same implementation. No background worker or provider key is involved.

## Start with the intent and references

1. Briefly infer the subject, style, defining features, intended use and the
   required deliverable. Preserve an existing supplied image. If something is
   unspecified, choose a reversible default and record it; do not impose the
   style of an earlier asset. With an image alone, inspect it and write the
   brief yourself. Run `create` with `brief`, optional `image`, and a short list
   of visual/technical `criteria` suited to this asset. The response includes
   relevant previous `lessons`; inspect their before/after evidence before
   reusing a technique.
2. Use the imagegen skill and available image-generation tool to make a
   modeling reference from the description or derive missing views from the
   supplied image. The preferred model is **gpt-image-2.5-sunburst**. If the
   actual tool exposes model selection, select it. If it does not, use the
   available image tool and record the reported model as unknown; never claim
   it ran a specific model without evidence. Do not create a custom API client
   or search for keys. Exact API/CLI routing is a separate explicitly requested
   provider task.
3. Prefer one coherent turnaround sheet or images derived from the same
   canonical image: front, side, back and three-quarter, neutral background,
   consistent identity, scale and pose. Prompt for level orthographic
   front/side/back, Z-up, front towards -Y, same landmarks and visible outlines,
   no scene clutter, captions or perspective on the orthographic views.
   The three-quarter view explains volume. Include close-ups only when they
   resolve a real ambiguity. Do not assemble unrelated independent designs.
4. Inspect every reference yourself. Check whether proportions, appendages,
   clothing and asymmetries agree across views. Correct contradictory generated
   references before modeling. Hidden sides inferred from a single image are
   hypotheses: mark them `inferred`, preserve the visible design, and do not
   describe the inferred geometry as a recovered fact.
5. Freeze the accepted pack with `references`, recording `consistency_review`,
   `reported_image_model` (null if unknown), and all four `views`. Each entry
   has `path`, `source` (supplied/generated/derived), `inferred`, and optional
   `region: [u0,v0,u1,v1]` in normalized bottom-left UV coordinates. A sheet can
   be used by all views with different regions; Blender displays those regions
   natively without editing the image. References remain fixed throughout the
   correction loop. Do not redraw the target to fit a poor mesh.

## Build, observe and correct

1. Run `setup`. It creates and opens an isolated visible Blender scene and
   loads the reference boards. Keep all authored meshes, rig and associated
   objects in the returned geometry collection. Work through existing live
   Blender MCP `exec`, structured tools, or visible mouse/keyboard when useful.
   Choose the simplest technique that fits the shape: mesh construction,
   curves, modifiers, sculpting, or a combination. For curves, keep the editable
   source separately in this job scene and update a mesh copy in the geometry
   collection before capture/export. Keep backup geometry, inactive LODs and
   collision proxies separately from the visible model. Do not edit another scene's
   assets or reuse an existing game's geometry as the new model.
2. First get the silhouette and large masses right. Make a coarse blockout,
   not a finished generic primitive assembly. Use the references to measure
   height/width/depth ratios and landmarks. Keep topology/editability suitable
   for later local corrections; join/remesh deliberately, not reflexively.
3. Run `capture` with `job` and a concrete `changes` description. It measures
   the source meshes, saves an isolated `.blend` checkpoint, and renders clay,
   black silhouettes and actual EEVEE material previews from four fixed views.
   The first camera framing is reused in later rounds. Read the returned full
   mesh-report JSON and open **every captured PNG** with the image viewer; use
   live eyes when viewport, tool state, motion or an occlusion needs inspection.
   Wireframe is optional: unsupported wire rendering does not prove bad topology.
4. Critique from the user's brief, frozen references and current images, not
   from the construction script's intended result. For every view, compare
   silhouette, proportions, defining features and the task's other criteria.
   Include side/back depth and how features join the body. Identify the largest
   visible mismatch and the exact local edit that can address it. Clay exposes
   geometry; silhouette exposes outline; material preview exposes surface and
   color. Texture/shadow cannot substitute for missing geometry. Distinguish
   an unobserved property from a failed property.
5. Run `review`. Supply all captured image keys in `viewed`, per-view
   `comparisons` for every criterion, `technical_review`, `issues` with view,
   severity, observation and specific change, and `verdict: REPAIR` or `PASS`.
   These are your evidenced judgments, not externally certified scores. Do not
   pass because the tool returned successfully, there are many polygons, or a
   single flattering angle looks good. Open boundaries can be intentional;
   document the reason instead of filling every opening or destroying edge flow.
6. On REPAIR, fix the largest errors first, capture again, and compare with
   both the frozen references and previous images. Do not repeat the same
   ineffective edit. Use a different technique when it stalls. Default is six
   captured rounds, bounded to twelve; an unchanged repeated model or exhausted
   budget stops the loop. Retain reviewed checkpoints and report remaining
   mismatches honestly. If an edit happened after capture, recapture with
   `discard_unreviewed: true`; do not review stale images as the new mesh.

If Blender restarted, append the latest verified job checkpoint scene with
`bpy.data.libraries.load` and activate that scene before continuing. Preserve
the already open scene. If there is no checkpoint, reconstruct the blockout
from the frozen pack. Recapture after recovery rather than accepting old
images as a view of the restored state.

## Finish and learn from the result

When the form matches, complete materials, UVs, shading and any requested rig,
animation, LOD or collision work. Recapture and review those actual changes.
For rigged assets, inspect representative deformation poses and playback;
a fitted skeleton or rest-pose picture alone is not a successful animation test.
Use live eyes and measurements for motion. If engine use is requested, check
the exported file with the existing engine import tools and inspect its real
render/playback in a temporary test context. Do not install or replace game
assets merely to test authoring.

After PASS, run `export`, which saves only the job scene and exports only its
geometry/rig collection to `.blend` and `.glb`. Reopen or inspect the exported
files and record actual `delivery_checks` with `finish`. A final export is
invalid if the model changed after the reviewed capture.

Save useful corrections in `finish.lessons`: `before` and `after` capture
numbers, `trigger`, `technique`, `limits`, and optionally the tested `variant`.
A lesson requires a diagnosed before result, a changed mesh, and a passed
after result. It is an observed technique on one task, not proof of universal
skill. On a future, genuinely different reference, try it and save the outcome
again. Repeated evidence is labeled separately. A failed attempt remains in
its job journal; do not promote a failure to a successful recipe. Synthetic
plumbing tests are not artistic training examples. This improves the stored
workflow, examples and methods; it does not alter the base model's weights.

Deliver the asset files and a short account of what actually passed and what
remains uncertain. Do the technical work yourself; the user should not have
to handle journal IDs, hashes or review forms.

## Operator examples

From the GoldGoblins workspace:

```bash
python3 gg-model create --input /path/to/brief.json
python3 gg-model references --input /path/to/references.json
python3 gg-model setup --input /path/to/job.json
python3 gg-model capture --input /path/to/capture.json
python3 gg-model review --input /path/to/review.json
python3 gg-model export --input /path/to/job.json
python3 gg-model finish --input /path/to/finish.json
```

`job.json` for an operator call is simply `{"job":"the returned job name"}`;
keep it distinct from the runtime's own journal file. A review payload looks
like this with all four views and **all actual image keys** filled in:

```json
{
  "job": "the returned job name",
  "viewed": ["clay/front", "clay/side", "clay/back", "clay/three_quarter",
    "silhouette/front", "silhouette/side", "silhouette/back", "silhouette/three_quarter",
    "appearance/front", "appearance/side", "appearance/back", "appearance/three_quarter"],
  "comparisons": {
    "front": {"silhouette": "Observed comparison to frozen front reference"},
    "side": {"silhouette": "Observed comparison to frozen side reference"},
    "back": {"silhouette": "Observed comparison to frozen back reference"},
    "three_quarter": {"silhouette": "Observed comparison to frozen volume reference"}
  },
  "technical_review": "Actual measured results and what still needs testing",
  "issues": [{"view":"side","severity":"major","observation":"Observed depth mismatch",
    "change":"Specific edit of the affected mesh region"}],
  "verdict": "REPAIR"
}
```
