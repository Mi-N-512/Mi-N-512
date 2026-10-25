"""Render only sanitized data into GitHub-compatible SVG and Markdown."""
import html
import textwrap
from pathlib import Path

INK, GREEN, MUTED = '#181818', '#226b42', '#626262'


def esc(value):
    return html.escape(str(value), quote=True)


def text(x, y, value, size=18, color=INK, mono=False):
    family = 'monospace' if mono else 'Arial, Helvetica, sans-serif'
    return f'<text x="{x:.2f}" y="{y:.2f}" fill="{color}" font-family="{family}" font-size="{size}">{esc(value)}</text>'


def rect(x, y, w, h, color):
    return f'<rect x="{x:.2f}" y="{y:.2f}" width="{max(0,w):.2f}" height="{max(0,h):.2f}" fill="{color}"/>'


def svg(title, body, height, width=904):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{esc(title)}" '
            f'viewBox="0 0 {width} {height}"><title>{esc(title)}</title>'
            + rect(0, 0, width, height, '#ffffff') + body + '</svg>\n')


def treemap(items, x=0, y=0, width=904, height=904 / 1.618):
    """Split at balanced cumulative weights along the longer dimension."""
    if not items:
        return []
    if len(items) == 1:
        return [(items[0], x, y, width, height)]
    total = sum(v for _, v in items)
    split = min(range(1, len(items)), key=lambda i: abs(sum(v for _, v in items[:i]) / total - .5))
    ratio = sum(v for _, v in items[:split]) / total
    if width >= height:
        return treemap(items[:split], x, y, width * ratio, height) + treemap(items[split:], x + width * ratio, y, width * (1-ratio), height)
    return treemap(items[:split], x, y, width, height * ratio) + treemap(items[split:], x, y + height * ratio, width, height * (1-ratio))


def language_svg(languages):
    items = sorted(((k, v) for k, v in languages.items() if v > 0), key=lambda p: (-p[1], p[0]))
    if not items:
        return svg('Languages: no source lines counted yet', text(30, 60, 'No source lines counted yet.', 24, MUTED), 110)
    total = sum(v for _, v in items)
    # Fold tiny blocks into a readable remainder; the equal-size table contains every language.
    shown = [p for p in items[:6] if p[1] / total >= .05]
    if not shown:
        shown = items[:1]
    remainder = total - sum(v for _, v in shown)
    if remainder:
        shown.append(('Other languages', remainder))
    colors = [INK, '#dceade', '#eff4ef', '#c8dbcc', '#e5e5df', '#f1f1ee', '#d3dfd5']
    body = ''
    for i, ((name, count), x, y, w, h) in enumerate(treemap(shown)):
        body += rect(x+3, y+3, w-6, h-6, colors[i % len(colors)])
        color = '#ffffff' if i == 0 else INK
        if w < 100 or h < 95:
            body += f'<g><title>{esc(name)}: {count:,} lines</title>' + text(x+8, y+h/2, '…', 14, color) + '</g>'
            continue
        size = min(38, max(12, (w-30) / max(len(name)*.61, 1)), max(12, h/5))
        body += text(x+16, y+30+size/2, name, round(size), color)
        body += text(x+16, y+h-44, f'{count/total:.1%}', 20, '#a9d7b5' if i == 0 else GREEN)
        body += text(x+16, y+h-20, f'{count:,} lines', 11, color, True)
    return svg('Languages sized by source lines; exact values in the expandable table', body, 904/1.618)


def safe_projects(repositories):
    """Discard all private metadata before constructing any public artifact."""
    result = []
    for repo in sorted(repositories, key=lambda r: r.get('pushed_at') or '', reverse=True)[:3]:
        if repo.get('private'):
            result.append({'private': True})
        else:
            result.append({'private': False, 'name': repo['name'], 'url': repo['html_url'], 'description': repo.get('description') or 'View the code and project notes on GitHub.'})
    return result


