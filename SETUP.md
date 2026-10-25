# Profile maintenance

Edit `profile.json` to change the introduction, repository exclusions or counting scope.

The daily workflow runs around 06:17 Africa/Johannesburg (04:17 UTC). GitHub schedules may be delayed. You can also run **Refresh profile** manually from Actions. Changes to the generator or configuration trigger a refresh on the main branch. Changes in other repositories appear after the next refresh.

## Private repositories

Add an Actions repository secret named `PROFILE_READ_TOKEN`. Use a fine-grained personal access token owned by Mi-N-512, with Contents read-only access to the repositories you want included. Metadata read access is automatic. Selecting all repositories also includes future repositories; selecting specific repositories limits coverage. Rotate the secret before its expiry date.

Without this secret, updates include public repositories only. The workflow's built-in GitHub token publishes the results; the read token is never used to push.

Private names, URLs, descriptions, source files and commit messages are never published. Only aggregate language totals and fixed redacted project cards are rendered. Private source is downloaded into temporary directories for counting and then deleted. Failed collection aborts the refresh and preserves the last published profile. Error output is deliberately generic to avoid exposing repository identifiers in public Actions logs.

## Language chart

The chart has a 1.618:1 outer rectangle. Nested block areas follow source-line counts, rather than fixed Fibonacci sizes. Small categories are combined into an Other languages block; the expandable table includes every language at the same text size.

cloc 2.10 counts nonblank, noncomment source lines on default branches. The updater excludes configured dependency, generated and build directories, minified files, lockfiles, embedded archives and files larger than 5 MiB. These are practical exclusions, not a guarantee that every generated file is detected. Mark additional directories in `exclude_directories` if needed. Counts describe repository contents, not personal authorship. Identical files within one repository may be deduplicated by cloc; copies across repositories are counted separately.

Repositories whose downloaded archive exceeds 100 MiB or whose expanded contents exceed 500 MiB are excluded from line counts. The expandable language section reports how many were excluded. Their project cards can still appear. Symbolic links are ignored. Smaller tiles may show an ellipsis; the complete language table remains available underneath.

The language chart excludes configuration and project metadata such as Properties, Visual Studio Solution, MSBuild, Gradle, Ant, Maven and TOML, as well as cloc's C# Generated category. `exclude_languages` contains the complete list.

Owned, nonarchived, nonfork repositories are included. The profile repository itself is excluded. The three latest projects are ranked by `pushed_at`. The activity chart counts commits attributed to this GitHub account on the default branches of included public repositories over 28 UTC days; it will differ from GitHub's contribution calendar.

## Local checks

Requires Python 3.12+ and cloc 2.10. Run `python -m unittest discover -s tests -v`.

Set `PROFILE_READ_TOKEN` in the environment for private access, or `GH_TOKEN` for authenticated public access, then run `python scripts/update_profile.py`. Never put tokens in files or commit them. Optionally set `CLOC` to the line counter's path, and `CLOC_PERL` to a Perl executable when using the Perl script on Windows.

The renderer produces SVGs supported as GitHub README images. It uses system font fallbacks, so typography varies slightly from the Figma concept. Native details elements provide the expandable views. GitHub controls the surrounding page theme; generated images retain white backgrounds with green accents.

GitHub may disable scheduled workflows in public repositories after prolonged inactivity. Re-enable the workflow in Actions if necessary. Check Actions for failed runs or an expired read token if the displayed update time becomes stale.
