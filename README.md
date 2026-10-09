# spatia-flood (archived; moved into spatia-data)

On 2026-10-09 the owner moved the flood work into
[spatia-data](https://github.com/ztzhou1224/spatia-data). Everything this repo held is there under
**`flood/`**: docs, research, review, tests, the viewer and `pipeline/`, which produces the
`fl_building_first_floor` artefact. It was taken from the newest branch, `claude/zen-wright-m851wi`
(commit c97b20b, Pinellas r1); `main` and `claude/rules-in-force` are both its ancestors.

- User-facing flood layers: `fl_building_first_floor` and its footprint, `fema_flood_zones`,
  `fema_flood_zones_h3` and `fema_flood_zone_prevalence`. `fema_bfe_context`, `fema_bfe_context_h3` and
  `fema_firm_panels` are published with `role: dependent` (spatia-data contract 2.30).
- The `_flood/` artefact prefix in the bucket is unchanged.

This repo's history, up to the move, is in its git log.
