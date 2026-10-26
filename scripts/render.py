"""Render only sanitized data into GitHub-compatible SVG and Markdown.

Each README section is one full-width SVG. Light and dark sets are written to
assets/ and assets/dark/; the README swaps them with <picture> so the image
background always matches GitHub's page and the sections read as one page.
"""
import base64
import html
import json
import textwrap
from pathlib import Path

W, PAD = 904, 40
CW = W - 2 * PAD
FONTS = Path(__file__).resolve().parents[1] / 'fonts'
METRICS = json.loads((FONTS / 'metrics.json').read_text(encoding='utf-8'))

LIGHT = {
    'bg': '#ffffff', 'ink': '#181818', 'muted': '#626262', 'faint': '#8a8f8a', 'green': '#226b42',
    'card': '#f7f8f5', 'rule': '#e3e5e0', 'redact': '#181818', 'redact_line': '#535b54', 'empty': '#dce5dd',
    'tiles': ['#181818', '#dceade', '#eff4ef', '#c8dbcc', '#e5e5df', '#f1f1ee', '#d3dfd5'],
    'first_text': '#ffffff', 'first_pct': '#a9d7b5',
}
DARK = {
    'bg': '#0d1117', 'ink': '#e6edf3', 'muted': '#9198a1', 'faint': '#6e7681', 'green': '#6cc488',
    'card': '#151b23', 'rule': '#262c36', 'redact': '#c9d1d9', 'redact_line': '#6e7681', 'empty': '#262c36',
    'tiles': ['#e6edf3', '#1d3326', '#161f19', '#24402e', '#22272e', '#1a1f25', '#2a3a2f'],
    'first_text': '#0d1117', 'first_pct': '#226b42',
}
# Class -> (metrics key, font family, weight)
FACES = {
    'g4': ('SpaceGrotesk-400', 'SG', 400), 'g5': ('SpaceGrotesk-500', 'SG', 500),
    'g7': ('SpaceGrotesk-700', 'SG', 700), 'm': ('SpaceMono-400', 'SM', 400),
}
FALLBACK = {'SG': "'Space Grotesk', Arial, Helvetica, sans-serif", 'SM': "'Space Mono', ui-monospace, Menlo, Consolas, monospace"}


def esc(value):
    return html.escape(str(value), quote=True)


def measure(value, size, face='g4'):
    widths = METRICS[FACES[face][0]]
    return sum(widths.get(ch, 0.6) for ch in str(value)) * size


def wrap(value, size, face, width):
    lines, line = [], ''
    for word in str(value).split():
        trial = f'{line} {word}'.strip()
        if line and measure(trial, size, face) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    return lines + ([line] if line else [])


def fit(value, size, face, width):
    """Shorten one line with an ellipsis so it never overflows its box."""
    value = str(value)
    while value and measure(value, size, face) > width:
        value = value[:-2].rstrip() + '…'
        if value == '…':
            break
    return value


class Canvas:
    """Collects SVG parts and the font faces they use, so only those get embedded."""

    def __init__(self, theme):
        self.theme, self.parts, self.faces = theme, [], set()

    def text(self, x, y, value, size=18, color='ink', face='g4', anchor='start'):
        self.faces.add(face)
        fill = self.theme.get(color, color)
        end = ' text-anchor="end"' if anchor == 'end' else ''
        self.parts.append(f'<text x="{x:.2f}" y="{y:.2f}" class="{face}" font-size="{size}" fill="{fill}"{end}>{esc(value)}</text>')

    def rect(self, x, y, w, h, color):
        fill = self.theme.get(color, color)
        self.parts.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{max(0, w):.2f}" height="{max(0, h):.2f}" fill="{fill}"/>')

    def rule(self, y=0):
        self.rect(PAD, y, CW, 1, 'rule')

    def label(self, y, value):
        self.text(PAD, y, value, 13, 'muted', 'm')

    def heading(self, y, value):
        self.text(PAD, y, value, 30, 'ink', 'g7')

    def svg(self, title, height):
        css = ''
        families = set()
        for face in sorted(self.faces):
            key, family, weight = FACES[face]
            data = base64.b64encode((FONTS / f'{key}.woff2').read_bytes()).decode('ascii')
            css += f"@font-face{{font-family:{family};font-weight:{weight};src:url(data:font/woff2;base64,{data}) format('woff2')}}"
            css += f'.{face}{{font-family:{family},{FALLBACK[family]};font-weight:{weight}}}'
            families.add(family)
        return (f'<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{esc(title)}" '
                f'viewBox="0 0 {W} {height:.0f}" width="{W}" height="{height:.0f}"><title>{esc(title)}</title>'
                f'<style>{css}</style>'
                f'<rect width="{W}" height="{height:.0f}" fill="{self.theme["bg"]}"/>' + ''.join(self.parts) + '</svg>\n')


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