def project_svg(project, index):
    body = rect(0, 0, 904, 160, '#f7f8f5') + rect(0, 0, 3, 160, GREEN)
    body += text(24, 30, f'{index:02} / ' + ('PRIVATE' if project['private'] else 'PUBLIC'), 11, GREEN, True)
    if project['private']:
        # Geometric redaction. No hidden text, filters or recoverable name.
        body += rect(24, 47, 240, 25, INK)
        for offset in range(0, 240, 12):
            body += rect(24+offset, 49, 2, 21, '#535b54')
        body += text(24, 104, 'Details withheld. Work in progress.', 15, MUTED)
        body += text(24, 137, '[ ACCESS RESTRICTED ]', 12, GREEN, True)
    else:
        name = textwrap.shorten(project['name'], width=65, placeholder='…')
        body += text(24, 65, name, min(24, 810/max(len(name)*.58, 1)))
        description = textwrap.shorten(project['description'], width=105, placeholder='…')
        body += text(24, 104, description, 14, MUTED)
        body += text(24, 137, 'Open repository ↗', 12, GREEN, True)
    return svg('Private project, name withheld' if project['private'] else project['name'], body, 160)


def render(config, data, output):
    output = Path(output)
    assets = output / 'assets'
    assets.mkdir(parents=True, exist_ok=True)
    body = text(0, 22, 'M / N', 12, GREEN, True) + text(0, 100, config['name'], 64)
    body += text(0, 150, config['tagline'], 25) + text(0, 190, config['intro'], 18, MUTED)
    (assets/'header.svg').write_text(svg(config['name'], body, 225), encoding='utf-8')
    (assets/'languages.svg').write_text(language_svg(data['languages']), encoding='utf-8')
    projects = safe_projects(data['repositories'])
    project_md = []
    for i, project in enumerate(projects, 1):
        (assets/f'project-{i}.svg').write_text(project_svg(project, i), encoding='utf-8')
        if project['private']:
            project_md.append(f'![Private project. Name withheld.](assets/project-{i}.svg)')
        else:
            project_md.append(f'[![Public project {i}](assets/project-{i}.svg)]({project["url"]})')
    for i in range(len(projects)+1, 4):
        (assets/f'project-{i}.svg').unlink(missing_ok=True)
    days = data['activity']
    maximum = max((d['count'] for d in days), default=0)
    wave = ''
    for i, day in enumerate(days):
        height = 4 + (day['count']/maximum*76 if maximum else 0)
        wave += rect(i*32+6, 48-height/2, 18, height, GREEN if day['count'] else '#dce5dd')
    wave += text(0, 126, 'Public commits · Past 28 days' if maximum else 'No public commits in the past 28 days.', 15, MUTED)
    (assets/'activity.svg').write_text(svg('Daily public commits; values in the expandable table', wave, 150), encoding='utf-8')
    total = sum(data['languages'].values())
    language_rows = '\n'.join(f'| {esc(k)} | {v:,} | {v/total:.1%} |' for k,v in sorted(data['languages'].items(), key=lambda p:(-p[1],p[0])))
    activity_rows = '\n'.join(f'| {d["date"]} | {d["count"]} |' for d in days)
    readme = f'''![{esc(config['name'])}](assets/header.svg)

### About me

{config['about']}

{config['note']}

### What I build with

![Languages sized by source lines](assets/languages.svg)

<details>
<summary>View all languages at equal size</summary>

| Language | Source lines | Share |
| :--- | ---: | ---: |
{language_rows or '| No source lines counted yet | 0 | — |'}

Source lines exclude blank lines and comments. Counts describe repository contents, not individual authorship. Generated and dependency directories are excluded. {data['coverage']}

</details>

### Latest work. Partial clearance.

The three most recently pushed projects.

{chr(10).join(project_md) or 'No eligible projects yet.'}

### My coding activity

![Public coding activity](assets/activity.svg)

<details>
<summary>View the daily breakdown</summary>

| Date (UTC) | Public commits |
| :--- | ---: |
{activity_rows}

Commits attributed to this GitHub account on the default branches of included public repositories.

</details>

<sub>Last updated: {data['updated']} · [@{config['username']}](https://github.com/{config['username']})</sub>
'''
    (output/'README.md').write_text(readme, encoding='utf-8')
