# Labelling

Two separate jobs live here.

- **live_v1 (blind).** `live_v1_sheet.csv` is the labelling sheet for the live benchmark: one row per real pipeline run, with the question, the ranked retrieved chunks and the answer. Read the cases in `live_v1_sheet.html`, pick gold chunks from `live_v1_corpus_chunks.csv`, and follow [docs/labelling-guide.md](../../docs/labelling-guide.md). The sheet does not show how a run was produced or what Retrace predicted; please keep it that way until labelling is done. When you are done, the guide's last section has the merge and report commands.
- **Judge label review.** Below.

## Judge label review

`judge_labels_v1_review.csv` holds every label in `backend/datasets/judges/judge_labels_v1.jsonl`, one row per label. The labels were drafted by an AI agent and no human has checked them yet. Nothing downstream (Phase 2 threshold work in particular) uses them until this review is done.

### How to review

Open the CSV in a spreadsheet app. For each row, read `what_to_judge` and `input`, then look at `current_label`.

- If the current label is right, leave `correction` empty.
- If it is wrong, write the right value in `correction`: `true` or `false`, or a range such as `0.5-0.5` for faithfulness bands.
- Use `notes` for anything the sheet cannot express, such as a claim that should be split in two or a chunk that is ambiguous. Notes are printed when the sheet is applied and handled by hand.

A faithfulness band should contain the share of supported claims. If you flip a claim, check that example's band row too; `apply` warns when they disagree.

| Row type | Count | Question |
| --- | ---: | --- |
| `chunk` | 51 | Is this chunk relevant to the question? |
| `context_sufficient` | 24 | Do the chunks together contain enough to answer? |
| `claim` | 56 | Is this claim supported by the context? |
| `faithfulness_band` | 24 | Acceptable faithfulness score range |
| `contradicts` | 18 | Does the answer contradict the context? |

### Applying the review

```bash
python scripts/judge_labels_review.py apply --dry-run   # preview what will change
python scripts/judge_labels_review.py apply             # write it
```

`apply` updates the labels, sets every example's annotator to `ai_draft_author_reviewed`, records the review date and the number of changed labels in the manifest, and recomputes the dataset hash. It refuses a sheet whose rows no longer match the dataset. After that, the docs wording changes from "AI-drafted, not yet reviewed" to "AI-drafted, reviewed and corrected by the author" with the change count.