def header_svg(config, theme):
    c = Canvas(theme)
    c.text(PAD, 48, 'M / N', 13, 'green', 'm')
    c.text(W - PAD, 48, f'github.com/{config["username"]}', 13, 'muted', 'm', 'end')
    c.text(PAD, 104, 'A little about me', 13, 'muted', 'm')
    c.text(PAD, 188, fit(config['name'], 76, 'g7', CW), 76, 'ink', 'g7')
    c.text(PAD, 240, fit(config['tagline'], 28, 'g7', CW), 28, 'ink', 'g7')
    c.text(PAD, 276, fit(config['intro'], 20, 'g4', CW), 20, 'muted', 'g4')
    return c.svg(config['name'], 316)


def about_svg(config, theme):
    c = Canvas(theme)
    c.rule()
    c.label(48, '01 / About me')
    y = 92
    for line in wrap(config['about'], 22, 'g4', CW):
        c.text(PAD, y, line, 22, 'ink', 'g4')
        y += 32
    y += 6
    for line in wrap(config['note'], 16, 'g4', CW):
        c.text(PAD, y, line, 16, 'muted', 'g4')
        y += 24
    return c.svg(f'About me. {config["about"]} {config["note"]}', y + 16)


def language_svg(languages, theme=LIGHT):
    c = Canvas(theme)
    c.rule()
    c.label(48, '02 / Languages')
    c.heading(94, 'What I build with')
    c.text(PAD, 124, 'Block area reflects source lines', 13, 'faint', 'm')
    top = 146
    items = sorted(((k, v) for k, v in languages.items() if v > 0), key=lambda p: (-p[1], p[0]))
    if not items:
        c.text(PAD, top + 30, 'No source lines counted yet.', 20, 'muted')
        return c.svg('Languages: no source lines counted yet', top + 60)
    total = sum(v for _, v in items)
    # Fold tiny blocks into a readable remainder; the equal-size table contains every language.
    shown = [p for p in items[:6] if p[1] / total >= .05] or items[:1]
    remainder = total - sum(v for _, v in shown)
    if remainder:
        shown.append(('Other languages', remainder))
    height = CW / 1.618
    for i, ((name, count), x, y, w, h) in enumerate(treemap(shown, PAD, top, CW, height)):
        x, y, w, h = x + 3, y + 3, w - 6, h - 6
        c.rect(x, y, w, h, theme['tiles'][i % len(theme['tiles'])])
        color = theme['first_text'] if i == 0 else 'ink'
        if w < 110 or h < 108:
            c.text(x + 10, y + 26, fit(name, 13, 'm', w - 16), 13, color, 'm')
            continue
        # Keep the name clear of the percentage and line count at the bottom of the tile.
        size = min(40, h / 5, h - 96, (w - 36) / max(measure(name, 1, 'g5'), .1))
        if size < 16:
            size = 16
            c.text(x + 18, y + 30, fit(name, size, 'g5', w - 32), size, color, 'g5')
        else:
            c.text(x + 18, y + 22 + size, fit(name, round(size), 'g5', w - 32), round(size), color, 'g5')
        c.text(x + 18, y + h - 42, f'{count/total:.1%}', 22, theme['first_pct'] if i == 0 else 'green', 'g5')
        c.text(x + 18, y + h - 18, f'{count:,} lines', 13, color, 'm')
    return c.svg('Languages sized by source lines; exact values in the expandable table', top + height + 24)


def safe_projects(repositories):
    """Discard all private metadata before constructing any public artifact."""
    result = []
    for repo in sorted(repositories, key=lambda r: r.get('pushed_at') or '', reverse=True)[:3]:
        if repo.get('private'):
            result.append({'private': True})
        else:
            result.append({'private': False, 'name': repo['name'], 'url': repo['html_url'], 'description': repo.get('description') or 'View the code and project notes on GitHub.'})
    return result


def projects_heading_svg(theme):
    c = Canvas(theme)
    c.rule()
    c.label(48, '03 / Recent work')
    c.heading(94, 'Latest work. Partial clearance.')
    c.text(PAD, 126, 'The three most recently pushed projects.', 16, 'muted')
    return c.svg('Latest work. Partial clearance. The three most recently pushed projects.', 142)


def project_svg(project, index, theme=LIGHT):
    c = Canvas(theme)
    c.rect(PAD, 6, CW, 156, 'card')
    c.rect(PAD, 6, 3, 156, 'green')
    x = PAD + 26
    c.text(x, 38, f'{index:02} / ' + ('PRIVATE' if project['private'] else 'PUBLIC'), 13, 'green', 'm')
    if project['private']:
        # Geometric redaction. No hidden text, filters or recoverable name.
        c.rect(x, 54, 260, 26, 'redact')
        for offset in range(0, 260, 13):
            c.rect(x + offset, 56, 2, 22, 'redact_line')
        c.text(x, 112, 'Details withheld. Work in progress.', 16, 'muted')
        c.text(x, 144, '[ ACCESS RESTRICTED ]', 13, 'green', 'm')
    else:
        c.text(x, 76, fit(project['name'], 26, 'g7', CW - 60), 26, 'ink', 'g7')
        c.text(x, 112, fit(project['description'], 16, 'g4', CW - 60), 16, 'muted')
        c.text(x, 144, 'Open repository ↗', 13, 'green', 'm')
    return c.svg('Private project, name withheld' if project['private'] else project['name'], 168)


