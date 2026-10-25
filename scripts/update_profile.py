"""Collect GitHub data without logging repository identifiers or source contents."""
import collections
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from render import render

ROOT = Path(__file__).resolve().parents[1]
MAX_ARCHIVE = 100 * 1024 * 1024
MAX_SOURCE = 500 * 1024 * 1024


def request(path, token, binary=False):
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'profile-readme', 'X-GitHub-Api-Version': '2022-11-28'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request('https://api.github.com' + path, headers=headers)
    with urllib.request.urlopen(req, timeout=90) as response:
        raw = response.read(MAX_ARCHIVE + 1)
    if len(raw) > MAX_ARCHIVE:
        raise ValueError('Response too large')
    return raw if binary else json.loads(raw)


def pages(path, token):
    result = []
    for page in range(1, 1001):
        separator = '&' if '?' in path else '?'
        rows = request(f'{path}{separator}per_page=100&page={page}', token)
        if not isinstance(rows, list):
            raise ValueError('Expected paginated list')
        result.extend(rows)
        if len(rows) < 100:
            return result
    raise ValueError('Pagination limit reached')


def eligible(repos, config):
    owner = config['username'].lower()
    excluded = {name.lower() for name in config['exclude_repositories']}
    return [r for r in repos if r['owner']['login'].lower() == owner and not r['fork']
            and not r['archived'] and r['name'].lower() != owner
            and r['name'].lower() not in excluded and r.get('pushed_at')]


def extract_sources(raw, destination, excluded):
    """Read ordinary ZIP files only, rejecting traversal, symlinks and oversized archives."""
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if sum(info.file_size for info in archive.infolist()) > MAX_SOURCE:
            raise ValueError('Source size limit exceeded')
        for info in archive.infolist():
            parts = PurePosixPath(info.filename).parts
            if info.is_dir() or len(parts) < 2:
                continue
            if '..' in parts or '\\' in info.filename or any(':' in part for part in parts):
                raise ValueError('Unsafe source path')
            if info.filename.startswith('/') or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Unsafe source entry')
            if any(part in excluded for part in parts[1:-1]):
                continue
            name = parts[-1]
            if name.endswith(('.min.js', '.min.css', '.map', '.lock', '.zip', '.tar', '.gz', '.jar', '.png', '.jpg')):
                continue
            if info.file_size > 5 * 1024 * 1024:
                continue
            target = destination.joinpath(*parts[1:])
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError('Unsafe source destination')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))


def count_lines(raw, config):
    with tempfile.TemporaryDirectory(prefix='profile-source-') as folder:
        source = Path(folder) / 'source'
        source.mkdir()
        extract_sources(raw, source, set(config['exclude_directories']))
        report = Path(folder) / 'counts.json'
        command = [os.environ.get('CLOC', 'cloc')]
        if os.environ.get('CLOC_PERL'):
            command.insert(0, os.environ['CLOC_PERL'])
        subprocess.run(command + [str(source), '--json', '--quiet', '--skip-archive=.*',
                                  '--exclude-lang=' + ','.join(config['exclude_languages']),
                                  '--out=' + str(report)], check=True, capture_output=True, timeout=180)
        if not report.exists():
            return {}
        counts = json.loads(report.read_text(encoding='utf-8'))
        return {k: v['code'] for k, v in counts.items() if k not in ('header', 'SUM') and v['code'] > 0}


def collect(config):
    private_token = os.environ.get('PROFILE_READ_TOKEN', '')
    token = private_token or os.environ.get('GH_TOKEN', '')
    username = urllib.parse.quote(config['username'], safe='')
    endpoint = '/user/repos?affiliation=owner&visibility=all' if private_token else f'/users/{username}/repos?type=owner'
    repositories = eligible(pages(endpoint, token), config)
    totals = collections.Counter()
    today = dt.datetime.now(dt.timezone.utc).date()
    dates = [(today-dt.timedelta(days=i)).isoformat() for i in reversed(range(28))]
    activity = collections.Counter({day: 0 for day in dates})
    def inspect(repo):
        lines = {}
        commits = collections.Counter()
        # Identifiers remain in memory only. No source code from a repository is executed.
        path = '/repos/' + '/'.join(urllib.parse.quote(s, safe='') for s in (config['username'], repo['name']))
        if repo.get('size', 0) and (not repo['private'] or config['include_private_languages']):
            raw = request(path + '/zipball/' + urllib.parse.quote(repo['default_branch'], safe=''), token, binary=True)
            lines = count_lines(raw, config)
        if not repo['private'] and repo.get('size', 0):
            query = urllib.parse.urlencode({'author': config['username'], 'since': dates[0]+'T00:00:00Z', 'until': today.isoformat()+'T23:59:59Z'})
            for commit in pages(path + '/commits?' + query, token):
                day = commit['commit']['committer']['date'][:10]
                if day in activity:
                    commits[day] += 1
        return lines, commits
    with ThreadPoolExecutor(max_workers=4) as pool:
        for lines, commits in pool.map(inspect, repositories):
            totals.update(lines)
            activity.update(commits)
    private_scope = bool(private_token and config['include_private_languages'])
    return {'languages': dict(totals), 'repositories': repositories,
            'activity': [{'date': day, 'count': activity[day]} for day in dates],
            'updated': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
            'coverage': 'Includes accessible private repositories in aggregate.' if private_scope else 'Public repositories only.'}


def main():
    config = json.loads((ROOT/'profile.json').read_text(encoding='utf-8'))
    # Collect completely before writing. Any collection failure keeps the previous profile intact.
    data = collect(config)
    with tempfile.TemporaryDirectory(prefix='profile-render-') as folder:
        render(config, data, folder)
        (ROOT/'assets').mkdir(exist_ok=True)
        for item in (Path(folder)/'assets').iterdir():
            shutil.copyfile(item, ROOT/'assets'/item.name)
        for i in range(1, 4):
            if not (Path(folder)/'assets'/f'project-{i}.svg').exists():
                (ROOT/'assets'/f'project-{i}.svg').unlink(missing_ok=True)
        shutil.copyfile(Path(folder)/'README.md', ROOT/'README.md')
    print('Profile refreshed successfully.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # Avoid URLs, credentials, private repository names and source paths in public Actions logs.
        print('Profile refresh failed; existing published assets were retained. Check token access, API limits and cloc availability.', file=sys.stderr)
        sys.exit(1)