def activity_svg(days, private, theme=LIGHT):
    c = Canvas(theme)
    c.rule()
    c.label(48, '04 / Activity')
    c.heading(94, 'My coding activity')
    middle, reach = 190, 56
    maximum = max((d['count'] for d in days), default=0)
    slot = CW / max(len(days), 1)
    for i, day in enumerate(days):
        half = max(2, day['count'] / maximum * reach) if maximum and day['count'] else 2
        bar = min(12, slot * .45)
        c.rect(PAD + i * slot + (slot - bar) / 2, middle - half, bar, half * 2, 'green' if day['count'] else 'empty')
    if days:
        c.text(PAD, middle + reach + 30, days[0]['date'], 12, 'faint', 'm')
        c.text(W - PAD, middle + reach + 30, days[-1]['date'], 12, 'faint', 'm', 'end')
    total = sum(d['count'] for d in days)
    scope = 'public and private repositories' if private else 'public repositories'
    caption = (f'{total:,} contributions in the past 28 days across {scope}.' if total
               else f'No contributions in the past 28 days across {scope}.')
    c.text(PAD, middle + reach + 62, caption, 16, 'muted')
    return c.svg('Daily contributions over the past 28 days; values in the expandable table', middle + reach + 84)


def footer_svg(config, updated, theme):
    c = Canvas(theme)
    c.rule()
    c.text(PAD, 40, 'M / N', 13, 'green', 'm')
    c.text(W - PAD, 40, f'Last updated {updated}', 13, 'faint', 'm', 'end')
    return c.svg(f'Last updated {updated}', 64)


def picture(name, alt, href=None):
    tag = (f'<picture><source media="(prefers-color-scheme: dark)" srcset="assets/dark/{name}.svg">'
           f'<img alt="{esc(alt)}" src="assets/{name}.svg"></picture>')
    return f'<a href="{esc(href)}">{tag}</a>' if href else tag


def render(config, data, output):
    output = Path(output)
    days = data['activity']
    private_activity = data.get('activity_private', False)
    projects = safe_projects(data['repositories'])
    for theme, folder in ((LIGHT, output / 'assets'), (DARK, output / 'assets' / 'dark')):
        folder.mkdir(parents=True, exist_ok=True)
        files = {
            'header': header_svg(config, theme), 'about': about_svg(config, theme),
            'languages': language_svg(data['languages'], theme), 'projects': projects_heading_svg(theme),
            'activity': activity_svg(days, private_activity, theme), 'footer': footer_svg(config, data['updated'], theme),
        }
        for i, project in enumerate(projects, 1):
            files[f'project-{i}'] = project_svg(project, i, theme)
        for i in range(len(projects) + 1, 4):
            (folder / f'project-{i}.svg').unlink(missing_ok=True)
        for name, content in files.items():
            (folder / f'{name}.svg').write_text(content, encoding='utf-8')

    project_tags = [picture(f'project-{i}', 'Private project. Name withheld.' if p['private'] else f'{p["name"]}: {p["description"]}',
                            None if p['private'] else p['url']) for i, p in enumerate(projects, 1)]
    total = sum(data['languages'].values())
    language_rows = '\n'.join(f'| {esc(k)} | {v:,} | {v/total:.1%} |' for k, v in sorted(data['languages'].items(), key=lambda p: (-p[1], p[0])))
    activity_rows = '\n'.join(f'| {d["date"]} | {d["count"]} |' for d in days)
    scope_note = ('Includes private contributions as daily totals only; no names or messages are published.'
                  if private_activity else 'Public repositories only.')
    readme = f'''{picture('header', f"{config['name']}. {config['tagline']} {config['intro']}")}
{picture('about', f"About me. {config['about']} {config['note']}")}
{picture('languages', 'What I build with: languages sized by source lines')}

<details>
<summary>View all languages at equal size</summary>

| Language | Source lines | Share |
| :--- | ---: | ---: |
{language_rows or '| No source lines counted yet | 0 | — |'}

Source lines exclude blank lines and comments. Counts describe repository contents, not individual authorship. Generated and dependency directories are excluded. {data['coverage']}

</details>

{picture('projects', 'Latest work. Partial clearance. The three most recently pushed projects.')}
{chr(10).join(project_tags)}
{picture('activity', 'My coding activity: contributions per day over the past 28 days')}

<details>
<summary>View the daily breakdown</summary>

| Date (UTC) | Contributions |
| :--- | ---: |
{activity_rows}

Daily totals from GitHub's contribution calendar: commits, issues, pull requests, reviews and new repositories. {scope_note}

</details>

{picture('footer', f"Last updated {data['updated']}")}
'''
    (output / 'README.md').write_text(readme, encoding='utf-8')
